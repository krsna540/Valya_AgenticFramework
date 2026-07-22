"""Multi-agent lifecycle hook engine — full 10-stage taxonomy.

Implements the comprehensive lifecycle registry the frontend's Hooks page
exposes: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse.Success,
PostToolUse.Failure, PreCompact, SubagentStart, SubagentStop, Stop,
Notification — plus the five return directives (Allow, Deny, Modify,
InjectContext, SilentLog) and two handler families:

  - `python`: a Hook's handler_key resolves to a vetted function in
    BUILTIN_HOOKS below (this repo's own code) — the safe default.
  - `http` / `command` / `mcp_tool`: real execution of an operator-configured
    webhook, local script, or MCP tool call — see app/services/hook_handlers.py
    for the dispatcher and the trust-boundary discussion.

Where each stage actually fires (this app is a lean, mostly-stub agent
runner, not a full coding-agent harness, so not all 10 have a natural
trigger point yet):

  SessionStart        -> once per new conversation (api/routes/chat.py::create_conversation)
  UserPromptSubmit     -> per turn, on the raw incoming message (agent_runner, was before_agent_step)
  PreToolUse            -> per turn, before the demo tool_call / skill invocation
  PostToolUse.Success   -> after a tool/skill call succeeds, and after the
                           assembled reply is ready (was before_message_send)
  PostToolUse.Failure   -> after a tool/skill call fails (skill result starting
                           with SKILL_EXECUTION_ERROR)
  Stop                  -> once per turn, after the message is persisted
                           (was after_agent_step) — final "audit" pass
  Notification          -> fault-isolation channel (was on_error), plus fired
                           whenever a UserPromptSubmit/PreToolUse hook denies
  PreCompact            -> not wired: no context-window compaction exists in
                           this stub runner. Hooks can be registered against
                           it (schema-ready) but never fire yet.
  SubagentStart/Stop    -> around each *secondary* agent's execution in a
                           multi-agent chat turn (api/routes/chat.py::run_one)
                           — the closest thing this app has to subagents today

Two corrections versus the reference design this was originally built from
(kept from the earlier 4-stage version, still load-bearing):

1. Halting. A hook that wants to actually stop generation raises
   `HookHaltException` rather than just returning a replacement value —
   `HookManager.trigger_pipeline` re-raises it immediately (bypassing the
   generic fault-isolation catch), and callers decide locally whether a
   halt at a given stage cancels the whole turn (UserPromptSubmit) or just
   skips one action (PreToolUse).

2. Fault isolation. A failing hook triggers the Notification pipeline from
   inside the except block, itself wrapped in its own try/except that only
   logs — so a broken Notification hook can never crash the turn that
   triggered it.
"""
import asyncio
import contextvars
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.services.hook_handlers import HookOutcome, run_custom_handler

logger = logging.getLogger("agentic_mvp.hooks")


# --- Core standard structures ---------------------------------------------


class HookContext(BaseModel):
    """The state payload passed across lifecycle hooks for one execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent_name: str
    conversation_id: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """A JSON-safe snapshot handed to http/command/mcp_tool handlers."""
        return {
            "trace_id": self.trace_id,
            "timestamp": self.timestamp.isoformat(),
            "agent_name": self.agent_name,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "metadata": self.metadata,
        }


class MessagePayload(BaseModel):
    """Structured data representing an outgoing agent message, passed through
    the PostToolUse.Success pipeline before it's finalized."""

    sender: str
    recipient: str
    content: str
    tokens: int | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HookHaltException(Exception):
    """Raised to cancel the current action and return `fallback_message`
    (UserPromptSubmit: cancels the whole turn; PreToolUse: the caller
    catches this locally and skips just that one tool/skill call)."""

    def __init__(self, fallback_message: str):
        self.fallback_message = fallback_message
        super().__init__(fallback_message)


# Request-scoped context, safely isolated per concurrent asyncio Task. Every
# `asyncio.create_task(...)` call snapshots the current contextvars state, so
# setting this inside each per-agent task in the SSE fan-out (chat.py) keeps
# concurrent agent streams from ever seeing each other's trace/context —
# no locks or manual plumbing needed.
current_hook_context: contextvars.ContextVar[HookContext | None] = contextvars.ContextVar(
    "current_hook_context", default=None
)


# --- Pipeline manager --------------------------------------------------------

STAGES = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse.Success",
    "PostToolUse.Failure",
    "PreCompact",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "Notification",
)

