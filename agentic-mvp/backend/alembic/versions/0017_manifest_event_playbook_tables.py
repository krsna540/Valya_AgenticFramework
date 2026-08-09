"""manifest compiler + event spine + playbook registry + platform rules

Four new tables backing docs/PLATFORM_ARCHITECTURE.md:

  * playbooks         — §11.5, the sixth registry kind (procedural memory,
                          when_to_use/canonical_steps/known_assumptions).
                          Same RegistryMixin/TenantScopedMixin shape as
                          skills/prompts/tools/plugins, so it picks up
                          access_class/visibility from migration 0016.
  * events            — §10/§11.3, the append-only episodic-memory spine.
                          Composite PK (run_id, seq).
  * manifests /
    manifest_sessions — §6, the hashed capability document a session pins
                          at start and never re-resolves mid-run.
  * policy_revisions  — the superadmin "Platform rules" screen's numbered,
                          append-only revision history.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-08

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- playbooks -----------------------------------------------------
    op.create_table(
        "playbooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("version", sa.String(length=30), nullable=False, server_default="1.0.0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Active"),
        sa.Column("access_class", sa.String(length=20), nullable=False, server_default="custom"),
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="private"),
        sa.Column("forked_from_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("forked_from_version", sa.String(length=30), nullable=True),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("when_to_use", sa.Text(), nullable=False, server_default=""),
        sa.Column("canonical_steps", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("required_criteria", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("known_assumptions", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("supporting_stats", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.create_index("ix_playbooks_tenant_id", "playbooks", ["tenant_id"])

    # --- events ----------------------------------------------------------
    op.create_table(
        "events",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("seq", sa.BigInteger(), primary_key=True),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("actor", sa.String(length=50), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_events_tenant_ts", "events", ["tenant_id", "ts"])
    op.create_index("ix_events_type", "events", ["type"])

    # --- manifests ---------------------------------------------------------
    op.create_table(
        "manifests",
        sa.Column("manifest_id", sa.String(length=71), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_manifests_project_id", "manifests", ["project_id"])

    op.create_table(
        "manifest_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("manifest_id", sa.String(length=71), sa.ForeignKey("manifests.manifest_id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False, server_default="en"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_manifest_sessions_project_id", "manifest_sessions", ["project_id"])

    # --- policy_revisions ----------------------------------------------
    op.create_table(
        "policy_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("revision_number", sa.Integer(), nullable=False, unique=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("rules", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("tests_passed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("published_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("published_by_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("policy_revisions")
    op.drop_index("ix_manifest_sessions_project_id", table_name="manifest_sessions")
    op.drop_table("manifest_sessions")
    op.drop_index("ix_manifests_project_id", table_name="manifests")
    op.drop_table("manifests")
    op.drop_index("ix_events_type", table_name="events")
    op.drop_index("ix_events_tenant_ts", table_name="events")
    op.drop_table("events")
    op.drop_index("ix_playbooks_tenant_id", table_name="playbooks")
    op.drop_table("playbooks")
