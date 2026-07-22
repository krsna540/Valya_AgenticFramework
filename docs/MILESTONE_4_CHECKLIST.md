# Milestone 4 — Retrieval Quality: Execution Checklist

Status: **built and validated in-sandbox**; real infra verification (live embedder/reranker/Anthropic/Postgres/Qdrant) is for Krishna's machine, same division of labor as Milestones 0–3.

> **Superseded 2026-07-08:** the contextualizer's "direct Anthropic call" and `settings.contextualizer_model` described below now go through the self-hosted MLflow AI Gateway's `contextualizer` endpoint (`settings.contextualizer_gateway_endpoint`) instead — see `docs/KN_Valya_Complete_Architecture.md` Part I §12 and `docker/README.md`. `worker` no longer gets `ANTHROPIC_API_KEY`; it gets `MLFLOW_GATEWAY_URI`. Left as a historical build record.

## What was built

### 1. Contextualization activity (§6 Stage 6)
- `backend/app/ingestion/contextualizer.py` — direct Anthropic call (Haiku-class model, `settings.contextualizer_model`, default `claude-haiku-4-5-20251001`), NOT a served microservice like embedder/reranker — Stage 6 is "a cheap LLM call", not a model that needs its own GPU-backed process.
- New activity `contextualize_chunks_activity` in `activities.py`, inserted into `IngestDocumentWorkflow` between chunk and embed. Writes `chunks.contextual_header` per child chunk.
- **Caching**: `config_db_scripts/009_chunk_contextualization_cache.sql` adds a `chunk_contextualizations` table, keyed by `(document_id, parent_content_hash, child_content_hash)` — deliberately NOT the architecture doc's literal `(parent_chunk_id, chunk_hash)` wording, because chunk ids are fresh `uuid4()`s every ingestion run (see `app/ingestion/chunking.py`), so a cache keyed on them would never survive a reindex. Content hashes do. `backend/app/repositories/contextualization.py` + `backend/app/models/chunk_contextualization.py` implement the lookup/write.
- `embed_chunks_activity` now folds `chunk.contextual_header` into what's embedded (`f"{header}\n\n{text}"`) — `display_text` (shown in citations) is untouched; only what gets embedded changes.
- `app/pipelines/schema.py`: `contextualizer` moved from `KNOWN_WORKERS` into `EXECUTABLE_WORKERS` (mapped to Milestone 4) — the Pipeline Editor's dry-run now actually runs it (sampled, uncached, unpersisted, same pattern as the other dry-run stages) instead of showing a "not implemented" placeholder.
- Updated `tests/test_pipeline_schema.py`'s executable/non-executable split assertion accordingly.

### 2. Reranker service (real BGE-reranker-v2-m3)
- `reranker/app/main.py` replaced the Milestone 0 identity-order stub with real `FlagEmbedding.FlagReranker` cross-encoder inference — same lazy-load-on-first-call pattern as `embedder/app/main.py`.
- **Contract change from the stub**: candidates now carry an explicit `id` alongside `text` (not text-only) so two candidates with identical text — duplicate boilerplate chunks aren't rare in real corpora — are never ambiguous when mapped back.
- `reranker/pyproject.toml` + `Dockerfile` updated to match `embedder/`'s real-model pattern (FlagEmbedding + torch, CPU wheel by default, GPU swap instructions in comments).
- `backend/app/services/reranker_client.py` — thin HTTP client, same shape as `embedding_client.py`.
- `docker-compose.yml`: `backend` service now depends on `reranker` and gets `RERANKER_URL`; `worker` service gets `ANTHROPIC_API_KEY` (needed by the new contextualize activity, which the worker process runs).

### 3. Retrieval Service: Steps 3–6 (§7.3)
Rewrote `backend/app/services/retrieval_service.py`:
- **Step 3** (RRF fusion) — confirmed this was already properly implemented in Milestone 2, not a shortcut (`reciprocal_rank_fusion` is the real Cormack et al. formula, unit-tested). No change needed here beyond feeding it into Step 4.
- **Step 4** (rerank) — fetches text for the RRF-fused top-N candidates (`settings.rerank_top_k_in`, default 50) from MinIO, calls the reranker service, keeps a pool larger than the final `top_k` to leave room for Steps 5–6 to collapse/drop results.
- **Step 5** (parent promotion + dedupe) — a reranked child chunk is replaced by its parent (fetched fresh from Postgres+MinIO); two children promoting to the same parent collapse into one result, keeping the higher-ranked child's score/citation metadata. Parents were never indexed in Qdrant ("parents are not embedded"), so a promoted result's `document_id`/`doc_type` are carried over from the winning child's Qdrant payload.
- **Step 6** (modality balance cap) — `_apply_modality_balance()`, a real generic algorithm (not a hardcoded no-op): caps any modality at `settings.modality_balance_cap` (30%) of the final result count on a first pass, then backfills from overflow if slots remain. Every chunk is `modality="text"` until Milestone 6, so the cap can structurally never bind today — verified by `tests/test_modality_balance.py`'s synthetic multi-modality cases, since real image/table/code chunks don't exist yet to exercise it end-to-end.
- `RetrievedChunk.text` is now always populated by the retrieval service itself (it has to be, to feed the reranker) — this let `chat_service.py` drop its own duplicate MinIO-fetch loop entirely.

