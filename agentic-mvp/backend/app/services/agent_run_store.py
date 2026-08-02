"""Persistence for agent runs — the write side of the Observatory.

Two entry points, and the split matters:

  * `PersistingEventSink` writes *while* the run is in flight. It is an
    `EventSink`, so it composes with the SSE queue sink via
    `CompositeEventSink` and needs no cooperation from the agents. This is
    what makes a run that crashes mid-flight still show up as `running` with
    the steps it completed, rather than vanishing entirely.
  * `finalize_run` writes the terminal projection once the graph returns.

**Why a synchronous Session inside an async sink.** The rest of this backend
is sync SQLAlchemy (`app/core/database.py`), and introducing an async engine
just for this would mean two connection pools against the same database and
two transaction models to reason about. Instead each write runs in a worker
thread via `asyncio.to_thread`, keeping the event loop unblocked without
forking the persistence stack. Each write opens and closes its own short
session — holding one open across a multi-minute run would pin a pooled
connection for the duration.

**Every write is best-effort.** A telemetry failure must never fail the run
it describes, so the store logs and swallows. The same rule the hook engine
and the usage ledger already follow in this codebase.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.agents.lifecycle import EventSink, EventType, LifecycleEvent
from app.agents.state import AgentState, RunPhase, RunStatus, get_critique, get_plan
from app.core.database import SessionLocal
from app.models.agent_run import AgentRun, AgentRunStep

logger = logging.getLogger("agentic_mvp.agents.store")

#: Events that become an `AgentRunStep` row. Everything else (tokens, phase
#: markers) is streaming detail — persisting a row per token would turn a
#: 500-token answer into 500 inserts for no analytical gain.
_STEP_EVENTS = frozenset(
    {
        EventType.NODE_END,
        EventType.NODE_ERROR,
    }
)


def _as_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _session() -> Session:
    return SessionLocal()


# --- create -----------------------------------------------------------------


def create_run(
    *,
    run_id: uuid.UUID,
    agent_id: uuid.UUID,
    objective: str,
    trace_id: str,
    tenant_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    language: str = "en",
    model_name: str | None = None,
    llm_provider: str | None = None,
    runtime_config: dict[str, Any] | None = None,
    thread_id: str | None = None,
    workflow_id: str | None = None,
) -> uuid.UUID | None:
    """Insert the run row. Returns the id, or None if the insert failed —
    callers treat None as "persistence is unavailable, keep going"."""
    try:
        with _session() as db:
            run = AgentRun(
                id=run_id,
                agent_id=agent_id,
                tenant_id=tenant_id,
                project_id=project_id,
                user_id=user_id,
                conversation_id=conversation_id,
                objective=objective[:20_000],
                trace_id=trace_id[:64],
                language=language[:16],
                model_name=model_name,
                llm_provider=llm_provider,
                runtime_config=runtime_config or {},
                thread_id=thread_id,
                workflow_id=workflow_id,
                status=RunStatus.RUNNING.value,
                phase=RunPhase.PENDING.value,
            )
            db.add(run)
            db.commit()
            return run.id
    except Exception:  # noqa: BLE001 — telemetry must never break a run
        logger.exception("Failed to create AgentRun row for %s", run_id)
        return None


# --- in-flight step writes --------------------------------------------------


class PersistingEventSink(EventSink):
    """Writes an `AgentRunStep` per completed node, as the run progresses.

    `seq` is assigned here from an in-memory counter rather than read back
    from the database: the sink is the only writer for a given run, so a
    counter is both correct and one fewer round-trip than a `MAX(seq)+1`
    query per step.
    """

    def __init__(self, run_id: uuid.UUID) -> None:
        self._run_id = run_id
        self._seq = 0

    async def _write(self, event: LifecycleEvent) -> None:
        if event.type not in _STEP_EVENTS:
            return
        self._seq += 1
        await asyncio.to_thread(self._insert_step, event, self._seq)

    def _insert_step(self, event: LifecycleEvent, seq: int) -> None:
        failed = event.type == EventType.NODE_ERROR
        try:
            with _session() as db:
                db.add(
                    AgentRunStep(
                        run_id=self._run_id,
                        seq=seq,
                        role=(event.role or "system")[:30],
                        phase=(event.phase or "")[:30],
                        revision=event.revision,
                        status="failed" if failed else "succeeded",
                        summary=(event.data.get("summary") or event.type.value)[:2000],
                        payload=event.data,
                        error=event.data if failed else None,
                        attempts=int(event.data.get("attempt", 1) or 1),
                        duration_ms=int(event.data.get("duration_ms", 0) or 0),
                    )
                )
                db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to persist AgentRunStep for run %s", self._run_id)


# --- terminal projection ----------------------------------------------------


async def finalize_run(
    run_id: uuid.UUID,
    state: AgentState,
    *,
    duration_ms: int | None = None,
    citations: list[dict[str, Any]] | None = None,
) -> None:
    """Project the finished graph state onto the run row.

    Runs in a thread for the same reason the step writes do. Called from the
    runtime's `finally`, so it also executes for a failed run — a run row
    stuck at `running` forever is worse than one marked failed.
    """
    await asyncio.to_thread(_finalize_run_sync, run_id, dict(state), duration_ms, citations or [])


def _finalize_run_sync(
    run_id: uuid.UUID,
    state: dict[str, Any],
    duration_ms: int | None,
    citations: list[dict[str, Any]],
) -> None:
    try:
        with _session() as db:
            run = db.get(AgentRun, run_id)
            if run is None:
                logger.warning("finalize_run: no AgentRun row for %s", run_id)
                return

            typed_state: AgentState = state  # type: ignore[assignment]
            plan = get_plan(typed_state)
            critique = get_critique(typed_state)
            usage = state.get("token_usage") or {}

            run.status = str(state.get("status") or RunStatus.FAILED.value)
            run.phase = str(state.get("phase") or RunPhase.DONE.value)
            run.final_answer = state.get("final_answer") or state.get("draft_answer") or None
            run.citations = citations
            run.error = state.get("error")
            run.needs_human_review = bool(state.get("needs_human_review"))
            run.revisions = int(state.get("revision") or 0)
            run.replans = int(state.get("replan_count") or 0)
            run.plan_step_count = len(plan.steps) if plan else 0
            run.critic_verdict = critique.verdict.value if critique else None
            run.critic_score = critique.score if critique else None
            run.input_tokens = int(usage.get("input", 0) or 0)
            run.output_tokens = int(usage.get("output", 0) or 0)
            run.llm_calls = int(usage.get("calls", 0) or 0)
            run.tokens_approximate = bool(usage.get("approximate", False))
            run.duration_ms = duration_ms
            run.finished_at = _now()
            db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to finalize AgentRun %s", run_id)


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


# --- read side (used by the Observatory routes) -----------------------------


def list_runs(
    db: Session,
    *,
    tenant_id: uuid.UUID | None,
    agent_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AgentRun]:
    """Recent runs, newest first. Takes a caller-supplied Session so it joins
    the request's transaction rather than opening its own — the read path is
    already inside a FastAPI dependency-managed session."""
    query = db.query(AgentRun)
    if tenant_id is not None:
        query = query.filter(AgentRun.tenant_id == tenant_id)
    if agent_id is not None:
        query = query.filter(AgentRun.agent_id == agent_id)
    if project_id is not None:
        query = query.filter(AgentRun.project_id == project_id)
    if status:
        query = query.filter(AgentRun.status == status)
    return (
        query.order_by(AgentRun.started_at.desc())
        .limit(min(max(limit, 1), 200))
        .offset(max(offset, 0))
        .all()
    )


def get_run(db: Session, run_id: uuid.UUID) -> AgentRun | None:
    return db.get(AgentRun, run_id)
