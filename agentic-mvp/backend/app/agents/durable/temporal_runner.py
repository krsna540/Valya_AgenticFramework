"""Temporal-backed `DurableRunner`.

Starts an `AgentRunWorkflow` and relays its outcome. The run executes on a
worker process (`app/agents/durable/worker.py`), not in the web process, so
it survives a backend restart, retries under a real policy, and can pause
for days awaiting a human.

**On streaming.** Temporal has no event stream from an in-flight activity —
heartbeat details are visible to the service, not pushed to a client. So
`stream()` here yields *coarse* progress derived from polling the workflow's
`status` query, then the final result. Token-level streaming is a property of
the in-process path only, and this is stated plainly rather than papered over
with a fake token stream: an interactive chat turn should use `LocalRunner`
(the default), and Temporal should be selected for work whose value is
durability rather than immediacy.

**Workflow ids are the run id.** That makes `start()` idempotent for free —
starting the same run twice is a duplicate-workflow error rather than two
concurrent runs spending two token budgets.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import timedelta

from app.agents.durable.base import DurableRunner, RunHandle
from app.agents.durable.client import get_client
from app.agents.lifecycle import EventSink, EventType, LifecycleEvent
from app.agents.runtime import AgentRunRequest, AgentRunResult
from app.agents.state import RunPhase, RunStatus
from app.core.config import settings

logger = logging.getLogger("agentic_mvp.agents.durable.temporal")

#: How often `stream()` polls the workflow's status query. A compromise: fast
#: enough that a phase change is visible promptly, slow enough not to hammer
#: the frontend service for a run that thinks for minutes.
_POLL_INTERVAL_S = 1.0


def workflow_id_for(run_id: str) -> str:
    return f"agent-run-{run_id}"


class TemporalRunner(DurableRunner):
    """Executes runs as Temporal workflows."""

    name = "temporal"

    def __init__(self, task_queue: str | None = None) -> None:
        self._task_queue = task_queue or settings.temporal_task_queue

    async def _start_handle(self, request: AgentRunRequest):
        from app.agents.durable.workflow import AgentRunWorkflow

        client = await get_client()
        return await client.start_workflow(
            AgentRunWorkflow.run,
            request,
            id=workflow_id_for(request.run_id),
            task_queue=self._task_queue,
            execution_timeout=timedelta(seconds=settings.temporal_workflow_timeout_s),
        )

    async def start(self, request: AgentRunRequest) -> RunHandle:
        handle = await self._start_handle(request)
        return RunHandle(
            run_id=request.run_id,
            workflow_id=handle.id,
            run_reference=handle.result_run_id,
            durable=True,
        )

    async def run(
        self, request: AgentRunRequest, *, sink: EventSink | None = None
    ) -> AgentRunResult:
        handle = await self._start_handle(request)
        return await handle.result()

    async def stream(
        self, request: AgentRunRequest, *, extra_sink: EventSink | None = None
    ) -> AsyncIterator[LifecycleEvent]:
        """Yield coarse phase progress, then the final result.

        See the module docstring: this is genuinely coarser than the local
        path, by nature of the transport rather than by omission.
        """
        handle = await self._start_handle(request)

        def _event(event_type: EventType, phase: str, **data) -> LifecycleEvent:
            return LifecycleEvent(
                type=event_type,
                run_id=request.run_id,
                agent_id=request.agent_id,
                agent_name=request.agent_name,
                trace_id=request.trace_id,
                phase=phase,
                data={"workflow_id": handle.id, **data},
            )

        start_event = _event(EventType.RUN_START, RunPhase.INITIALIZING.value, durable=True)
        if extra_sink is not None:
            await extra_sink.emit(start_event)
        yield start_event

        result_task = asyncio.ensure_future(handle.result())
        last_phase: str | None = None

        try:
            while not result_task.done():
                await asyncio.sleep(_POLL_INTERVAL_S)
                try:
                    status = await handle.query("status")
                except Exception as exc:  # noqa: BLE001 — a failed poll is not a failed run
                    logger.debug("Status query failed for %s: %s", handle.id, exc)
                    continue
                phase = str(status.get("phase") or "")
                if phase and phase != last_phase:
                    last_phase = phase
                    event = _event(EventType.PHASE_ENTER, phase, status=status.get("status"))
                    if extra_sink is not None:
                        await extra_sink.emit(event)
                    yield event
                if status.get("awaiting_human"):
                    yield _event(EventType.HUMAN_REVIEW_REQUIRED, phase)

            result = await result_task
        except asyncio.CancelledError:
            # The consumer went away. The workflow deliberately keeps
            # running — that is the entire point of durable execution, and
            # cancelling it here would make Temporal behave like the local
            # path it exists to differ from.
            result_task.cancel()
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Temporal run %s failed", request.run_id)
            yield _event(
                EventType.RUN_END,
                RunPhase.DONE.value,
                status=RunStatus.FAILED.value,
                error={"error_type": type(exc).__name__, "message": str(exc)},
                final_answer="This request could not be completed by the durable runtime.",
                final=True,
            )
            return

        self._last_result = result
        end_event = _event(
            EventType.RUN_END,
            result.phase.value,
            status=result.status.value,
            final_answer=result.final_answer,
            critic_verdict=result.critic_verdict,
            critic_score=result.critic_score,
            needs_human_review=result.needs_human_review,
            token_usage=result.token_usage,
            duration_ms=result.duration_ms,
            final=True,
        )
        if extra_sink is not None:
            await extra_sink.emit(end_event)
        yield end_event

    async def cancel(self, handle: RunHandle) -> bool:
        """Cooperative cancel via signal, so the workflow still writes its
        terminal row — `handle.cancel()` would abort it mid-flight."""
        if not handle.workflow_id:
            return False
        try:
            client = await get_client()
            wf = client.get_workflow_handle(handle.workflow_id)
            await wf.signal("cancel_run")
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Failed to cancel workflow %s", handle.workflow_id)
            return False

    async def submit_human_decision(
        self, run_id: str, *, approved: bool, note: str = ""
    ) -> bool:
        """Deliver a reviewer's verdict to a paused run."""
        try:
            client = await get_client()
            wf = client.get_workflow_handle(workflow_id_for(run_id))
            await wf.signal("human_decision", {"approved": approved, "note": note})
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Failed to signal human decision for run %s", run_id)
            return False

    @property
    def last_result(self) -> AgentRunResult | None:
        return getattr(self, "_last_result", None)
