"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _registry_columns():
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "skills",
        *_registry_columns(),
        sa.Column("config", postgresql.JSON(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "tools",
        *_registry_columns(),
        sa.Column("config", postgresql.JSON(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "plugins",
        *_registry_columns(),
        sa.Column("config", postgresql.JSON(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "hooks",
        *_registry_columns(),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("config", postgresql.JSON(), nullable=False, server_default="{}"),
    )

    op.create_table(
        "agents",
        *_registry_columns(),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=False, server_default="stub-echo"),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
    )

    op.create_table(
        "agent_skills",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "agent_tools",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tool_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "agent_plugins",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("plugin_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("plugins.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "agent_hooks",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("hook_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hooks.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False, server_default="New conversation"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("agent_hooks")
    op.drop_table("agent_plugins")
    op.drop_table("agent_tools")
    op.drop_table("agent_skills")
    op.drop_table("agents")
    op.drop_table("hooks")
    op.drop_table("plugins")
    op.drop_table("tools")
    op.drop_table("skills")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
