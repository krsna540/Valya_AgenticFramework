"""Lifecycle plumbing: event sinks and the cross-cutting node decorators.

Everything here is deliberately framework-neutral — no LangGraph and no
Temporal imports. That is what lets the same decorated `BaseAgent` run
unchanged as a LangGraph node in-process and inside a Temporal activity: the
durability layer swaps underneath without the agents noticing.

**Event sinks.** Nodes never write to a socket. They emit `LifecycleEvent`s
into an `EventSink`, and whoever is driving the run decides what that means
— `QueueEventSink` for the SSE path, `NullEventSink` inside a Temporal
activity replay (where emitting would be a non-deterministic side effect),
`CollectingEventSink` in tests. Emission is best-effort by contract: a sink
that raises is logged and swallowed, because a broken observer must never
fail the run it is observing. Same fault-isolation rule the hook engine uses
(app/services/hooks.py).

**Decorators.** Four, each doing exactly one thing, composed in a fixed
order by `BaseAgent` (see base.py):

    @traced       — timing, trace ids, start/finish events
    @time_bounded — wall-clock ceiling
    @retryable    — backoff retry for errors marked retryable
    @instrumented — the three above, in the one order that is correct

Order matters and is not arbitrary. `retryable` must be *inside*
`time_bounded` so the timeout covers all attempts rather than resetting per
attempt (otherwise 3 attempts × 90s silently becomes a 270s node). `traced`
must be outermost so one span covers the retries and the emitted duration is
the one the caller actually waited.
"""
from __future__ import annotations

import asyncio
import enum
import functools
import inspect
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.agents.errors import AgentRuntimeError, AgentTimeoutError

logger = logging.getLogger("agentic_mvp.agents.lifecycle")

T = TypeVar("T")
AsyncFn = Callable[..., Awaitable[Any]]


# --- Events -----------------------------------------------------------------


class EventType(str, enum.Enum):
    """Lifecycle events. A strict superset of the SSE event names the
    frontend already consumes (`stream_start`, `token`, `tool_call`,
    `skill_call`, `stream_end`) — the extra ones let the Run Observatory
    show phase-level progress without changing the chat contract. The
    adapter in app/services/agent_runner.py maps this vocabulary onto the
    wire vocabulary; nothing here leaks to the browser unmapped.
    """

    RUN_START = "run_start"
    RUN_END = "run_end"
    PHASE_ENTER = "phase_enter"
    PHASE_EXIT = "phase_exit"
    NODE_START = "node_start"
    NODE_END = "node_end"
    NODE_RETRY = "node_retry"
    NODE_ERROR = "node_error"
    PLAYBOOK_SELECTED = "playbook_selected"
    PLAN_READY = "plan_ready"
    STEP_START = "step_start"
    STEP_END = "step_end"
    TOOL_CALL = "tool_call"
    SKILL_CALL = "skill_call"
    TOKEN = "token"
    CRITIQUE_READY = "critique_ready"
    REVISION_START = "revision_start"
    HUMAN_REVIEW_REQUIRED = "human_review_required"


class LifecycleEvent(BaseModel):
    """One observation emitted during a run. Immutable, JSON-safe, and
    carrying enough identity (run/trace/agent) to be correlated after the
    fact without joining against anything."""

    model_config = ConfigDict(frozen=True)

    type: EventType
    run_id: str
    agent_id: str | None = None
    agent_name: str | None = None
    role: str | None = None
    phase: str | None = None
    revision: int = 0
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# --- Sinks ------------------------------------------------------------------


class EventSink(ABC):
    """Where lifecycle events go. Implementations must not raise; the
    `emit()` template below enforces that even if `_write` misbehaves."""

    async def emit(self, event: LifecycleEvent) -> None:
        try:
            await self._write(event)
        except Exception:  # noqa: BLE001 — an observer may never break the run
            logger.exception("Event sink %s failed on %s", type(self).__name__, event.type)

    @abstractmethod
    async def _write(self, event: LifecycleEvent) -> None:
        """Deliver one event. May raise; `emit` isolates it."""


