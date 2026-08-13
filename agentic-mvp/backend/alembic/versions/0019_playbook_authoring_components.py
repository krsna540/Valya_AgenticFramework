"""playbook authoring components

Migration 0017 created `playbooks` with the four PLATFORM_ARCHITECTURE.md
§11.5 procedural-memory fields (when_to_use / canonical_steps /
required_criteria / known_assumptions) — enough for the Planner to select
and score a playbook, but not enough for a human to *author* one. This
migration adds the seven authoring components an operations author
actually writes:

    objective          §1 "High-Level Goal"      — Text
    target_persona     §1 "Target Persona"       — Text
    out_of_scope       §1 "Out of Scope"         — JSON [{topic, handoff_to}]
    inputs             §2 "Inputs & Tools"       — JSON [{name, kind, description, ref_id}]
    guardrails         §4 "Guardrails & Banned Moves" — JSON [{rule, severity}]
    approval_gates     §5 "Approval Gates"       — JSON [{name, condition, approver, threshold}]
    few_shot_examples  §6 "Few-Shot Examples"    — JSON [{title, exchanges}],
                                                   exchange = {role, content, internal_note}

Additive only. Every new column is nullable-or-defaulted, so the rows
created by 0017 and anything the Planner already reads keep working
untouched — `canonical_steps` in particular keeps its existing
{title, detail} shape and merely gains two OPTIONAL keys (`condition`,
`else_detail`) for the IF/ELSE branching the authoring spec calls for.
That is a pure JSON-shape widening with no DDL and no backfill: an
existing step with neither key is still a valid unconditional step (see
app/schemas/playbook.py::PlaybookStep).

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-13

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSON list/dict columns are given a server_default so the ALTER on a
# non-empty table doesn't need a separate UPDATE pass, matching how 0017
# declared canonical_steps/required_criteria and how 0018 declared
# skills.blob_digests.
_JSON_LIST_COLUMNS = (
    "out_of_scope",
    "inputs",
    "guardrails",
    "approval_gates",
    "few_shot_examples",
)


def upgrade() -> None:
    for column in ("objective", "target_persona"):
        op.add_column("playbooks", sa.Column(column, sa.Text(), nullable=False, server_default=""))
    for column in _JSON_LIST_COLUMNS:
        op.add_column(
            "playbooks",
            sa.Column(column, sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        )


def downgrade() -> None:
    for column in reversed(_JSON_LIST_COLUMNS):
        op.drop_column("playbooks", column)
    op.drop_column("playbooks", "target_persona")
    op.drop_column("playbooks", "objective")
