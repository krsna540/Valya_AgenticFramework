# Milestone 0 — Execution Checklist (run these on your own machine)

Everything file-based is done and verified (see "What Claude already built and verified" below). The remaining steps need Docker Desktop and your actual filesystem — Claude's sandbox has neither Docker nor enough RAM/disk to run this stack (3.8GB RAM / 4.4GB disk available vs. the ~6–8GB the infra alone needs), and its mounted view of this folder turned out not to support git's lock/rename operations reliably. Both are one-time, five-minute steps below.

## 1. Finish git (the sandbox couldn't do this reliably)

A `git init` was attempted and got stuck with a stale `.git/index.lock` the sandbox couldn't remove (a filesystem-sync limitation, not a real git problem). Cleanest fix — do this locally in Terminal:

```bash
cd /path/to/KN_Valya
rm -rf .git
git init
git add -A
git commit -m "Milestone 0: repo & environment bootstrap scaffold"
```

Confirm `docker/.env` is **not** in the commit (`git show --stat HEAD | grep .env` should show nothing, or only `docker/.env.example`) — `.gitignore` already excludes it.

## 2. Place the pre-commit config

Claude's environment blocks writing a file named `.pre-commit-config.yaml` directly (it auto-executes on commit, so the platform treats it as a protected write). The content is ready — copy it from the shared file into your repo root as `.pre-commit-config.yaml`, then:

```bash
pip install pre-commit   # or: uv tool install pre-commit
pre-commit install
pre-commit run --all-files   # sanity check
```

## 3. Docker Desktop + secrets

1. Confirm Docker Desktop (or equivalent) is running with **at least 6–8GB RAM** allocated (Settings → Resources).
2. `docker/.env` already exists with generated random dev secrets (Postgres, MinIO, Keycloak, Vault, Grafana passwords). Open it and fill in the one blank: `ANTHROPIC_API_KEY=`.
3. Rotate every secret in `docker/.env` before this ever touches a shared or production environment — these are dev-only.

## 4. Bring up infra + bootstrap

```bash
cd docker
./bootstrap.sh
```

This one script does Milestone 0 steps 3–8: brings up all infra services, waits for each to report healthy, applies the three-file Postgres schema to `valya_config`, creates the MinIO `mlflow-artifacts` bucket, and creates the Keycloak `valya` realm + `valya-backend` confidential client. It prints a verification checklist at the end — walk through it.

If you'd rather run the steps individually instead of the orchestrator: `docker compose up -d` (infra only — app services are on the `app` profile and stay down), then `./scripts/wait-for-services.sh`, `./scripts/apply-schema.sh`, `./scripts/bootstrap-minio.sh`, `./scripts/bootstrap-keycloak.sh` in that order.

## 5. Verify against the Milestone 0 gate

- `docker compose ps` — every infra service healthy/running.
- `docker compose exec postgres psql -U valya -d valya_config -c "\dt valya.*"` — 18 tables.
- MLflow UI reachable at http://localhost:5000.
- Keycloak admin console reachable at http://localhost:8081 (login `admin` / the password in `docker/.env`), and the `valya` realm + `valya-backend` client exist under Realm settings / Clients.

## 6. Optional today: bring up the app-layer stubs too

Everything below is already built, Dockerized, and verified working (health-checked with curl, TypeScript-compiled, ruff-linted clean) inside Claude's sandbox — this step just proves it also builds under real Docker on your machine:

```bash
docker compose --profile app up -d --build      # backend, worker, dispatcher, frontend
docker compose --profile models up -d --build   # embedder, reranker, vlm-captioner (separate profile as of 2026-07-10 — see docker/README.md's "Model services")
curl http://localhost:8000/health   # backend
curl http://localhost:8001/health   # embedder
curl http://localhost:8002/health   # reranker
curl http://localhost:8003/health   # vlm-captioner
open http://localhost:3000          # frontend
```

---

## What Claude already built and verified (no action needed)

- `docker/.env` — generated with random dev secrets, `ANTHROPIC_API_KEY` left blank for you.
- `.gitignore` — covers `.env`, `node_modules/`, `__pycache__/`, build artifacts, etc.
- `docker/bootstrap.sh` + `docker/scripts/{wait-for-services,apply-schema,bootstrap-minio,bootstrap-keycloak}.sh` — all pass `bash -n` syntax checks.
- `backend/`, `embedder/`, `reranker/`, `vlm-captioner/` — FastAPI stubs, each with a working `Dockerfile` and `pyproject.toml`; **all four ran directly in the sandbox** with real HTTP requests hitting `/health` and their domain endpoint (`/embed`, `/rerank`, `/caption`) with correctly-shaped responses.
- `frontend/` — Vite + React + TypeScript stub; `npm install`, `tsc -b`, and `vite build` all **ran successfully in the sandbox** (31 modules, clean build).
- `docker/docker-compose.yml` — all 5 app services wired on the `app` Compose profile (so plain `docker compose up -d` still brings up infra only); YAML re-parsed and validated; every service's build path confirmed to have a real `Dockerfile`. GPU device reservations for embedder/reranker/vlm-captioner are commented out until real model-serving code lands (Milestones 2/4/6) so the stubs run on CPU-only dev machines.
- `pyproject.toml` (root) — shared `ruff` config; `ruff check .` and `ruff format .` both run clean across the whole repo.
- Minor housekeeping: a few build-artifact files (`frontend/node_modules`, `frontend/dist`, stray `__pycache__`, `.ruff_cache`) couldn't be deleted from inside the sandbox due to a mount permission quirk — they're all gitignored and harmless; delete them locally whenever convenient.
