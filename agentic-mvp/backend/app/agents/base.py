"""`BaseAgent` — the abstract contract every role in the graph implements.

This is a template-method class, not a marker interface. `__call__` owns the
entire node lifecycle and is deliberately `final`-by-convention; subclasses
implement `_invoke` and, optionally, three hook points. The point of putting
the lifecycle here rather than in each role is that the guarantees below then
hold for *every* agent, including ones added later, without anyone
re-deriving them:

    guard      → a node in a terminal run is a no-op, not a second answer
    validate   → bad input fails as a typed error before any model call
    enter      → PHASE_ENTER emitted, phase transition validated
    invoke     → @instrumented: traced, time-bounded, retried
    exit       → PHASE_EXIT + transcript entry appended
    isolate    → the node never raises; failures become state, not stack traces

**Why "never raises" is the right default here.** A LangGraph node that
raises aborts the whole graph run, which throws away the checkpoint, the
partial answer, and the audit trail — and the caller (an SSE generator
mid-stream) has no good way to recover. Converting a failure into
`state["error"] + status` instead lets the router send the run to `finalize`,
which persists what happened and returns a usable response. The same
zero-crash reasoning this codebase already applies to Skills and to the hook
engine's fault boundary.

The one exception is `asyncio.CancelledError`, which is cooperative
cancellation rather than a failure and must propagate untouched.
"""
from __future__ import annotations

import enum
import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Optional

# LangGraph decides whether to inject the runnable config by matching this
# parameter's *raw* annotation against a fixed allowlist
# (langgraph._internal._runnable.KWARGS_CONFIG_KEYS): the RunnableConfig type
# itself, the literal strings "RunnableConfig" / "Optional[RunnableConfig]",
# or no annotation at all. Because these modules use
# `from __future__ import annotations`, every annotation is a *string* at
# runtime — so `RunnableConfig | None` stringifies to "RunnableConfig | None",
# which is not on that list, and LangGraph silently skips injection. The node
# still runs, but never sees the per-request event sink, so streaming goes
# quiet with no error anywhere. Hence `Optional[...]` rather than the modern
# union syntax, with UP045 suppressed at each use — the same suppression
# LangGraph applies to its own allowlist entry.
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field

from app.agents.config import AgentRuntimeConfig
from app.agents.errors import AgentRuntimeError, RunHaltedError
from app.agents.lifecycle import (
    EventSink,
    EventType,
    NodeContext,
    NullEventSink,
    instrumented,
)
from app.agents.llm import LLMProvider
from app.agents.state import (
    AgentState,
    RunPhase,
    RunStatus,
    get_phase,
    get_status,
    make_transcript_entry,
    transition,
)
from app.agents.tools import ToolInvoker
from app.agents.tracing import set_span_attributes, set_span_outputs, traced_span

logger = logging.getLogger("agentic_mvp.agents")


class AgentRole(str, enum.Enum):
    """The roles the graph knows about. Adding a member here plus a
    `@register_agent`-decorated class is all it takes to add a fourth role;
    the graph builder reads the registry, not a hardcoded list."""

    PLANNER = "planner"
    EXECUTOR = "executor"
    CRITIC = "critic"


