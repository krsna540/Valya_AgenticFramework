-- =====================================================================
-- KN_Valya :: Fix tenant_admin permission grant
-- =====================================================================
-- Bug found while implementing Milestone 1: 004_auth_and_rbac.sql grants
-- tenant_admin permissions with:
--
--   WHERE code <> 'tenant.admin' OR code = 'tenant.admin'
--
-- That predicate is a tautology (true for every row regardless of `code`),
-- so despite the comment above it ("everything except super-admin-only
-- operations") tenant_admin actually received every permission, identical
-- to super_admin. In practice this is softened by user_roles being scoped
-- by tenant_id/project_id — a tenant_admin's role grant is bound to their
-- own tenant, so v_user_effective_permissions still can't be used to reach
-- into another tenant. But it's not what the schema's own comment says it
-- does, so fixing it rather than leaving a silent discrepancy between intent
-- and behavior.
--
-- Idempotent: safe to re-run.
-- Apply AFTER 001-006.
-- =====================================================================

BEGIN;
SET search_path TO valya, public;

DELETE FROM role_permissions
WHERE role_id = '10000000-0000-0000-0000-000000000002'  -- tenant_admin
  AND permission_id = (SELECT id FROM permissions WHERE code = 'tenant.admin');

COMMIT;
