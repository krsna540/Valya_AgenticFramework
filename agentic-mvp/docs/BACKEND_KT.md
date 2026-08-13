# Backend KT — `core/`, `models/`, `schemas/`, `api/`, `services/`

A walkthrough of the five layers under `backend/app/`, written for a developer
who knows Python and FastAPI but has never seen this codebase.

Read it top to bottom once. After that, §2 (the request lifecycle) and §9 (the
conventions cheat sheet) are the two sections you will come back to.

Assessed against the code as of **2026-08-13**. Roughly 9,000 lines across the
five folders:

| Folder | Files | Lines | One-line job |
|---|---:|---:|---|
| `core/` | 8 | 710 | Cross-cutting infrastructure — config, DB, JWT, OPA, tenant scoping, Redis, MinIO |
| `models/` | 24 | 1,745 | SQLAlchemy ORM — the 34 tables and their relationships |
| `schemas/` | 18 | 1,548 | Pydantic contracts — what the HTTP API accepts and returns |
| `api/` | 25 | 4,022 | FastAPI routers (24) + `deps.py` |
| `services/` | 11 | 1,869 | Business logic that is too big, or too shared, to live in a route |

(File counts exclude empty `__init__.py` files; line counts include them.)

---

## 1. The layering rule

```
HTTP request
    │
    ▼
api/deps.py ──────────────► core/security.py   (decode JWT)
    │  authenticate                 core/opa.py        (ask OPA: may this role do this?)
    ▼
api/routes/*.py ──────────► schemas/*.py       (validate the body)
    │  orchestrate         └─► core/tenant_scope.py (which ROWS may they see?)
    ▼
services/*.py ────────────► models/*.py        (ORM)
    │  business logic              core/database.py   (Session)
    ▼
PostgreSQL
```

Three rules that are actually enforced, not aspirational:

1. **Routes never build authorization logic inline.** They declare
   `Depends(authorize("skill", "create"))`. The rules live in Rego
   (`backend/policies/authz.rego`), not in Python.
2. **Models never import from `schemas/` or `api/`.** The dependency arrow only
   points one way. `services/` may import `models/`; `models/` may not import
   `services/`.
3. **`core/` imports nothing from the other four.** It is the bottom of the
   stack. (`core/opa.py` and `core/tenant_scope.py` reference `models.User`, but
   `opa.py` does it under `TYPE_CHECKING` specifically to keep the runtime graph
   acyclic.)

### The two-layer authorization split

This trips up everyone once, so learn it before anything else.

| Question | Answered by | Where |
|---|---|---|
| "May a user with role X attempt action Y on resource type Z **at all**?" | OPA / Rego | `core/opa.py` → `policies/authz.rego` |
| "Given they may, **which rows** do they get back?" | SQL `WHERE` clause | `core/tenant_scope.py` |

OPA is deliberately coarse — it never sees a row. It answers at the level of
"admins may create skills." The moment you ask "…but is *this* skill in *their*
tenant?", that is a `WHERE` clause, and it belongs in `tenant_scope.py`.

Both must fire. Neither substitutes for the other. A route that calls
`authorize(...)` but forgets `apply_shared_or_own_tenant(...)` will happily
return another tenant's rows to an authenticated admin.

---

## 2. The request lifecycle, traced

`POST /api/v1/skills` from a tenant admin:

1. **`main.py`** routes to `skills.router`, mounted under `settings.api_v1_prefix`.
2. **`deps.oauth2_scheme`** pulls the bearer token out of the `Authorization` header.
3. **`deps._resolve_user`** calls `core.security.decode_access_token`, which tries
   RS256 against the configured public key, then falls back to the HS256 dev
   secret. Returns the `sub` claim → a user UUID → `db.get(User, ...)`. A missing,
   expired, or inactive user is a 401.
4. **`deps.authorize("skill", "create")`** builds the OPA input document
   (`subject.role`, `action`, `resource.type`, `resource.tenant_id`) and POSTs it
   to OPA. Denied → 403. It then applies one extra guard OPA cannot express: a
   super_admin performing a *tenant-scoped write* with no tenant of their own
   gets a 400, because the row would otherwise be inserted with `tenant_id=NULL`.