# Stages with a genuine trigger point today vs. schema-only placeholders —
# surfaced to the frontend via GET /hooks/handlers so the UI can label
# PreCompact accordingly instead of implying it fires.
WIRED_STAGES = frozenset(s for s in STAGES if s != "PreCompact")

DIRECTIVES = ("Allow", "Deny", "Modify", "InjectContext", "SilentLog")

HookFn = Callable[[Any, HookContext], Awaitable[Any]]


class HookManager:
    """Manages ordering and execution of hooks for one composed pipeline
    instance. A fresh instance is built per chat turn in chat.py so that
    global/agent/task-scoped hooks can be combined without cross-request
    state — see build_pipeline_for_agent below."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookFn]] = {stage: [] for stage in STAGES}

    def register(self, stage: str) -> Callable[[HookFn], HookFn]:
        if stage not in self._hooks:
            raise ValueError(f"Invalid hook stage: {stage}")

        def decorator(func: HookFn) -> HookFn:
            self._hooks[stage].append(func)
            return func

        return decorator

    def add(self, stage: str, func: HookFn) -> None:
        if stage not in self._hooks:
            raise ValueError(f"Invalid hook stage: {stage}")
        self._hooks[stage].append(func)

    async def trigger_pipeline(self, stage: str, data: Any, context: HookContext) -> Any:
        """Executes hooks for `stage` in registration order. Mutating hooks'
        return values become the input to the next hook (a pipeline, not a
        fan-out) so e.g. a redaction hook can run after a token-counting hook."""
        current_data = data
        for hook in self._hooks.get(stage, []):
            try:
                current_data = await hook(current_data, context)
            except HookHaltException:
                # Deliberate control flow, not a fault — must propagate so the
                # caller can short-circuit generation. Never isolated/swallowed.
                raise
            except Exception as e:  # noqa: BLE001 — intentional catch-all fault boundary
                logger.error(
                    "Hook failure in stage '%s' inside %s: %s",
                    stage,
                    getattr(hook, "__name__", repr(hook)),
                    e,
                )
                if stage == "Notification":
                    # A Notification hook itself failed — log and move on to
                    # the next Notification hook rather than recursing.
                    continue
                try:
                    await self.trigger_pipeline(
                        "Notification", {"source_stage": stage, "error": str(e)}, context
                    )
                except Exception:  # noqa: BLE001
                    logger.exception("Notification pipeline failed; isolating so it can't crash the caller")
                # Skip this hook's mutation, continue the pipeline with the
                # last-good value rather than crashing the whole turn.
        return current_data


async def notify(manager: "HookManager", context: HookContext, payload: dict[str, Any]) -> None:
    """Best-effort helper for firing an explicit out-of-band Notification
    (e.g. when a Deny happens) without risking the caller's own flow."""
    try:
        await manager.trigger_pipeline("Notification", payload, context)
    except Exception:  # noqa: BLE001
        logger.exception("Notification pipeline failed during explicit notify()")


# --- Built-in (python) hook implementations & registry -----------------------

# name -> (stage, fn(data, context, config) -> data). `config` is the
# executing Hook DB row's `config` JSON column, bound in build_pipeline_for_agent
# so each hook instance can be tuned (e.g. its own banned-phrase list) without
# hooks stepping on each other's settings via shared HookContext.metadata.
ConfiguredHookFn = Callable[[Any, HookContext, dict[str, Any]], Awaitable[Any]]
BUILTIN_HOOKS: dict[str, dict[str, Any]] = {}


def builtin_hook(name: str, stage: str, description: str) -> Callable[[ConfiguredHookFn], ConfiguredHookFn]:
    if stage not in STAGES:
        raise ValueError(f"Invalid hook stage: {stage}")

    def decorator(func: ConfiguredHookFn) -> ConfiguredHookFn:
        BUILTIN_HOOKS[name] = {"stage": stage, "fn": func, "description": description}
        return func

    return decorator


DEFAULT_BANNED_PHRASES = ["rm -rf", "drop table"]


@builtin_hook(
    "guardrail_interceptor",
    "UserPromptSubmit",
    "Blocks requests containing banned phrases (config: banned_phrases: string[]) and halts generation.",
)
async def guardrail_interceptor(task: str, context: HookContext, config: dict[str, Any]) -> str:
    banned = config.get("banned_phrases") or DEFAULT_BANNED_PHRASES
    lowered = task.lower()
    for phrase in banned:
        if phrase.lower() in lowered:
            logger.warning("guardrail_interceptor blocked task for agent %s (matched %r)", context.agent_name, phrase)
            raise HookHaltException("This request was blocked by a safety policy and could not be processed.")
    return task


