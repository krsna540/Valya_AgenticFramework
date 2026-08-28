"""Contract tests for the chat SSE adapter (`app/services/agent_runner.py`).

This module replaced a working stub, and `api/routes/chat.py` was left
untouched — so the thing most worth testing is not the agents (covered in
test_agent_runtime.py) but the *contract* the route still depends on:

  * the same generator signature and the same event names,
  * `stream_start` first and `stream_end` last, with the keys the route reads
    (`content`, `citations`, `message_id`, `blocked`, `tokens`),
  * the hook pipeline firing at the same stages, with the same
    "UserPromptSubmit denies the turn / PreToolUse denies one action"
    asymmetry,
  * no runtime-only lifecycle event leaking to the browser unmapped.

Persistence is patched out: these assert on the wire contract, and a database
would only add a dependency without adding coverage. `test_agent_runtime.py`
owns graph behaviour; this file owns the boundary.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.agents.config import AgentRuntimeConfig
from app.services import agent_runner
from app.services.hooks import HookContext, HookHaltException, HookManager

# Event names the deployed frontend subscribes to. If a change here is ever
# needed, the frontend changes with it — that is the point of pinning them.
FRONTEND_EVENTS = {"stream_start", "token", "tool_call", "skill_call", "stream_end"}


@pytest.fixture(autouse=True)
def _no_database(monkeypatch):
    """Neutralise the run store. Returns None from create_run, which the
    adapter must tolerate — persistence being unavailable may never break a
    chat turn."""
    monkeypatch.setattr(agent_runner.agent_run_store, "create_run", lambda **kw: None)

    async def _noop_finalize(*args, **kwargs):
        return None

    monkeypatch.setattr(agent_runner.agent_run_store, "finalize_run", _noop_finalize)

    class _NoopSink(agent_runner.EventSink):
        def __init__(self, *a, **kw):
            pass

        async def _write(self, event):
            return None

    monkeypatch.setattr(agent_runner.agent_run_store, "PersistingEventSink", _NoopSink)


def make_agent(*, tools=(), skills=()):
    """A duck-typed stand-in for the Agent ORM row. The adapter only reads
    attributes, so this avoids a database without weakening the test."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="Test Agent",
        system_prompt="You are helpful.",
        model_name="gpt-test",
        tenant_id=uuid.uuid4(),
        tools=list(tools),
        skills=list(skills),
        plugins=[],
        hooks=[],
        runtime_config=AgentRuntimeConfig(
            critic_complexity_threshold=1, node_timeout_s=5, run_timeout_s=30
        ).model_dump(),
    )


def make_context():
    return HookContext(
        agent_name="Test Agent",
        conversation_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
    )


async def collect(agent, manager, context, *, message="Explain the revenue drivers.", files=()):
    return [
        event
        async for event in agent_runner.stream_agent_response(
            agent, message, list(files), manager, context
        )
    ]


# --- wire contract ----------------------------------------------------------


@pytest.mark.asyncio
async def test_the_stream_opens_and_closes_with_the_expected_events():
    events = await collect(make_agent(), HookManager(), make_context())

    assert events[0]["type"] == "stream_start"
    assert events[-1]["type"] == "stream_end"
    assert all("agent_id" in e for e in events)


@pytest.mark.asyncio
async def test_stream_end_carries_every_key_the_chat_route_reads():
    events = await collect(make_agent(), HookManager(), make_context())
    end = events[-1]

    # api/routes/chat.py reads exactly these when it persists the message and
    # writes the usage ledger entry.
    for key in ("content", "citations", "message_id", "blocked", "tokens"):
        assert key in end, f"chat.py reads {key!r} from stream_end"
    assert end["blocked"] is False
    assert end["content"]


@pytest.mark.asyncio
async def test_tokens_are_streamed_before_the_final_message():
    events = await collect(make_agent(), HookManager(), make_context())

    tokens = [e for e in events if e["type"] == "token"]
    assert tokens, "the executor's synthesis should stream token events"
    assert all(isinstance(e["text"], str) for e in tokens)
    assert events.index(tokens[-1]) < events.index(events[-1])


@pytest.mark.asyncio
async def test_no_unmapped_runtime_event_reaches_the_wire():
    """The adapter allowlists; a new lifecycle event must not leak through."""
    events = await collect(make_agent(), HookManager(), make_context())

    emitted = {e["type"] for e in events}
    unknown = emitted - FRONTEND_EVENTS - {"agent_status"}
    assert not unknown, f"unmapped events reached the frontend: {unknown}"


