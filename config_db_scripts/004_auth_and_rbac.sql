-- =====================================================================
-- KN_Valya :: Auth + RBAC schema
-- =====================================================================
-- Replaces reliance on the ENUM `user_role` for permission checks with
-- a proper RBAC model (roles + permissions + bindings), keeps the enum
-- around as a *display category* only.
--
-- Covers: password credentials (argon2id), SSO providers, JWT refresh
-- tokens, fine-grained permissions, role bindings at tenant + project
-- scope, login audit.
--
-- Apply AFTER 001/002/003.
-- =====================================================================

BEGIN;
SET search_path TO valya, public;

-- ---------------------------------------------------------------------
-- ENUM additions
-- ---------------------------------------------------------------------
CREATE TYPE auth_method        AS ENUM ('password', 'oidc', 'saml', 'api_key');
CREATE TYPE permission_effect  AS ENUM ('allow', 'deny');
CREATE TYPE role_scope         AS ENUM ('global', 'tenant', 'project');

-- =====================================================================
-- 19. PASSWORD CREDENTIALS  (one row per password-auth user)
-- =====================================================================
CREATE TABLE password_credentials (
    user_id             UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    password_hash       TEXT        NOT NULL,                 -- argon2id encoded
    must_change         BOOLEAN     NOT NULL DEFAULT FALSE,
    last_changed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    failed_attempts     INTEGER     NOT NULL DEFAULT 0,
    locked_until        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TRIGGER trg_pwd_creds_updated_at
    BEFORE UPDATE ON password_credentials
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- 20. SSO PROVIDERS  (per tenant: OIDC / SAML config)
-- =====================================================================
CREATE TABLE sso_providers (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name                    VARCHAR(128) NOT NULL,
    protocol                VARCHAR(16)  NOT NULL,            -- 'oidc' | 'saml'
    issuer                  TEXT         NOT NULL,
    client_id               TEXT,
    client_secret_ref       VARCHAR(512),                     -- ref into SecretProvider (Vault later)
    discovery_url           TEXT,                             -- OIDC well-known
    saml_metadata_xml       TEXT,
    jit_provision           BOOLEAN      NOT NULL DEFAULT TRUE,
    default_role_id         UUID,                             -- FK added after roles table
    allowed_email_domains   TEXT[]       NOT NULL DEFAULT ARRAY[]::TEXT[],
    attribute_mapping       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    is_active               BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);
CREATE INDEX idx_sso_tenant ON sso_providers(tenant_id) WHERE is_active;

CREATE TRIGGER trg_sso_updated_at
    BEFORE UPDATE ON sso_providers
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- =====================================================================
-- 21. PERMISSIONS  (the catalog of "what you can do")
-- =====================================================================
CREATE TABLE permissions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            VARCHAR(128) NOT NULL UNIQUE,             -- 'pipeline.create', 'document.read', etc.
    resource_type   VARCHAR(64)  NOT NULL,                    -- 'pipeline', 'document', 'tenant', ...
    action          VARCHAR(32)  NOT NULL,                    -- 'create','read','update','delete','run','admin'
    description     TEXT,
    is_system       BOOLEAN      NOT NULL DEFAULT TRUE        -- system perms cannot be deleted
);
CREATE INDEX idx_permissions_resource ON permissions(resource_type, action);

-- =====================================================================
-- 22. ROLES  (named bundles of permissions; tenant- or global-scoped)
-- =====================================================================
CREATE TABLE roles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,  -- NULL = global / built-in
    name            VARCHAR(128) NOT NULL,
    scope           role_scope   NOT NULL DEFAULT 'tenant',
    description     TEXT,
    is_system       BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, name)
);
CREATE INDEX idx_roles_tenant ON roles(tenant_id);

CREATE TRIGGER trg_roles_updated_at
    BEFORE UPDATE ON roles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Backfill sso_providers.default_role_id FK
ALTER TABLE sso_providers
    ADD CONSTRAINT fk_sso_default_role
    FOREIGN KEY (default_role_id) REFERENCES roles(id) ON DELETE SET NULL;

