"""user <-> policy mappings (Norms tab "Users & assignments")

Mirrors user_persona_mappings (migration 0008) — lets an admin call out
that a specific Policy applies to a specific User, alongside the existing
persona assignment. See app/models/policy.py::UserPolicyMapping.

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_policy_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint("uq_user_policy", "user_policy_mappings", ["user_id", "policy_id"])


def downgrade() -> None:
    op.drop_table("user_policy_mappings")
