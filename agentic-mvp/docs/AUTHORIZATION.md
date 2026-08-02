# Authorization: OPA-backed three-role model

This document describes how this app decides who can do what — the
Super Admin / Admin / User flow model, built on
[Open Policy Agent](https://www.openpolicyagent.org/) (OPA) and its Rego
policy language, replacing the earlier binary `require_admin` gate.

## 1. The three flows

| Role | Tenant scope | Capabilities |
|---|---|---|
| `super_admin` | none (`tenant_id` is always `NULL`) | Unrestricted. Creates tenants, assigns admins to tenants, and — per the app's existing "platform-shared" convention — can read/write across every tenant's users, projects, skills, hooks, plugins, prompts, personas, and datasources. |
| `admin` | exactly one tenant | Full CRUD on everything inside their own tenant: users (but never other admins/super admins), projects (incl. freeze/deploy), agents, skills, hooks, plugins, prompts, personas, datasources, tools. Can read (but not edit) their own tenant's profile via `/tenants/me`. |
| `user` | exactly one tenant | Read-only Agents/Projects/Prompts, plus full use of their own Chat conversations. Nothing else. |

This directly implements the three flows requested: Super Admin owns tenant
lifecycle and has platform-wide reach; Admin owns everything under their own
tenant including user/project/agent creation and freezing; User is
restricted to agents (read-only) and chat.

## 2. Why OPA, and what it does (and doesn't) decide

OPA answers one narrow, coarse-grained question: **"is this role even
allowed to attempt this kind of action on this resource type?"** — e.g. "can
an `admin` `create` a `skill`?" It does not know about individual rows.

Everything about *which specific row* — "does this Project actually belong
to my tenant?", "is this Skill platform-shared or tenant-private?" — remains
exactly where it always lived: in each route's own SQL query / `_get_..._or_
404`-style helper. This split is deliberate and standard OPA practice: OPA
is a policy decision point for coarse authorization, not a replacement for
tenant-scoped data access.

```
Request → FastAPI route → Depends(authorize("skill", "create"))
                                │
                                ├─→ POST http://opa:8181/v1/data/agentic/authz/allow
                                │     { "input": { subject, action, resource } }
                                │
                                └─→ 403 if false, else route body runs its own
                                    tenant-scoped SQL query/filter as before
```

### Input contract

Every decision is a single Rego query against `data.agentic.authz.allow`,
given this input shape:

```json
{
  "subject": { "id": "<uuid>", "role": "super_admin|admin|user", "tenant_id": "<uuid>|null" },
  "action": "list|read|create|update|delete|freeze|unfreeze|deploy",
  "resource": { "type": "tenant|user|project|agent|skill|hook|plugin|prompt|persona|datasource|tool|chat", "tenant_id": "<uuid>|null", "target_role": "admin|super_admin (optional)" }
}
```

`resource.tenant_id` is the tenant the *resource* belongs to — normally just
the caller's own `tenant_id`, but explicitly `null` for Tenant-lifecycle
actions, and an explicit target tenant for `/platform` endpoints.
`target_role` is only set for `user` resource writes, so the policy can deny
an Admin creating/promoting a privileged account even before it looks at
anything else.

### The policy itself

`backend/policies/authz.rego` (package `agentic.authz`) is the single
source of truth. `backend/policies/authz_test.rego` is a companion
`opa test`-compatible suite (~30 cases) covering every role/action/resource
combination described in this document, including the edge cases below.

Key rules, summarized:

- `super_admin` → unconditional allow.
- `admin` + `resource.type == "tenant"` + `action in {read, update}` +
  `resource.tenant_id == subject.tenant_id` → allowed (this is `/tenants/me`
  self-service — an Admin renaming their own tenant profile). All other
  Tenant actions (create/delete/list/cross-tenant read) are denied for
  Admin — Super Admin-exclusive.
- `admin`, any other resource type, `read`/`list` →allowed when
  `resource.tenant_id` is the admin's own tenant **or** `null` (the
  platform-shared convention already used by Skill/Hook/Plugin/Tool/Prompt/
  Agent — see `TenantScopedMixin`).
- `admin`, any other resource type, write actions (`create/update/delete/
  freeze/unfreeze/deploy`) → allowed only when `resource.tenant_id` exactly
  equals the admin's own tenant (never `null`, never another tenant) — an
  Admin can *read* a platform-shared item but never edit or delete one.
- `admin`, `resource.type == "user"`, write action, `target_role in {admin,
  super_admin}` → denied. An Admin can create/update/delete plain `user`
  accounts in their tenant, never privileged ones.
- `user`, `resource.type in {agent, project, prompt}`, `read`/`list`,
  own tenant → allowed.
- `user`, `resource.type == "chat"`, own tenant, any action → allowed.
- Everything else → denied (`default allow := false`).

## 3. Python-side integration

- **`app/core/opa.py`** — the only place that speaks HTTP to OPA.
  `check_allow(input_doc)` POSTs to `{OPA_URL}/v1/data/agentic/authz/allow`
  and returns the boolean `result`, raising `OpaUnavailableError` on any
  network/parse failure. `authorize(user, resource_type, action, *,
  tenant_id, target_role)` builds the input document and wraps
  `check_allow` with **fail-closed** behavior: unreachable OPA, a timeout,
  or a malformed response always denies and logs an error — never grants by
  default. There is deliberately no "allow if OPA is down" configuration
  knob.

- **`app/api/deps.py`** — the FastAPI dependency layer, replacing the old
  `require_admin`:
  - `authorize(resource_type, action)` — factory returning a
    `Depends()`-compatible function. Calls `opa.authorize(...)` scoped to
    the caller's own tenant, 403s on deny. It also adds one guard OPA can't
    express on its own: since OPA's `super_admin` rule is unconditional, a
    super_admin attempting a *write* action through one of these
    tenant-scoped routes (with no tenant context — `tenant_id is None`)
    would otherwise insert a row with `tenant_id=NULL`. That's rejected
    with **400** (not 403 — it's not a permissions problem, OPA already
    said yes; there's just no tenant to scope the write to). A super_admin
    manages a tenant's contents by creating/promoting that tenant's Admin
    instead.
  - `authorize_tenant(action)` — same shape, but always passes
    `resource.tenant_id = null` (used for `/platform/tenants/*` and
    `/tenants/me`, since a Tenant row has no "tenant's tenant_id" of its
    own).
  - `require_super_admin` — a plain role check for the handful of
    `/platform` endpoints (cross-tenant user listing, role promotion) that
    don't map onto a single `(resource_type, action, tenant_id)` tuple.

- **`app/core/tenant_scope.py`** — the "which specific rows" half, shared
  across every route that lists/fetches tenant-scoped data:
  `shared_or_own_tenant_filter` / `apply_shared_or_own_tenant` (own tenant +
  platform-shared, for Skill/Hook/Plugin/Tool/Prompt/Agent),
  `own_tenant_filter` / `apply_own_tenant` (own tenant only, for
  Persona/Datasource/User — no platform-shared concept), and `is_visible`
  (the single-row equivalent for `_get_..._or_404`-style helpers). The one
  thing that changed here versus the pre-OPA code: `super_admin` has no
  `tenant_id`, so these helpers return "match everything" for that role
  rather than filtering down to nothing.

## 4. Tenant and role lifecycle

- **`POST /auth/signup`** (unchanged) — public self-service. Creates a new
  Tenant and the signing-up user as that tenant's first `admin`.
- **`POST /auth/bootstrap-super-admin`** — one-time only. Works exactly
  once, while zero `super_admin` rows exist anywhere; after that it
  **404s** (deliberately, not 403 — it "looks like it doesn't exist" once
  used, rather than advertising a locked-but-present endpoint).
- **`POST /platform/tenants`** (Super Admin only) — provision a tenant up
  front, independent of self-service signup.
- **`POST /platform/tenants/{id}/admins`** (Super Admin only) — "assigning
  admins to tenants": creates a new `admin` account directly inside a
  tenant. There's no pool of unassigned users to promote across tenants —
  every user already belongs to exactly one tenant the moment they exist —
  so assigning an admin means creating their account there.
- **`PUT /platform/users/{id}/role`** (Super Admin only) — the ongoing
  mechanism for promoting/demoting *existing* users to any role, including
  minting additional super admins after bootstrap has self-disabled.
  Promoting to `super_admin` clears `tenant_id` to `null`; demoting away
  from `super_admin` requires a target tenant (explicit `tenant_id` in the
  payload, or the user's prior tenant if still set) — 400 if neither is
  available.
- **`POST /admin/users`** (Admin, own tenant) — schema-locked to
  `role="user"` (`AdminUserCreate.role: Field(pattern="^user$")`); an Admin
  structurally cannot create a fellow Admin or Super Admin through this
  endpoint. `AdminUserUpdate` has no `role` field at all — role changes are
  exclusively a Super Admin action.

## 5. Data model changes (migration `0012`)

- `users.tenant_id` is now **nullable** — `NULL` exclusively for
  `super_admin`.
- `role` values are exactly `super_admin` / `admin` / `user` (the old
  `member` value is renamed to `user` — same capabilities, new name). No
  DB-level `CHECK` constraint on `role`, consistent with how `status`
  fields elsewhere in this app (`Hook.status`, `TenantScopedMixin.status`)
  are validated at the Pydantic layer, not the database layer.

## 6. Deployment

OPA runs as its own container (`docker-compose.yml`, service `opa`,
`openpolicyagent/opa:0.68.0-static`). There is no embedded/in-process Rego
evaluator — none exists for Python — so an HTTP sidecar is the only
integration shape available. `backend`'s `OPA_URL` environment variable
points at `http://opa:8181`; `depends_on: opa: condition: service_started`
(not health-gated — the `-static` OPA image has no shell/wget for a `CMD`
healthcheck, and `app/core/opa.py` already fails closed rather than
crashing if OPA isn't ready yet, so a strict health gate isn't necessary for
correctness).

`opa` no longer loads `backend/policies/` directly. A second service,
`opa-control-plane` (`openpolicyagent/opa-control-plane:v0.7.0`, config at
`opa-control-plane/ocp.yml`), builds `backend/policies/authz.rego` into a
compiled bundle and writes it to the `opa_bundles` named volume shared by
both containers; `opa` runs `run --server --watch /bundles/authz/bundle.tar.gz`
to pick up and re-serve that bundle whenever opa-control-plane rebuilds it
(e.g. after a policy edit). This is OCP's standard filesystem
`object_storage` pattern — for cloud deployments the same `ocp.yml` bundle
can point at S3/GCS/Azure instead, with `opa` polling that store over HTTP
via its own `services`/`bundles` config, without changing anything on the
`backend` side.

### 6.1 OCP's own database, and `--apply-migrations`

OCP keeps its own state — the source and bundle definitions it is working
from — in a SQL database. With no `database:` block in `ocp.yml` that is an
**in-memory SQLite** store, which suits this deployment: `ocp.yml` is checked
into the repo and is already the durable source of truth, so OCP's copy is a
cache that can be rebuilt from scratch on every boot.

What that arrangement *requires*, and what was missing here, is
`--apply-migrations` on `opactl run`. An in-memory database starts empty every
time, so unless migrations run at startup the schema never exists. Without the
flag OCP does not fail loudly: it warns about unapplied migrations and then, in
the upstream wording, "attempts to use the database as-is". The observable
result is a cascade that looks nothing like its cause —

1. OCP starts and appears healthy, but never publishes a bundle.
2. `opa run --watch` exits immediately on the missing bundle path and
   crash-loops, backing off exponentially.
3. `app/core/opa.py` fails closed, as designed.
4. **Every** admin-gated route returns 403, and the app looks like it has a
   permissions bug rather than a container that never started.

Upstream's own manifest carries the flag with the note "single OCP instance can
run migrations on startup", which is exactly this deployment. A multi-instance
rollout should instead run `opactl db migrate` out of band and drop the flag,
so two instances can't race the same migration.

### 6.2 Startup ordering

`opa` does not depend on opa-control-plane merely having *started* — that is a
race, and losing it means a crash-loop whose backoff can outlast the build that
triggered it. A one-shot `opa-bundle-wait` container blocks until the bundle
exists and passes `gzip -t`, and `opa` waits for that to complete. "The bundle
is readable" is a truer readiness signal than any healthcheck on OCP, since
that artifact is the only thing `opa` actually consumes. It times out after
120s with a pointer to `docker compose logs opa-control-plane`.

Both named volumes (`opa_bundles`, `opa_data`) are chowned to uid 1000 by the
`opa-bundles-init` container first: Docker creates named volumes root-owned,
and the OCP image runs as uid 1000 (upstream `Dockerfile`: `ARG USER=1000:1000`).
Missing the chown on `--data-dir` produces a permissions failure that reads
like a config error.

### 6.3 Image pinning and API exposure

The image is pinned to a release tag rather than `:edge`. `edge` tracks the tip
of `main` and is rebuilt continuously, so an unpinned stack can break with no
change on our side. When bumping it, check the flags against
`docs/k8s-manifests.yaml` at the matching upstream tag.

OCP's management API (`OPA_CONTROL_PLANE_PORT`, default `8282`) is bound to
`127.0.0.1` only. It runs unauthenticated here — there is no `tokens:` block in
`ocp.yml` — and it can rewrite the bundle that authorizes every request in this
app, so it should not reach a shared interface without tokens configured first.
Nothing in this app calls it; `curl localhost:8282/v1/bundles` still works from
the host for debugging.

**This sandbox cannot run or download OPA** (no docker; GitHub release-asset
downloads are blocked by the sandbox's network allowlist), so the Rego
policy has never been executed here. `backend/policies/authz_test.rego` is
written to be run with a real `opa` binary once this repo is on a machine
with docker/network access:

```bash
opa test backend/policies/ -v
```

All Python-side integration code (`app/core/opa.py`, `app/api/deps.py`,
`app/core/tenant_scope.py`, `app/api/routes/platform.py`) is unit-tested in
this sandbox by mocking the HTTP layer — see `tests/test_opa.py`,
`tests/test_authorize_dependency.py`, `tests/test_tenant_scope.py`,
`tests/test_platform_routes.py`. Those tests verify the *Python* side calls
OPA correctly and fails closed; they cannot verify the Rego policy's own
correctness, which is what `authz_test.rego` is for.

## 7. Frontend

- `types.ts` — `Role = "super_admin" | "admin" | "user"`; `User.tenant_id`
  is `string | null`.
- `AuthContext.tsx` — adds `bootstrapSuperAdmin()` alongside `login`/
  `signup`.
- `Layout.tsx` — nav is role-aware: Chat + Projects for everyone; Agents +
  Prompts (read-only for `user`) for everyone; Skills/Tools/Plugins/Hooks/
  Personas/Datasources only for `admin`/`super_admin`; "Tenant & Users"
  only for `admin`; a new "Platform > Tenants" section only for
  `super_admin`. This is UI convenience only — the OPA policy is the real
  enforcement; every one of these links still 403s/400s server-side if
  reached in a way the backend disallows.
- `PlatformTenantsPage.tsx` (new, Super Admin only) — tenant list, create,
  activate/deactivate, delete; per-tenant "Add Admin"; per-tenant user list
  with a role-change dropdown wired to `PUT /platform/users/{id}/role`.
- `BootstrapSuperAdmin.tsx` (new, public route `/bootstrap-super-admin`) —
  one-time setup form; shows an "already bootstrapped" message on 404
  rather than a generic error.
- `AdminUsersPage.tsx` — the role-toggle button and create-time role picker
  were removed: `AdminUserCreate`/`AdminUserUpdate` no longer support role
  changes through this endpoint at all (schema-enforced server-side).
