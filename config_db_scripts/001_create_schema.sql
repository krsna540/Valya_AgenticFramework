-- =====================================================================
-- KN_Valya :: Configuration Database (Postgres) :: Schema DDL
-- =====================================================================
-- Purpose : Holds tenants, projects, users, connectors, datasources,
--           documents, pipeline definitions, run metadata, and chunk
--           index pointers. Execution state lives in Temporal; bytes
--           live in MinIO; vectors live in Qdrant. This DB is the
--           source of truth for *configuration* and *lineage pointers*.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "citext";     -- case-insensitive emails
CREATE EXTENSION IF NOT EXISTS "pg_trgm";    -- fuzzy search on names

-- ---------------------------------------------------------------------
-- Schema
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS valya;
SET search_path TO valya, public;

-- ---------------------------------------------------------------------
-- ENUM types
-- ---------------------------------------------------------------------
CREATE TYPE user_role           AS ENUM ('super_admin', 'tenant_admin', 'project_admin', 'member', 'viewer');
CREATE TYPE connector_type      AS ENUM ('sharepoint', 'confluence', 'sql', 'nosql', 's3', 'gdrive', 'upload', 'http');
CREATE TYPE document_status     AS ENUM ('pending', 'ingesting', 'indexed', 'failed', 'archived', 'deleted');
CREATE TYPE run_status          AS ENUM ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'timed_out');
CREATE TYPE trigger_source      AS ENUM ('user', 'connector', 'schedule', 'reindex', 'api');
CREATE TYPE pipeline_lifecycle  AS ENUM ('draft', 'active', 'deprecated', 'archived');
CREATE TYPE chunk_kind          AS ENUM ('child', 'parent', 'raptor_summary');
CREATE TYPE retention_unit      AS ENUM ('days', 'months', 'years', 'forever');

