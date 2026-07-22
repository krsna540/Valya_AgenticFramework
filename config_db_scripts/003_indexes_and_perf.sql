-- =====================================================================
-- KN_Valya :: Additional indexes for query patterns that emerge in the
-- admin UI (filtering, search, run-observatory dashboards).
-- =====================================================================
-- Run AFTER 001 + 002. Safe to re-run (uses IF NOT EXISTS).
-- These are kept separate so prod DBAs can apply them CONCURRENTLY
-- if needed (strip the BEGIN/COMMIT and run one at a time).
-- =====================================================================

BEGIN;
SET search_path TO valya, public;

-- Run observatory: "show me failed runs in last 24h per tenant"
CREATE INDEX IF NOT EXISTS idx_runs_failed_recent
    ON pipeline_runs (created_at DESC)
    WHERE status = 'failed';

-- Document inspector: latest version per doc
CREATE INDEX IF NOT EXISTS idx_doc_versions_doc_desc
    ON document_versions (document_id, version DESC);

-- Stage telemetry: average duration per stage per pipeline
CREATE INDEX IF NOT EXISTS idx_stage_runs_stage_dur
    ON pipeline_stage_runs (stage_id, duration_ms)
    WHERE status = 'succeeded';

-- Audit drilldown
CREATE INDEX IF NOT EXISTS idx_audit_action_time
    ON audit_log (action, created_at DESC);

-- Chunk traversal: walk parent->children quickly
CREATE INDEX IF NOT EXISTS idx_chunks_parent_ordinal
    ON chunks (parent_chunk_id, ordinal);

-- Events outbox dispatcher
CREATE INDEX IF NOT EXISTS idx_events_outbox_dispatch
    ON events (created_at)
    WHERE NOT published;

COMMIT;
