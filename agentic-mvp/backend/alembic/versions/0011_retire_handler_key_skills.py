"""retire handler_key Skill/BaseSkill catalog; SkillPackage becomes the only Skill

The handler_key-bound Skill system (a DB row pointing at a vetted Python
BaseSkill implementation in app/skills/catalog.py's SKILL_REGISTRY) is
retired at the user's explicit request, in favor of making the SKILL.md-
folder format (formerly a separate "SkillPackage" model) the only way a
skill is defined in this app. See docs/SKILL_STANDARD.md and
[[project_agentic_mvp_nexusclaw_manifest_conventions]] /
[[project_agentic_mvp_market_standard_structures]] in project memory.

Steps (order matters — both the old and new schemas used the name "skills"
and "agent_skills"):
  1. Drop the old handler_key `agent_skills` join table and `skills` table.
  2. Rename `skill_packages` -> `skills`, `agent_skill_packages` ->
     `agent_skills` (column `skill_package_id` -> `skill_id`).
  3. Add skill.json-derived columns to the renamed `skills` table:
     skill_json_raw (nullable — the file is optional), triggers, hooks.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. drop the old handler_key-bound tables ---------------------------
    op.drop_table("agent_skills")
    op.drop_table("skills")

    # --- 2. promote skill_packages to be "skills" ---------------------------
    op.rename_table("skill_packages", "skills")
    op.rename_table("agent_skill_packages", "agent_skills")
    op.alter_column("agent_skills", "skill_package_id", new_column_name="skill_id")

    # --- 3. skill.json-derived columns --------------------------------------
    op.add_column("skills", sa.Column("skill_json_raw", sa.Text(), nullable=True))
    op.add_column("skills", sa.Column("triggers", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("skills", sa.Column("hooks", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("skills", "hooks")
    op.drop_column("skills", "triggers")
    op.drop_column("skills", "skill_json_raw")

    op.alter_column("agent_skills", "skill_id", new_column_name="skill_package_id")
    op.rename_table("agent_skills", "agent_skill_packages")
    op.rename_table("skills", "skill_packages")

    # Recreate the old handler_key Skill/agent_skills shape (0001 + 0004's
    # handler_key column + 0008's tenant_id/version/status), empty.
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("handler_key", sa.String(length=100), nullable=False, server_default="word_count"),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("version", sa.String(length=30), nullable=False, server_default="1.0.0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="Active"),
    )
    op.create_table(
        "agent_skills",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True),
    )
