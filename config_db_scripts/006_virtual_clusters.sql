-- =====================================================================
-- KN_Valya :: Virtual clusters
-- =====================================================================
-- Gap found while implementing Milestone 1 (backend/app): Part I decision #14
-- and §5.2 ("Default virtual clusters seeded: All, Last 90 days, My team")
-- both assume a `virtual_clusters` table exists, but 001_create_schema.sql
-- never defined one. This adds it.
--
-- Virtual clusters are *saved filter expressions*, not collections — they
-- get applied server-side as Qdrant `must` clauses at retrieval time, ACL
-- always AND-ed on top (docs/KN_Valya_Complete_Architecture.md §8.1, B.3.2).
-- This table is the Postgres source of truth for those saved filters; the
-- retrieval service (Milestone 2+) reads it, translates filter_spec into a
-- Qdrant filter, and ANDs the caller's ACL groups in at query time — the
-- ACL enforcement is never delegated to what's stored here.
--
-- Apply AFTER 001-005.
-- =====================================================================

BEGIN;
SET search_path TO valya, public;

CREATE TABLE virtual_clusters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    tenant_id       UUID NOT NULL REFERENCES tenants(id)  ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    filter_spec     JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- translated to Qdrant `must` clauses
    is_default      BOOLEAN      NOT NULL DEFAULT FALSE,        -- seeded at project bootstrap (§5.2)
    is_system       BOOLEAN      NOT NULL DEFAULT FALSE,        -- All/Last 90 days/My team cannot be deleted
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    UNIQUE (project_id, name)
);
CREATE INDEX idx_virtual_clusters_project ON virtual_clusters(project_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_virtual_clusters_tenant  ON virtual_clusters(tenant_id);

CREATE TRIGGER trg_virtual_clusters_updated_at
    BEFORE UPDATE ON virtual_clusters
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