-- =====================================================================
-- 23. ROLE_PERMISSIONS  (M:N + effect for deny overrides)
-- =====================================================================
CREATE TABLE role_permissions (
    role_id         UUID NOT NULL REFERENCES roles(id)       ON DELETE CASCADE,
    permission_id   UUID NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    effect          permission_effect NOT NULL DEFAULT 'allow',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (role_id, permission_id)
);

-- =====================================================================
-- 24. USER_ROLES  (user gets role at tenant or project scope)
-- =====================================================================
CREATE TABLE user_roles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id         UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    tenant_id       UUID REFERENCES tenants(id)  ON DELETE CASCADE,
    project_id      UUID REFERENCES projects(id) ON DELETE CASCADE,
    granted_by      UUID REFERENCES users(id),
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    UNIQUE (user_id, role_id, COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid),
                                COALESCE(project_id, '00000000-0000-0000-0000-000000000000'::uuid))
);
CREATE INDEX idx_user_roles_user    ON user_roles(user_id)    WHERE revoked_at IS NULL;
CREATE INDEX idx_user_roles_tenant  ON user_roles(tenant_id)  WHERE revoked_at IS NULL;
CREATE INDEX idx_user_roles_project ON user_roles(project_id) WHERE revoked_at IS NULL;

-- =====================================================================
-- 25. REFRESH TOKENS  (JWT refresh; access tokens are stateless)
-- =====================================================================
CREATE TABLE refresh_tokens (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash      CHAR(64) NOT NULL UNIQUE,                  -- sha256 of opaque token
    family_id       UUID     NOT NULL,                         -- rotation family
    issued_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL,
    revoked_at      TIMESTAMPTZ,
    replaced_by_id  UUID REFERENCES refresh_tokens(id),
    user_agent      TEXT,
    ip_address      INET
);
CREATE INDEX idx_refresh_user_active ON refresh_tokens(user_id) WHERE revoked_at IS NULL;
CREATE INDEX idx_refresh_family      ON refresh_tokens(family_id);

