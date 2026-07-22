"""Agent execution abstraction — streaming version, now hook-aware across the
full 10-stage lifecycle taxonomy.

Still a deterministic stub (see the note below), shaped as an async generator
of structured events matching the FastAPI event-name contract the frontend
listens for: stream_start, token, tool_call, skill_call, stream_end.

`skill_call` used to mean "a Skill's real handler_key-bound BaseSkill.execute()
ran" (see git history / [[project_agentic_mvp_nexusclaw_manifest_conventions]]
if this needs revisiting) — that whole handler_key/BaseSkill catalog was
retired in favor of making the SKILL.md-folder format the only Skill
definition, which this app never executes (see app/api/routes/skills.py's
module docstring). `skill_call` is repurposed below to mean "a Skill was
activated for context" (its SKILL.md excerpt surfaced), not "ran".

Every call now runs through the lifecycle hook pipeline (app/services/hooks.py):

  - UserPromptSubmit can inspect/mutate the incoming task, or halt generation
    entirely by raising HookHaltException (caught here, ends the turn with a
    fallback message).
  - PreToolUse runs before the demo tool_call and before the skill invocation;
    a halt here is caught locally and just skips that one action rather than
    ending the turn, since blocking one tool call shouldn't necessarily cancel
    the whole response.
  - PostToolUse.Success / PostToolUse.Failure run right after each of those,
    keyed off whether the action actually succeeded (a skill's zero-crash
    BaseSkill.execute() contract means "failure" here is detected by checking
    for a SKILL_EXECUTION_ERROR-prefixed result, not an exception).
  - PostToolUse.Success also runs on the assembled final message (was
    before_message_send) — pii_redactor/telemetry_observer live here.

Stop (was after_agent_step) is triggered by the caller (api/routes/chat.py)
once the message is actually persisted, since it needs the saved message
id/duration that only exists after this generator finishes. SessionStart
fires once per conversation in chat.py's create_conversation, not per turn.

To plug in a real model later, replace the generation logic below (the
"full_text" construction and token loop) with calls into your LLM provider's
streaming API — the hook pipeline and event shapes don't need to change.
"""
import asyncio
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from app.models.agent import Agent
from app.models.file import UploadedFile
from app.services.hooks import HookContext, HookHaltException, HookManager, MessagePayload, notify


async def _run_pre_tool_use(
    hook_manager: HookManager, hook_context: HookContext, tool_name: str, extra: dict[str, Any]
) -> dict[str, Any] | None:
    """Runs the PreToolUse pipeline for one tool/skill invocation. Returns the
    (possibly modified) payload dict to proceed with, or None if a hook
    denied it — in which case the caller should skip the action, not the
    whole turn."""
    payload = {"tool_name": tool_name, **extra}
    try:
        return await hook_manager.trigger_pipeline("PreToolUse", payload, hook_context)
    except HookHaltException as halt:
        await notify(hook_manager, hook_context, {"stage": "PreToolUse", "tool_name": tool_name, "reason": halt.fallback_message})
        return None


