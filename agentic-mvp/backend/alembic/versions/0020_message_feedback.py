"""message feedback

Adds a like/dislike feedback signal to `messages`, per the Agent Chat UI
frontend spec's message-level action bar (§5): a single nullable
`feedback` column ("like" | "dislike") makes the two mutually exclusive
by construction, plus `feedback_reason` for the optional reason chip/
free-text captured when a user dislikes a reply.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("feedback", sa.String(10), nullable=True))
    op.add_column("messages", sa.Column("feedback_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "feedback_reason")
    op.drop_column("messages", "feedback")
