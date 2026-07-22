# Milestone 1 — Execution Checklist (run these on your own machine)

Same split as Milestone 0: everything file-based (code, config, migrations, scripts) is written and validated as far as this sandbox can validate it — no Docker, no live Postgres/Keycloak/Qdrant/MinIO here. The pieces that talk to real infra need your machine. Read `docs/MILESTONE_0_CHECKLIST.md` first if you haven't already gone through it.

## What Claude built this milestone

- **Auth**: OIDC/JWT validation against Keycloak's JWKS endpoint (`backend/app/core/security.py`), signature/issuer/audience/expiry all checked, with 12 passing unit tests (`backend/tests/test_security.py`) using a throwaway RSA keypair — no live Keycloak needed for those to mean something.
- **RBAC**: `backend/app/core/permissions.py` reads `v_user_effective_permissions` (deny-overrides-allow), with the combination logic itself unit-tested (`backend/tests/test_permissions.py`). Tenant scoping is structural, not a convention: `TenantScopedRepository` (`backend/app/repositories/base.py`) requires `tenant_id` as a parameter on every `list`/`get`/`create` call — there's no code path that queries without it.
- **Tenant/project/user CRUD**: `backend/app/api/v1/{tenants,projects,users}.py`, backed by `backend/app/services/{tenant,project,user}_service.py`.
- **Project bootstrap event** (Part I §5.2): `backend/app/services/bootstrap.py` — Qdrant collection + MinIO prefixes + default virtual clusters, all in one call right after project creation.
- **User invite**: creates a real Keycloak user via the Admin API (`backend/app/services/keycloak_admin.py`) with a temporary password (no SMTP configured yet, so the password comes back in the API/UI response for you to relay — see the note printed there).
- **Audit log**: every mutation writes to `audit_log` in the same transaction (`backend/app/core/audit.py`).
- **Frontend**: OIDC login (Authorization Code + PKCE via `react-oidc-context`) against the new `valya-frontend` public client, tenant list/create, project list/create, user invite form. `tsc -b` and `vite build` both pass clean.
- **Three real gaps found and fixed** while implementing this (all as new numbered SQL scripts, nothing rewritten in place):
  - `config_db_scripts/006_virtual_clusters.sql` — the `virtual_clusters` table didn't exist despite being required by Part I decision #14 and the bootstrap step.
  - `config_db_scripts/007_fix_tenant_admin_permission_grant.sql` — 004's tenant_admin seed grant had a tautological `WHERE` clause that silently gave tenant_admin every permission, including `tenant.admin`.
  - `config_db_scripts/008_seed_bootstrap_admin_role.sql` — the bootstrap super_admin (`admin@valya.local`) had the display-only enum label but no actual `user_roles` grant, so it couldn't have done anything once RBAC was wired up.
- `docker/scripts/apply-schema.sh` now globs and applies every `NNN_*.sql` file automatically instead of a hardcoded list.
- `docker/scripts/bootstrap-keycloak.sh` rewritten: creates the `valya-backend` confidential client and **writes its secret into `docker/.env` automatically**, grants it the `realm-management manage-users` role, creates the public `valya-frontend` client (PKCE), wires an audience client-scope so the backend's audience check has something to verify, and creates a real Keycloak user for the bootstrap admin.

## Highest-risk areas for a first real run

Everything above was validated as far as syntax checks, unit tests, and running the stub services directly allow — but **none of the following has ever executed against real infra**, only against mocks or not at all. If something breaks on first run, look here first:

- The async SQLAlchemy/asyncpg session layer (`backend/app/core/db.py` and every repository) — never hit a real Postgres.
- The Qdrant client calls in `backend/app/services/qdrant_admin.py` (`create_collection`, `create_payload_index`, named-vector config) — never hit a real Qdrant.
- The MinIO/boto3 calls in `backend/app/services/storage.py` — never hit real MinIO.
- The Keycloak Admin API calls in `backend/app/services/keycloak_admin.py` — never hit a real Keycloak.
- `docker/scripts/bootstrap-keycloak.sh`'s `kcadm.sh` commands (client-scope + protocol-mapper creation especially) — syntax-checked only; Keycloak's exact JSON shapes for `-s attributes=...` / `-s config=...` are easy to get subtly wrong and I have no way to catch that without a live realm.

## Steps

### 1. Pull in the new schema + Keycloak setup