5. **Pydantic** validates the body against `schemas/skill.py`. Invalid → 422,
   before the handler runs.
6. **The route** does its work, usually delegating to `services/`.
7. **`schemas.SkillRead.model_validate(row)`** serializes the ORM object back out.
   `model_config = ConfigDict(from_attributes=True)` is what lets Pydantic read
   attributes off a SQLAlchemy object.

Steps 2–4 are the same for every authenticated route in the app. That uniformity
is the point.

---

## 3. `core/` — infrastructure

Eight files, no business logic. Everything here is imported by everything else.

### `config.py` (187 lines)

One `Settings(BaseSettings)` class, loaded from `.env`, exposed as a module-level
`settings` singleton via `@lru_cache`. Every tunable in the app is here and
nowhere else.

Grouped roughly as: Postgres connection → JWT keys → CORS → upload limits → skill
package limits → OPA → Redis → MinIO → platform KPI targets → **agent runtime**.

The agent runtime block is the largest and most consequential:

- `agent_llm_provider` — `"stub"` (default, deterministic, offline, no
  credentials needed), `"gateway"` (MLflow AI Gateway), or `"direct"` (httpx
  straight to Anthropic/OpenAI). The default being `stub` is why a fresh
  checkout runs with an empty `.env`.
- `agent_llm_route_planner` / `_executor` / `_critic` — the role-split. Planner
  and Critic are the strong-reasoning roles (Claude); Executor is the
  high-volume latency-sensitive one (OpenAI). **Only takes effect when an
  Agent's own `model_name` is `"default"`** — an explicit `model_name` pins all
  three roles to that one model.
- `agent_checkpointer` — `"memory"` or `"postgres"`. Postgres makes runs
  resumable across a restart; it degrades to memory with a warning rather than
  hard-failing.
- `temporal_enabled` — off means runs execute in-process (`LocalRunner`),
  correct for dev. On means each turn is a durable workflow.

> **Gotcha:** `jwt_algorithm` defaults to RS256 but `jwt_private_key` /
> `jwt_public_key` default to empty strings, so an unconfigured checkout
> silently falls back to the HS256 `jwt_secret`. That is deliberate (so
> `docker compose up` works), and it is **never** acceptable outside local dev —
> a shared HS256 secret means every service that can *verify* a token can also
> *mint* one.

### `database.py` (21 lines)

The whole persistence setup: a sync `create_engine` with `pool_pre_ping=True`, a
`SessionLocal` factory, the `Base` declarative class, and a `get_db()` generator
used as a FastAPI dependency.

**The backend is synchronous SQLAlchemy.** This matters when you touch async
code — see `services/agent_run_store.py`, which wraps its writes in
`asyncio.to_thread` rather than introducing a second async engine and a second
connection pool against the same database.

### `security.py` (71 lines)

Password hashing (bcrypt, with a hard 72-byte truncation guard that
`schemas.user.UserCreate` mirrors as a `max_length=72`) and JWT mint/verify.

`_signing_key()` returns RS256 if a private key is configured, else HS256.
`decode_access_token_claims` tries RS256 *then* HS256, so tokens minted under
either scheme survive a key rotation. Verification is fully offline — no call to
any auth service.

### `opa.py` (105 lines)

The HTTP client for Open Policy Agent. Two functions matter:

- `check_allow(input_doc)` — POSTs to `/v1/data/agentic/authz/allow`, raises
  `OpaUnavailableError` on network/parse failure. Does *not* fail closed on its
  own, deliberately, so it stays trivially unit-testable.
- `authorize(user, resource_type, action, *, tenant_id, target_role)` — the one
  function every check in the app should call. Builds the input doc, calls
  `check_allow`, and **returns `False` on any error**.