class AgentOutcome(BaseModel):
    """What an agent returns. Deliberately *not* a full state — nodes emit
    partial updates so LangGraph's reducers can merge them, and returning a
    whole state would clobber concurrent writers' channels."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    #: Partial state update, merged by the channel reducers in state.py.
    updates: dict[str, Any] = Field(default_factory=dict)
    #: One-line summary for the transcript.
    summary: str = ""
    #: Structured detail for the transcript entry.
    payload: dict[str, Any] = Field(default_factory=dict)
    #: Phase to move to. None keeps the agent's own phase.
    next_phase: RunPhase | None = None


class BaseAgent(ABC):
    """Abstract base for a node in the Planner→Executor→Critic graph."""

    # --- class-level contract (subclasses must set both) --------------------
    role: ClassVar[AgentRole]
    #: The RunPhase this agent occupies while running.
    phase: ClassVar[RunPhase]
    #: Node name in the graph. Defaults to the role's value.
    node_name: ClassVar[str] = ""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        config: AgentRuntimeConfig,
        sink: EventSink | None = None,
        tool_invoker: ToolInvoker | None = None,
    ) -> None:
        self.llm = llm
        self.config = config
        self.tool_invoker = tool_invoker
        # Read by the lifecycle decorators; rebound per call in __call__.
        self._sink: EventSink = sink or NullEventSink()
        self._ctx: NodeContext | None = None
        self._last_duration_ms: int = 0

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Fail at import time, not at run time, if a subclass forgets its
        class-level contract. A node missing `role`/`phase` would otherwise
        only blow up on the first request that reaches it."""
        super().__init_subclass__(**kwargs)
        if ABC in cls.__bases__:
            return
        for attr in ("role", "phase"):
            if getattr(cls, attr, None) is None:
                raise TypeError(f"{cls.__name__} must define a class-level `{attr}`")
        if not cls.node_name:
            cls.node_name = cls.role.value

    # --- the node entry point ----------------------------------------------

    async def __call__(
        self, state: AgentState, config: Optional[RunnableConfig] = None  # noqa: UP045
    ) -> dict[str, Any]:
        """LangGraph node signature. Returns a partial state update.

        `config` **must** be annotated as `RunnableConfig | None`, not `Any`:
        LangGraph inspects the annotation to decide whether to inject the
        runnable config, and silently passes None for an unrecognised type.
        That failure mode is invisible — the node runs fine and simply never
        sees the per-request event sink, so streaming goes quiet with no
        error anywhere.

        Never raises except on cancellation — see the module docstring.
        """
        ctx = self._build_context(state)
        self._ctx = ctx
        self._sink = self._resolve_sink(config)

        # 1. Guard — a run that already reached a terminal status must not do
        #    more work. This is what makes a halted or failed run stop at the
        #    first node instead of racing to the end of the graph.
        if get_status(state) in {
            RunStatus.FAILED,
            RunStatus.HALTED,
            RunStatus.CANCELLED,
        }:
            logger.debug(
                "%s skipped: run %s already terminal", self.role.value, state.get("run_id")
            )
            return {}

        try:
            # 2. Validate — typed failure before any model call is made.
            self.validate_input(state)

            # 3. Enter — validated transition, then the phase event.
            next_phase = transition(get_phase(state), self.phase)
            await self._sink.emit(ctx.event(EventType.PHASE_ENTER, phase=next_phase.value))
            await self.on_start(state)

            # 4. Invoke — instrumented (traced / time-bounded / retried).
            outcome = await self._invoke_instrumented(state)

            # 5. Exit.
            await self.on_success(state, outcome)
            await self._sink.emit(
                ctx.event(EventType.PHASE_EXIT, phase=self.phase.value, summary=outcome.summary)
            )
            return self._merge_outcome(state, outcome)

        except RunHaltedError as halt:
            # A guardrail denial is an expected outcome, not a fault: record
            # it as the run's disposition and let the router finalize.
            await self.on_error(state, halt)
            return {
                "phase": RunPhase.FINALIZING.value,
                "status": RunStatus.HALTED.value,
                "final_answer": halt.fallback_message,
                "error": halt.as_dict(),
                "transcript": [
                    make_transcript_entry(
                        state,
                        role=self.role.value,
                        phase=self.phase,
                        summary=f"Run halted by policy at {halt.stage or self.role.value}",
                        payload=halt.as_dict(),
                    )
                ],
            }

        except AgentRuntimeError as exc:
            await self.on_error(state, exc)
            return self._failure_update(state, exc, terminal=exc.terminal)

        except Exception as exc:  # noqa: BLE001 — the node fault boundary
            logger.exception("Unhandled error in %s node", self.role.value)
            await self.on_error(state, exc)
            wrapped = AgentRuntimeError(f"{self.role.value} failed: {exc}")
            return self._failure_update(state, wrapped, terminal=True)

        finally:
            await self.on_finish(state)

    @instrumented
    async def _invoke_instrumented(self, state: AgentState) -> AgentOutcome:
        """Thin seam that carries the decorator stack. Kept separate from
        `_invoke` so a subclass overriding `_invoke` can't accidentally drop
        the instrumentation by forgetting to re-apply the decorator.

        Also where the MLflow AGENT span is opened — one per node execution,
        nested under the run's root span (see runtime.py) via MLflow's own
        contextvar propagation, so a single trace tree shows exactly what
        `@instrumented`'s NODE_START/NODE_END events show the SSE stream,
        just persisted and queryable in the MLflow UI instead of ephemeral.
        Opened here rather than by `@instrumented` itself so it wraps only
        the real work — retries each get their own span via the LLM calls
        inside `_invoke`, not a fresh AGENT span per attempt.
        """
        ctx = self._ctx
        with traced_span(
            f"agent.{self.role.value}",
            span_type="AGENT",
            inputs={
                "objective": state.get("objective"),
                "revision": ctx.revision if ctx else 0,
            },
            attributes={
                "agent.role": self.role.value,
                "agent.phase": self.phase.value,
                "agent.run_id": ctx.run_id if ctx else "",
                "agent.agent_id": ctx.agent_id or "" if ctx else "",
                "agent.agent_name": ctx.agent_name or "" if ctx else "",
                "agent.revision": ctx.revision if ctx else 0,
            },
        ) as span:
            outcome = await self._invoke(state)
            set_span_outputs(
                span, {"summary": outcome.summary, "next_phase": (outcome.next_phase or self.phase).value}
            )
            set_span_attributes(span, {"agent.payload_keys": list(outcome.payload.keys())})
            return outcome

    # --- subclass contract --------------------------------------------------

    @abstractmethod
    async def _invoke(self, state: AgentState) -> AgentOutcome:
        """Do the role's actual work. Raise `AgentRuntimeError` subclasses
        for expected failures; `__call__` converts them into state."""

    def validate_input(self, state: AgentState) -> None:
        """Reject a state this agent can't operate on. Default: require an
        objective, which every role needs. Override to add preconditions —
        the executor requires a plan, the critic requires a draft."""
        if not (state.get("objective") or "").strip():
            raise AgentRuntimeError("Run has no objective", role=self.role.value)

    # The four hooks below are deliberately concrete no-ops, not @abstractmethod
    # (hence the B027 suppressions): they are *optional* extension points, and
    # forcing every role to implement four empty methods to satisfy the ABC
    # would be pure ceremony. `_invoke` is the one genuinely abstract member.

    async def on_start(self, state: AgentState) -> None:  # noqa: B027
        """Called after validation, before invocation. Override for setup."""

    async def on_success(  # noqa: B027
        self, state: AgentState, outcome: AgentOutcome
    ) -> None:
        """Called after a successful invocation."""

    async def on_error(self, state: AgentState, error: Exception) -> None:  # noqa: B027
        """Called on any failure. Must not raise — a failing error handler
        would mask the original error, which is the worst possible outcome
        for whoever is debugging it later."""

    async def on_finish(self, state: AgentState) -> None:  # noqa: B027
        """Always called, success or failure. Release per-call resources."""

    # --- internals ----------------------------------------------------------

    def _build_context(self, state: AgentState) -> NodeContext:
        return NodeContext(
            run_id=str(state.get("run_id") or ""),
            role=self.role.value,
            phase=self.phase.value,
            revision=int(state.get("revision") or 0),
            agent_id=state.get("agent_id"),
            agent_name=state.get("agent_name"),
            trace_id=str(state.get("trace_id") or ""),
        )

    def _resolve_sink(self, config: Optional[RunnableConfig]) -> EventSink:  # noqa: UP045
        """Prefer the sink LangGraph threaded through `config.configurable`
        over the one this instance was constructed with.

        This is what lets a single compiled graph — built once at import and
        shared across requests — stream to a *different* SSE queue per
        request. Binding the sink at construction instead would force a graph
        rebuild per turn, which throws away compilation and any node caching.
        """
        if isinstance(config, dict):
            configurable = config.get("configurable") or {}
            sink = configurable.get("event_sink")
            if isinstance(sink, EventSink):
                return sink
        return self._sink

    def _merge_outcome(self, state: AgentState, outcome: AgentOutcome) -> dict[str, Any]:
        """Turn an AgentOutcome into the partial dict LangGraph expects,
        appending the transcript entry and stamping the phase."""
        updates = dict(outcome.updates)
        target_phase = outcome.next_phase or self.phase
        updates.setdefault("phase", target_phase.value)
        updates["transcript"] = [
            make_transcript_entry(
                state,
                role=self.role.value,
                phase=self.phase,
                summary=outcome.summary or f"{self.role.value} completed",
                payload={**outcome.payload, "duration_ms": self._last_duration_ms},
            )
        ]
        scratch = dict(updates.get("scratchpad") or {})
        scratch[f"{self.role.value}_duration_ms"] = self._last_duration_ms
        updates["scratchpad"] = scratch
        return updates

    def _failure_update(
        self, state: AgentState, exc: AgentRuntimeError, *, terminal: bool
    ) -> dict[str, Any]:
        """Partial update representing "this node failed".

        A terminal failure routes to FINALIZING with status FAILED. A
        non-terminal one leaves the status RUNNING and records the error, so
        the critic/router can decide whether to revise around it — that
        distinction is the whole reason `terminal` exists on the error class.
        """
        update: dict[str, Any] = {
            "error": exc.as_dict(),
            "transcript": [
                make_transcript_entry(
                    state,
                    role=self.role.value,
                    phase=self.phase,
                    summary=f"{self.role.value} failed: {exc.message}",
                    payload=exc.as_dict(),
                )
            ],
        }
        if terminal:
            update["phase"] = RunPhase.FINALIZING.value
            update["status"] = RunStatus.FAILED.value
        else:
            update["phase"] = self.phase.value
        return update
