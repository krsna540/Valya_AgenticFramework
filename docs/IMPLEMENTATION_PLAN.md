# KN_Valya — End-to-End Implementation Plan (Solo Build Path)

> Companion to `KN_Valya_Complete_Architecture.md` (the frozen architecture — Parts I & II, ADR-001/002). This document does not re-decide anything architectural; it sequences the already-locked 10-milestone roadmap (Part I §10) into concrete, executable steps for a solo build. If a step here seems to contradict the architecture doc, the architecture doc wins — update this plan, not the other way around.

## How to use this document

Each milestone below has: a goal, a definition of done (DoD) copied/expanded from the frozen roadmap, an ordered list of concrete steps, the exact files/folders you'll touch, and a verification gate — a check you run before allowing yourself to move to the next milestone. As a solo builder, the discipline that matters most is **not starting milestone N+1 before milestone N's gate passes**. The architecture is wide (ingestion + agent runtime + 6 self-hosted services); the failure mode for a solo build is 40% progress on 10 things instead of 100% on 4.

Work happens in one repo (monorepo) — the `docker-compose.yml` and `config_db_scripts/` already assume this.

---

## Milestone 0 — Repo & Environment Bootstrap (not in the frozen roadmap; do this first)

**Goal:** a running local infra stack and a repo skeleton the rest of the milestones drop code into.