_DLP_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[dlp-masked-ssn]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[dlp-masked-card]"),
    (re.compile(r"\b(sk|pk|api)[_-][A-Za-z0-9]{16,}\b", re.IGNORECASE), "[dlp-masked-secret]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[dlp-masked-email]"),
]


@builtin_hook(
    "dlp_scrubber",
    "UserPromptSubmit",
    "Pre-LLM DLP hook: masks SSNs/card numbers/API-key-shaped strings/emails in the raw "
    "user prompt before it reaches any model provider (config: enabled, fail_closed).",
)
async def dlp_scrubber(task: str, context: HookContext, config: dict[str, Any]) -> str:
    """The Intelligence Layer spec calls this out specifically: 'A Pre-LLM
    Hook intercepts user text to validate against DLP policies before it
    hits an external API provider.' pii_redactor (below) does the same kind
    of masking but on the *outbound* PostToolUse.Success message; this is
    the inbound counterpart, registered at UserPromptSubmit so it runs
    before the prompt is ever sent anywhere. fail_closed=true switches from
    masking to a hard Deny (HookHaltException) when a match is found,
    for tenants that want to block rather than silently rewrite."""
    if not config.get("enabled", True):
        return task
    masked = task
    matched = False
    for pattern, replacement in _DLP_PATTERNS:
        if pattern.search(masked):
            matched = True
            masked = pattern.sub(replacement, masked)
    if matched:
        logger.warning("[trace=%s] dlp_scrubber masked sensitive content in prompt for %s", context.trace_id, context.agent_name)
        if config.get("fail_closed", False):
            raise HookHaltException("This request contains data that violates data-loss-prevention policy and was blocked.")
    return masked


@builtin_hook(
    "telemetry_observer",
    "PostToolUse.Success",
    "Read-only: measures outgoing message length as a token-count proxy.",
)
async def telemetry_observer(message: MessagePayload, context: HookContext, config: dict[str, Any]) -> MessagePayload:
    message.tokens = len(message.content.split())
    logger.info(
        "[trace=%s] %s -> %s | tokens=%s", context.trace_id, message.sender, message.recipient, message.tokens
    )
    return message


_PII_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[redacted-email]"),
    (re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"), "[redacted-phone]"),
]


@builtin_hook(
    "pii_redactor",
    "PostToolUse.Success",
    "Mutating: redacts emails/phone numbers from outgoing message content before it's persisted.",
)
async def pii_redactor(message: MessagePayload, context: HookContext, config: dict[str, Any]) -> MessagePayload:
    if not config.get("enabled", True):
        return message
    redacted = message.content
    for pattern, replacement in _PII_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    if redacted != message.content:
        logger.info("[trace=%s] pii_redactor redacted content for %s", context.trace_id, message.recipient)
    message.content = redacted
    return message


@builtin_hook(
    "usage_logger",
    "Stop",
    "Read-only: logs a structured line summarizing the completed turn (config: min_tokens_to_log).",
)
async def usage_logger(data: dict[str, Any], context: HookContext, config: dict[str, Any]) -> dict[str, Any]:
    tokens = data.get("tokens", 0)
    if tokens >= config.get("min_tokens_to_log", 0):
        logger.info(
            "[trace=%s] agent=%s conversation=%s tokens=%s duration_ms=%s",
            context.trace_id,
            context.agent_name,
            context.conversation_id,
            tokens,
            data.get("duration_ms"),
        )
    return data


@builtin_hook(
    "error_alert_logger",
    "Notification",
    "Read-only: logs errors/faults raised anywhere else in the pipeline with full trace context.",
)
async def error_alert_logger(payload: Any, context: HookContext, config: dict[str, Any]) -> Any:
    logger.error("[trace=%s] agent=%s notification: %s", context.trace_id, context.agent_name, payload)
    return payload


@builtin_hook(
    "session_logger",
    "SessionStart",
    "Read-only: logs a new conversation/session for security-audit purposes.",
)
async def session_logger(data: dict[str, Any], context: HookContext, config: dict[str, Any]) -> dict[str, Any]:
    logger.info("[trace=%s] SessionStart agent=%s conversation=%s", context.trace_id, context.agent_name, context.conversation_id)
    return data