class NullEventSink(EventSink):
    """Discards everything. The default, and the correct sink inside a
    Temporal workflow replay where emitting would be a side effect."""

    async def _write(self, event: LifecycleEvent) -> None:
        return None


class QueueEventSink(EventSink):
    """Feeds an asyncio.Queue that the SSE generator drains concurrently
    with graph execution — the mechanism that makes token-level streaming
    work through a framework (LangGraph) whose own streaming granularity is
    the node, not the token.

    Unbounded on purpose: the consumer is a local generator that always
    drains, and a bounded queue would let a slow HTTP client apply
    backpressure all the way into the reasoning loop.
    """

    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue

    async def _write(self, event: LifecycleEvent) -> None:
        await self._queue.put(event)


class CollectingEventSink(EventSink):
    """In-memory sink for tests and for replaying a run's event stream."""

    def __init__(self) -> None:
        self.events: list[LifecycleEvent] = []

    async def _write(self, event: LifecycleEvent) -> None:
        self.events.append(event)

    def of_type(self, event_type: EventType) -> list[LifecycleEvent]:
        return [e for e in self.events if e.type == event_type]


class CompositeEventSink(EventSink):
    """Fan-out to several sinks (e.g. SSE queue + run-step persistence).
    Each child's own `emit` isolates its failures, so one bad sink cannot
    starve the others."""

    def __init__(self, *sinks: EventSink) -> None:
        self._sinks = [s for s in sinks if s is not None]

    async def _write(self, event: LifecycleEvent) -> None:
        for sink in self._sinks:
            await sink.emit(event)


# --- Execution context ------------------------------------------------------


class NodeContext(BaseModel):
    """Everything a decorator needs to describe the node it wraps, without
    reaching into the node's own state. Passed as a keyword by BaseAgent."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    role: str
    phase: str
    revision: int = 0
    agent_id: str | None = None
    agent_name: str | None = None
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    attempt: int = 1

    def event(self, event_type: EventType, **data: Any) -> LifecycleEvent:
        return LifecycleEvent(
            type=event_type,
            run_id=self.run_id,
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            role=self.role,
            phase=self.phase,
            revision=self.revision,
            trace_id=self.trace_id,
            data=data,
        )


def _resolve(obj: Any, attr: str, default: Any = None) -> Any:
    """Pull a decorator's operating parameters off `self` when the decorated
    function is a method, so budgets stay per-instance (per-run config) rather
    than baked in at import time by the decorator's arguments."""
    value = getattr(obj, attr, None)
    return default if value is None else value


# --- Decorators -------------------------------------------------------------


def traced(func: AsyncFn) -> AsyncFn:
    """Emit NODE_START/NODE_END around the call and record its duration.

    Reads `self._ctx` (a NodeContext) and `self._sink` (an EventSink), both
    set by `BaseAgent.__call__` before dispatch. If either is missing the
    decorator degrades to a plain pass-through rather than raising — a node
    used outside the runtime (a unit test calling `_invoke` directly) should
    still work.
    """

    @functools.wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        ctx: NodeContext | None = _resolve(self, "_ctx")
        sink: EventSink = _resolve(self, "_sink", NullEventSink())
        if ctx is None:
            return await func(self, *args, **kwargs)

        started = time.monotonic()
        await sink.emit(ctx.event(EventType.NODE_START))
        try:
            result = await func(self, *args, **kwargs)
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            await sink.emit(
                ctx.event(
                    EventType.NODE_ERROR,
                    duration_ms=duration_ms,
                    **(
                        exc.as_dict()
                        if isinstance(exc, AgentRuntimeError)
                        else {"error_type": type(exc).__name__, "message": str(exc)}
                    ),
                )
            )
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        await sink.emit(ctx.event(EventType.NODE_END, duration_ms=duration_ms))
        # Surfaced to the caller for the run-step record; the decorator owns
        # the measurement so no node has to remember to take a timestamp.
        self._last_duration_ms = duration_ms
        return result

    return wrapper