-- ---------------------------------------------------------------------
-- Helper: updated_at trigger
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- =====================================================================
-- 1. TENANTS
-- =====================================================================
CREATE TABLE tenants (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug                VARCHAR(64)  NOT NULL UNIQUE,
    name                VARCHAR(255) NOT NULL,
    status              VARCHAR(32)  NOT NULL DEFAULT 'active',
    settings            JSONB        NOT NULL DEFAULT '{}'::jsonb,
    quota               JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,
    CONSTRAINT tenants_slug_format CHECK (slug ~ '^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$')
);
CREATE INDEX idx_tenants_status     ON tenants(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_tenants_name_trgm  ON tenants USING GIN (name gin_trgm_ops);

CREATE TRIGGER trg_tenants_updated_at
    BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- 2. PROJECTS
-- =====================================================================
CREATE TABLE projects (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    slug                    VARCHAR(64)  NOT NULL,
    name                    VARCHAR(255) NOT NULL,
    description             TEXT,
    default_language        VARCHAR(16)  NOT NULL DEFAULT 'en',
    supported_languages     TEXT[]       NOT NULL DEFAULT ARRAY['en']::TEXT[],
    default_pipeline_id     UUID,                       -- FK added later (forward ref)
    qdrant_collection       VARCHAR(255) NOT NULL,      -- e.g. tenant_{t}_project_{p}
    settings                JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_by              UUID,                       -- FK added later
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at              TIMESTAMPTZ,
    UNIQUE (tenant_id, slug)
);
CREATE INDEX idx_projects_tenant     ON projects(tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_projects_name_trgm  ON projects USING GIN (name gin_trgm_ops);

CREATE TRIGGER trg_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- 3. USERS  (scoped to tenant)
-- =====================================================================
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email           CITEXT       NOT NULL,
    display_name    VARCHAR(255) NOT NULL,
    role            user_role    NOT NULL DEFAULT 'member',
    auth_provider   VARCHAR(64)  NOT NULL DEFAULT 'local',  -- local, oidc, saml
    auth_subject    VARCHAR(255),                            -- external subject id
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    last_login_at   TIMESTAMPTZ,
    preferences     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    UNIQUE (tenant_id, email)
);
CREATE INDEX idx_users_tenant     ON users(tenant_id)  WHERE deleted_at IS NULL;
CREATE INDEX idx_users_email      ON users(email)      WHERE deleted_at IS NULL;
CREATE INDEX idx_users_auth_sub   ON users(auth_provider, auth_subject) WHERE auth_subject IS NOT NULL;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Backfill FK references that needed users
ALTER TABLE projects
    ADD CONSTRAINT fk_projects_created_by
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;

-- =====================================================================
-- 4. PROJECT MEMBERSHIPS  (user <-> project ACL)
-- =====================================================================
CREATE TABLE project_memberships (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    role            user_role NOT NULL DEFAULT 'member',
    granted_by      UUID REFERENCES users(id),
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at      TIMESTAMPTZ,
    UNIQUE (project_id, user_id)
);
CREATE INDEX idx_membership_user ON project_memberships(user_id) WHERE revoked_at IS NULL;

-- =====================================================================
-- 5. CONNECTORS  (tenant-scoped, reusable across projects)
-- =====================================================================
CREATE TABLE connectors (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                    VARCHAR(255)   NOT NULL,
    type                    connector_type NOT NULL,
    config                  JSONB          NOT NULL DEFAULT '{}'::jsonb,   -- non-secret config
    credentials_secret_ref  VARCHAR(512),                                  -- pointer to Vault/SecretsMgr
    is_active               BOOLEAN        NOT NULL DEFAULT TRUE,
    health_status           VARCHAR(32)    NOT NULL DEFAULT 'unknown',
    last_health_check_at    TIMESTAMPTZ,
    created_by              UUID REFERENCES users(id),
    created_at              TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    deleted_at              TIMESTAMPTZ,
    UNIQUE (tenant_id, name)
);
CREATE INDEX idx_connectors_tenant_type ON connectors(tenant_id, type) WHERE deleted_at IS NULL;

CREATE TRIGGER trg_connectors_updated_at
    BEFORE UPDATE ON connectors
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- 6. DATASOURCES  (project-scoped instances of a connector)
-- =====================================================================
CREATE TABLE datasources (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          UUID NOT NULL REFERENCES projects(id)   ON DELETE CASCADE,
    connector_id        UUID NOT NULL REFERENCES connectors(id) ON DELETE RESTRICT,
    name                VARCHAR(255) NOT NULL,
    scope_config        JSONB        NOT NULL DEFAULT '{}'::jsonb,  -- sites/libs/queries/folders
    sync_schedule_cron  VARCHAR(64),
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    last_sync_at        TIMESTAMPTZ,
    last_sync_status    VARCHAR(32),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,
    UNIQUE (project_id, name)
);
CREATE INDEX idx_datasources_project ON datasources(project_id) WHERE deleted_at IS NULL;

CREATE TRIGGER trg_datasources_updated_at
    BEFORE UPDATE ON datasources
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- 7. PIPELINES  (YAML-defined ingestion DAG, versioned)
-- =====================================================================
CREATE TABLE pipelines (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                VARCHAR(255) NOT NULL,
    version             INTEGER      NOT NULL DEFAULT 1,
    lifecycle           pipeline_lifecycle NOT NULL DEFAULT 'draft',
    doc_types           TEXT[]       NOT NULL DEFAULT ARRAY[]::TEXT[],  -- pdf, docx, html, ...
    datasource_types    TEXT[]       NOT NULL DEFAULT ARRAY[]::TEXT[],  -- sharepoint, sql, ...
    yaml_spec           TEXT         NOT NULL,
    parsed_spec         JSONB        NOT NULL,
    spec_checksum       CHAR(64)     NOT NULL,                          -- sha256 of yaml_spec
    description         TEXT,
    created_by          UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    activated_at        TIMESTAMPTZ,
    deprecated_at       TIMESTAMPTZ,
    UNIQUE (tenant_id, name, version)
);
CREATE INDEX idx_pipelines_tenant_active ON pipelines(tenant_id, lifecycle) WHERE lifecycle = 'active';
CREATE INDEX idx_pipelines_doc_types     ON pipelines USING GIN (doc_types);
CREATE INDEX idx_pipelines_ds_types      ON pipelines USING GIN (datasource_types);

CREATE TRIGGER trg_pipelines_updated_at
    BEFORE UPDATE ON pipelines
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Backfill projects.default_pipeline_id FK
ALTER TABLE projects
    ADD CONSTRAINT fk_projects_default_pipeline
    FOREIGN KEY (default_pipeline_id) REFERENCES pipelines(id) ON DELETE SET NULL;

-- =====================================================================
-- 8. PIPELINE BINDINGS  (project/datasource/doctype -> pipeline override)
-- =====================================================================
CREATE TABLE pipeline_bindings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id)  ON DELETE CASCADE,
    datasource_id   UUID REFERENCES datasources(id)        ON DELETE CASCADE,
    doc_type        VARCHAR(64),
    pipeline_id     UUID NOT NULL REFERENCES pipelines(id) ON DELETE RESTRICT,
    priority        INTEGER NOT NULL DEFAULT 100,           -- lower wins
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, datasource_id, doc_type)
);
CREATE INDEX idx_bindings_lookup ON pipeline_bindings(project_id, datasource_id, doc_type) WHERE is_active;