### 4. Eval script
- `backend/scripts/eval_retrieval.py` — CLI harness that calls `hybrid_search` directly against live infra and prints each result's score, parent-promotion status, and a text snippet, for eyeballing retrieval quality on a real question. See its own docstring for why "before/after" is a manual comparison now (contextualization/reranking are unconditionally wired into the real pipeline, no feature flag) rather than something the script itself can toggle.

## Validated in-sandbox

- `ruff check app/ tests/ scripts/` — clean, zero errors.
- `pytest tests/` — 46/46 passing: all 41 pre-existing (M1–M3) tests still green, plus 4 new `test_modality_balance.py` tests (synthetic multi-modality cap behavior) and 1 new `test_hybrid_search_pipeline.py` integration-style test (mocked Qdrant/Postgres/S3/reranker) exercising the full Step 3→6 wiring end-to-end, including the parent-dedupe scenario (two children promoting to the same parent collapse to one result, the higher-ranked child wins).
- `python -c "from app.main import app; ..."` — imports cleanly, all 23 routes still register (no route changes this milestone — it's all ingestion/retrieval internals).
- Reranker service import-checked with `FlagEmbedding` stubbed out (no real model download possible in this sandbox — no GPU, no HF network access) — confirmed the FastAPI app builds, routes register, and the `/rerank` endpoint's sort/top-k/id-mapping logic is correct against a fake `compute_score`.
- `docker-compose.yml` re-parses via `yaml.safe_load` with the updated `backend`/`worker`/`reranker` service blocks.
- `config_db_scripts/009_chunk_contextualization_cache.sql` parses via `sqlparse` (2 `CREATE` + 1 `COMMIT` statement, as expected).
- `pyproject.toml` (backend, reranker) parse via `tomli` with the expected dependency lists.

## Known gaps / not done in this pass

- **No feature flag to compare "before" vs. "after"** — contextualization and reranking are unconditionally wired into `IngestDocumentWorkflow` and `hybrid_search`. The milestone's "run the same eval question before/after" gate has to be done by comparing against the Milestone 2 checklist's qualitative notes (or checking out the pre-M4 commit), not by toggling a setting. If this comparison turns out to matter for tuning later, consider adding one.
- **The reranker HTTP call is currently single-shot with no retry/circuit-breaker** — if `reranker/` is down or slow, `hybrid_search` will raise straight through to a 502 at the chat endpoint. Fine for now (matches the "reranker is the most expensive/most fragile per-query step" warning in the architecture doc), but worth hardening before production load.
- **Modality balance cap is genuinely untested against real non-text chunks** — the algorithm is correct (proven with synthetic data), but it has never seen a real `modality="image"` chunk, because none exist until Milestone 6. Re-verify with a real mixed-modality corpus once Milestone 6 lands.
- **Query-intent classification, HyDE expansion, and layer weighting (§7.3 Step 2 and part of Step 3) are still not implemented** — explicitly deferred to Milestone 5, which needs RAPTOR levels to give layer weighting something to weight.
- **The dry-run endpoint's new `contextualizer` branch samples only the first 5 children** (same `_EMBED_SAMPLE_SIZE` as the embedder/indexer branches) and never writes to the contextualization cache — consistent with dry-run's existing "real logic, sampled, never persisted" contract, not a new gap.

## What needs verification on Krishna's machine (real infra)

1. **Rebuild the reranker image** (`docker compose --profile models build reranker` — reranker moved off the `app` profile onto a separate `models` profile 2026-07-10, see docker/README.md's "Model services") — first `/rerank` call downloads BGE-reranker-v2-m3 weights from Hugging Face; confirm `/health` responds immediately and the model loads lazily on first real request, same as the embedder did in Milestone 2.
2. **Re-upload a document through the full pipeline** and confirm in Postgres: `chunks.contextual_header` is populated for child chunks, and a corresponding row exists in `chunk_contextualizations`. Re-upload the *same* document again (or trigger a reindex) and confirm the second run's contextualize stage reports `cache_hits` > 0 in its `pipeline_stage_runs.metrics` (visible in the Run Observatory) — this is the actual proof the caching works, not just that the column got populated once.
3. **`python -m scripts.eval_retrieval --tenant-id ... --project-id ... --question "..."`** against a real ingested project — eyeball whether surfaced results are full parent passages (not bare child fragments) and whether the top-ranked result is genuinely on-topic rather than "almost right, wrong specific fact." Compare qualitatively against what Milestone 2's bare RRF-only retrieval would have surfaced for the same question.
4. **Confirm the reranker's `compute_score` call actually improves ranking** — pick a question where the RRF-fused top-1 and the reranked top-1 differ, and manually judge which one is the better answer. If they never differ in practice, something's wrong with either the reranker's dtype/normalize settings or the RRF fuse itself.
5. **Latency check**: the reranker is called on every chat turn now (up to `rerank_top_k_in`=50 candidates per query) — measure p95 latency for a chat round-trip and decide whether `RERANK_TOP_K_IN`/`RERANK_TOP_K_OUT` need tuning down for the target hardware (CPU inference will be materially slower than GPU here).
6. **Contextualization cost**: for a large document, count how many Anthropic API calls a first-time ingestion makes (one per child chunk, cache misses only) and sanity-check this against expected per-tenant LLM spend before rolling out to a real corpus.