**Fails closed, always.** There is no "allow if OPA is down" mode. If OPA is
unreachable the app denies everything and logs an error. Note the subtlety in
`check_allow`: OPA omits `"result"` entirely when the queried path is undefined
(e.g. the bundle failed to load), and that is treated as a deny — the policy's
own `default allow := false` would not save you there, because an unloaded
bundle bypasses the policy entirely.

### `tenant_scope.py` (82 lines)

The row-level counterpart to OPA. Four helpers, and picking the right one is the
single most common source of tenant-isolation bugs:

| Helper | Use when | Behaviour |
|---|---|---|
| `shared_or_own_tenant_filter` | Registries where `tenant_id IS NULL` means "platform-shared" — Skill, Hook, Plugin, Tool, Prompt, Agent, Playbook | shared rows + your tenant's rows |
| `own_tenant_filter` | Registries with no shared concept — Persona, Datasource, User, Project, Policy | your tenant's rows only |
| `is_visible(row_tenant_id, user, *, shared_ok=True)` | Single-row check after a `db.get()` | the Python equivalent of the above |
| `apply_registry_visibility` | Opt-in, adds the migration-0016 `visibility` axis | also exposes other tenants' `public` custom rows |

In every one of them, **super_admin sees everything** (`return true()`), because
super_admin has `tenant_id = None` and would otherwise be filtered down to
nothing.

`apply_registry_visibility` is additive and opt-in — no existing route uses it.
Do not swap it in for `apply_shared_or_own_tenant` without understanding that it
widens visibility across tenant boundaries.

### `redis_client.py` (116 lines)

One lazily-created process-wide async client. Three of Redis's four documented
jobs are wired: manifest handoff (`manifest:{session_id}`, 900s TTL), event
fan-out (`PUBLISH run:{run_id}:events`), and the pure-tool result cache
(`tool:{hash}`, 3600s TTL).

**Every function swallows its exceptions.** Redis is a lossy accelerator here —
a failed publish costs a UI update, never correctness. Do not "fix" this by
letting errors propagate.

### `minio_client.py` (99 lines)

Content-addressed blob storage. `put_blob` returns `"sha256:<hex>"` and stores
under `blobs/<digest>` — a second write of identical bytes is idempotent by
construction. `get_blob` **re-hashes on read** and raises `ValueError` on
mismatch rather than returning corrupted bytes.

Honest scope: skill package files are mirrored here, but serving still reads
from the local `dir_path`. This is a verifiable second copy, not yet the source
of truth.

### `slug.py` (29 lines)

`slugify` + `unique_slug` for tenant slugs. Shared by `/auth/signup` and
`POST /platform/tenants`. Collision handling appends a 6-hex-char suffix rather
than looping — fine at this scale, not a transactional reservation.

---

## 4. `models/` — the ORM

23 modules, 34 tables. `models/__init__.py` imports every model eagerly, which
is what makes `Base.metadata` complete for Alembic autogenerate.

### `mixins.py` — read this first

Three mixins compose almost every registry table:

**`RegistryMixin`** — `id`, `name`, `description`, `is_active`, `created_at`,
`updated_at`.

**`RegistryAccessMixin`** — the two independent access axes from
PLATFORM_ARCHITECTURE §7.2:

- `access_class` — who may **mutate**: `default` (platform-shipped, super_admin
  only) or `custom` (tenant-authored).
- `visibility` — who may **see/use**: `public` / `protected` / `private`.
- `forked_from_id` / `forked_from_version` — provenance. **Deliberately not a
  foreign key**, so the record survives the source row being archived.
- `owner_user_id`, `reviewed_by_user_id`.

**`TenantScopedMixin(RegistryAccessMixin)`** — adds `tenant_id` (nullable!),
`version` (SemVer string), `status` (Active/Experimental/Deprecated).

> **The nullable `tenant_id` convention.** `NULL` = platform-shared, visible to
> every tenant, editable by none. Non-NULL = private to that tenant. As of
> migration 0016, `tenant_id IS NULL` is exactly `access_class="default"`; the
> two are kept in sync at the write path (`services/registry_access.py`) rather
> than merged, so every pre-existing `tenant_id` query keeps working.

