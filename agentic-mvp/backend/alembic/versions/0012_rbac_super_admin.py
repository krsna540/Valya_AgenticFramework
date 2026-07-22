"""three-role RBAC: super_admin/admin/user, tenant_id nullable on users

Introduces the OPA-backed three-flow role model (see
docs/AUTHORIZATION.md and backend/policies/authz.rego):

  super_admin — platform-level, not scoped to any one tenant. Creates
                tenants and assigns admins to them.
  admin       — full control of everything within their own tenant
                (renamed from the old "admin" — same value, no data
                change needed).
  user        — agents + chat only (renamed from the old "member").

Steps:
  1. users.tenant_id becomes nullable — a super_admin has no tenant.
  2. Existing role='member' rows become role='user' (pure rename; no
     behavior change for those accounts, they already had the narrower
     capabilities the new "user" role also has).

No DB-level CHECK constraint on `role` — consistent with how `status`
fields elsewhere in this app (Hook.status, TenantScopedMixin.status) are
validated at the Pydantic schema layer, not the database layer.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "tenant_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.execute("UPDATE users SET role = 'user' WHERE role = 'member'")


def downgrade() -> None:
    # Best-effort: any super_admin rows (tenant_id IS NULL) can't be
    # restored to a valid tenant-scoped admin/member automatically — this
    # app has never been deployed against a real Postgres instance, so a
    # hand-crafted downgrade path for that edge case isn't worth building
    # (matches the precedent set by earlier migrations' downgrade
    # docstrings, e.g. 0011).
    op.execute("UPDATE users SET role = 'member' WHERE role = 'user'")
    op.alter_column("users", "tenant_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
