-- =====================================================================
-- KN_Valya :: Reference / seed data (idempotent)
-- =====================================================================
-- Optional. Loads a system tenant + default lifecycle policies so a
-- fresh install can boot. Safe to re-run.
-- =====================================================================

BEGIN;
SET search_path TO valya, public;

-- ---------------------------------------------------------------------
-- System tenant (for cross-tenant admin tooling, internal pipelines)
-- ---------------------------------------------------------------------
INSERT INTO tenants (id, slug, name, status, settings)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'system',
    'System',
    'active',
    '{"internal": true}'::jsonb
)
ON CONFLICT (slug) DO NOTHING;

-- ---------------------------------------------------------------------
-- Bootstrap super_admin
-- ---------------------------------------------------------------------
INSERT INTO users (id, tenant_id, email, display_name, role, auth_provider)
VALUES (
    '00000000-0000-0000-0000-0000000000aa',
    '00000000-0000-0000-0000-000000000001',
    'admin@valya.local',
    'Bootstrap Admin',
    'super_admin',
    'local'
)
ON CONFLICT (tenant_id, email) DO NOTHING;

-- ---------------------------------------------------------------------
-- Default lifecycle policies (apply tenant-wide, no project scope)
-- ---------------------------------------------------------------------
INSERT INTO lifecycle_policies
    (tenant_id, project_id, name, applies_to, retention_value, retention_unit, action_on_expiry)
VALUES
    ('00000000-0000-0000-0000-000000000001', NULL, 'default-raw',       'raw',       365, 'days',  'archive'),
    ('00000000-0000-0000-0000-000000000001', NULL, 'default-interim',   'interim',    30, 'days',  'delete'),
    ('00000000-0000-0000-0000-000000000001', NULL, 'default-canonical', 'canonical',   1, 'years', 'archive'),
    ('00000000-0000-0000-0000-000000000001', NULL, 'default-final',     'final',       1, 'years', 'archive')
ON CONFLICT DO NOTHING;

COMMIT;