**Hook is the exception.** It inherits `RegistryMixin, RegistryAccessMixin`
directly — not `TenantScopedMixin` — because it already declared its own
`version`/`status` columns before the mixin existed, and inheriting both would
duplicate them. It declares `tenant_id` by hand.

### Model groups

**Tenancy & identity**
- `tenant.py` — `Tenant`. `settings` is one JSONB blob holding rate limits and
  guardrail toggles (`DEFAULT_TENANT_SETTINGS`), stored schema-less so a new
  guardrail needs no migration.
- `user.py` — `User`. `tenant_id` is **nullable** because super_admin is
  platform-level and belongs to no tenant. `role` is the `subject.role` input
  to every OPA decision: `super_admin` / `admin` / `user`.

**The Intelligence Layer registries** — all `RegistryMixin + TenantScopedMixin`:
- `agent.py` — `Agent` plus the `agent_tools` / `agent_plugins` / `agent_hooks`
  association tables. `runtime_config` is per-agent tuning (revision budgets,
  node timeouts, whether tools may actually fire).
- `skill.py` — `Skill` plus `agent_skills`. A skill is an uploaded zip in the
  agentskills.io folder format (`SKILL.md` + optional `skill.json`,
  `references/`, `scripts/`, `assets/`). **Nothing here is ever executed** —
  `scripts/` are store-only, and that is deliberate (this app built real code
  execution once and removed it).
- `tool.py` — `Tool`. `tool_type` is `function` or `mcp`; the `mcp_*` columns
  describe how to reach an MCP host. `annotations` holds the MCP 2025-06-18
  display hints, which are **advisory, never a security boundary**.
- `plugin.py` — `Plugin`. Bundles of already-registered skills/hooks/tools by
  string key. `exports_*` are plain strings that must resolve to vetted
  handler keys; no code is imported at install time.
- `hook.py` — `Hook`. `lifecycle_event` is one of 10 stages; `handler_type` is
  `python` (safe, resolves to a vetted `BUILTIN_HOOKS` entry) or
  `http`/`command`/`mcp_tool` (**real network/code execution**).
- `prompt.py` — `Prompt`. Chat-style `messages` with `{{variables}}` plus
  `model_params`. Named `model_params`, not `model_config`, because the latter
  is reserved on every Pydantic `BaseModel`.
- `playbook.py` — `Playbook`. Two field groups: the §11.5 procedural-memory
  fields the Planner reads (`when_to_use`, `canonical_steps`,
  `required_criteria`, `known_assumptions`, `supporting_stats`) and the seven
  authoring components a human writes (`objective`, `target_persona`,
  `out_of_scope`, `inputs`, `guardrails`, `approval_gates`,
  `few_shot_examples`).

**Deployment**
- `project.py` — `Project` plus `project_users` / `project_datasources`.
  Lifecycle is `draft → frozen → deployed → archived`. `frozen_snapshot` is the
  live topology JSON captured at freeze time.
- `project_intelligence_binding.py` — the association-matrix row: "for Project
  X, attach Agent v1.2 / grant this Tool / apply this Hook."
- `persona.py` — `Persona` + `UserPersonaMapping`. **Naming trap:** this is an
  *authored behavioural template* a user adopts, not the §11.6 learned persona
  memory. Same word, opposite data flow.
- `datasource.py` — `Datasource`. 10 connector types, Airbyte-style sync modes.
  Explicitly a **scaffold**: no real OAuth handshake, no live tunnel, no
  crawler. `connect`/`sync` are synchronous stub state transitions.

**Chat**
- `chat.py` — `Conversation` + `Message`. Message is a **self-referential
  tree**: editing or regenerating creates a *sibling* (same
  `parent_message_id` + same `agent_id`), and exactly one sibling has
  `is_active_branch=True`. `secondary_agent_ids` on the conversation drives
  split-screen compare.
- `file.py` — `UploadedFile`.