@builtin_hook(
    "tool_allowlist_guard",
    "PreToolUse",
    "Blocks tool/skill calls whose name isn't in config: allowed_names: string[] (empty list = allow all).",
)
async def tool_allowlist_guard(data: dict[str, Any], context: HookContext, config: dict[str, Any]) -> dict[str, Any]:
    allowed = config.get("allowed_names") or []
    name = data.get("tool_name") or data.get("skill_name")
    if allowed and name and name not in allowed:
        raise HookHaltException(f"Tool/skill '{name}' is not in the allowed list for this pipeline.")
    return data


@builtin_hook(
    "subagent_metrics_logger",
    "SubagentStop",
    "Read-only: logs metrics when a secondary agent finishes its part of a multi-agent turn.",
)
async def subagent_metrics_logger(data: dict[str, Any], context: HookContext, config: dict[str, Any]) -> dict[str, Any]:
    logger.info("[trace=%s] SubagentStop agent=%s data=%s", context.trace_id, context.agent_name, data)
    return data


def list_builtin_handlers() -> list[dict[str, str]]:
    return [
        {"key": key, "stage": entry["stage"], "description": entry["description"]}
        for key, entry in sorted(BUILTIN_HOOKS.items())
    ]


def _bind_config(fn: ConfiguredHookFn, config: dict[str, Any]) -> HookFn:
    async def wrapped(data: Any, context: HookContext) -> Any:
        return await fn(data, context, config)

    return wrapped


def _interpret_outcome(outcome: HookOutcome, data: Any, context: HookContext) -> Any:
    """Uniform mapping from a custom handler's HookOutcome to pipeline
    behavior, shared by http/command/mcp_tool hooks."""
    if outcome.context_updates:
        context.metadata.update(outcome.context_updates)
    if outcome.directive == "Deny":
        raise HookHaltException(outcome.reason or "Denied by hook policy.")
    if outcome.directive == "SilentLog":
        logger.info("[trace=%s] SilentLog: %s", context.trace_id, outcome.reason or "(no detail)")
        return data
    # Allow / Modify / InjectContext all resolve the same way: use the
    # handler's replacement data if it supplied one, else pass through.
    return outcome.data if outcome.data is not None else data


def _bind_custom(hook: Any) -> HookFn:
    async def wrapped(data: Any, context: HookContext) -> Any:
        outcome = await run_custom_handler(
            hook.handler_type, hook.handler_config, hook.execution_policy, hook.lifecycle_event, data, context.as_dict()
        )
        return _interpret_outcome(outcome, data, context)

    return wrapped


def build_pipeline_for_agent(db: Any, agent: Any, extra_hook_ids: list | None = None) -> HookManager:
    """Compose a fresh HookManager for one chat turn from three scoped
    sources, deduplicated by hook id:
      - global:  every active Hook with scope='global', regardless of agent
      - agent:   hooks attached to this agent via the agent_hooks join
      - task:    hook_ids passed in on this one request only (SendMessageRequest.hook_ids)
    A new HookManager per turn (rather than one shared singleton) is what
    keeps these three scopes from bleeding into each other across concurrent
    requests/agents — see current_hook_context for the complementary
    per-request-data isolation."""
    from app.models.hook import Hook  # local import: avoids a services->models->services cycle

    manager = HookManager()

    global_hooks = db.query(Hook).filter(Hook.scope == "global", Hook.is_active == True).all()  # noqa: E712
    agent_hooks = [h for h in agent.hooks if h.is_active]
    extra_hooks = []
    if extra_hook_ids:
        extra_hooks = (
            db.query(Hook).filter(Hook.id.in_(extra_hook_ids), Hook.is_active == True).all()  # noqa: E712
        )

    seen: set = set()
    for hook in [*global_hooks, *agent_hooks, *extra_hooks]:
        if hook.id in seen:
            continue
        seen.add(hook.id)

        if hook.handler_type == "python":
            entry = BUILTIN_HOOKS.get(hook.handler_key)
            if entry is None:
                logger.warning("Hook %s references unknown handler_key '%s'; skipping", hook.id, hook.handler_key)
                continue
            manager.add(hook.lifecycle_event, _bind_config(entry["fn"], hook.config))
        else:
            manager.add(hook.lifecycle_event, _bind_custom(hook))

    return manager
