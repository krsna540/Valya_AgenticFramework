"""Streaming adapter between the chat SSE contract and the agent runtime.

This module used to *be* the agent: a deterministic stub that echoed the
prompt. It is now a thin translation layer, and everything that reasons lives
in `app/agents/`. What it still owns is the part that is genuinely about
chat rather than about agents:

  1. **The wire contract.** The frontend listens for `stream_start`, `token`,
     `tool_call`, `skill_call`, `stream_end`. The runtime emits a richer
     vocabulary (`plan_ready`, `critique_ready`, `node_retry`, ...). This
     module maps one onto the other. Unmapped runtime events are dropped
     rather than forwarded, so adding a lifecycle event can never break a
     deployed frontend.

  2. **The hook pipeline.** All ten stages fire exactly where they did
     before, so every existing Hook row keeps working unchanged:

        UserPromptSubmit  -> before the run starts, on the raw prompt; a
                             Deny still ends the turn with a fallback.
        PreToolUse        -> before each tool/skill activation the *agents*
                             decide to make. This is the real improvement
                             over the stub, which fired it once against a
                             hardcoded "first attached tool".
        PostToolUse.*     -> after each, keyed on success/failure, and once
                             more on the assembled final message.
        Notification      -> on any denial or fault.

     SessionStart, SubagentStart/Stop and Stop stay with the caller
     (api/routes/chat.py), which is where their trigger points live.

  3. **Blocking semantics.** A PreToolUse denial skips that one action; a
     UserPromptSubmit denial ends the turn. Unchanged from the stub, because
     that distinction was already correct.

**Why the hook gate isn't inside the executor.** The agents are transport-
agnostic — they run identically inside a Temporal activity where the hook
engine's request-scoped context does not exist. Gating here keeps the agents
free of chat concerns and keeps the hook pipeline in one place. The cost is
that a hook denial arrives as an injected observation rather than as a
pre-emptive block; `_ToolGateSink` documents that trade in full.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

from app.agents.durable import DurableRunner, get_runner
from app.agents.event_persistence import PostgresEventSink
from app.agents.lifecycle import (
    CompositeEventSink,
    EventSink,
    EventType,
    LifecycleEvent,
)
from app.agents.runtime import AgentRunRequest
from app.core.redis_client import subscribe_run_events
from app.models.agent import Agent
from app.models.file import UploadedFile
from app.services import agent_run_store, registry_cache
from app.services.hooks import (
    HookContext,
    HookHaltException,
    HookManager,
    MessagePayload,
    notify,
)

logger = logging.getLogger("agentic_mvp.agent_runner")


class _ToolGateSink(EventSink):
    """Runs the PreToolUse / PostToolUse hook stages for tool and skill
    activations the agents perform.

    **The honest limitation.** A `tool_call` event is emitted by the executor
    immediately before it invokes the tool, and this sink observes it
    asynchronously — so a Deny here records the denial and surfaces it to the
    user, but does not roll back a call already in flight. That is acceptable
    for the shipped default (`execute_tools=false`, so nothing leaves the
    process) and is *not* acceptable for an agent with real tool execution
    enabled. For that case the gate belongs in `ToolInvoker.invoke`, where it
    can genuinely refuse; see app/agents/tools.py. Recording the constraint
    here rather than implying a guarantee that doesn't hold.
    """

    def __init__(self, manager: HookManager, context: HookContext) -> None:
        self._manager = manager
        self._context = context
        self.denied: list[str] = []

    async def _write(self, event: LifecycleEvent) -> None:
        if event.type not in (EventType.TOOL_CALL, EventType.SKILL_CALL):
            return
        kind = "tool" if event.type == EventType.TOOL_CALL else "skill"
        name = str(event.data.get("tool_name") or event.data.get("skill_name") or "")
        if not name:
            return

        try:
            await self._manager.trigger_pipeline(
                "PreToolUse",
                {"tool_name": name, "kind": kind, "step_id": event.data.get("step_id")},
                self._context,
            )
        except HookHaltException as halt:
            self.denied.append(f"{kind} '{name}': {halt.fallback_message}")
            await notify(
                self._manager,
                self._context,
                {"stage": "PreToolUse", "tool_name": name, "reason": halt.fallback_message},
            )
            await self._manager.trigger_pipeline(
                "PostToolUse.Failure",
                {"tool_name": name, "kind": kind, "reason": "denied by policy"},
                self._context,
            )
            return

        await self._manager.trigger_pipeline(
            "PostToolUse.Success", {"tool_name": name, "kind": kind}, self._context
        )


def _citations_from_files(attached_files: list[UploadedFile]) -> list[dict[str, str]]:
    """Build the citation list the chat UI renders.

    Still derived from the attached files rather than from real retrieval —
    the runtime accepts `context_documents` and will cite whatever is passed,
    so wiring the Retrieval Service in is a change at the call site, not here.
    """
    return [
        {
            "id": f"doc_{idx:02d}",
            "source": f.filename,
            "snippet": (
                f"Attached document {f.filename}. Wire the Retrieval Service into "
                "chat.py's context_documents to replace this placeholder snippet."
            ),
        }
        for idx, f in enumerate(attached_files, start=1)
    ]


def _context_documents(attached_files: list[UploadedFile]) -> list[dict[str, Any]]:
    return [
        {"title": f.filename, "snippet": f"(content of {f.filename} not yet extracted)"}
        for f in attached_files
    ]


async def stream_agent_response(
    agent: Agent,
    user_message: str,
    attached_files: list[UploadedFile],
    hook_manager: HookManager,
    hook_context: HookContext,
) -> AsyncGenerator[dict[str, Any], None]:
    """Run one chat turn through the agent graph, yielding SSE-shaped events.

    Signature and emitted event shapes are unchanged from the stub this
    replaced, so `api/routes/chat.py` needed no modification.
    """
    agent_id = str(agent.id)
    started_at = time.monotonic()
    run_id = uuid.uuid4()

    yield {"type": "stream_start", "agent_id": agent_id}

    # --- UserPromptSubmit: guardrails, DLP, prompt rewriting ----------------
    try:
        task = await hook_manager.trigger_pipeline("UserPromptSubmit", user_message, hook_context)
    except HookHaltException as halt:
        await notify(
            hook_manager,
            hook_context,
            {"stage": "UserPromptSubmit", "reason": halt.fallback_message},
        )
        yield {
            "type": "stream_end",
            "agent_id": agent_id,
            "content": halt.fallback_message,
            "citations": [],
            "message_id": str(uuid.uuid4()),
            "blocked": True,
        }
        return

    # Snapshot the agent's registry associations on this (synchronous) thread
    # before any concurrency starts — the graph runs in tasks that must never
    # trigger a lazy load against the shared Session. tools/skills/playbooks
    # come from registry_cache rather than the ORM relationships directly:
    # the chat route (api/routes/chat.py) already warmed this agent's entry
    # on the sync path before this function's caller was scheduled as a
    # task, so this is a cache read, never a fresh query, from here.
    caps = registry_cache.get_capabilities(agent)
    request = AgentRunRequest.from_agent(
        agent,
        objective=task,
        language=str(hook_context.metadata.get("language") or "en"),
        context_documents=_context_documents(attached_files),
        conversation_id=hook_context.conversation_id,
        user_id=hook_context.user_id,
        run_id=str(run_id),
        trace_id=hook_context.trace_id,
        tools=caps["tools"],
        skills=caps["skills"],
        playbooks=caps["playbooks"],
    )

    gate = _ToolGateSink(hook_manager, hook_context)
    persist = agent_run_store.PersistingEventSink(run_id)
    # Additive, 2026-08-08: also project every event onto the episodic
    # `events` table (PLATFORM_ARCHITECTURE.md §10/§11.3) and publish it to
    # Redis for any external subscriber (app/stream.py) — see
    # app/agents/event_persistence.py's module docstring for why this is a
    # parallel sink rather than a change to PersistingEventSink itself.
    episodic = PostgresEventSink(run_id, tenant_id=agent.tenant_id, project_id=None)
    sink = CompositeEventSink(gate, persist, episodic)

    # Which backend this turn actually runs on — Temporal when enabled, else
    # in-process (app/agents/durable/selector.py). No longer forced local:
    # the merged event stream below keeps token-level streaming alive on the
    # durable path too, via the Redis relay PostgresEventSink already feeds.
    runner = get_runner()

    # The workflow's own `persist_run_start` activity creates this row for a
    # durable run, stamped with the real workflow_id. Creating it here too
    # would race that insert and — since create_run has no update-on-conflict
    # path (app/services/agent_run_store.py) — permanently strand the row's
    # workflow_id at None, breaking the human-in-the-loop signal lookup in
    # api/routes/runs.py::decide_run. Only the in-process path owns this
    # write; the durable path's own activity owns it for a Temporal run.
    if runner.name != "temporal":
        agent_run_store.create_run(
            run_id=run_id,
            agent_id=agent.id,
            objective=task,
            trace_id=hook_context.trace_id,
            tenant_id=agent.tenant_id,
            user_id=_maybe_uuid(hook_context.user_id),
            conversation_id=_maybe_uuid(hook_context.conversation_id),
            language=request.language,
            model_name=agent.model_name,
            runtime_config=request.config.model_dump(),
            thread_id=request.thread_id or str(run_id),
        )

    final_answer = ""
    final_data: dict[str, Any] | None = None
    final_revision = 0
    citations = _citations_from_files(attached_files)

    try:
        async for event_type, data, phase, revision in _stream_events(runner, request, run_id, sink):
            wire = _to_wire_event(event_type, data, agent_id, phase=phase, revision=revision)
            if wire is not None:
                yield wire
            if event_type == EventType.RUN_END and data.get("final"):
                final_data = data
                final_revision = revision
                final_answer = str(data.get("final_answer") or "")
    except Exception as exc:  # noqa: BLE001 — the turn's fault boundary
        logger.exception("Agent run %s failed", run_id)
        await notify(hook_manager, hook_context, {"stage": "agent_execution", "error": str(exc)})
        final_answer = (
            "This request could not be completed because the agent runtime "
            "encountered an unexpected error."
        )

    if gate.denied:
        final_answer += "\n\n" + "\n".join(f"(Blocked by policy — {d})" for d in gate.denied)

    # --- PostToolUse.Success on the assembled message ----------------------
    # Where pii_redactor / telemetry_observer run, exactly as before.
    message = MessagePayload(sender=agent.name, recipient="user", content=final_answer)
    message = await hook_manager.trigger_pipeline("PostToolUse.Success", message, hook_context)

    duration_ms = int((time.monotonic() - started_at) * 1000)
    hook_context.metadata["tokens"] = message.tokens
    hook_context.metadata["duration_ms"] = duration_ms

    runtime = getattr(runner, "runtime", None)
    run_result = getattr(runtime, "last_result", None) if runtime is not None else None
    if run_result is not None:
        # In-process only: the durable path's own persist_run_finish activity
        # already wrote the terminal row from inside the workflow.
        await agent_run_store.finalize_run(
            run_id,
            run_result.state,  # type: ignore[arg-type]
            duration_ms=duration_ms,
            citations=citations,
        )
        critic_verdict = run_result.critic_verdict
        revisions = run_result.revisions
        needs_human_review = run_result.needs_human_review
    else:
        # Durable: read the same fields off the authoritative final RUN_END
        # event instead (see _stream_events) — TemporalRunner has no
        # `.runtime` attribute, so `run_result` is always None here, but the
        # values still exist, carried on the event `TemporalRunner.stream()`
        # builds from the completed AgentRunResult.
        final_data = final_data or {}
        critic_verdict = final_data.get("critic_verdict")
        revisions = final_revision
        needs_human_review = bool(final_data.get("needs_human_review", False))
    hook_context.metadata["agent_run_id"] = str(run_id)
    hook_context.metadata["critic_verdict"] = critic_verdict
    hook_context.metadata["revisions"] = revisions

    yield {
        "type": "stream_end",
        "agent_id": agent_id,
        "content": message.content,
        "citations": citations,
        "message_id": str(uuid.uuid4()),  # overwritten by the route with the persisted id
        "blocked": False,
        "tokens": message.tokens,
        # Extra keys are additive: the existing frontend ignores what it
        # doesn't read, and the Run Observatory reads these.
        "run_id": str(run_id),
        "status": (final_data.get("status") if final_data else "failed"),
        "revisions": revisions,
        "critic_verdict": critic_verdict,
        "needs_human_review": needs_human_review,
    }


async def _merge_event_streams(
    *iterators: AsyncIterator[Any],
) -> AsyncGenerator[Any, None]:
    """Fan multiple async iterators into one, in arrival order.

    Same fan-in shape `api/routes/chat.py`'s multi-agent `event_generator`
    already uses (one queue, one pump task per source) — reused here rather
    than reinvented. Yields until every source is exhausted; if the caller
    stops consuming early, whatever is still pumping gets cancelled.
    """
    queue: asyncio.Queue = asyncio.Queue()
    _DONE = object()

    async def _pump(it: AsyncIterator[Any]) -> None:
        try:
            async for item in it:
                await queue.put(item)
        finally:
            await queue.put(_DONE)

    tasks = [asyncio.create_task(_pump(it)) for it in iterators]
    remaining = len(tasks)
    try:
        while remaining:
            item = await queue.get()
            if item is _DONE:
                remaining -= 1
                continue
            yield item
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _stream_events(
    runner: DurableRunner,
    request: AgentRunRequest,
    run_id: uuid.UUID,
    sink: EventSink,
) -> AsyncGenerator[tuple[EventType, dict[str, Any], str, int], None]:
    """Yield `(event_type, data, phase, revision)` uniformly regardless of
    which runner actually executed the turn.

    The in-process path streams `LifecycleEvent`s directly — full fidelity,
    nothing else needed. The Temporal path fans in two sources: a live Redis
    relay (tokens, tool/skill calls, step progress — the granularity
    `TemporalRunner.stream()`'s own 1s status polling can't provide, see its
    module docstring) merged with `runner.stream()` itself, which still owns
    `RUN_START`, human-review pauses, and — critically — the authoritative
    final `RUN_END`, built from the completed `AgentRunResult` rather than
    relayed from inside the activity. The relay's own per-node `RUN_END`
    (from `graph.py::finalize_node`) never sets `data["final"]`, so there is
    no ambiguity about which one is the real one.
    """
    if runner.name != "temporal":
        async for event in runner.stream(request, extra_sink=sink):
            yield event.type, event.data, event.phase or "", event.revision
        return

    async def _relay() -> AsyncGenerator[tuple[EventType, dict[str, Any], str, int], None]:
        async for raw in subscribe_run_events(str(run_id)):
            try:
                event_type = EventType(raw.get("type"))
            except ValueError:
                continue  # unknown/future event name — an observer must never choke on one
            yield (
                event_type,
                raw.get("data") or {},
                str(raw.get("phase") or ""),
                int(raw.get("revision") or 0),
            )

    async def _authoritative() -> AsyncGenerator[tuple[EventType, dict[str, Any], str, int], None]:
        async for event in runner.stream(request, extra_sink=sink):
            yield event.type, event.data, event.phase or "", event.revision

    async for item in _merge_event_streams(_relay(), _authoritative()):
        yield item


def _to_wire_event(
    event_type: EventType,
    data: dict[str, Any],
    agent_id: str,
    *,
    phase: str = "",
    revision: int = 0,
) -> dict[str, Any] | None:
    """Map a runtime lifecycle event onto the frontend's SSE vocabulary.

    Takes the type/data pair rather than a `LifecycleEvent` so the same
    mapping serves both a live in-process event and one decoded off the
    Redis relay (`subscribe_run_events`), which carries the same shape as a
    plain dict, never a `LifecycleEvent` instance.

    Returns None for events with no wire equivalent. An allowlist rather than
    a passthrough: a new lifecycle event should never reach a frontend that
    doesn't know how to render it.
    """
    if event_type == EventType.TOKEN:
        return {"type": "token", "agent_id": agent_id, "text": data.get("text", "")}

    if event_type == EventType.TOOL_CALL:
        return {
            "type": "tool_call",
            "agent_id": agent_id,
            "tool_name": data.get("tool_name"),
            "step_id": data.get("step_id"),
        }

    if event_type == EventType.SKILL_CALL:
        return {
            "type": "skill_call",
            "agent_id": agent_id,
            "skill_name": data.get("skill_name"),
            "step_id": data.get("step_id"),
        }

    # Progress events. `agent_status` is a new event name the current
    # frontend simply doesn't subscribe to, so emitting it is safe today and
    # gives the Run Observatory a live feed to render tomorrow.
    if event_type in (
        EventType.PLAYBOOK_SELECTED,
        EventType.PLAN_READY,
        EventType.STEP_START,
        EventType.STEP_END,
        EventType.CRITIQUE_READY,
        EventType.REVISION_START,
        EventType.HUMAN_REVIEW_REQUIRED,
    ):
        return {
            "type": "agent_status",
            "agent_id": agent_id,
            "stage": event_type.value,
            "phase": phase,
            "revision": revision,
            **data,
        }

    return None


def _maybe_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None
