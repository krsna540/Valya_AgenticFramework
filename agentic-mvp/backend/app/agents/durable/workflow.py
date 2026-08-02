"""`AgentRunWorkflow` — the durable envelope around one agent run.

What the workflow adds over calling the graph directly:

  * **Survivability.** The run's position is in Temporal's history, so a
    worker that dies mid-run is replaced and the run continues. LangGraph's
    checkpointer resumes *within* a run; Temporal is what guarantees somebody
    resumes it at all.
  * **Retry with a real policy.** Activity-level retries with backoff, and a
    non-retryable list derived from the error taxonomy (`errors.py`), so a
    misconfiguration fails fast instead of retrying for an hour.
  * **Human-in-the-loop.** When the critic escalates, the workflow *waits* —
    for days if need be — on a signal. This is the capability that most
    justifies the envelope: no request-scoped process can hold that pause.
  * **Visibility.** A query handler exposes live status without touching the
    database.

**Determinism.** Everything in this module is replayed from history on every
worker restart, so it contains no I/O, no `datetime.now()`, no `random`, and
no direct imports of application modules that might do work at import time.
The `workflow.unsafe.imports_passed_through()` block is how the shared
request/result models are imported without the sandbox re-importing (and
re-executing) the application package on every replay.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.agents.durable.activities import (
        RunFinishPayload,
        RunStartPayload,
        execute_agent_graph,
        persist_run_finish,
        persist_run_start,
    )
    from app.agents.errors import NON_RETRYABLE_ERROR_TYPES
    from app.agents.runtime import AgentRunRequest, AgentRunResult
    from app.agents.state import RunStatus


#: How long the workflow waits for a human decision after an escalation
#: before giving up and returning the degraded answer. Long, because the
#: point of the pause is to accommodate a human's timescale, not a request's.
HUMAN_REVIEW_TIMEOUT = timedelta(days=3)

#: Short, idempotent database writes. Aggressive retries are safe and cheap.
_PERSIST_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=5,
)

#: The expensive one. Few attempts, because every retry re-runs the whole
#: graph and re-spends its token budget — and the classes listed as
#: non-retryable (bad config, exhausted budget, policy halt) cannot be fixed
#: by trying again.
_EXECUTE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1),
    maximum_attempts=3,
    non_retryable_error_types=list(NON_RETRYABLE_ERROR_TYPES),
)


@workflow.defn(name="AgentRunWorkflow")
class AgentRunWorkflow:
    """Durable orchestration of one Planner → Executor → Critic run."""

    def __init__(self) -> None:
        # Replayed deterministically on every worker restart; safe to
        # initialise here because none of it does I/O.
        self._status: str = RunStatus.RUNNING.value
        self._phase: str = "pending"
        self._human_decision: dict | None = None
        self._cancelled: bool = False

    # --- signals ------------------------------------------------------------

    @workflow.signal(name="human_decision")
    def submit_human_decision(self, decision: dict) -> None:
        """Deliver a reviewer's verdict for an escalated run.

        Expected shape: `{"approved": bool, "note": str}`. Stored rather than
        acted on directly — the main coroutine is what advances the run, so a
        signal handler that tried to would be racing it.
        """
        self._human_decision = decision

    @workflow.signal(name="cancel_run")
    def cancel_run(self) -> None:
        """Cooperative cancellation. Checked at the next await point rather
        than interrupting an activity mid-flight, so a partially-completed
        run still gets its terminal row written."""
        self._cancelled = True

    # --- queries ------------------------------------------------------------

    @workflow.query(name="status")
    def query_status(self) -> dict:
        """Live status without a database read. Must stay side-effect free —
        Temporal may run a query during replay."""
        return {
            "status": self._status,
            "phase": self._phase,
            "awaiting_human": self._human_decision is None
            and self._status == RunStatus.AWAITING_HUMAN.value,
            "cancelled": self._cancelled,
        }

    # --- main ---------------------------------------------------------------

    @workflow.run
    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        workflow_id = workflow.info().workflow_id

        await workflow.execute_activity(
            persist_run_start,
            RunStartPayload(
                run_id=request.run_id,
                agent_id=request.agent_id,
                objective=request.objective,
                trace_id=request.trace_id,
                tenant_id=request.tenant_id,
                project_id=request.project_id,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                language=request.language,
                model_name=request.model_name,
                runtime_config=request.config.model_dump(),
                thread_id=request.thread_id or request.run_id,
                workflow_id=workflow_id,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_PERSIST_RETRY,
        )

        self._phase = "planning"
        result: AgentRunResult = await workflow.execute_activity(
            execute_agent_graph,
            request,
            # Exceeds the runtime's own run_timeout_s so the graph gets to
            # enforce its budget and return a proper timeout result, rather
            # than Temporal killing the activity and discarding the state.
            start_to_close_timeout=timedelta(seconds=request.config.run_timeout_s + 120),
            # Must exceed the gap between lifecycle events. A node can think
            # for a while between emissions, so this is generous relative to
            # the heartbeat rate.
            heartbeat_timeout=timedelta(seconds=request.config.node_timeout_s + 60),
            retry_policy=_EXECUTE_RETRY,
        )

        self._status = result.status.value
        self._phase = result.phase.value

        # The pause that justifies the envelope: hold the run open for a
        # human, for as long as a human plausibly needs.
        if result.needs_human_review and not self._cancelled:
            result = await self._await_human_review(result)

        if self._cancelled:
            result = result.model_copy(update={"status": RunStatus.CANCELLED})
            self._status = RunStatus.CANCELLED.value

        await workflow.execute_activity(
            persist_run_finish,
            RunFinishPayload(
                run_id=request.run_id,
                state={**result.state, "status": result.status.value},
                duration_ms=result.duration_ms,
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_PERSIST_RETRY,
        )

        return result

    async def _await_human_review(self, result: AgentRunResult) -> AgentRunResult:
        """Block until a decision arrives or the review window closes.

        A timeout is not a failure: the answer already exists and stays
        DEGRADED. Failing the run because nobody looked at it would discard
        work that is merely unreviewed.
        """
        self._status = RunStatus.AWAITING_HUMAN.value
        workflow.logger.info("Run %s awaiting human review", result.run_id)

        # `wait_condition` signals expiry by raising, not by returning a
        # flag — so the timeout branch has to be an except clause.
        try:
            await workflow.wait_condition(
                lambda: self._human_decision is not None or self._cancelled,
                timeout=HUMAN_REVIEW_TIMEOUT,
            )
        except asyncio.TimeoutError:
            self._human_decision = None

        if self._human_decision is None:
            workflow.logger.info("Human review timed out for run %s", result.run_id)
            self._status = RunStatus.DEGRADED.value
            return result.model_copy(
                update={"status": RunStatus.DEGRADED, "needs_human_review": True}
            )

        approved = bool(self._human_decision.get("approved"))
        note = str(self._human_decision.get("note") or "")
        status = RunStatus.SUCCEEDED if approved else RunStatus.FAILED
        self._status = status.value
        return result.model_copy(
            update={
                "status": status,
                "needs_human_review": False,
                "final_answer": (
                    result.final_answer
                    if approved
                    else f"This response was rejected during human review. {note}".strip()
                ),
            }
        )
