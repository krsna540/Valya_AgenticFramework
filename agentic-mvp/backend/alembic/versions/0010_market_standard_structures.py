"""market-standard structures for tools/prompts/datasources

Tools: MCP tool annotation hints (title/readOnlyHint/destructiveHint/
idempotentHint/openWorldHint per MCP spec 2025-06-18).

Prompts: full restructure from a flat `content: Text` (no tenant scoping at
all) to tenant-scoped, versioned, chat-style `messages` + `variables` +
`model_params` + `tags` + `label`, matching Langfuse/LangSmith Hub/
PromptLayer conventions. Existing `content` values are backfilled into a
single user-role message before the column is dropped — see
docs/SKILL_STANDARD.md's Prompts section and
app/models/prompt.py's class docstring.

Datasources: auth_type + sync_mode/sync_schedule_cron, and connector
connection_config fields now follow a structured, Airbyte-inspired spec
(app/api/routes/datasources.py::CONNECTOR_FIELD_SPECS) — no schema change
needed there since connection_config was already a free JSON dict.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- tools: MCP annotations ---------------------------------------------
    op.add_column(
        "tools",
        sa.Column(
            "annotations",
            sa.JSON(),
            nullable=False,
            server_default=sa.text(
                """'{"title": null, "readOnlyHint": false, "destructiveHint": false, "idempotentHint": false, "openWorldHint": true}'"""
            ),
        ),
    )

    # --- prompts: tenant scoping + versioning + structured content ---------
    op.add_column("prompts", sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_prompts_tenant_id", "prompts", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE")
    op.add_column("prompts", sa.Column("version", sa.String(length=30), nullable=False, server_default="1.0.0"))
    op.add_column("prompts", sa.Column("status", sa.String(length=20), nullable=False, server_default="Active"))
    op.add_column("prompts", sa.Column("label", sa.String(length=50), nullable=False, server_default="latest"))
    op.add_column("prompts", sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("prompts", sa.Column("messages", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("prompts", sa.Column("variables", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("prompts", sa.Column("model_params", sa.JSON(), nullable=False, server_default="{}"))

    # Backfill: every existing prompt's flat `content` becomes a single
    # user-role message, so no prompt goes live with an empty messages list.
    op.execute(
        """
        UPDATE prompts
        SET messages = jsonb_build_array(jsonb_build_object('role', 'user', 'content', content))
        WHERE content IS NOT NULL AND content <> ''
        """
    )

    op.drop_column("prompts", "content")

    # --- datasources: auth_type + sync_mode/schedule ------------------------
    op.add_column("datasources", sa.Column("auth_type", sa.String(length=20), nullable=False, server_default="none"))
    op.add_column("datasources", sa.Column("sync_mode", sa.String(length=20), nullable=False, server_default="full_refresh"))
    op.add_column("datasources", sa.Column("sync_schedule_cron", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("datasources", "sync_schedule_cron")
    op.drop_column("datasources", "sync_mode")
    op.drop_column("datasources", "auth_type")

    op.add_column("prompts", sa.Column("content", sa.Text(), nullable=False, server_default=""))
    op.execute(
        """
        UPDATE prompts
        SET content = COALESCE(messages -> 0 ->> 'content', '')
        """
    )
    op.drop_column("prompts", "model_params")
    op.drop_column("prompts", "variables")
    op.drop_column("prompts", "messages")
    op.drop_column("prompts", "tags")
    op.drop_column("prompts", "label")
    op.drop_column("prompts", "status")
    op.drop_column("prompts", "version")
    op.drop_constraint("fk_prompts_tenant_id", "prompts", type_="foreignkey")
    op.drop_column("prompts", "tenant_id")

    op.drop_column("tools", "annotations")
