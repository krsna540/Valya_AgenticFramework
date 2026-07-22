"""skill packages: agentskills.io-format (SKILL.md + scripts/references/assets)

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill_packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("license", sa.String(length=255), nullable=True),
        sa.Column("compatibility", sa.String(length=500), nullable=True),
        sa.Column("metadata_fields", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("allowed_tools", sa.String(length=2000), nullable=True),
        sa.Column("skill_md_raw", sa.Text(), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("dir_path", sa.String(length=1000), nullable=False),
        sa.Column("file_manifest", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "agent_skill_packages",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "skill_package_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill_packages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("agent_skill_packages")
    op.drop_table("skill_packages")
