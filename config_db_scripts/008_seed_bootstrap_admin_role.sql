-- =====================================================================
-- KN_Valya :: Grant the bootstrap admin an actual super_admin role
-- =====================================================================
-- Gap found while implementing Milestone 1: 002_seed_reference_data.sql
-- creates the bootstrap admin user (admin@valya.local) with
-- `users.role = 'super_admin'`, but that column is a display-only enum as
-- of 004_auth_and_rbac.sql — real authorization reads
-- `v_user_effective_permissions`, which is driven entirely by `user_roles`.
-- Without a row here, the bootstrap admin has the *label* super_admin but
-- zero actual permissions, and can't even create the first tenant.
--
-- Idempotent: safe to re-run.
-- Apply AFTER 001-007.
-- =====================================================================

BEGIN;
SET search_path TO valya, public;

INSERT INTO user_roles (user_id, role_id, tenant_id, project_id)
VALUES (
    '00000000-0000-0000-0000-0000000000aa',  -- bootstrap admin (002_seed_reference_data.sql)
    '10000000-0000-0000-0000-000000000001',  -- super_admin (004_auth_and_rbac.sql)
    NULL,                                      -- global scope, not tied to one tenant
    NULL
)
ON CONFLICT (user_id, role_id, COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'::uuid),
                                COALESCE(project_id, '00000000-0000-0000-0000-000000000000'::uuid))
DO NOTHING;

COMMIT;
