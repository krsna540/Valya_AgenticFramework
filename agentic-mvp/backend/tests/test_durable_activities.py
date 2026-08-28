"""`execute_agent_graph` must give a durable run the same event-visibility a
chat-originated run already gets — the whole point of routing everything
through Temporal is that nothing observing a run has to know which backend
ran it. `AgentRuntime.run` itself is monkeypatched out: this test is about
what sink the activity builds, not about running the graph (that's
`test_agent_runtime.py`'s job), and `_HeartbeatSink` requires a live Temporal
worker context to actually heartbeat, which a unit test has no business
standing up.
"""
from __future__ import annotations

import uuid

import pytest

from app.agents.config import AgentRuntimeConfig
from app.agents.durable.activities import execute_agent_graph
from app.agents.event_persistence import PostgresEventSink
from app.agents.lifecycle import CompositeEventSink
from app.agents.runtime import AgentRunRequest, AgentRunResult
from app.agents.state import RunPhase, RunStatus
from app.services.agent_run_store import PersistingEventSink


def make_request() -> AgentRunRequest:
    return AgentRunRequest(
        objective="do the thing",
        agent_id=str(uuid.uuid4()),
        agent_name="Test Agent",
        run_id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        config=AgentRuntimeConfig(),
    )


@pytest.mark.asyncio
async def test_execute_agent_graph_wires_persistence_and_episodic_sinks(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_run(self, request, *, sink=None):
        captured["sink"] = sink
        return AgentRunResult(
            run_id=request.run_id,
            status=RunStatus.SUCCEEDED,
            phase=RunPhase.DONE,
            final_answer="done",
        )

    monkeypatch.setattr("app.agents.runtime.AgentRuntime.run", fake_run)

    result = await execute_agent_graph(make_request())

    assert result.status == RunStatus.SUCCEEDED
    sink = captured["sink"]
    assert isinstance(sink, CompositeEventSink)
    child_types = [type(s) for s in sink._sinks]
    assert PersistingEventSink in child_types
    assert PostgresEventSink in child_types


@pytest.mark.asyncio
async def test_execute_agent_graph_tolerates_missing_tenant_and_project(monkeypatch):
    """tenant_id/project_id are optional on AgentRunRequest — the sink build
    must not blow up when they're absent (e.g. a platform-shared agent)."""
    captured: dict[str, object] = {}

    async def fake_run(self, request, *, sink=None):
        captured["sink"] = sink
        return AgentRunResult(
            run_id=request.run_id,
            status=RunStatus.SUCCEEDED,
            phase=RunPhase.DONE,
            final_answer="done",
        )

    monkeypatch.setattr("app.agents.runtime.AgentRuntime.run", fake_run)

    request = make_request().model_copy(update={"tenant_id": None, "project_id": None})
    await execute_agent_graph(request)

    sink = captured["sink"]
    episodic = next(s for s in sink._sinks if isinstance(s, PostgresEventSink))
    assert episodic._tenant_id is None
    assert episodic._project_id is None
