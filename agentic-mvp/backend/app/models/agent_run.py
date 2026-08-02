"""Agent run records — the queryable audit trail for the Observatory.

Deliberately separate from LangGraph's checkpoint tables, which serve a
different purpose and belong to a different owner:

  * **Checkpoints** (LangGraph, `app/agents/checkpointer.py`) are opaque
    serialized state, written after every super-step, keyed by thread id.
    They exist to *resume* a run. They are not queryable — you cannot ask
    them "what was the p95 planner latency for tenant X last week".
  * **These tables** are a normalized, indexed projection of what happened,
    written by `app/services/agent_run_store.py`. They exist to *report* on
    runs, and they outlive the checkpoints (which a retention job can prune
    without losing the audit trail).

Two tables rather than one JSON blob because the questions asked of them are
per-step: "which node fails most", "how much does critique cost us", "how
often does the revision loop actually change the verdict". Those are
aggregate queries over steps, and a JSON column makes each one a table scan.

Tenant scoping follows the existing convention (`TenantScopedMixin`'s
nullable tenant_id means platform-shared), except that a run is never
platform-shared — every run belongs to whoever ran it. It is nullable only
because a super_admin has no tenant of their own; see
`app/api/deps.py::authorize`.
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AgentRun(Base):
    """One execution of the Planner → Executor → Critic graph."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # --- ownership / correlation -------------------------------------------
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True
    )
    #: Correlates this run with hook-engine traces (HookContext.trace_id) and
    #: with MLflow spans. Not unique — a retried run reuses its trace.
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: LangGraph checkpoint thread id. The handle for resuming this run;
    #: nullable because an in-memory-checkpointed run has nothing to resume.
    thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Temporal workflow id when the run went through the durable envelope,
    #: NULL when it ran in-process. The one field that tells you which
    #: execution path a given run actually took.
    workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- inputs -------------------------------------------------------------
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    #: The AgentRuntimeConfig actually in force, snapshotted. Without this a
    #: run's behaviour is unexplainable after someone edits the agent's
    #: config — "why did this only revise once?" has no answer.
    runtime_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # --- outcome ------------------------------------------------------------
    #: RunStatus value. String rather than a DB enum so adding a status is a
    #: code change, not a migration with a lock on a hot table.
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running", index=True)
    phase: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    final_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    needs_human_review: Mapped[bool] = mapped_column(default=False, nullable=False)

    # --- loop accounting ----------------------------------------------------
    revisions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    replans: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    plan_step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    critic_verdict: Mapped[str | None] = mapped_column(String(20), nullable=True)
    critic_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- cost / latency -----------------------------------------------------
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: True when token counts are estimated rather than reported — streaming
    #: responses usually omit usage. Flagged so a cost report can state its
    #: own accuracy instead of quietly mixing exact and approximate figures.
    tokens_approximate: Mapped[bool] = mapped_column(default=False, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    steps = relationship(
        "AgentRunStep",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentRunStep.seq",
    )

    __table_args__ = (
        # The Observatory's primary view: one tenant's recent runs.
        Index("ix_agent_runs_tenant_started", "tenant_id", "started_at"),
        # "Show me what needs attention" — failures and escalations.
        Index("ix_agent_runs_status_started", "status", "started_at"),
    )


class AgentRunStep(Base):
    """One node execution within a run — planner, executor, critic, or one of
    the control nodes. The grain is deliberately the *node*, not the plan
    step: a plan step that runs three times across three revisions produces
    three rows, which is what makes "did revising actually help" answerable.
    """

    __tablename__ = "agent_run_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )

    #: Monotonic ordering within the run. Explicit rather than derived from
    #: created_at, which is not unique at millisecond resolution.
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: planner | executor | critic | system
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    phase: Mapped[str] = mapped_column(String(30), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: StepStatus value.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Structured detail — the plan, the critique, the step result. The one
    #: place a JSON column is right here: its shape is genuinely
    #: role-dependent and nothing aggregates over its interior.
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run = relationship("AgentRun", back_populates="steps")

    __table_args__ = (Index("ix_agent_run_steps_run_seq", "run_id", "seq"),)