```bash
cd docker
./bootstrap.sh
```

If infra is already up from Milestone 0, this re-applies the schema (now 001-008 — new files 006/007/008 apply cleanly; 001-005 are unchanged from before) and re-runs the now-much-larger Keycloak bootstrap. If you'd rather not re-run everything, apply just the new files by hand:

```bash
docker compose exec -T postgres psql -U valya -d valya_config < ../config_db_scripts/006_virtual_clusters.sql
docker compose exec -T postgres psql -U valya -d valya_config < ../config_db_scripts/007_fix_tenant_admin_permission_grant.sql
docker compose exec -T postgres psql -U valya -d valya_config < ../config_db_scripts/008_seed_bootstrap_admin_role.sql
./scripts/bootstrap-keycloak.sh
```

**Watch the output of `bootstrap-keycloak.sh` for two things:**
- `KEYCLOAK_BACKEND_CLIENT_SECRET` being written into `docker/.env` (the backend needs this for the invite flow's Admin API calls).
- A one-time printed **temporary Keycloak password for `admin@valya.local`** — you'll need it for the very first login.

### 2. Bring up the app layer

```bash
docker compose --profile app up -d --build
```

Verify:
```bash
curl http://localhost:8000/health   # {"status":"ok","service":"backend"}
open http://localhost:3000          # should show the sign-in page
```

### 3. First login (bootstraps the seeded super_admin)

1. Go to http://localhost:3000, click Sign in.
2. Log in as `admin@valya.local` with the temporary password printed in step 1. Keycloak will require setting a real password.
3. You should land back on the KN_Valya tenant list, signed in. Behind the scenes: this is the "first login bootstraps OIDC subject" moment (Part I §5.1) — `backend/app/core/context.py` matched the token's email to the unlinked seed row from `config_db_scripts/002` and linked it permanently.

### 4. Create the first tenant, then a project

1. In the UI, create a tenant (any slug/name). This should succeed — the bootstrap admin has the global `tenant.admin` grant from `008_seed_bootstrap_admin_role.sql`.
2. Click into it, create a project. This triggers the bootstrap event — verify all three side effects actually happened:
   - **Qdrant**: http://localhost:6333/dashboard → collection `project_<uuid>` exists with `dense_text`/`sparse_text`/`image_clip` vectors.
   - **MinIO**: http://localhost:9001 → bucket `valya` has `raw/<tenant-slug>/<project-slug>/.keep`, same for `interim/` and `images/`.
   - **Postgres**: `docker compose exec postgres psql -U valya -d valya_config -c "SELECT name, is_system FROM valya.virtual_clusters;"` → three rows (`All`, `Last 90 days`, `My team`).

### 5. Invite a user

1. From the project page, invite a user by email/name/role.
2. The response includes a temporary password — note it (this is the "no SMTP yet" tradeoff documented in `keycloak_admin.py`).
3. Verify in the Keycloak admin console (http://localhost:8081) that a matching user now exists in the `valya` realm.
4. Verify in Postgres: `SELECT email, role, auth_subject FROM valya.users;` — the invited user should already have `auth_subject` populated (invite flow sets it directly, unlike the bootstrap admin which needed the first-login fallback).

### 6. Verify the RBAC gate (the milestone's explicit ask: "rejects a cross-tenant query in a manual test")

1. Invite a second user as `tenant_admin` in **tenant A**.
2. Have them log in, then try to `GET /api/v1/tenants/<tenant-B-id>` for a **different** tenant B (via the browser dev tools Network tab, or `curl` with their access token). Expect `403 Missing permission: tenant.read` — their `user_roles` grant is scoped to tenant A only, so `v_user_effective_permissions` has nothing for tenant B.
3. As a sanity check on the flip side, confirm they *can* read/list projects within their own tenant A without issue.

## Known deferrals (by design, not oversight)

- No SMTP → invite passwords are relayed manually, not emailed. Switch `keycloak_admin.py`'s `create_user` to call `execute-actions-email` once SMTP is configured on the realm.
- Vault is still in dev mode (Milestone 0 already flagged this — still true, still needs fixing before anything beyond local dev).
- No connectors, pipelines, or document upload yet — that's Milestone 2 onward.
- No project-level admin UI polish (Pipeline Editor, Document Inspector, Run Observatory) — Milestone 3+, deliberately not built early per the plan's pacing notes.