-- =====================================================================
-- 26. LOGIN AUDIT
-- =====================================================================
CREATE TABLE login_audit (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    tenant_id       UUID REFERENCES tenants(id) ON DELETE SET NULL,
    auth_method     auth_method NOT NULL,
    success         BOOLEAN     NOT NULL,
    failure_reason  VARCHAR(64),                              -- bad_password|locked|sso_failed|...
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_login_user_time   ON login_audit(user_id, created_at DESC);
CREATE INDEX idx_login_failures    ON login_audit(created_at DESC) WHERE NOT success;

-- =====================================================================
-- 27. Seed system permissions + built-in roles
-- =====================================================================
INSERT INTO permissions (code, resource_type, action, description) VALUES
    ('tenant.read',         'tenant',     'read',   'View tenant settings'),
    ('tenant.admin',        'tenant',     'admin',  'Full tenant administration'),
    ('project.create',      'project',    'create', 'Create projects in tenant'),
    ('project.read',        'project',    'read',   'View project'),
    ('project.update',      'project',    'update', 'Edit project settings'),
    ('project.delete',      'project',    'delete', 'Delete project'),
    ('user.invite',         'user',       'create', 'Invite users to tenant'),
    ('user.read',           'user',       'read',   'View users'),
    ('user.update',         'user',       'update', 'Edit user profile/role'),
    ('user.delete',         'user',       'delete', 'Remove user'),
    ('connector.create',    'connector',  'create', 'Create connector'),
    ('connector.read',      'connector',  'read',   'View connector config (non-secret)'),
    ('connector.update',    'connector',  'update', 'Edit connector'),
    ('connector.delete',    'connector',  'delete', 'Delete connector'),
    ('datasource.create',   'datasource', 'create', 'Create datasource'),
    ('datasource.read',     'datasource', 'read',   'View datasource'),
    ('datasource.update',   'datasource', 'update', 'Edit datasource'),
    ('datasource.delete',   'datasource', 'delete', 'Delete datasource'),
    ('document.upload',     'document',   'create', 'Upload documents'),
    ('document.read',       'document',   'read',   'View documents and content'),
    ('document.delete',     'document',   'delete', 'Delete documents'),
    ('pipeline.create',     'pipeline',   'create', 'Create pipeline'),
    ('pipeline.read',       'pipeline',   'read',   'View pipeline'),
    ('pipeline.update',     'pipeline',   'update', 'Edit pipeline'),
    ('pipeline.delete',     'pipeline',   'delete', 'Delete pipeline'),
    ('pipeline.run',        'pipeline',   'run',    'Trigger ingestion / reindex'),
    ('agent.create',        'agent',      'create', 'Create agent'),
    ('agent.read',          'agent',      'read',   'View agent'),
    ('agent.update',        'agent',      'update', 'Edit agent'),
    ('agent.delete',        'agent',      'delete', 'Delete agent'),
    ('agent.run',           'agent',      'run',    'Execute agent in user flow'),
    ('audit.read',          'audit',      'read',   'Read audit log')
ON CONFLICT (code) DO NOTHING;

-- Built-in roles (global; not tied to any tenant). Tenants reference these
-- by id from user_roles, OR clone them into a tenant-scoped role for customization.
INSERT INTO roles (id, tenant_id, name, scope, description, is_system) VALUES
    ('10000000-0000-0000-0000-000000000001', NULL, 'super_admin',    'global',  'Full system access',                TRUE),
    ('10000000-0000-0000-0000-000000000002', NULL, 'tenant_admin',   'tenant',  'Manages a tenant',                  TRUE),
    ('10000000-0000-0000-0000-000000000003', NULL, 'project_admin',  'project', 'Manages a project',                 TRUE),
    ('10000000-0000-0000-0000-000000000004', NULL, 'member',         'project', 'Read + run within a project',       TRUE),
    ('10000000-0000-0000-0000-000000000005', NULL, 'viewer',         'project', 'Read-only within a project',        TRUE)
ON CONFLICT (tenant_id, name) DO NOTHING;

-- Grant: super_admin → all permissions
INSERT INTO role_permissions (role_id, permission_id)
SELECT '10000000-0000-0000-0000-000000000001', id FROM permissions
ON CONFLICT DO NOTHING;

-- Grant: tenant_admin → everything except super-admin-only operations
INSERT INTO role_permissions (role_id, permission_id)
SELECT '10000000-0000-0000-0000-000000000002', id FROM permissions
WHERE code <> 'tenant.admin' OR code = 'tenant.admin'
ON CONFLICT DO NOTHING;

-- Grant: project_admin → project + ingestion + agent management
INSERT INTO role_permissions (role_id, permission_id)
SELECT '10000000-0000-0000-0000-000000000003', id FROM permissions
WHERE code IN (
    'project.read','project.update',
    'datasource.create','datasource.read','datasource.update','datasource.delete',
    'document.upload','document.read','document.delete',
    'pipeline.create','pipeline.read','pipeline.update','pipeline.delete','pipeline.run',
    'agent.create','agent.read','agent.update','agent.delete','agent.run',
    'connector.read'
) ON CONFLICT DO NOTHING;

-- Grant: member → read + run
INSERT INTO role_permissions (role_id, permission_id)
SELECT '10000000-0000-0000-0000-000000000004', id FROM permissions
WHERE code IN (
    'project.read','datasource.read','document.read','document.upload',
    'pipeline.read','agent.read','agent.run'
) ON CONFLICT DO NOTHING;

-- Grant: viewer → read only
INSERT INTO role_permissions (role_id, permission_id)
SELECT '10000000-0000-0000-0000-000000000005', id FROM permissions
WHERE code IN (
    'project.read','datasource.read','document.read','pipeline.read','agent.read'
) ON CONFLICT DO NOTHING;

-- =====================================================================
-- 28. Helper view: effective permissions per user (flattens user_roles)
-- =====================================================================
CREATE OR REPLACE VIEW v_user_effective_permissions AS
SELECT  ur.user_id,
        ur.tenant_id   AS scope_tenant_id,
        ur.project_id  AS scope_project_id,
        p.code         AS permission_code,
        rp.effect      AS effect
FROM    user_roles ur
JOIN    role_permissions rp ON rp.role_id = ur.role_id
JOIN    permissions p       ON p.id = rp.permission_id
WHERE   ur.revoked_at IS NULL
  AND   (ur.expires_at IS NULL OR ur.expires_at > NOW());

COMMIT;
