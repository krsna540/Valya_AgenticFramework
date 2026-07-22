"""hook lifecycle expansion: 10-stage taxonomy + custom handler types

Adds the full lifecycle_event taxonomy (SessionStart, UserPromptSubmit,
PreToolUse, PostToolUse.Success, PostToolUse.Failure, PreCompact,
SubagentStart, SubagentStop, Stop, Notification) and three real-execution
handler types (http webhook, command/script, mcp_tool) alongside the
existing safe python handler_key path. See app/services/hooks.py and
app/services/hook_handlers.py.

handler_key becomes nullable (only meaningful for handler_type="python").
Existing rows default lifecycle_event to "UserPromptSubmit" and
handler_type to "python", matching guardrail_interceptor — the most common
seeded hook. Rows using a different built-in handler_key (e.g.
pii_redactor, usage_logger) should have lifecycle_event corrected manually
or via re-seeding, since this is pre-production data.

Revision ID: 0006
Revises: 0004
Create Date: 2026-07-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "hooks", sa.Column("lifecycle_event", sa.String(length=50), nullable=False, server_default="UserPromptSubmit")
    )
    op.add_column("hooks", sa.Column("handler_type", sa.String(length=20), nullable=False, server_default="python"))
    op.add_column(
        "hooks", sa.Column("handler_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json"))
    )
    op.add_column(
        "hooks", sa.Column("execution_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json"))
    )
    op.add_column("hooks", sa.Column("version", sa.String(length=30), nullable=False, server_default="1.0.0"))
    op.add_column("hooks", sa.Column("status", sa.String(length=20), nullable=False, server_default="Active"))
    op.add_column("hooks", sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("hooks", sa.Column("author", sa.String(length=255), nullable=True))
    op.alter_column("hooks", "handler_key", existing_type=sa.String(length=100), nullable=True)


def downgrade() -> None:
    op.alter_column(
        "hooks", "handler_key", existing_type=sa.String(length=100), nullable=False, server_default="guardrail_interceptor"
    )
    op.drop_column("hooks", "author")
    op.drop_column("hooks", "tags")
    op.drop_column("hooks", "status")
    op.drop_column("hooks", "version")
    op.drop_column("hooks", "execution_policy")
    op.drop_column("hooks", "handler_config")
    op.drop_column("hooks", "handler_type")
    op.drop_column("hooks", "lifecycle_event")
