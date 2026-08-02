"""Temporal activities — every side effect the workflow needs.

The split between this module and `workflow.py` is the fundamental Temporal
rule: workflow code is replayed from history and must be deterministic, so
anything that touches a network, a database, a clock or a random number
generator lives here. The workflow decides *what* happens and in what order;
activities are the only things that actually do it.

Three activities, matching the three side effects a run has:

    persist_run_start   — insert the AgentRun row
    execute_agent_graph — run the LangGraph graph (the expensive one)
    persist_run_finish  — project the terminal state onto the row

**Heartbeating.** `execute_agent_graph` can run for minutes. Without a
heartbeat Temporal cannot distinguish "still thinking" from "worker died",
so the activity heartbeats on every lifecycle event via a sink. That is also
what makes the activity cancellable mid-run: `activity.heartbeat()` is where
a cancellation request is delivered.

**Idempotency.** Activities can be retried after a partial success — the
worker may die between the database write and Temporal recording the result.
`persist_run_start` therefore takes the caller-generated `run_id` and treats
an existing row as success rather than inserting a duplicate.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from temporalio import activity

from app.agents.lifecycle import EventSink, LifecycleEvent
from app.agents.runtime import AgentRunRequest, AgentRunResult, AgentRuntime

logger = logging.getLogger("agentic_mvp.agents.durable.activities")


# --- activity payloads ------------------------------------------------------
#
# Typed rather than dicts so the workflow/activity contract is checked at the
# boundary. Serialized by `pydantic_data_converter` (see client.py), which is
# configured identically on the client and the worker — a mismatch there is
# the classic "works locally, fails in the worker" Temporal bug.


class RunStartPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    agent_id: str
    objective: str
    trace_id: str
    tenant_id: str | None = None
    project_id: str | None = None
    user_id: str | None = None
    conversation_id: str | None = None
    language: str = "en"
    model_name: str | None = None
    llm_provider: str | None = None
    runtime_config: dict[str, Any] = Field(default_factory=dict)
    thread_id: str | None = None
    workflow_id: str | None = None


class RunFinishPayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    state: dict[str, Any]
    duration_ms: int = 0
    citations: list[dict[str, Any]] = Field(default_factory=list)


class _HeartbeatSink(EventSink):
    """Relays progress to Temporal as activity heartbeats.

    The event is passed as heartbeat *details*, which Temporal retains — so a
    retried activity can inspect how far the previous attempt got, and the
    Temporal UI shows live progress instead of an opaque long-running call.
    """

    async def _write(self, event: LifecycleEvent) -> None:
        activity.heartbeat(
            {
                "type": event.type.value,
                "phase": event.phase,
                "revision": event.revision,
            }
        )


@activity.defn(name="persist_run_start")
async def persist_run_start(payload: RunStartPayload) -> str | None:
    """Insert the run row. Idempotent — a retry after a partial success
    returns the existing id instead of inserting again."""
    from app.services import agent_run_store

    run_id = uuid.UUID(payload.run_id)
    agent_id = uuid.UUID(payload.agent_id)

    created = agent_run_store.create_run(
        run_id=run_id,
        agent_id=agent_id,
        objective=payload.objective,
        trace_id=payload.trace_id,
        tenant_id=_maybe_uuid(payload.tenant_id),
        project_id=_maybe_uuid(payload.project_id),
        user_id=_maybe_uuid(payload.user_id),
        conversation_id=_maybe_uuid(payload.conversation_id),
        language=payload.language,
        model_name=payload.model_name,
        llm_provider=payload.llm_provider,
        runtime_config=payload.runtime_config,
        thread_id=payload.thread_id,
        workflow_id=payload.workflow_id,
    )
    return str(created) if created else None


@activity.defn(name="execute_agent_graph")
async def execute_agent_graph(request: AgentRunRequest) -> AgentRunResult:
    """Run the LangGraph graph to completion.

    The whole graph is one activity rather than one activity per node. Two
    reasons: the graph's routing (the revision loop, the risk gate) would
    otherwise have to be reimplemented in the workflow and kept in sync with
    `graph.py`, and LangGraph's own checkpointer already provides
    within-run resumability — so per-node activities would buy a second
    durability mechanism layered on the first, for the cost of duplicating
    the control flow. Temporal's job here is the envelope: retry the run,
    time-bound it, keep it visible, and pause it for a human.
    """
    activity.logger.info("Executing agent graph for run %s", request.run_id)
    runtime = AgentRuntime()
    result = await runtime.run(request, sink=_HeartbeatSink())
    activity.logger.info(
        "Run %s finished: %s (%d revisions)", request.run_id, result.status.value, result.revisions
    )
    return result


@activity.defn(name="persist_run_finish")
async def persist_run_finish(payload: RunFinishPayload) -> None:
    """Project the terminal state onto the run row. Idempotent by
    construction — it overwrites the same fields with the same values."""
    from app.services import agent_run_store

    await agent_run_store.finalize_run(
        uuid.UUID(payload.run_id),
        payload.state,  # type: ignore[arg-type]
        duration_ms=payload.duration_ms,
        citations=payload.citations,
    )


def _maybe_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None


#: Registered with the worker. Kept as a module-level list so the worker
#: entrypoint can't drift out of sync with what is defined here.
ALL_ACTIVITIES = [persist_run_start, execute_agent_graph, persist_run_finish]
