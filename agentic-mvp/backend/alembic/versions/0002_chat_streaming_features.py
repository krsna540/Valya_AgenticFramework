"""chat streaming features: message tree, citations, files, prompts

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- conversations: split-screen support ---
    op.add_column(
        "conversations",
        sa.Column("secondary_agent_ids", postgresql.JSON(), nullable=False, server_default="[]"),
    )

    # --- messages: tree structure, citations, attachments ---
    op.add_column(
        "messages",
        sa.Column(
            "parent_message_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
        ),
    )
    op.add_column(
        "messages",
        sa.Column(
            "agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.add_column(
        "messages", sa.Column("is_active_branch", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column("messages", sa.Column("citations", postgresql.JSON(), nullable=False, server_default="[]"))
    op.add_column("messages", sa.Column("file_ids", postgresql.JSON(), nullable=False, server_default="[]"))
    op.alter_column("messages", "content", server_default="")
    op.create_index("ix_messages_parent_message_id", "messages", ["parent_message_id"])
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    # --- prompts ---
    op.create_table(
        "prompts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
    )

    # --- uploaded_files ---
    op.create_table(
        "uploaded_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_path", sa.String(length=1000), nullable=False),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("uploaded_files")
    op.drop_table("prompts")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_index("ix_messages_parent_message_id", table_name="messages")
    op.drop_column("messages", "file_ids")
    op.drop_column("messages", "citations")
    op.drop_column("messages", "is_active_branch")
    op.drop_column("messages", "agent_id")
    op.drop_column("messages", "parent_message_id")
    op.drop_column("conversations", "secondary_agent_ids")
