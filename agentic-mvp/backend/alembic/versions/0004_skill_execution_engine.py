"""skill execution engine: handler_key binds a Skill row to a BaseSkill impl

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "skills", sa.Column("handler_key", sa.String(length=100), nullable=False, server_default="word_count")
    )


def downgrade() -> None:
    op.drop_column("skills", "handler_key")