@pytest.mark.asyncio
async def test_attached_files_become_citations():
    files = [SimpleNamespace(filename="q3.pdf"), SimpleNamespace(filename="notes.md")]
    events = await collect(make_agent(), HookManager(), make_context(), files=files)

    citations = events[-1]["citations"]
    assert [c["source"] for c in citations] == ["q3.pdf", "notes.md"]
    assert [c["id"] for c in citations] == ["doc_01", "doc_02"]


# --- hook pipeline ----------------------------------------------------------


@pytest.mark.asyncio
async def test_user_prompt_submit_can_rewrite_the_prompt():
    manager = HookManager()

    async def rewrite(task, context):
        return f"{task} (rewritten by a hook)"

    manager.add("UserPromptSubmit", rewrite)
    events = await collect(make_agent(), manager, make_context())

    assert events[-1]["type"] == "stream_end"
    assert events[-1]["blocked"] is False


@pytest.mark.asyncio
async def test_a_user_prompt_submit_denial_ends_the_turn_with_a_fallback():
    manager = HookManager()

    async def deny(task, context):
        raise HookHaltException("Blocked by a safety policy.")

    manager.add("UserPromptSubmit", deny)
    events = await collect(make_agent(), manager, make_context())

    assert [e["type"] for e in events] == ["stream_start", "stream_end"]
    assert events[-1]["blocked"] is True
    assert events[-1]["content"] == "Blocked by a safety policy."


@pytest.mark.asyncio
async def test_pre_tool_use_fires_for_the_tools_the_agent_actually_chooses():
    """The stub fired this once against a hardcoded 'first attached tool';
    now it fires per real activation."""
    seen: list[str] = []
    manager = HookManager()

    async def observe(payload, context):
        seen.append(payload["tool_name"])
        return payload

    manager.add("PreToolUse", observe)

    agent = make_agent(
        skills=[
            SimpleNamespace(
                name="exec-summary",
                description="Write an executive summary",
                body_markdown="# Be brief",
                allowed_tools=None,
            )
        ]
    )
    events = await collect(agent, manager, make_context())

    activations = [e for e in events if e["type"] in ("tool_call", "skill_call")]
    # Guard against the vacuous pass: if the planner selects nothing, the
    # two empty lists below would match and the test would assert nothing.
    assert activations, "expected the plan to activate the attached skill"
    # Every activation on the wire was gated, and nothing was gated that
    # didn't happen.
    assert sorted(seen) == sorted(
        e.get("tool_name") or e.get("skill_name") for e in activations
    )
    assert "exec-summary" in seen


@pytest.mark.asyncio
async def test_a_pre_tool_use_denial_annotates_the_answer_without_ending_the_turn():
    """The stub's asymmetry is preserved: denying one action is not denying
    the turn."""
    manager = HookManager()

    async def deny(payload, context):
        raise HookHaltException("tool not permitted")

    manager.add("PreToolUse", deny)

    agent = make_agent(
        skills=[
            SimpleNamespace(
                name="exec-summary",
                description="Write an executive summary",
                body_markdown="# Be brief",
                allowed_tools=None,
            )
        ]
    )
    events = await collect(agent, manager, make_context())
    end = events[-1]

    assert end["type"] == "stream_end"
    assert end["blocked"] is False  # the turn still completed
    assert "Blocked by policy" in end["content"]


@pytest.mark.asyncio
async def test_post_tool_use_success_can_still_rewrite_the_final_message():
    """Where pii_redactor / telemetry_observer run — unchanged from the stub."""
    manager = HookManager()

    async def redact(message, context):
        return message.model_copy(update={"content": "[redacted]", "tokens": 7})

    manager.add("PostToolUse.Success", redact)
    events = await collect(make_agent(), manager, make_context())

    assert events[-1]["content"] == "[redacted]"
    assert events[-1]["tokens"] == 7


@pytest.mark.asyncio
async def test_a_failing_hook_does_not_break_the_turn():
    manager = HookManager()

    async def explode(task, context):
        raise RuntimeError("hook is broken")

    manager.add("UserPromptSubmit", explode)
    events = await collect(make_agent(), manager, make_context())

    assert events[-1]["type"] == "stream_end"
    assert events[-1]["blocked"] is False


@pytest.mark.asyncio
async def test_run_metadata_is_published_for_the_stop_stage_and_the_observatory():
    context = make_context()
    events = await collect(make_agent(), HookManager(), context)
    end = events[-1]

    # Additive keys — the existing frontend ignores them, the Observatory reads them.
    assert uuid.UUID(end["run_id"])
    assert end["status"]
    assert "revisions" in end and "critic_verdict" in end
    # chat.py's Stop stage reads duration_ms off the hook context.
    assert context.metadata["duration_ms"] >= 0
    assert context.metadata["agent_run_id"] == end["run_id"]