**Runtime & observability**
- `agent_run.py` — `AgentRun` + `AgentRunStep`. The queryable Observatory audit
  trail. Deliberately separate from LangGraph checkpoints, which are opaque
  serialized state with a different owner.
- `event.py` — `Event`. The append-only episodic spine. Composite PK
  `(run_id, seq)`, `seq` monotonic per run under an advisory lock, so an SSE
  client can reconnect and ask "everything after seq N."
- `manifest.py` — `Manifest` + `ManifestSession`. The manifest PK **is** its
  content hash, so `INSERT ... ON CONFLICT DO NOTHING` is the entire dedup
  mechanism.
- `usage_event.py`, `audit_log.py`, `model_route.py`, `policy.py`,
  `policy_revision.py`.

---

## 5. `schemas/` — the API contracts

18 modules. The convention is a three-way split per resource:

- **`XCreate`** — POST body. Required fields required, defaults applied.
- **`XUpdate`** — PUT body. **Every field optional.** Routes apply
  `model_dump(exclude_unset=True)`, so an omitted key leaves the stored value
  alone; a caller clearing a list must send `[]` explicitly.
- **`XRead`** — response. Always carries
  `model_config = ConfigDict(from_attributes=True)`.

`registry.py` (176 lines) is the one shared module and does double duty:

- the generic `RegistryCreate/Update/Read` trio that `registry_factory.py` is
  built around — in practice unused, since nothing calls the factory (§6);
- the **Hook and Agent** schemas (`HookCreate/Read/Update`, `AgentCreate/Read/
  Update`, plus the `HookHandlerInfo` / `LifecycleEventInfo` discovery
  responses), which `routes/hooks.py` and `routes/agents.py` genuinely import.

So do not assume a schema lives in a file named after its resource — there is
no `schemas/hook.py` or `schemas/agent.py`. Grep before you create one.

Validation lives here, not in routes. Patterns to copy:

- `Field(pattern="^(Active|Experimental|Deprecated)$")` for enum-ish strings —
  kept as strings, not DB enums, so adding a value is a schema-only change.