-- =====================================================================
-- 9. DOCUMENTS  (logical document; versions hold the bytes)
-- =====================================================================
CREATE TABLE documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          UUID NOT NULL REFERENCES projects(id)    ON DELETE CASCADE,
    datasource_id       UUID REFERENCES datasources(id)          ON DELETE SET NULL,
    external_id         VARCHAR(512),                       -- id in the source system
    source_uri          TEXT,                               -- original URI (sp://, s3://, etc.)
    title               TEXT,
    mime_type           VARCHAR(128),
    doc_type            VARCHAR(64),                        -- pdf, docx, html, ...
    language            VARCHAR(16),
    current_version     INTEGER     NOT NULL DEFAULT 0,
    content_hash        CHAR(64),                           -- sha256 of latest raw bytes
    status              document_status NOT NULL DEFAULT 'pending',
    tags                TEXT[]      NOT NULL DEFAULT ARRAY[]::TEXT[],
    metadata            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    size_bytes          BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,
    UNIQUE (datasource_id, external_id)
);
CREATE INDEX idx_documents_project_status ON documents(project_id, status) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_hash           ON documents(content_hash);
CREATE INDEX idx_documents_tags           ON documents USING GIN (tags);
CREATE INDEX idx_documents_metadata       ON documents USING GIN (metadata jsonb_path_ops);
CREATE INDEX idx_documents_title_trgm     ON documents USING GIN (title gin_trgm_ops);

CREATE TRIGGER trg_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- 10. DOCUMENT VERSIONS  (immutable; one row per ingested revision)
-- =====================================================================
CREATE TABLE document_versions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id             UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version                 INTEGER NOT NULL,
    content_hash            CHAR(64) NOT NULL,
    size_bytes              BIGINT,
    minio_raw_uri           TEXT NOT NULL,
    minio_canonical_uri     TEXT,
    extracted_metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    page_count              INTEGER,
    is_current              BOOLEAN NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, version)
);
CREATE INDEX idx_doc_versions_current ON document_versions(document_id) WHERE is_current;
CREATE INDEX idx_doc_versions_hash    ON document_versions(content_hash);

