"""adopt NexusClaw-inspired manifest conventions for plugins/tools

Gives Plugin real exports/requires semantics (mirroring NexusClaw's
plugins/<name>/manifest.yaml shape) and gives Tool the same manifest.json-
style metadata (input_schema/permissions/rate_limit_per_min/timeout_s/tags)
Skill's handler_key catalog already exposes via GET /skills/handlers. See
docs/SKILL_STANDARD.md for the full convention and why NexusClaw's
logic.py-as-executable-code / dynamically-imported hook modules were
deliberately NOT adopted (this app's handler_key-only, no-stored-code
invariant is unchanged).

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- plugins: exports/requires (NexusClaw manifest.yaml shape) ---------
    op.add_column("plugins", sa.Column("exports_skills", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("plugins", sa.Column("exports_hooks", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("plugins", sa.Column("exports_tools", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("plugins", sa.Column("exports_commands", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("plugins", sa.Column("requires_permissions", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("plugins", sa.Column("requires_env", sa.JSON(), nullable=False, server_default="[]"))

    # --- tools: manifest.json-style metadata --------------------------------
    op.add_column("tools", sa.Column("input_schema", sa.JSON(), nullable=True))
    op.add_column("tools", sa.Column("permissions", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("tools", sa.Column("rate_limit_per_min", sa.Integer(), nullable=False, server_default="60"))
    op.add_column("tools", sa.Column("timeout_s", sa.Integer(), nullable=False, server_default="15"))
    op.add_column("tools", sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("tools", "tags")
    op.drop_column("tools", "timeout_s")
    op.drop_column("tools", "rate_limit_per_min")
    op.drop_column("tools", "permissions")
    op.drop_column("tools", "input_schema")

    op.drop_column("plugins", "requires_env")
    op.drop_column("plugins", "requires_permissions")
    op.drop_column("plugins", "exports_commands")
    op.drop_column("plugins", "exports_tools")
    op.drop_column("plugins", "exports_hooks")
    op.drop_column("plugins", "exports_skills")
