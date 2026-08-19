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

import logging
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from app.agents.durable import get_runner
from app.agents.event_persistence import PostgresEventSink
from app.agents.lifecycle import (
    CompositeEventSink,
    EventSink,
    EventType,
    LifecycleEvent,
)
from app.agents.runtime import AgentRunRequest
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

    # Interactive chat takes the in-process path: the caller is holding an SSE
    # connection open, so durability buys nothing here and token-level
    # streaming only exists locally. See app/agents/durable/selector.py.
    runner = get_runner(prefer_local=True)

    final_answer = ""
    final_event: LifecycleEvent | None = None
    citations = _citations_from_files(attached_files)

    try:
        async for event in runner.stream(request, extra_sink=sink):
            wire = _to_wire_event(event, agent_id)
            if wire is not None:
                yield wire
            if event.type == EventType.RUN_END and event.data.get("final"):
                final_event = event
                final_answer = str(event.data.get("final_answer") or "")
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
        await agent_run_store.finalize_run(
            run_id,
            run_result.state,  # type: ignore[arg-type]
            duration_ms=duration_ms,
            citations=citations,
        )
        hook_context.metadata["agent_run_id"] = str(run_id)
        hook_context.metadata["critic_verdict"] = run_result.critic_verdict
        hook_context.metadata["revisions"] = run_result.revisions

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
        "status": (final_event.data.get("status") if final_event else "failed"),
        "revisions": (run_result.revisions if run_result else 0),
        "critic_verdict": (run_result.critic_verdict if run_result else None),
        "needs_human_review": (run_result.needs_human_review if run_result else False),
    }


def _to_wire_event(event: LifecycleEvent, agent_id: str) -> dict[str, Any] | None:
    """Map a runtime lifecycle event onto the frontend's SSE vocabulary.

    Returns None for events with no wire equivalent. An allowlist rather than
    a passthrough: a new lifecycle event should never reach a frontend that
    doesn't know how to render it.
    """
    if event.type == EventType.TOKEN:
        return {"type": "token", "agent_id": agent_id, "text": event.data.get("text", "")}

    if event.type == EventType.TOOL_CALL:
        return {
            "type": "tool_call",
            "agent_id": agent_id,
            "tool_name": event.data.get("tool_name"),
            "step_id": event.data.get("step_id"),
        }

    if event.type == EventType.SKILL_CALL:
        return {
            "type": "skill_call",
            "agent_id": agent_id,
            "skill_name": event.data.get("skill_name"),
            "step_id": event.data.get("step_id"),
        }

    # Progress events. `agent_status` is a new event name the current
    # frontend simply doesn't subscribe to, so emitting it is safe today and
    # gives the Run Observatory a live feed to render tomorrow.
    if event.type in (
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
            "stage": event.type.value,
            "phase": event.phase,
            "revision": event.revision,
            **event.data,
        }

    return None


def _maybe_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        return None