-- =====================================================================
-- 11. PIPELINE RUNS  (one per (document_version, pipeline))
-- =====================================================================
CREATE TABLE pipeline_runs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id             UUID NOT NULL REFERENCES pipelines(id)         ON DELETE RESTRICT,
    document_version_id     UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    temporal_workflow_id    VARCHAR(255) NOT NULL,
    temporal_run_id         VARCHAR(255),
    trigger_source          trigger_source NOT NULL DEFAULT 'connector',
    triggered_by_user_id    UUID REFERENCES users(id),
    status                  run_status NOT NULL DEFAULT 'queued',
    error_message           TEXT,
    stages_completed        INTEGER NOT NULL DEFAULT 0,
    stages_total            INTEGER NOT NULL DEFAULT 0,
    started_at              TIMESTAMPTZ,
    finished_at             TIMESTAMPTZ,
    duration_ms             INTEGER,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (temporal_workflow_id)
);
CREATE INDEX idx_runs_status        ON pipeline_runs(status) WHERE status IN ('queued','running');
CREATE INDEX idx_runs_doc_version   ON pipeline_runs(document_version_id);
CREATE INDEX idx_runs_pipeline      ON pipeline_runs(pipeline_id, created_at DESC);

-- =====================================================================
-- 12. PIPELINE STAGE RUNS  (per-stage telemetry & artifact pointers)
-- =====================================================================
CREATE TABLE pipeline_stage_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    stage_id            VARCHAR(128) NOT NULL,          -- matches YAML stage.id
    worker_name         VARCHAR(128) NOT NULL,
    status              run_status NOT NULL DEFAULT 'queued',
    attempt             INTEGER NOT NULL DEFAULT 1,
    input_artifact_uri  TEXT,
    output_artifact_uri TEXT,                           -- MinIO uri to interim output
    metrics             JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message       TEXT,
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    duration_ms         INTEGER,
    UNIQUE (run_id, stage_id, attempt)
);
CREATE INDEX idx_stage_runs_run ON pipeline_stage_runs(run_id);

-- =====================================================================
-- 13. CHUNKS  (parent/child + RAPTOR summaries; Qdrant pointers)
-- =====================================================================
CREATE TABLE chunks (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id     UUID NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    parent_chunk_id         UUID REFERENCES chunks(id) ON DELETE CASCADE,
    kind                    chunk_kind NOT NULL,
    level                   INTEGER NOT NULL DEFAULT 0,         -- 0 = leaf; >0 = RAPTOR layer
    ordinal                 INTEGER NOT NULL,                   -- order within parent / doc
    token_count             INTEGER,
    char_count              INTEGER,
    page_number             INTEGER,
    section_path            TEXT,                               -- e.g. "1.2.3 Methods > Sampling"
    content_hash            CHAR(64) NOT NULL,
    minio_text_uri          TEXT NOT NULL,
    qdrant_collection       VARCHAR(255),
    qdrant_point_id         VARCHAR(64),                        -- UUID or numeric string
    embedding_model         VARCHAR(128),
    embedding_dim           INTEGER,
    pipeline_run_id         UUID REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_chunks_doc_version ON chunks(document_version_id);
CREATE INDEX idx_chunks_parent      ON chunks(parent_chunk_id);
CREATE INDEX idx_chunks_qdrant      ON chunks(qdrant_collection, qdrant_point_id);
CREATE INDEX idx_chunks_kind_level  ON chunks(kind, level);
CREATE INDEX idx_chunks_metadata    ON chunks USING GIN (metadata jsonb_path_ops);

-- =====================================================================
-- 14. EVENTS  (outbox for Kafka/Redis triggers; also audit trail)
-- =====================================================================
CREATE TABLE events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    project_id      UUID REFERENCES projects(id) ON DELETE CASCADE,
    event_type      VARCHAR(128) NOT NULL,             -- document.uploaded, datasource.synced, ...
    aggregate_type  VARCHAR(64),                       -- document, datasource, pipeline
    aggregate_id    UUID,
    payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    published       BOOLEAN NOT NULL DEFAULT FALSE,
    published_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_events_unpublished ON events(created_at) WHERE NOT published;
CREATE INDEX idx_events_type        ON events(event_type, created_at DESC);
CREATE INDEX idx_events_aggregate   ON events(aggregate_type, aggregate_id);

-- =====================================================================
-- 15. DATA LIFECYCLE POLICIES  (retention, archival, deletion rules)
-- =====================================================================
CREATE TABLE lifecycle_policies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    project_id          UUID REFERENCES projects(id) ON DELETE CASCADE,
    name                VARCHAR(255) NOT NULL,
    applies_to          VARCHAR(64)  NOT NULL,          -- raw|interim|canonical|final|chunks
    retention_value     INTEGER      NOT NULL,
    retention_unit      retention_unit NOT NULL,
    action_on_expiry    VARCHAR(32)  NOT NULL DEFAULT 'delete', -- delete|archive|cold_storage
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, project_id, applies_to, name)
);

