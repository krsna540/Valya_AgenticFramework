-- =====================================================================
-- KN_Valya :: Refine chunks table to align with converged-KB metadata.
-- =====================================================================
-- The chunks table in 001_create_schema.sql already has a flexible
-- `metadata` JSONB column. This script adds explicit columns for fields
-- the retrieval layer filters on most often, so we can index them in
-- Postgres (mirroring the Qdrant payload indexes) and join lineage
-- queries without unpacking JSON every time.
-- =====================================================================

BEGIN;
SET search_path TO valya, public;

ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS tenant_id          UUID,
    ADD COLUMN IF NOT EXISTS project_id         UUID,
    ADD COLUMN IF NOT EXISTS doc_type           VARCHAR(64),
    ADD COLUMN IF NOT EXISTS datasource_id      UUID,
    ADD COLUMN IF NOT EXISTS datasource_type    connector_type,
    ADD COLUMN IF NOT EXISTS language           VARCHAR(16),
    ADD COLUMN IF NOT EXISTS classification     VARCHAR(32),
    ADD COLUMN IF NOT EXISTS topic              VARCHAR(255),
    ADD COLUMN IF NOT EXISTS tags               TEXT[] DEFAULT ARRAY[]::TEXT[],
    ADD COLUMN IF NOT EXISTS effective_date     TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS contextual_header  TEXT,
    ADD COLUMN IF NOT EXISTS sparse_vector_id   VARCHAR(64),
    ADD COLUMN IF NOT EXISTS cluster_members    UUID[];

-- FK / indexes
CREATE INDEX IF NOT EXISTS idx_chunks_tenant_project
    ON chunks(tenant_id, project_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_type
    ON chunks(doc_type);
CREATE INDEX IF NOT EXISTS idx_chunks_datasource
    ON chunks(datasource_id);
CREATE INDEX IF NOT EXISTS idx_chunks_language
    ON chunks(language);
CREATE INDEX IF NOT EXISTS idx_chunks_classification
    ON chunks(classification);
CREATE INDEX IF NOT EXISTS idx_chunks_tags
    ON chunks USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_chunks_effective_date
    ON chunks(effective_date);

COMMIT;
