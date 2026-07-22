"""tenancy + RBAC, Persona/Project/Datasource pillars, Intelligence Layer
formalization (tenant scoping + SemVer + MCP fields), project<->intelligence
association matrix, chat project scoping

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-17

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Tenancy & RBAC ----------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    # tenant_id starts nullable so this migration works against a database
    # that already has users in it (pre-dating tenancy) — filled in by the
    # backfill below, then locked to NOT NULL. A fresh/empty database just
    # skips the backfill and goes straight to NOT NULL, same end state.
    op.add_column("users", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True))
    op.add_column("users", sa.Column("role", sa.String(length=20), nullable=False, server_default="member"))

    # Backfill: any pre-existing users (from before this migration) get
    # moved into one shared "Legacy Workspace" tenant, all as admins — the
    # closest equivalent of this app's pre-tenancy behavior, where every
    # authenticated user could already CRUD every registry entity. New
    # signups after this migration each get their own fresh tenant (see
    # app/api/routes/auth.py::signup) and are unaffected.
    conn = op.get_bind()
    existing_user_count = conn.execute(sa.text("SELECT COUNT(*) FROM users WHERE tenant_id IS NULL")).scalar()
    if existing_user_count:
        legacy_tenant_id = str(uuid.uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO tenants (id, name, slug, is_active, created_at, updated_at) "
                "VALUES (:id, :name, :slug, true, now(), now())"
            ),
            {"id": legacy_tenant_id, "name": "Legacy Workspace", "slug": "legacy-workspace"},
        )
        conn.execute(
            sa.text("UPDATE users SET tenant_id = :tid, role = 'admin' WHERE tenant_id IS NULL"),
            {"tid": legacy_tenant_id},
        )

    op.alter_column("users", "tenant_id", nullable=False)

    # --- Personas ------------------------------------------------------------
    op.create_table(
        "personas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("archetype", sa.String(length=100), nullable=True),
        sa.Column("base_model", sa.String(length=100), nullable=True),
        sa.Column("traits", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("safety_compliance_tier", sa.String(length=50), nullable=False, server_default="Standard"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # --- Datasources -----------------------------------------------------------
    op.create_table(
        "datasources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("connector_type", sa.String(length=30), nullable=False),
        sa.Column("connection_config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("auth_status", sa.String(length=20), nullable=False, server_default="not_connected"),
        sa.Column("auth_config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("security_classification", sa.String(length=20), nullable=False, server_default="Internal"),
        sa.Column("sync_status", sa.String(length=20), nullable=False, server_default="idle"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chunking_policy", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("embedding_policy", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # --- Projects ------------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("cost_center", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("execution_mode", sa.String(length=30), nullable=False, server_default="real_time_chat"),
        sa.Column("schedule_cron", sa.String(length=100), nullable=True),
        sa.Column("webhook_slug", sa.String(length=100), nullable=True),
        sa.Column("frozen_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frozen_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "project_users",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_in_project", sa.String(length=20), nullable=False, server_default="member"),
    )
    op.create_table(
        "project_datasources",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("datasource_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("datasources.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "user_persona_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("personas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("user_id", "persona_id", "project_id", name="uq_user_persona_project"),
    )

    op.create_table(
        "project_intelligence_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("component_type", sa.String(length=20), nullable=False),
        sa.Column("component_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_pinned", sa.String(length=30), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("project_id", "component_type", "component_id", name="uq_project_component"),
    )

    # --- Intelligence Layer formalization: tenant scoping + SemVer ---------
    for table in ("agents", "skills", "tools", "plugins", "skill_packages"):
        op.add_column(table, sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True))
        op.add_column(table, sa.Column("version", sa.String(length=30), nullable=False, server_default="1.0.0"))
        op.add_column(table, sa.Column("status", sa.String(length=20), nullable=False, server_default="Active"))
    op.add_column("hooks", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True))

    # Tools: MCP transport metadata
    op.add_column("tools", sa.Column("tool_type", sa.String(length=20), nullable=False, server_default="function"))
    op.add_column("tools", sa.Column("mcp_transport", sa.String(length=10), nullable=True))
    op.add_column("tools", sa.Column("mcp_endpoint", sa.String(length=500), nullable=True))
    op.add_column("tools", sa.Column("mcp_command", sa.String(length=500), nullable=True))
    op.add_column("tools", sa.Column("mcp_tool_name", sa.String(length=255), nullable=True))

    # --- Chat project scoping ------------------------------------------------
    op.add_column("conversations", sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "project_id")

    op.drop_column("tools", "mcp_tool_name")
    op.drop_column("tools", "mcp_command")
    op.drop_column("tools", "mcp_endpoint")
    op.drop_column("tools", "mcp_transport")
    op.drop_column("tools", "tool_type")

    op.drop_column("hooks", "tenant_id")
    for table in ("skill_packages", "plugins", "tools", "skills", "agents"):
        op.drop_column(table, "status")
        op.drop_column(table, "version")
        op.drop_column(table, "tenant_id")

    op.drop_table("project_intelligence_bindings")
    op.drop_table("user_persona_mappings")
    op.drop_table("project_datasources")
    op.drop_table("project_users")
    op.drop_table("projects")
    op.drop_table("datasources")
    op.drop_table("personas")

    op.drop_column("users", "role")
    op.drop_column("users", "tenant_id")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