- `Field(min_length=1)` on a list to enforce non-empty (e.g. a playbook's
  `required_criteria` — "a playbook nobody can tell succeeded is not a
  playbook").
- `EmailStr` for emails; `max_length=72` on passwords to match bcrypt's limit.

> **The NULL-vs-absent trap.** A Pydantic `= ""` or `default_factory=list`
> default only applies when the key is **absent**. Under
> `from_attributes=True` the attribute is always *present*, so a row carrying
> `NULL` in that column arrives as `None` and raises — 500-ing the whole list
> endpoint over one row. `schemas/playbook.py::PlaybookRead._null_to_declared_default`
> is the fix: a `mode="before"` validator that coerces `None` to the field's
> declared default. **Other Read schemas in this folder likely have the same
> latent gap** — worth auditing.

---

## 6. `api/` — routers and dependencies

### `deps.py` (137 lines) — the most important file in the folder

- `get_current_user` — the standard bearer-token dependency.
- `get_current_user_flexible` — also accepts `?access_token=` as a query param,
  because browsers loading `<img src>` / `<a href>` cannot set custom headers.
  Used by three routes: `files.py`'s file-content route and `skills.py`'s
  file-serve and download routes.
- **`authorize(resource_type, action)`** — the dependency factory used by
  essentially every route. Calls OPA, 403s on denial, then 400s a super_admin
  attempting a tenant-scoped write (`create`/`update`/`delete`/`freeze`/
  `unfreeze`/`deploy`) since they have no tenant to write into.
- `authorize_tenant(action)` — for `resource_type="tenant"`, which has no
  tenant of its own; always passes `tenant_id=None`.
- `require_super_admin` — the plain role gate for the handful of `/platform`
  endpoints that do not fit the `(resource_type, action, tenant_id)` shape.

**When `authorize()` is not enough:** if the decision depends on something only
known after the body is parsed or a row is fetched — e.g. "is this user's
`target_role` admin or user?" — the route calls `core.opa.authorize(...)`
directly. `routes/platform.py` is the example.

### `routes/registry_factory.py` (98 lines) — ⚠️ currently dead code

`make_registry_router(model=, prefix=, tag=)` generates the full CRUD five-pack
for a plain registry: derives the OPA resource type by stripping the trailing
`s` from the tag (`"tools"` → `"tool"`), applies `apply_shared_or_own_tenant`
on list, and **403s any write against a `tenant_id IS NULL` row**
("Platform-shared items cannot be edited").

**Nothing imports it.** `grep -rn "make_registry_router" app/` returns only the
definition. Every registry — including tools and plugins, which its own
docstring names — hand-rolls its endpoints instead, because each grew fields
the generic `RegistryCreate/Update/Read` trio does not cover (`tools.py`:
MCP transport fields and `validate_mcp_config`; `plugins.py`: structured
`exports_*` validation). Both say so in a comment at the top.

So treat this file as **the reference implementation of the pattern, not a
utility you can call**. It is still the clearest single statement of what a
registry route is supposed to do, which is why it is worth reading — but adding
a registry means copying `prompts.py`, the cleanest hand-rolled example, not
invoking the factory. If nobody adopts it, it should probably be deleted.

### Route modules by flow

**Auth & tenancy**
- `auth.py` — `/signup` (creates a tenant, caller becomes its first admin),
  `/login`, `/me`, `/bootstrap-super-admin`.
- `tenants.py` — `GET`/`PUT /tenants/me`, the Norms tab's settings blob.
- `admin_users.py` — admin CRUD over `user`-role accounts inside their own
  tenant. Creating an *admin* is blocked in Rego (`_privileged_user_write`).

**Registries** — `agents.py` (5), `skills.py` (11, incl. zip upload, file
browse, download, fork), `tools.py` + `plugins.py` (via the factory),
`hooks.py` (8, incl. `/handlers` and `/lifecycle-events` discovery),
`prompts.py` (6), `playbooks.py` (6), `personas.py` (9), `policies.py` (8).

> **Route-order gotcha, called out in `policies.py`:** static paths must be
> declared *before* dynamic ones. `/mappings` has to come before `/{policy_id}`
> or Starlette's first-match routing tries to parse `"mappings"` as a UUID and
> 422s before reaching the real handler.

**Deployment** — `projects.py` (19 endpoints — the largest router: CRUD, user
and datasource attachment, intelligence bindings, `available-agents`,
`topology`, `freeze`, `unfreeze`, `deploy`), `datasources.py` (8, incl. the
`connector-types` field-spec endpoint the UI renders forms from).

**Chat** — `chat.py` (7). The SSE streaming endpoint
`POST /conversations/{id}/messages/stream` is the hot path. Plus branch
navigation (`/messages/{id}/siblings`, `/select-branch`).

**Runtime** — `runs.py` (3, incl. `POST /{run_id}/decision` which signals a
Temporal workflow for durable runs, or writes directly onto the row for
in-process ones), `manifests.py` (2), `models.py` (1).

**Super Admin** — `platform.py` (18: tenant lifecycle, admin assignment, role
changes, overview KPIs, usage, cost, health, audit, model routes),
`platform_catalog.py`, `platform_rules.py`.

**Aggregation** — `admin_overview.py` (1 endpoint, a read-side convenience so
the frontend does not fire four list calls per render).

**Files** — `files.py` (3).

---

## 7. `services/` — business logic

Code lands here when it is shared across routes, or too large to sit in one.

### `hooks.py` (469 lines) — the lifecycle engine

10 stages (`SessionStart`, `UserPromptSubmit`, `PreToolUse`,
`PostToolUse.Success`, `PostToolUse.Failure`, `PreCompact`, `SubagentStart`,
`SubagentStop`, `Stop`, `Notification`), five return directives (`Allow`,
`Deny`, `Modify`, `InjectContext`, `SilentLog`).

`BUILTIN_HOOKS` is a registry populated by the `@builtin_hook` decorator —
`guardrail_interceptor`, `dlp_scrubber`, `pii_redactor`, `telemetry_observer`,
`usage_logger`, `tool_allowlist_guard`, and others. A `python`-type Hook row's
`handler_key` resolves here; **no code is ever stored or eval'd**.

`build_pipeline_for_agent` composes a **fresh `HookManager` per chat turn** from
three scoped sources (global hooks, agent-attached hooks, extras) rather than
sharing a singleton — that is what gives per-turn fault isolation.

### `hook_handlers.py` (192 lines) — the unsafe path, honestly labelled

Executes `http`, `command`, and `mcp_tool` handlers. Its own docstring is blunt:
there is no sandbox beyond a timeout and a fail-open/fail-closed fallback.
**Treat any Hook with `handler_type != "python"` as equivalent to giving whoever
can create Hook rows the ability to run code on the host.** `static_gate()` runs
`blocked_keywords`/`allowed_tools` checks *before* any handler fires,
independent of handler type.

### `agent_runner.py` (351 lines) — chat ↔ runtime adapter

Translates the rich runtime event vocabulary (`plan_ready`, `critique_ready`,
`node_retry`, …) onto the five events the frontend listens for (`stream_start`,
`token`, `tool_call`, `skill_call`, `stream_end`). **Unmapped events are
dropped**, so adding a lifecycle event can never break a deployed frontend.
Also owns where each of the 10 hook stages fires during a turn.

### `agent_run_store.py` (262 lines) — the Observatory write side

Two entry points, and the split matters:

- `PersistingEventSink` writes **while the run is in flight**, composing with
  the SSE queue sink via `CompositeEventSink`. This is why a run that crashes
  mid-flight still shows as `running` with its completed steps, rather than
  vanishing.
- `finalize_run` writes the terminal projection once the graph returns.

Each write opens and closes its own short session inside `asyncio.to_thread` —
holding one open across a multi-minute run would pin a pooled connection.

### `registry_access.py` (114 lines)

Enforces the two §7.2 axes. `assign_access_class` keeps `access_class` in
lockstep with the `tenant_id IS NULL` convention at write time.
`fork_row` implements "fork, don't edit": default/public rows are immutable, so
changing one means copying it into a new `custom` row with `forked_from_id` set.
Every registry's `/fork` endpoint calls it.

### `manifest.py` (156 lines)

The §6.2 resolution algorithm. Wired: resolve bindings → canonicalize → hash →
persist → cache in Redis → return. Deferred and clearly marked: live credential
validation, retrieval-filter compilation, OPA bundle pinning. What it produces
is a real hashed deduplicated capability snapshot; its `policy_bundle` and
`retrieval` fields are honest placeholders.

### `thread.py` (131 lines)

Message-tree traversal. `get_active_thread` walks level by level following only
`is_active_branch=True` messages. Because non-primary agent responses never gain
children, this naturally yields a linear backbone with parallel agent columns
fanned out at each assistant turn.

### Smaller

- **`audit.py`** (47) — `record()`. Synchronous, best-effort, **called after the
  caller's own `db.commit()`** so a failed audit write cannot roll back the
  mutation it describes. Deliberately non-exhaustive: only governance-significant
  actions.
- **`pricing.py`** (33) — resolves `Agent.model_name` to a `ModelRoute` and
  computes real cost from real token counts. Unmatched models fall back to a
  documented non-zero rate rather than $0, so "unpriced usage" does not look
  like "free usage."
- **`mcp_client.py`** (41) — an honest scaffold. `validate_mcp_config` is real
  and enforces transport-specific required fields. Nothing connects. The
  docstring spells out exactly how to make it real.
- **`platform_rules.py`** (73) — seed content for the Platform rules screen.

---

## 8. Where things are *not* finished

Stated plainly, because a KT that oversells is worse than useless. All of these
are documented in the code and in `docs/PLATFORM_ARCHITECTURE.md` §17.

| Area | Reality |
|---|---|
| Datasource connect/sync | Synchronous stub state transitions. No OAuth, no tunnel, no crawler. |
| MCP | Metadata + validation only. No live client. |
| Skill `scripts/` | Stored, never executed. Deliberate. |
| Playbook `guardrails` / `approval_gates` | Stored and displayed, not enforced at runtime. |
| Agent roles | 3 of the spec's 5. Manager is staged for build stage 6; Scheduler-as-code is a real pending refactor (ordering currently lives in LangGraph). |
| Memory | Episodic (`events`) and procedural (skills + playbooks) exist. Working memory (`plans`/`steps`/`verdicts`), semantic (glossary/Qdrant) and §11.6 persona memory do **not**. |
| `Policy.rule_expression` | A display record. Not compiled into real filters. |
| MinIO | A verifiable second copy. Serving still reads local `dir_path`. |

---

## 9. Conventions cheat sheet

Hand this page out on its own if nothing else.

1. **Two-layer authz.** `Depends(authorize(type, action))` for the coarse check,
   `apply_shared_or_own_tenant` / `own_tenant_filter` for the rows. Both, always.
2. **`tenant_id IS NULL` means platform-shared** — visible to all, editable by
   none. Every write path must 403 on it.
3. **super_admin has `tenant_id = None`.** Every tenant filter must special-case
   it or it sees nothing; every tenant-scoped write must reject it or it writes
   `NULL`.
4. **Fail closed.** OPA errors deny. Redis errors are swallowed (lossy by
   design). Know which posture applies to what you are touching.
5. **`exclude_unset=True` on updates.** Omitted ≠ cleared.
6. **`model_dump()` recurses** into nested Pydantic models — you do not need to
   dump nested lists by hand before writing to a JSON column.
7. **Enum-ish values are strings** with a Pydantic `pattern`, not DB enums, so
   adding one is schema-only.
8. **Static routes before dynamic routes** in a router.
9. **New FK to `users.id` on a table that already has one?** Add
   `foreign_keys=[...]` to the relationship, or `configure_mappers()` raises
   `AmbiguousForeignKeysError` — and it fires on the *first query anywhere in
   the app*, not necessarily one touching your table. `models/agent.py::owner`
   documents a real instance of this.
10. **No stored or eval'd code**, anywhere, for skills/plugins/python-hooks.
    `handler_key` strings resolve to vetted in-repo functions. The three
    non-python hook types are the deliberate, documented exception.

### Adding a new registry kind — the checklist

1. `models/<thing>.py` — inherit `RegistryMixin, TenantScopedMixin, Base`.
2. Add the import to `models/__init__.py` **and** `__all__`.
3. `alembic/versions/00NN_*.py` — new revision, `down_revision` = current head.
4. `schemas/<thing>.py` — `Create` / `Update` / `Read`.
5. `api/routes/<thing>.py` — copy `prompts.py`; wire `_visible_or_404`,
   `apply_shared_or_own_tenant`, and the `/fork` endpoint.
6. `main.py` — `include_router`.
7. `policies/authz.rego` — usually **nothing to do**; the generic admin rules
   cover any resource type not in `_tenant_resource_types`. Only touch it if
   role `user` needs read access, which means adding to `_user_readable_types`.

---

## 10. Reading order for a new joiner

Day 1, in this order:

1. `core/config.py` — the shape of everything.
2. `core/database.py` + `core/security.py` — 92 lines total.
3. `policies/authz.rego` — the actual permission rules, in one file.
4. `core/opa.py` + `api/deps.py` — how that Rego reaches a route.
5. `core/tenant_scope.py` — the other half of authorization.
6. `models/mixins.py` — then any one registry model.
7. `api/routes/prompts.py` — the canonical route module, end to end.
8. `api/routes/registry_factory.py` — the same thing, generated.

Then pick a small ticket rather than reading further.

---

## Related docs

- `docs/AUTHORIZATION.md` — the three-role model in full.
- `docs/AGENT_RUNTIME.md` — `app/agents/`, deliberately out of scope here.
- `docs/SKILL_STANDARD.md` — the skill folder format and the no-code-execution rationale.
- `../docs/PLATFORM_ARCHITECTURE.md` — target architecture; §17 is the gap map.
