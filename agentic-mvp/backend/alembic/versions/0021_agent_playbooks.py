"""agent_playbooks association

Wires the Playbook registry (migration 0017) into the Agent, so a Planner
can actually be given playbooks to select from at run time — see
app/agents/playbooks.py. Playbooks were storage-only before this; this is
the runtime-wiring piece their own model docstring flagged as deferred.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_playbooks",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("playbook_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("playbooks.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("agent_playbooks")