**Steps:**
1. Confirm Docker Desktop (or equivalent) is installed and has enough resources allocated (the stack brings up Postgres, Qdrant, Redis, MinIO, Temporal, Keycloak, Vault, MLflow, Prometheus, Grafana, OTel Collector, Traefik — budget ~6–8GB RAM for infra alone, before GPU services).
2. `cp docker/.env.example docker/.env` and fill in real values (don't leave placeholder secrets even in local dev — bad habits compound).
3. `cd docker && docker compose up -d` — bring up only the infra services (app-layer services are commented out, per `docker/README.md`).
4. Verify every service in the table in `docker/README.md` is reachable (Temporal UI :8080, Keycloak :8081, Vault :8200, MLflow :5000, MinIO Console :9001, Grafana :3001, Prometheus :9090, Qdrant :6333/dashboard).
5. Apply the Postgres schema: `psql "$DATABASE_URL" -f config_db_scripts/001_create_schema.sql`, then `002_seed_reference_data.sql`, then `003_indexes_and_perf.sql` (in that order — see `config_db_scripts/README.md`).
6. Create the Keycloak `valya` realm + an OIDC client for the backend (manual, one-time, via the Keycloak admin console).
7. Create the MinIO bucket MLflow needs: `mc mb minio/mlflow-artifacts`.
8. Vault is in dev mode by default — fine for now, but note in your own tracker that this must change before anything beyond local dev.
9. Repo skeleton — create the five app-layer folders the Docker Compose file already has env wiring for, even if they're just stubs today:
   - `backend/` (FastAPI gateway + Config Service + Retrieval Service + Agent Runtime)
   - `frontend/` (React admin + user UI)
   - `embedder/` (BGE-M3 serving)
   - `reranker/` (BGE-reranker-v2-m3 serving)
   - `vlm-captioner/` (Qwen2-VL-7B serving)
   - Add a minimal `Dockerfile` to each (even a "hello world" FastAPI/uvicorn stub) so `docker compose up` can eventually bring up the whole stack. You'll flesh these out milestone by milestone.
10. Pick and set up your Python tooling once, now: dependency manager (uv or poetry), linter/formatter (ruff), pre-commit hooks. Retrofitting this after 5 services exist is worse than doing it once at the start.

**Verification gate:** `docker compose ps` shows every infra service healthy; you can `psql` into the config DB and see the 18 tables from `001_create_schema.sql`; you can log into the MLflow UI and Keycloak admin console.

---

## Milestone 1 — Foundations (frozen roadmap: Week 1–3)

**DoD (from architecture doc):** Postgres schema deployed; FastAPI gateway with auth (OIDC) and RBAC middleware; tenant/project/user CRUD; React shell (tenant + project list, user invite); infra running locally via Docker Compose.

**Steps:**
1. **Auth first, not last.** Wire FastAPI ↔ Keycloak OIDC before writing any business endpoint — every other milestone assumes `tenant_id`/`user_id`/`groups[]` are already on the request context. Use a standard OIDC middleware (e.g., `fastapi-oidc` or hand-rolled JWT validation against Keycloak's JWKS endpoint).
2. Build the RBAC middleware: enforce `tenant_id` as a required filter at the ORM/query-builder level, not by convention in each endpoint (Part I §8.1 — this is a locked cross-cutting rule, not a suggestion).
3. Config Service CRUD, in this order (each depends on the last via FK): `tenants` → `projects` → `users` / `project_memberships`.
4. Wire the **project bootstrap event** (Part I §5.2): creating a project must trigger Qdrant collection creation (`project_{uuid}`, named vectors `dense_text`/`sparse_text`/`image_clip` declared up front — §9.3), MinIO prefix creation (`raw/`, `interim/`, `images/`), and default virtual clusters (`All`, `Last 90 days`, `My team`). Get this right now — every later ingestion milestone assumes it already happened.
5. React shell: tenant list, project list, user invite flow. Don't build the Pipeline Editor or Document Inspector yet — those are Milestone 3+.
6. Audit log: every mutation in this milestone should already be writing to `audit_log` (Part I decision #19) — establish the pattern here so it's not bolted on later.

**Verification gate:** you can create a tenant, invite a user, have them log in via Keycloak, create a project, and see a Qdrant collection + MinIO prefixes appear automatically. RBAC middleware rejects a cross-tenant query in a manual test.

---

## Milestone 2 — Single Pipeline End-to-End (Week 4–6) — **the spine**

**DoD:** Canonical DOM schema published; one extractor (PDF); bare-minimum pipeline (extract → chunk parent-child only → embed → index); upload UI works; user can ask a question and get a text answer with citations.

This is the highest-leverage milestone in the whole plan — everything else is enrichment on top of this working end-to-end. Treat it as its own mini-project.

**Steps:**
1. Publish the DocumentDOM JSON Schema (Part I §4) as an actual schema file (`jsonschema` or `pydantic` model) — this is the one contract every future extractor must satisfy, so get the shape right before writing the PDF extractor against it.
2. Stand up Temporal: define the `IngestDocument` workflow skeleton with the stages that exist so far as activities (extract → chunk → embed → index — you're deliberately skipping caption/enrich/contextualize/RAPTOR for this milestone).
3. PDF extractor activity: produce a DocumentDOM from a real PDF (tables as markdown+JSON twin, but don't worry about images yet).
4. Chunker activity: parent-child only (§6 Stage 5), no contextualization, no RAPTOR — write `chunks` rows to Postgres.
5. Embedder service (`embedder/` from Milestone 0): stand up BGE-M3, expose a simple `/embed` endpoint. Wire the embed activity to call it.
6. Indexer activity: upsert into the project's Qdrant collection (dense + sparse from BGE-M3).
7. Upload flow: object-store upload → `documents`/`document_versions` rows → outbox event → dispatcher → `Temporal.start_workflow`.
8. Retrieval Service (bare version): dense+sparse search, RRF fuse, **no reranker yet** (that's Milestone 4) — return top-k with citations (doc_id, section_path, page, source_uri).
9. Minimal chat endpoint: retrieval + LLM call (Claude/GPT-class, via the self-hosted MLflow AI Gateway — see Part I §12 "Chat/generation LLM & embedding access path", revisited 2026-07-08) + citation rendering in the UI.

**Verification gate:** upload a real PDF through the UI, watch it move through the Temporal UI as a workflow, ask a question about its content in the chat UI, get an answer with a citation that links back to the right page. If this doesn't work end-to-end, nothing after this milestone matters yet.

---

## Milestone 3 — Pipeline Configurability (Week 7–8)

**DoD:** YAML editor in admin UI with schema validation and dry-run; versioned pipelines with bindings table and draft/active/deprecated lifecycle; trigger dispatcher (outbox → Redis → Temporal); Run Observatory (live status, retry, DLQ).

**Steps:**
1. Pipeline YAML schema + validator, matching the skeleton in §9.2. Store both `yaml_spec` (text) and `parsed_spec` (JSONB).
2. Pipeline Editor UI: Monaco YAML editor + side-by-side DAG render (this is one of the three load-bearing admin screens per §11 — don't skimp on it).
3. Dry-run endpoint: run the pipeline against a sample doc, return each stage's output without persisting.
4. Promote/deprecate lifecycle + the `(project, datasource, doc_type) → pipeline` binding table (§5.5).
5. Formalize the trigger dispatcher as its own service (outbox reader → Redis Streams → `Temporal.start_workflow`, idempotent by `workflow_id`).
6. Run Observatory: per-tenant throughput, success rate, p95 stage latency, drill-into-failed-run, DLQ inspector, retry button.

**Verification gate:** edit a pipeline's YAML, dry-run it against a sample doc, promote it, watch a real document get bound to it and processed; kill a worker mid-run and confirm Temporal retries and the Observatory shows the failure with a working retry button.

---

## Milestone 4 — Retrieval Quality (Week 9–10)

**DoD:** contextual chunking; hybrid retrieval (dense+sparse+RRF — you already have the dense+sparse part from Milestone 2, add RRF fusion properly if you shortcut it earlier); cross-encoder reranking; parent promotion; modality balance.

**Steps:**
1. Contextualization activity (§6 Stage 6): cheap LLM call per child chunk, cached by `(parent_chunk_id, chunk_hash)`. This is the single biggest quality lever (35–49% failure-rate reduction per Anthropic's published research) — don't cut corners on caching or you'll re-pay the LLM cost on every reindex.
2. Reranker service (`reranker/` from Milestone 0): stand up BGE-reranker-v2-m3, top-50 → top-10.
3. Parent promotion + dedupe logic in the Retrieval Service (§7.3 Step 5).
4. Modality balance cap (30% per modality unless query is explicitly visual) — this can be a no-op until Milestone 6 adds images, but wire the cap now so you don't forget it later.

**Verification gate:** run the same eval question before/after contextualization and reranking are wired in; you should see qualitatively better citations and fewer "almost right" retrievals.

---

## Milestone 5 — RAPTOR + Virtual Clusters (Week 11–12)

**DoD:** RAPTOR summarizer stage; per-layer query weighting by intent; `virtual_clusters` table + UI; payload-index discipline enforced.

**Steps:**
1. RAPTOR activity (§6 Stage 7): UMAP→10d→GMM-with-BIC clustering over contextualized child embeddings, grounded-summary prompt, `source_chunk_ids` stored, 3 levels max.
2. Query-intent classifier (small router model, ~50ms) + the layer-weighting table from §7.3 Step 3 (factual/conceptual/thematic).
3. `virtual_clusters` table + admin UI for create/edit/select; apply as Qdrant `must` clauses, ACL always AND-ed.
4. Audit every payload field used in a filter has a declared Qdrant index (§B.3.1 — forgetting this silently degrades to a full scan).

**Verification gate:** ask a thematic "what does the corpus say about X overall" question and confirm a RAPTOR summary chunk is what answers it, with `source_chunk_ids` traceable back to real leaves.

---

## Milestone 6 — Multimodal (Week 13–14)

**DoD:** image extraction during DOM build; VLM-based contextual captioning; SHA-256-keyed image storage with thumbnails; multimodal retrieval.

**Steps:**
1. Extend the PDF extractor (and any other extractor) to pull images into `object_store://images/{tenant}/{project}/{doc}/v{n}/{sha256}.{ext}` with a thumbnail twin.
2. `vlm-captioner/` service (Qwen2-VL-7B): contextual captions using surrounding text + breadcrumbs, OCR, cached by SHA-256.
3. Embed captions+OCR via the same text embedder (no separate image-text index for the default path — CLIP is optional, add only if you'll need "find similar diagrams" queries).
4. Turn on the modality-balance cap you stubbed in Milestone 4.

**Verification gate:** upload a PDF with diagrams, ask a question whose answer is a diagram, confirm the citation includes a thumbnail and the caption is contextually correct (not generic).

---

## Milestone 7 — Connectors (Week 15–18)

**DoD:** SharePoint, Confluence, S3, SQL, NoSQL connectors — one per sprint, each implementing the DocumentDOM contract, each with ACL passthrough.

**Steps (repeat per connector):**
1. Implement the connector as a Temporal worker that enumerates the source and emits `documents`/`document_versions` rows + raw bytes to object store, deduped by `content_hash`.
2. Map the source's native structure into DocumentDOM (a SQL row becomes a single synthetic section, per §4).
3. Carry ACL through from the source system into `acl_groups[]` — no separate ACL store (§8.1).
4. Health-check endpoint for the connector (§5.3).

**Verification gate:** for each connector, a scheduled sync pulls new/changed content, dedup works (re-syncing unchanged content doesn't create new versions), and a document sourced through that connector is queryable with correct ACL enforcement.

---

## Milestone 8 — Agents (Week 19–22) — the whole of Part II

This is the biggest milestone by far — it's Part II of the architecture doc in full. Don't attempt it as one block; the sub-steps below are already roughly dependency-ordered.

**DoD (frozen roadmap, Part II-detailed):** Agent & Registry Console; Project Agent Configuration (freeze workflow); LangGraph runtime + Temporal envelope; tool framework (native + internal MCP); per-agent/persona retrieval policies; Agent Observatory dashboard.

**Steps:**
1. Extend the `agents` table + add `personas`, `tools`, `skills`, `hooks`, `role_permissions`, `project_registry_bindings`, `project_agent_configs`, `usage_ledger` (§A2.14 — this is schema work, do it before any runtime code).
2. Agent & Registry Console (admin UI): CRUD for agent skeletons, personas, tools registry (native + internal MCP), skills registry, hooks registry — all versioned/immutable-per-version like pipelines (§A2.4).
3. Project Agent Configuration: draft → role-mapping → dry-run → promote (freeze) workflow (§A2.5) — the exact analog of pipeline binding, applied to agents.
4. LangGraph runtime: session graph, checkpointing (Postgres checkpointer, chunk text passed by reference — never duplicated into graph state, §A2.9.1), streaming, interrupt/resume.
5. Temporal envelope around LangGraph for long tasks / HITL pauses (§A2.8 #2).
6. Hooks layer: `SessionStart → PreAgentCall → PreToolUse → [tool] → PostToolUse → PostAgentCall → ... → SessionEnd`.
7. Tools registry with semantic retrieval (not full-catalog stuffing) — native functions + internal MCP servers only, no public MCP registry reach (§A2.8 #5–6).
8. **Agentic memory — build the memU adapter now.** Per ADR-002, memU is the default (`pip install memu-py`), implementing `write`/`search`/`consolidate` over its Resource→Item→Category layers, with RAG-mode search hitting a dedicated Qdrant namespace `mem_{tenant}_{project}` and LLM-mode reading memU's structured files directly. Keep the interface generic enough that Mem0/Zep/Graphiti can be swapped in later per `memory_policy.backend` — don't hardcode memU calls into agent code (§A2.9.2).
9. RBAC enforcement at `PreToolUse`/`PreAgentCall` (Simple RBAC / Sandhu model, no ABAC — §A2.8 #13).
10. Rate limiting (Redis token-bucket) + metering (`SessionStart` tagging → `usage_ledger` rollup) (§A2.8 #14–15).
11. MLflow 3.10 wiring: Tracing, Evaluation (RAGAS, RLC, persona-consistency, τ-bench-style), Prompt Registry, full governance AI Gateway usage (traffic routing, budget alerts, usage dashboards — §A2.6.2, §A2.16). Basic LLM routing already exists as of Milestone 2/4 via the AI Gateway built into the `mlflow` service (`docker/scripts/bootstrap-mlflow-gateway.sh` creates the `chat`/`contextualizer` routes); this item is the fuller observability/evaluation layer on top of it, not the first gateway wiring.
12. Agent Observatory dashboard: stats + quality + approval queue (§A2.6) — third load-bearing agent-runtime screen.
13. Feedback loop: collect → evaluate → update (GEPA prompt optimization, distilled episodic write-back, candidate skills) → gated redeployment, nothing auto-promotes (§A2.10).
14. User flow UI: project picker → agent picker (frozen-config-filtered) → persona → language → chat (§A2.7) — this is the whole User Flow from your original two-flow requirement; it should feel thin because almost all the complexity lives in the admin config above it.

**Verification gate:** as a project admin, enable a specific agent+persona+tool subset for a project, freeze it (v1), then as a test user in a role that's allowed, run a chat session that retrieves, calls a tool, writes to memU, and shows up correctly in the Agent Observatory with cost/latency/quality numbers. As a user in a role that's *not* allowed, confirm the agent doesn't even appear in their picker.

---

## Milestone 9 — Production Hardening (Week 23–24)

**DoD:** lifecycle policies enforced by sweeper jobs; DR drills; cost dashboard per tenant; SLO dashboards + alerting.

**Steps:**
1. Daily sweeper job: apply `lifecycle_policies` to object store + Postgres (interim artifacts default 30d, raw archived beyond 1y).
2. Right-to-erasure path: delete a document → cascade to versions/chunks/Qdrant points/image files, audit retains action only.
3. DR drills: Postgres replica + logical backups, Qdrant snapshots, MinIO cross-region replication, monthly re-ingest-from-raw test.
4. Cost dashboard: extend the Agent Observatory's usage_ledger view to a per-tenant chargeback dashboard.
5. SLO dashboards + alerting in Grafana/Prometheus (already running from Milestone 0) — wire real alert rules, not just dashboards.

**Verification gate:** simulate a full Postgres or Qdrant loss and successfully restore from snapshot/backup in a non-prod environment; trigger a right-to-erasure and confirm every downstream system is actually clean.

---

## Milestone 10 — Reindex & Migration Tooling (Week 25–26)

**DoD:** safe reindex on pipeline-version bump; embedding-model migration playbook; per-tenant export/import.

**Steps:**
1. Reindex trigger: pipeline change → re-emit `document.reindex` events → new `pipeline_version` upserted → sweeper deletes stale-version points (§5.9) — zero downtime.
2. Embedding-model migration playbook: parallel collection, dual-write, cutover, decommission old collection.
3. Per-tenant export/import tooling (useful for both DR and customer offboarding/onboarding).

**Verification gate:** bump a pipeline version on a project with real data, reindex it live while users are querying, confirm zero downtime and that stale-version points are swept afterward.

---

## Suggested Repo Layout

```
KN_Valya/
├── docker/                  # already exists — infra compose, env, configs
├── config_db_scripts/       # already exists — Postgres DDL
├── docs/                    # already exists — architecture + this plan
├── backend/
│   ├── config_service/      # tenants/projects/users/connectors/pipelines CRUD
│   ├── retrieval_service/   # hybrid search, rerank, parent-promotion, packing
│   ├── agent_runtime/       # LangGraph + Temporal envelope + hooks + tools + memU adapter
│   ├── trigger_dispatcher/  # outbox -> Redis Streams -> Temporal
│   ├── workers/             # extractor, enricher, chunker, captioner, raptor, indexer
│   └── connectors/          # sharepoint, confluence, sql, nosql, s3
├── frontend/
│   ├── admin/                # Pipeline Editor, Document Inspector, Run Observatory,
│   │                          # Clusters & Connectors, Agent & Registry Console,
│   │                          # Project Agent Configuration, Agent Observatory
│   └── user/                  # project picker, agent/persona/language picker, chat, citations
├── embedder/                # BGE-M3 serving
├── reranker/                 # BGE-reranker-v2-m3 serving
└── vlm-captioner/            # Qwen2-VL-7B serving
```

## Pacing Notes for a Solo Build

- Milestone 2 (the spine) is intentionally the most detailed above — resist adding contextualization, RAPTOR, images, or connectors until it's genuinely working. A working PDF-in, cited-answer-out loop is the thing that de-risks everything else.
- Milestone 8 (Agents) is roughly as much work as Milestones 1–7 combined. Budget accordingly — the 4-week frozen estimate assumes a team; solo, treat it as its own multi-month project once you arrive there.
- The five app-layer Dockerfiles (`backend`, `frontend`, `embedder`, `reranker`, `vlm-captioner`) can stay minimal stubs through Milestone 2 — don't over-invest in container polish before there's real service code to containerize.
- Re-read the relevant architecture section *before* starting each milestone, not after — the locked decisions (§12 in Part I, §A2.8 in Part II) exist specifically to stop you from re-litigating settled tradeoffs mid-build.

## Starting Right Now

If you're beginning today: Milestone 0, steps 1–8 (bring the infra stack up, apply the schema, confirm every service is reachable). That's a same-day task and it's the prerequisite for literally everything else in this plan.
