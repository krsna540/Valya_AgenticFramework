-- =====================================================================
-- KN_Valya :: Milestone 7 — ACL passthrough columns.
-- =====================================================================
-- `app/ingestion/dom.py`'s DocumentDOM has carried `acl_groups: list[str]`
-- since Milestone 2 ("§4: acl_groups[], copied from source system"), and
-- the whole read path (Qdrant payload index, retrieval_service.py's
-- FieldCondition filter, virtual_cluster_filters.py's "already
-- unconditionally AND-ed" note) was already built assuming it exists.
-- The only gap: nothing ever WROTE it, because the only connector that
-- existed through Milestone 6 was manual PDF upload, which has no source
-- ACL to copy — app/ingestion/activities.py's index_chunks_activity
-- hardcoded `acl_groups=[]` with a comment pointing at this exact
-- migration ("no ACL passthrough until connectors land (Milestone 7)").
--
-- These columns are where connectors write what they read from the
-- source system, mirroring how doc_type/language already live on both
-- `documents` (source of truth, written once at ingest/connector-sync
-- time) and `chunks` (denormalized copy, written at chunk time so the
-- indexer never has to join back to `documents` per chunk).
-- =====================================================================

BEGIN;
SET search_path TO valya, public;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS acl_groups TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS acl_groups TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

-- GIN indexes for the `acl_groups && :user_groups` overlap check — same
-- index shape as the existing `idx_chunks_tags` (also a GIN over TEXT[]).
CREATE INDEX IF NOT EXISTS idx_documents_acl_groups ON documents USING GIN (acl_groups);
CREATE INDEX IF NOT EXISTS idx_chunks_acl_groups    ON chunks USING GIN (acl_groups);

COMMIT;