async def stream_agent_response(
    agent: Agent,
    user_message: str,
    attached_files: list[UploadedFile],
    hook_manager: HookManager,
    hook_context: HookContext,
) -> AsyncGenerator[dict[str, Any], None]:
    agent_id = str(agent.id)
    started_at = time.monotonic()

    yield {"type": "stream_start", "agent_id": agent_id}

    try:
        task = await hook_manager.trigger_pipeline("UserPromptSubmit", user_message, hook_context)
    except HookHaltException as halt:
        await notify(hook_manager, hook_context, {"stage": "UserPromptSubmit", "reason": halt.fallback_message})
        yield {
            "type": "stream_end",
            "agent_id": agent_id,
            "content": halt.fallback_message,
            "citations": [],
            "message_id": str(uuid.uuid4()),
            "blocked": True,
        }
        return

    # Demo tool-call event: if the agent has tools attached, "use" the first
    # one so the UI's expandable tool-call affordance has something to show.
    # Gated by PreToolUse/PostToolUse.Success so those stages are genuinely
    # exercised, not just defined.
    tool_blocked_note = ""
    if agent.tools:
        tool = agent.tools[0]
        gated = await _run_pre_tool_use(hook_manager, hook_context, tool.name, {"kind": "tool"})
        if gated is None:
            tool_blocked_note = f" (Tool '{tool.name}' was blocked by policy before it ran.)"
        else:
            yield {"type": "tool_call", "agent_id": agent_id, "tool_name": tool.name}
            await asyncio.sleep(0.4)
            await hook_manager.trigger_pipeline("PostToolUse.Success", {"tool_name": tool.name, "kind": "tool"}, hook_context)

    # Skill "activation": no BaseSkill/handler_key catalog exists anymore
    # (see this module's docstring), so there is nothing to actually run —
    # skills are instructional content an agent loads progressively, per the
    # Agent Skills spec. This emits skill_call for the first attached skill
    # to stand in for "activation" until this runner has a real tool-calling
    # loop that can decide which skills to load and when.
    invoked_skill_name: str | None = None
    skill_blocked_note = ""
    if agent.skills:
        first_skill = agent.skills[0]
        gated = await _run_pre_tool_use(hook_manager, hook_context, first_skill.name, {"kind": "skill"})
        if gated is None:
            skill_blocked_note = f" (Skill '{first_skill.name}' was blocked by policy before it activated.)"
        else:
            invoked_skill_name = first_skill.name
            yield {"type": "skill_call", "agent_id": agent_id, "skill_name": first_skill.name}
            await asyncio.sleep(0.3)
            await hook_manager.trigger_pipeline(
                "PostToolUse.Success", {"tool_name": first_skill.name, "kind": "skill"}, hook_context
            )

    capabilities = []
    if agent.skills:
        # Progressive disclosure, "metadata" tier (per the Agent Skills
        # spec): name + description only, always visible — the full
        # SKILL.md body is loaded below only for the first one, standing in
        # for "activation".
        capabilities.append(f"skills: {', '.join(f'{s.name} ({s.description})' for s in agent.skills)}")
    if agent.tools:
        capabilities.append(f"tools: {', '.join(t.name for t in agent.tools)}")
    if agent.plugins:
        capabilities.append(f"plugins: {', '.join(p.name for p in agent.plugins)}")
    if agent.hooks:
        capabilities.append(f"hooks: {', '.join(h.name for h in agent.hooks)}")
    capability_note = f" I have access to {'; '.join(capabilities)}." if capabilities else ""

    skill_note = ""
    if invoked_skill_name is not None:
        activated = agent.skills[0]
        skill_note = (
            f" Activating skill '{activated.name}' — its SKILL.md instructions "
            f"(first 200 chars): {activated.body_markdown.strip()[:200]!r}"
        )

    citations: list[dict[str, str]] = []
    citation_note = ""
    if attached_files:
        for idx, f in enumerate(attached_files, start=1):
            citations.append(
                {
                    "id": f"doc_{idx:02d}",
                    "source": f.filename,
                    "snippet": (
                        f"Demo snippet from {f.filename} — wire real text "
                        "extraction/RAG into agent_runner.py to replace this."
                    ),
                }
            )
        refs = " ".join(f"[{i}]" for i in range(1, len(citations) + 1))
        citation_note = f" Based on your attached file(s) {refs}."

    full_text = (
        f"[{agent.name} | {agent.model_name} stub] You said: \"{task}\"."
        f"{capability_note}{citation_note}{skill_note}{tool_blocked_note}{skill_blocked_note} "
        "This is a placeholder response — wire a real model into app/services/agent_runner.py to get live answers."
    )

    for word in full_text.split(" "):
        yield {"type": "token", "agent_id": agent_id, "text": word + " "}
        await asyncio.sleep(0.02)

    message = MessagePayload(sender=agent.name, recipient="user", content=full_text)
    message = await hook_manager.trigger_pipeline("PostToolUse.Success", message, hook_context)

    hook_context.metadata["tokens"] = message.tokens
    hook_context.metadata["duration_ms"] = int((time.monotonic() - started_at) * 1000)

    yield {
        "type": "stream_end",
        "agent_id": agent_id,
        "content": message.content,
        "citations": citations,
        "message_id": str(uuid.uuid4()),  # overwritten by the route with the real persisted id
        "blocked": False,
        "tokens": message.tokens,
    }
