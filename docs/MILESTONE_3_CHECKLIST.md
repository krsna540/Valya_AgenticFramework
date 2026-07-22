# Milestone 3 — Pipeline Configurability: Execution Checklist

Status: **built and validated in-sandbox**; real infra verification (Postgres/Redis/Temporal/UI-in-browser) is for Krishna's machine, same division of labor as Milestones 0–2.

## What was built

### 1. Pipeline YAML schema + validator (§9.2)
- `backend/app/pipelines/schema.py`: `PipelineSpec`/`Stage`/`AppliesTo`/`Trigger`/`OnFailure` Pydantic models, DAG validation (duplicate ids, dangling `depends_on`, cycle detection via Kahn's algorithm), `topological_order()`/`stage_depths()` for DAG layout, `parse_yaml()`, `compute_checksum()`, `to_parsed_spec()`.
- `EXECUTABLE_WORKERS` (pdf_extractor, parent_child_chunker, embedder, qdrant_indexer — real Milestone 2 activities) vs. `KNOWN_WORKERS` (adds image_captioner/metadata_enricher/contextualizer/raptor_summarizer, reserved for Milestones 4–6). Admins can author the full 8-stage architecture-shaped pipeline today; only the executable subset actually runs.
- Both `yaml_spec` (text) and `parsed_spec` (JSONB) are stored on every `pipelines` row — no new SQL migration needed, the tables already existed in `001_create_schema.sql`.
- 11 unit tests in `tests/test_pipeline_schema.py`, all passing.

### 2. Pipeline Editor UI
- `frontend/src/pages/PipelineEditorPage.tsx`: Monaco YAML editor (`@monaco-editor/react`, added to `package.json`) side-by-side with a live SVG DAG render (`frontend/src/components/PipelineDag.tsx`, client-side depth computation mirroring the backend's Kahn's-algorithm layering).
- Version list grouped by pipeline name, lifecycle badges (draft/active/deprecated), promote/deprecate buttons, save-as-new-version flow (pipelines are immutable per version, same philosophy as numbered SQL migrations).
- Dry-run panel: pick a project + already-uploaded document, run the saved pipeline against it, see a per-stage status/duration/notes table.

### 3. Dry-run endpoint
- `POST /api/v1/tenants/{tenant_id}/projects/{project_id}/pipelines/{pipeline_id}/dry-run`
- `backend/app/services/dry_run_service.py`: walks the pipeline's stages in topological order; executable stages run REAL logic (pdf extraction, chunking, embedding a 5-chunk sample, indexer point-building) but never write to Qdrant; non-executable stages return a "not implemented until Milestone N" placeholder; a failed stage marks all downstream executable stages as skipped.

### 4. Promote/deprecate lifecycle + bindings table (§5.5)
- `backend/app/services/pipeline_service.py`: `create_pipeline` (draft), `promote_pipeline` (deprecates the prior active version of the same name, activates this one), `deprecate_pipeline`.
- `backend/app/services/pipeline_binding_service.py`: `resolve_pipeline_for(tenant_id, project_id, datasource_id, doc_type)` tries 4 specificity levels before falling back to `projects.default_pipeline_id`.
- Bindings UI folded into the Run Observatory page (`frontend/src/pages/RunObservatoryPage.tsx`) — pick a project, see current bindings, bind a doc_type to any active pipeline.

### 5. Trigger dispatcher (own service)
- `backend/app/dispatcher.py` — two loops in one process: outbox poller (`events` table → `documents.uploaded` Redis stream) and stream consumer (resolves the pipeline binding, creates a `pipeline_runs` row, calls `Temporal.start_workflow` with `workflow_id = {tenant}:{doc}:v{version}:{pipeline_version}`).
- Idempotent by `workflow_id` — a redelivered message hits Temporal's `WorkflowAlreadyStartedError` and is treated as success, not a duplicate.
- Failed dispatches go to the `ingestion.dlq` Redis stream carrying the full original message fields (not just a summary) so a requeue can reconstruct it exactly.
- `docker/docker-compose.yml` has a new `dispatcher` service (`profiles: ["app"]`, same shape as `worker`).
- `document_service.py`'s inline Temporal call from Milestone 2 was removed — upload now only writes the outbox row; the dispatcher owns starting workflows.

### 6. Run Observatory
- API: `backend/app/api/v1/runs.py` — `GET /pipeline-runs` (list, filterable by status), `GET /pipeline-runs/{id}` (detail incl. per-stage runs), `POST /pipeline-runs/{id}/retry` (starts a fresh workflow + `pipeline_runs` row, `pipeline.run` permission), `GET /observatory/stats` (24h window: total/succeeded/failed/running, success rate, p95 stage latency via `percentile_cont`), `GET /observatory/dlq` + `POST /observatory/dlq/{stream_id}/requeue` (tenant-filtered — the DLQ stream itself isn't partitioned per tenant, so entries are matched by their own `tenant_id` field).
- UI: `frontend/src/pages/RunObservatoryPage.tsx` — stat cards, live-polling run table (3s while anything queued/running), drill-into-run detail panel with per-stage attempt/status/error, retry button on failed/timed-out/cancelled runs, DLQ inspector with requeue.
- Per-attempt stage tracking: `activities.py`'s `_stage_tracker` context manager writes each attempt (via `activity.info().attempt`) to its own dedicated DB session — separate from the activity's main-work session, so a stage-run failure record survives even if the main transaction rolls back.

## Validated in-sandbox

- `ruff check app/` — clean, zero errors, across the whole backend (not just this milestone's new files).
- `pytest tests/` — 41/41 passing (11 pipeline-schema tests + 4 binding-resolution tests + all pre-existing M1/M2 tests, still green).
- `PYTHONPATH=. python3 -c "from app.main import app; ..."` — imports cleanly; confirmed via `app.openapi()['paths']` that every new route registers, including the Run Observatory's 6 endpoints.
- `npx tsc -b` — frontend type-checks clean (Pipeline Editor, Run Observatory, DAG component, new hooks/types).
- `npx vite build` — 161 modules bundle successfully. (Building to the repo's own `dist/` hits a pre-existing sandbox/mount permission quirk on file deletion — same class of issue noted in the Milestone 0 memory record — confirmed cosmetic by building to a scratch `outDir` instead, which succeeded.)
- `docker/docker-compose.yml` parses via `yaml.safe_load` with the new `dispatcher` service present and correctly configured.
- No new SQL migration was needed — `pipelines`, `pipeline_bindings`, `pipeline_runs`, `pipeline_stage_runs` were already in `001_create_schema.sql` from the original schema design.

## Known gaps / not done in this pass

- **No eslint config exists in the frontend project** (`package.json`'s `lint` script has no `eslint.config.js` to run against) — this predates Milestone 3 and wasn't introduced by it; `tsc -b` + `vite build` were used as the real gates instead. Worth adding an eslint flat config in a future cleanup pass.
- The client-side YAML preview parser in `PipelineEditorPage.tsx` (`yamlToSpecPreview`) is a minimal indent-based subset parser for the DAG preview only — it is NOT the source of truth (the backend's Pydantic validator is, and runs again on save). Good enough for a live preview while typing; don't extend it to handle arbitrary YAML.
- The Pipeline Editor's "edit" flow is read-only-then-copy (loading a saved version populates the editor as read-only; the admin copies the YAML, bumps `version`, and saves as new) rather than an in-place "clone as new version" button. Small UX polish opportunity, not a functional gap.

## What needs verification on Krishna's machine (real infra)

1. **`docker compose --profile app up`** (postgres, redis, temporal, backend, worker, dispatcher, frontend) — confirm the dispatcher starts cleanly and its outbox/consumer loops log activity.
2. **Full verification gate from the milestone spec**, in order:
   - Open the Pipeline Editor, edit/save a pipeline's YAML as a new version.
   - Dry-run it against a real uploaded sample document — confirm each stage's real output (extracted text summary, chunk counts, embedding dims) shows up, and confirm nothing was actually written to Qdrant (no new points in the collection).
   - Promote the new version to active.
   - Upload a new document (or bind an existing project/doc_type to this pipeline) and confirm the dispatcher picks up the `documents.uploaded` event, resolves the binding to this pipeline, and the Temporal workflow starts — watch the Run Observatory's run list show it move queued → running → succeeded.
   - **Kill a worker process mid-run** (`docker compose kill worker` while a run is `running`) and confirm: Temporal's `IngestDocumentWorkflow` retries the interrupted activity per its retry policy (visible in the Temporal UI at :8088), the Run Observatory's stage-run table shows the failed attempt (attempt=1) and the retry recorded separately (attempt=2, thanks to the dedicated-session `_stage_tracker` bookkeeping), and if it ultimately lands in `failed`, the Observatory's retry button successfully starts a fresh workflow.
3. **DLQ path**: force a dispatch failure (e.g. temporarily stop Temporal, or delete a project's binding) and confirm the failed message lands in `ingestion.dlq`, shows up in the Observatory's DLQ inspector (tenant-filtered), and that "Requeue" successfully re-publishes it for the dispatcher to pick up once the underlying issue is fixed.
4. **Multi-tenant DLQ isolation spot-check**: since the DLQ Redis stream isn't partitioned per tenant, confirm a tenant A admin genuinely cannot see or requeue a tenant B DLQ entry (the tenant_id filter in `run_service.py`'s `list_dlq_entries`/`requeue_dlq_entry` is the only thing enforcing this — worth a deliberate two-tenant test).
5. **Monaco editor bundle size / CDN**: `@monaco-editor/react` pulls in the Monaco editor core at runtime from its CDN by default (or bundles it, depending on version) — confirm the Pipeline Editor page loads correctly with real browser network access (this wasn't exercised in the sandbox beyond `tsc`/`vite build`).
