"""registry access model — access_class / visibility / fork provenance

Adds the two independent access-modifier axes from
docs/PLATFORM_ARCHITECTURE.md §7.2 to every registry kind that carries
TenantScopedMixin (agents, skills, tools, plugins, prompts) plus hooks
(which gets the same columns directly via the new RegistryAccessMixin,
since it predates TenantScopedMixin and can't pick them up through it
without duplicate version/status columns — see app/models/hook.py).

  access_class  "default" | "custom"   — who may MUTATE the row
  visibility    "public" | "protected" | "private" — who may SEE/USE it
  forked_from_id / forked_from_version — provenance when forked (§7.5)
  owner_user_id / reviewed_by_user_id  — the named-human invariant M3
                                           requires before LIVE (Frozen
                                           Spec §6.2)

Backfill: access_class is derived from the existing tenant_id-IS-NULL
convention (NULL => "default", the platform-shared rows every table
already had; non-NULL => "custom") so the new column agrees with what
every pre-existing query already assumes, rather than starting all rows
as "custom" and quietly making every platform-shared row admin-editable.
visibility backfills to "protected" for custom rows (their pre-migration
behavior — visible/attachable across the owning tenant) and is irrelevant
for default rows (always readable regardless of visibility, per §7.2).

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-08

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# TenantScopedMixin tables (already have tenant_id/version/status).
_TENANT_SCOPED_TABLES = ("agents", "skills", "tools", "plugins", "prompts")
# Hook has tenant_id but not via TenantScopedMixin — same new columns, added
# in the same loop since the column set is identical.
_ALL_TABLES = (*_TENANT_SCOPED_TABLES, "hooks")


def upgrade() -> None:
    for table in _ALL_TABLES:
        op.add_column(table, sa.Column("access_class", sa.String(length=20), nullable=False, server_default="custom"))
        op.add_column(table, sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"))
        op.add_column(table, sa.Column("forked_from_id", postgresql.UUID(as_uuid=True), nullable=True))
        op.add_column(table, sa.Column("forked_from_version", sa.String(length=30), nullable=True))
        op.add_column(
            table,
            sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )
        op.add_column(
            table,
            sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        )

        # Backfill from the existing tenant_id convention.
        op.execute(f"UPDATE {table} SET access_class = 'default', visibility = 'public' WHERE tenant_id IS NULL")
        op.execute(f"UPDATE {table} SET access_class = 'custom', visibility = 'protected' WHERE tenant_id IS NOT NULL")

        op.create_index(f"ix_{table}_access_class", table, ["access_class"])
        op.create_index(f"ix_{table}_visibility", table, ["visibility"])


def downgrade() -> None:
    for table in _ALL_TABLES:
        op.drop_index(f"ix_{table}_visibility", table_name=table)
        op.drop_index(f"ix_{table}_access_class", table_name=table)
        op.drop_column(table, "reviewed_by_user_id")
        op.drop_column(table, "owner_user_id")
        op.drop_column(table, "forked_from_version")
        op.drop_column(table, "forked_from_id")
        op.drop_column(table, "visibility")
        op.drop_column(table, "access_class")