# --- routing onto Temporal ---------------------------------------------------


class _FakeTemporalRunner:
    """Stands in for `TemporalRunner`: `name == "temporal"`, no `.runtime`
    attribute (the real adapter has none either — that absence is what tells
    `stream_agent_response` the terminal row was already written by the
    workflow's own `persist_run_finish` activity, not by this module)."""

    name = "temporal"

    def __init__(self, end_data: dict, *, revision: int = 2) -> None:
        self._end_data = end_data
        self._revision = revision

    async def stream(self, request, *, extra_sink=None):
        from app.agents.lifecycle import EventType, LifecycleEvent

        yield LifecycleEvent(
            type=EventType.RUN_END,
            run_id=request.run_id,
            agent_id=request.agent_id,
            agent_name=request.agent_name,
            trace_id=request.trace_id,
            phase="done",
            revision=self._revision,
            data=self._end_data,
        )


async def _empty_relay(run_id):
    return
    yield  # pragma: no cover — makes this an async generator with no items


@pytest.mark.asyncio
async def test_a_temporal_routed_run_does_not_pre_create_the_run_row(monkeypatch):
    """Pre-creating the AgentRun row from here would race the workflow's own
    `persist_run_start` activity and, because `create_run` has no
    update-on-conflict path, permanently strand the row's `workflow_id` at
    None — breaking human-in-the-loop signaling for every Temporal-routed
    chat run (see api/routes/runs.py::decide_run). This is a regression
    guard for that bug."""
    calls: list[dict] = []
    monkeypatch.setattr(
        agent_runner.agent_run_store, "create_run", lambda **kw: calls.append(kw) or None
    )
    monkeypatch.setattr(
        agent_runner,
        "get_runner",
        lambda: _FakeTemporalRunner({"status": "succeeded", "final_answer": "ok", "final": True}),
    )
    monkeypatch.setattr(agent_runner, "subscribe_run_events", _empty_relay)

    await collect(make_agent(), HookManager(), make_context())

    assert calls == [], "create_run must not be called directly for a Temporal-routed run"


@pytest.mark.asyncio
async def test_a_temporal_routed_run_reports_the_authoritative_final_fields(monkeypatch):
    """With no `.runtime.last_result` to read (TemporalRunner has none), the
    wire's revisions/critic_verdict/needs_human_review must come from the
    authoritative final RUN_END event instead of silently defaulting."""
    monkeypatch.setattr(agent_runner.agent_run_store, "create_run", lambda **kw: None)
    monkeypatch.setattr(
        agent_runner,
        "get_runner",
        lambda: _FakeTemporalRunner(
            {
                "status": "succeeded",
                "final_answer": "done via temporal",
                "critic_verdict": "accept",
                "needs_human_review": False,
                "final": True,
            },
            revision=3,
        ),
    )
    monkeypatch.setattr(agent_runner, "subscribe_run_events", _empty_relay)

    events = await collect(make_agent(), HookManager(), make_context())
    end = events[-1]

    assert end["content"] == "done via temporal"
    assert end["status"] == "succeeded"
    assert end["critic_verdict"] == "accept"
    assert end["revisions"] == 3
    assert end["needs_human_review"] is False


# --- _to_wire_event -----------------------------------------------------


def test_to_wire_event_maps_type_and_data_pairs_directly():
    """Signature takes (event_type, data, agent_id, phase=, revision=)
    instead of a LifecycleEvent, so the same mapping works for both a live
    in-process event and one decoded off the Redis relay. This pins the
    mapping itself, independent of which source produced the pair."""
    from app.agents.lifecycle import EventType

    assert agent_runner._to_wire_event(
        EventType.TOKEN, {"text": "hi"}, "agent-1"
    ) == {"type": "token", "agent_id": "agent-1", "text": "hi"}

    assert agent_runner._to_wire_event(
        EventType.TOOL_CALL, {"tool_name": "sql_query", "step_id": "s1"}, "agent-1"
    ) == {"type": "tool_call", "agent_id": "agent-1", "tool_name": "sql_query", "step_id": "s1"}

    status = agent_runner._to_wire_event(
        EventType.PLAN_READY, {"step_count": 3}, "agent-1", phase="planning", revision=1
    )
    assert status == {
        "type": "agent_status",
        "agent_id": "agent-1",
        "stage": "plan_ready",
        "phase": "planning",
        "revision": 1,
        "step_count": 3,
    }

    assert agent_runner._to_wire_event(EventType.NODE_START, {}, "agent-1") is None