def time_bounded(func: AsyncFn) -> AsyncFn:
    """Enforce `self.config.node_timeout_s` over the whole call, retries
    included. Converts a timeout into the runtime's own AgentTimeoutError so
    callers have one exception taxonomy to match on.

    The except clause names *both* `asyncio.TimeoutError` and the builtin
    `TimeoutError` on purpose. They are the same class from 3.11 on, but
    distinct classes on 3.10 — and this repo deliberately stays runnable on
    3.10 (see the UP017/UP041/UP042 ignores in pyproject.toml). Collapsing
    them to the builtin alone, which is exactly what `ruff --fix` wants to do,
    makes node timeouts escape this handler on 3.10 and surface as an
    unhandled TimeoutError instead of a typed AgentTimeoutError.
    """

    @functools.wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        config = _resolve(self, "config")
        timeout = getattr(config, "node_timeout_s", None) if config else None
        if not timeout:
            return await func(self, *args, **kwargs)
        try:
            return await asyncio.wait_for(func(self, *args, **kwargs), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            role = _resolve(self, "role", "agent")
            raise AgentTimeoutError(
                f"{role} exceeded its {timeout}s budget",
                role=str(role),
                timeout_s=timeout,
            ) from exc

    return wrapper


def retryable(func: AsyncFn) -> AsyncFn:
    """Retry with exponential backoff, but only for errors that say they are
    retryable.

    An `AgentRuntimeError` carries its own `retryable` flag (see errors.py),
    so a PlanValidationError retries and a BudgetExceededError doesn't. An
    unexpected non-runtime exception is treated as retryable-once-removed:
    retried, because most are transient I/O, but never masked — the last one
    is re-raised with the attempt count attached.
    """

    @functools.wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        config = _resolve(self, "config")
        max_attempts = int(getattr(config, "max_attempts_per_node", 1) or 1) if config else 1
        backoff = float(getattr(config, "retry_backoff_s", 0.5) or 0.5) if config else 0.5
        multiplier = (
            float(getattr(config, "retry_backoff_multiplier", 2.0) or 2.0) if config else 2.0
        )
        ctx: NodeContext | None = _resolve(self, "_ctx")
        sink: EventSink = _resolve(self, "_sink", NullEventSink())

        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            if ctx is not None:
                ctx = ctx.model_copy(update={"attempt": attempt})
                self._ctx = ctx
            try:
                return await func(self, *args, **kwargs)
            except AgentRuntimeError as exc:
                last_exc = exc
                if not exc.retryable or attempt >= max_attempts:
                    raise
            except asyncio.CancelledError:
                # Cooperative cancellation is not a failure — never retry it.
                raise
            except Exception as exc:  # noqa: BLE001 — retried, not swallowed
                last_exc = exc
                if attempt >= max_attempts:
                    raise

            delay = backoff * (multiplier ** (attempt - 1))
            if ctx is not None:
                await sink.emit(
                    ctx.event(
                        EventType.NODE_RETRY,
                        attempt=attempt,
                        max_attempts=max_attempts,
                        delay_s=round(delay, 3),
                        reason=str(last_exc),
                    )
                )
            logger.warning(
                "Retrying %s attempt %d/%d after %.2fs: %s",
                getattr(self, "role", func.__name__),
                attempt,
                max_attempts,
                delay,
                last_exc,
            )
            await asyncio.sleep(delay)

        # Unreachable: the loop either returns or re-raises on the final
        # attempt. Kept so a future edit to the loop can't silently return None.
        raise last_exc if last_exc else RuntimeError(
            "retryable() exited without a result"
        )

    return wrapper


def instrumented(func: AsyncFn) -> AsyncFn:
    """The standard node decorator stack, applied in the only correct order.

    Reading outward-in: `traced(time_bounded(retryable(f)))`. One span covers
    everything, the timeout covers all attempts, and the retries sit
    innermost where they belong. Use this rather than stacking the three by
    hand — the ordering is load-bearing and easy to get subtly wrong.
    """
    if not inspect.iscoroutinefunction(func):
        raise TypeError(f"@instrumented requires an async function, got {func!r}")
    return traced(time_bounded(retryable(func)))