CREATE TRIGGER trg_lifecycle_updated_at
    BEFORE UPDATE ON lifecycle_policies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- 16. API KEYS  (programmatic access; tenant- or user-scoped)
-- =====================================================================
CREATE TABLE api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id         UUID REFERENCES users(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    key_prefix      VARCHAR(16)  NOT NULL,
    key_hash        CHAR(64)     NOT NULL,             -- sha256 of full key
    scopes          TEXT[]       NOT NULL DEFAULT ARRAY[]::TEXT[],
    expires_at      TIMESTAMPTZ,
    last_used_at    TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (key_hash)
);
CREATE INDEX idx_apikeys_prefix ON api_keys(key_prefix) WHERE revoked_at IS NULL;
CREATE INDEX idx_apikeys_tenant ON api_keys(tenant_id);

-- =====================================================================
-- 17. AUDIT LOG
-- =====================================================================
CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID REFERENCES tenants(id) ON DELETE SET NULL,
    actor_user_id   UUID REFERENCES users(id)   ON DELETE SET NULL,
    actor_type      VARCHAR(32)  NOT NULL DEFAULT 'user',     -- user|api_key|system
    action          VARCHAR(128) NOT NULL,                    -- pipeline.create, document.delete, ...
    resource_type   VARCHAR(64),
    resource_id     UUID,
    request_ip      INET,
    user_agent      TEXT,
    before_state    JSONB,
    after_state     JSONB,
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_tenant_time  ON audit_log(tenant_id, created_at DESC);
CREATE INDEX idx_audit_resource     ON audit_log(resource_type, resource_id);
CREATE INDEX idx_audit_actor        ON audit_log(actor_user_id, created_at DESC);

-- =====================================================================
-- 18. AGENTS  (catalog of agent definitions usable in user flow)
-- =====================================================================
CREATE TABLE agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id)  ON DELETE CASCADE,
    project_id      UUID REFERENCES projects(id)          ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    yaml_spec       TEXT         NOT NULL,
    parsed_spec     JSONB        NOT NULL,
    version         INTEGER      NOT NULL DEFAULT 1,
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, project_id, name, version)
);
CREATE INDEX idx_agents_project ON agents(project_id) WHERE is_active;

CREATE TRIGGER trg_agents_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- Convenience views
-- =====================================================================
CREATE OR REPLACE VIEW v_active_pipelines AS
SELECT p.id, p.tenant_id, t.slug AS tenant_slug, p.name, p.version,
       p.doc_types, p.datasource_types, p.activated_at
FROM pipelines p
JOIN tenants t ON t.id = p.tenant_id
WHERE p.lifecycle = 'active';

CREATE OR REPLACE VIEW v_document_lineage AS
SELECT d.id        AS document_id,
       d.project_id,
       d.title,
       d.status,
       dv.version,
       dv.minio_raw_uri,
       dv.minio_canonical_uri,
       pr.id       AS run_id,
       pr.status   AS run_status,
       pl.name     AS pipeline_name,
       pl.version  AS pipeline_version
FROM documents d
LEFT JOIN document_versions dv ON dv.document_id = d.id
LEFT JOIN pipeline_runs    pr ON pr.document_version_id = dv.id
LEFT JOIN pipelines        pl ON pl.id = pr.pipeline_id;

COMMIT;
