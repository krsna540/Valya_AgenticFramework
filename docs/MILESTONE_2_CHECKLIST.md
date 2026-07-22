# Milestone 2 — Execution Checklist (run these on your own machine)

Same split as Milestones 0/1: everything file-based is written and validated as far as this sandbox allows — no Docker, no live Postgres/Qdrant/MinIO/Temporal/Keycloak here. Read `docs/MILESTONE_0_CHECKLIST.md` and `docs/MILESTONE_1_CHECKLIST.md` first if you haven't already.

No new `config_db_scripts/*.sql` file this milestone — `documents`, `document_versions`, `chunks`, and `events` already existed from `001_create_schema.sql`; Milestone 2 only added SQLAlchemy models/repositories over them. Nothing to re-apply.

> **Superseded 2026-07-08:** the "direct Anthropic API call" described below (chat endpoint, and Milestone 4's contextualizer) now goes through the AI Gateway built into the `mlflow` service instead — see `docs/KN_Valya_Complete_Architecture.md` Part I §12 and `docker/README.md`'s "LLM access" section. `ANTHROPIC_API_KEY` still goes in `docker/.env`, but is read once by `docker/scripts/bootstrap-mlflow-gateway.sh` and stored as an encrypted gateway secret, not a `backend`/`worker` env var. This section is left as a historical build record; don't follow its `ANTHROPIC_API_KEY` wiring instructions literally.

## What Claude built this milestone

- **DocumentDOM contract** (`backend/app/ingestion/dom.py`): Pydantic models matching Part I §4 exactly, plus a JSON Schema export at `docs/schemas/document_dom.schema.json` (regenerate with `python -m app.ingestion.dom` from `backend/`).
- **PDF extractor** (`backend/app/ingestion/extractors/pdf.py`): font-size/format heading heuristics, table detection via pdfplumber's ruling-line strategy (bordered tables only — see the module's docstring for the borderless-table gap). Genuinely tested against a real generated PDF (`backend/tests/test_pdf_extractor.py`, 2 tests).
- **Parent-child chunker** (`backend/app/ingestion/chunking.py`): parent snap-to-section (splitting only at paragraph boundaries when a section exceeds ~2500 tokens), child sentence-packing with ~15% overlap, tables/code/images as atomic single-chunk pairs. 5 unit tests, no contextualization/RAPTOR yet (Milestones 4/5).
- **Embedder service** (`embedder/app/main.py`): replaced the Milestone 0 stub with real `BAAI/bge-m3` inference via `FlagEmbedding.BGEM3FlagModel` — lazy-loaded on first `/embed` call, same request/response shape as before.
- **Indexer** (`backend/app/ingestion/indexing.py`): builds Qdrant points (named vectors `dense_text`/`sparse_text`) from embedded chunks; point-building logic unit-tested without a live Qdrant.
- **Temporal wiring** (`backend/app/ingestion/{temporal_types,activities,workflows}.py`, `backend/app/worker.py`): `IngestDocumentWorkflow` running extract → chunk → embed → index → finalize as five activities, each re-deriving its inputs from Postgres via `document_version_id` (not large payloads over the wire). Activities invoked by string name from the workflow to keep Temporal's workflow-sandbox import graph free of sqlalchemy/boto3/qdrant_client/httpx.
- **Upload flow** (`backend/app/services/document_service.py`, `backend/app/api/v1/documents.py`): multipart upload → MinIO `raw/` → `documents`/`document_versions` rows → `events` outbox row → inline `Temporal.start_workflow` call (Milestone 3 formalizes this as a real dispatcher; the event row's `published` flag is exactly what that dispatcher will later pick up if this inline call fails). Dedup by `content_hash` within a project.
- **Retrieval service** (`backend/app/services/retrieval_service.py`): dense+sparse hybrid search, RRF fusion (`k=60`) — the fusion math itself is pure and unit-tested (5 tests) independent of Qdrant.
- **Chat endpoint** (`backend/app/services/chat_service.py`, `backend/app/api/v1/chat.py`): retrieval + direct Anthropic API call (`anthropic` SDK) + citation rendering (doc title, section, page).
- **Frontend**: `DocumentsPage` (upload + polling status table) and `ChatPage` (message list with inline citations), linked from `ProjectsPage`. `tsc -b` and `vite build` both pass clean.
- **docker-compose.yml**: new `worker` service (same backend image, `python -m app.worker` instead of uvicorn) on the `app` profile; `backend`/`worker` env gained `EMBEDDER_URL`, `TEMPORAL_TASK_QUEUE`, `ANTHROPIC_API_KEY`.

## Highest-risk areas for a first real run

Everything above was validated as far as unit tests, import checks, and running pure-Python logic directly allow. These specific pieces have **never executed against real infra**:

- The Temporal workflow/activities end-to-end (`IngestDocumentWorkflow`, all 5 activities) — never connected to a live Temporal server. Syntax/import-correctness only; string-based activity dispatch (`workflow.execute_activity("name", ...)`) was chosen specifically to avoid known sandbox-import pitfalls, but the actual worker registration/execution has never run.
- The embedder's real BGE-M3 inference (`embedder/app/main.py`) — no network access to Hugging Face or enough disk in this sandbox to download the ~2.2GB model. First real call will also be slow (model load + first inference).
- Qdrant hybrid search (`hybrid_search` in `retrieval_service.py`) against a real collection — `query_points` with named dense/sparse vectors and filters has never executed live.
- The Anthropic API call in `chat_service.py` — needs a real `ANTHROPIC_API_KEY` in `docker/.env` (currently blank); never called live.
- MinIO round-trips inside the Temporal activities (raw bytes in, canonical.json out, per-chunk text out) — boto3 calls are syntax-checked only, same caveat as Milestone 1's storage.py.

If something breaks on first run, look here first — in that order (Temporal wiring is most likely to have a subtle issue, since it's the newest kind of integration in this codebase).

## Steps

### 1. Bring up infra + app layer (including the new worker)

```bash
cd docker
docker compose up -d                          # infra only, if not already up
docker compose --profile app up -d --build    # backend, worker, dispatcher, frontend
docker compose --profile models up -d --build # embedder, reranker, vlm-captioner (separate profile as of 2026-07-10 — see docker/README.md's "Model services")
```

First boot of `embedder` will be slow — it downloads BGE-M3's weights on the first `/embed` call, not at container start. Watch its logs:

```bash
docker compose logs -f embedder
```

### 2. Set your Anthropic API key

```bash
# in docker/.env
ANTHROPIC_API_KEY=sk-ant-...
docker compose --profile app up -d --build backend
```

Chat requests 503 with a clear message until this is set.

### 3. Verify the worker registered

```bash
docker compose logs worker
# expect: "KN_Valya ingestion worker starting on task queue 'ingestion' ..."
open http://localhost:8080   # Temporal UI — Task Queues -> ingestion should show a poller
```

### 4. Upload a PDF and watch it ingest

1. In the UI, go to a project's **documents** page, upload a real PDF.
2. Watch the Temporal UI (`http://localhost:8080`) — a new `IngestDocumentWorkflow` run should appear, moving through `extract_pdf_activity` → `chunk_document_activity` → `embed_chunks_activity` → `index_chunks_activity` → `finalize_activity`.
3. Back in the UI, the documents table should flip `pending` → `ingesting` → `indexed` (polls every 3s).
4. Verify in Postgres: `SELECT kind, count(*) FROM valya.chunks GROUP BY kind;` — should show both `parent` and `child` rows.
5. Verify in Qdrant (`http://localhost:6333/dashboard`): the project's collection should have points with non-zero `dense_text` vectors and populated payload (`document_id`, `section_path`, ...).

### 5. Ask a question

1. Go to the project's **chat** page, ask a question about the uploaded PDF's content.
2. Expect an answer with numbered citations `[1]`, `[2]`, ... below it, each showing the document title, section, and page.
3. This is the milestone's verification gate: upload → Temporal workflow visible → question → cited answer. If this works, Milestone 2 is genuinely done, not just "code exists."

## Known deferrals / limitations (by design, not oversight)

- Table detection only works for bordered tables (pdfplumber's default ruling-line strategy) — a borderless whitespace-aligned table's text falls through to paragraph blocks instead. Documented in `pdf.py`.
- No contextualization (Milestone 4), no RAPTOR (Milestone 5), no reranker (Milestone 4), no parent-promotion or modality-balance in retrieval (Milestone 4) — this is deliberately the "bare-minimum pipeline" the plan asked for.
- No ACL passthrough yet — `acl_groups` is always `[]` on indexed chunks until connectors (Milestone 7) carry real ACLs through.
- The upload flow's `Temporal.start_workflow` call is inline in the request path, not behind a real dispatcher — Milestone 3 formalizes outbox → Redis Streams → Temporal without changing the `events` table's shape.
- The chat endpoint reuses the existing `agent.run` permission (no dedicated `chat`/`query` permission exists yet in the RBAC seed data) — revisit if Milestone 8's agent-specific permissions want something more precise.
- `approx_token_count` is a regex word/punctuation-split heuristic, not BGE-M3's real tokenizer — good enough for chunk-size targets, avoids pulling in a GPT tokenizer as an ill-fitting proxy.
