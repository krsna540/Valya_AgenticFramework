"""The event spine — PLATFORM_ARCHITECTURE.md §10 / §11.3 (episodic memory).

An append-only projection of what the existing Planner->Executor->Critic
runtime already emits via app/agents/lifecycle.py's EventSink/LifecycleEvent
mechanism. This table does not replace agent_runs/agent_run_steps
(app/models/agent_run.py) — those remain the normalized, queryable
Observatory audit trail this codebase already had. `events` is the
narrower, Frozen-Spec-shaped companion: one append-only row per
LifecycleEvent, typed, with an evidence_ref, so "what happened, in what
order, and why" survives independently of whichever reporting tables get
added or reshaped later (§10.1's "state tables are projections; events are
the truth").

Written by app.agents.event_persistence.PostgresEventSink (additive — it is
composed alongside the existing sinks, nothing about the current streaming
or Observatory-write path changes). Nothing on the interactive chat hot path
reads this table; it exists for audit, replay, and (eventually) the mining
job in Frozen Spec §9 — see PLATFORM_ARCHITECTURE.md §11.3's "deliberately
not the hot path".
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Mirrors app.agents.lifecycle.EventType plus the Frozen Spec §5.2 taxonomy
# names not yet emitted by the runtime (OBJECTIVE_COMMITTED, OBJECTIVE_PIVOT,
# MEMORY_WRITTEN) — kept as a superset comment rather than a DB CHECK
# constraint so a new event type is a one-line addition, not a migration.
# See app/agents/event_persistence.py for the LifecycleEvent -> row mapping.


class Event(Base):
    __tablename__ = "events"

    # Composite PK (run_id, seq) per PLATFORM_ARCHITECTURE.md §10.4 — seq is
    # monotonic PER RUN (assigned by the writer under a per-run advisory
    # lock, see event_persistence.py), which is what lets an SSE client
    # reconnect and ask "everything after seq N for this run" cheaply.
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor: Mapped[str] = mapped_column(String(50), nullable=False)  # manager|planner|scheduler|executor|critic|system
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)

    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # Nullable, but §5.3's rule ("every decision event that changes scope
    # must carry an evidence_ref") is enforced at the writer, not here —
    # see event_persistence.py::_requires_evidence.
    evidence_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_events_tenant_ts", "tenant_id", "ts"),
        Index("ix_events_type", "type"),
    )
