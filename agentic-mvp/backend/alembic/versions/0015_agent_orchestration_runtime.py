"""agent orchestration runtime — run/step audit trail + per-agent tuning

Backs the Planner -> Executor -> Critic runtime in app/agents/:

  * agents.runtime_config — per-agent budgets (revisions, replans, timeouts,
    whether the critic runs, whether tools may actually be invoked).
    Server-default '{}' so every existing row gets "use the defaults" without
    a data backfill, and so an insert from older application code that
    doesn't know about the column still succeeds.

  * agent_runs / agent_run_steps — the queryable audit trail. Deliberately
    NOT LangGraph's checkpoint tables, which are opaque resume state owned by
    the library and created by its own `setup()` (see
    app/agents/checkpointer.py). Keeping a third party's schema out of
    Alembic means upgrading that package isn't a hand-written migration.

Indexes are the three access patterns the Observatory actually has: one
tenant's recent runs, runs needing attention (failed/escalated), and one
run's steps in order. No index on trace_id beyond the plain one — correlation
lookups are rare and exact.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-31

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "runtime_config",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # --- ownership / correlation ---
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("thread_id", sa.String(length=128), nullable=True),
        sa.Column("workflow_id", sa.String(length=255), nullable=True),
        # --- inputs ---
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False, server_default="en"),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("llm_provider", sa.String(length=50), nullable=True),
        sa.Column(
            "runtime_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
        # --- outcome ---
        sa.Column("status", sa.String(length=30), nullable=False, server_default="running"),
        sa.Column("phase", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("final_answer", sa.Text(), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column(
            "needs_human_review", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        # --- loop accounting ---
        sa.Column("revisions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("replans", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("plan_step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("critic_verdict", sa.String(length=20), nullable=True),
        sa.Column("critic_score", sa.Float(), nullable=True),
        # --- cost / latency ---
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "tokens_approximate", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_runs_tenant_id", "agent_runs", ["tenant_id"])
    op.create_index("ix_agent_runs_agent_id", "agent_runs", ["agent_id"])
    op.create_index("ix_agent_runs_trace_id", "agent_runs", ["trace_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_index("ix_agent_runs_tenant_started", "agent_runs", ["tenant_id", "started_at"])
    op.create_index("ix_agent_runs_status_started", "agent_runs", ["status", "started_at"])

    op.create_table(
        "agent_run_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("phase", sa.String(length=30), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="succeeded"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_run_steps_run_seq", "agent_run_steps", ["run_id", "seq"])


def downgrade() -> None:
    op.drop_index("ix_agent_run_steps_run_seq", table_name="agent_run_steps")
    op.drop_table("agent_run_steps")

    for index_name in (
        "ix_agent_runs_status_started",
        "ix_agent_runs_tenant_started",
        "ix_agent_runs_status",
        "ix_agent_runs_trace_id",
        "ix_agent_runs_agent_id",
        "ix_agent_runs_tenant_id",
    ):
        op.drop_index(index_name, table_name="agent_runs")
    op.drop_table("agent_runs")

    op.drop_column("agents", "runtime_config")
