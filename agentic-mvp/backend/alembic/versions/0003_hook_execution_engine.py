"""hook execution engine: scope + handler_key replace free-text event_type

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("hooks", sa.Column("scope", sa.String(length=20), nullable=False, server_default="agent"))
    op.add_column(
        "hooks", sa.Column("handler_key", sa.String(length=100), nullable=False, server_default="guardrail_interceptor")
    )
    op.drop_column("hooks", "event_type")


def downgrade() -> None:
    op.add_column("hooks", sa.Column("event_type", sa.String(length=100), nullable=False, server_default="pre_message"))
    op.drop_column("hooks", "handler_key")
    op.drop_column("hooks", "scope")
