"""skills.blob_digests — content-addressed MinIO mirror

Adds the {relative path: "sha256:<hex>"} column skills.py's upload route
now populates alongside dir_path. See app/core/minio_client.py's module
docstring and app/models/skill.py::Skill.blob_digests.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-08

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column("blob_digests", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )


def downgrade() -> None:
    op.drop_column("skills", "blob_digests")
