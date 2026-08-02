"""`AgentRuntime` — the one public entry point into the agent stack.

Callers (the chat SSE adapter, the Temporal activities, a future /runs API)
construct an `AgentRunRequest` and get back either a final `AgentRunResult`
or an async stream of `LifecycleEvent`s. Nothing outside this package should
touch `graph.py`, `state.py`, or the agent classes directly.

**How streaming works, and why it isn't LangGraph's streaming.** LangGraph
streams at node granularity — you learn the executor finished, not what it
said as it said it. Token-level output needs the nodes to push, so the
runtime creates an `asyncio.Queue`, wraps it in a `QueueEventSink`, hands
that to the graph through `config["configurable"]["event_sink"]`, and runs
the graph as a background task while draining the queue. The sentinel-on-
completion pattern below is what keeps the drain loop from either hanging
after the graph finishes or exiting before the last event is consumed.

**Failure containment.** `stream()` never propagates an exception from the
graph task: it converts it into a terminal `RUN_END` event and returns. By
the time streaming starts the caller has already committed to an SSE
response, so raising would leave a half-written stream with no explanation
in it.

**Capability snapshotting.** `AgentRunRequest.from_agent` flattens the
Agent's tool/skill relationships into plain dicts at construction time.
That happens on the caller's synchronous request thread deliberately — the
graph runs concurrently, and a lazy-loaded relationship touched from a
worker task would issue a query against a Session another task is using.
The existing chat route already eager-loads for exactly this reason.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents.config import AgentRuntimeConfig
from app.agents.graph import compile_graph
from app.agents.lifecycle import (
    CompositeEventSink,
    EventSink,
    EventType,
    LifecycleEvent,
    NullEventSink,
    QueueEventSink,
)
from app.agents.llm import LLMProvider, get_llm_provider
from app.agents.state import (
    AgentState,
    RunPhase,
    RunStatus,
    get_critique,
    get_plan,
    new_state,
)
from app.agents.tools import SkillSpec, ToolSpec, build_tool_invoker

logger = logging.getLogger("agentic_mvp.agents.runtime")

#: Pushed onto the queue when the graph task finishes, so the drain loop
#: knows to stop. A dedicated object rather than None, because None is a
#: plausible value to put on a queue by mistake and would end the stream early.
_DONE = object()


class AgentRunRequest(BaseModel):
    """Everything needed to run a turn, fully detached from the ORM."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    objective: str
    agent_id: str
    agent_name: str
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    system_prompt: str | None = None
    model_name: str = "default"
    language: str = "en"

    tenant_id: str | None = None
    project_id: str | None = None
    conversation_id: str | None = None
    user_id: str | None = None

    tools: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    context_documents: list[dict[str, Any]] = Field(default_factory=list)

    config: AgentRuntimeConfig = Field(default_factory=AgentRuntimeConfig)

    #: LangGraph checkpoint thread. Defaults to the run id; pass a stable
    #: value to resume an interrupted run.
    thread_id: str | None = None

    @classmethod
    def from_agent(
        cls,
        agent: Any,
        *,
        objective: str,
        language: str = "en",
        context_documents: list[dict[str, Any]] | None = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        config_overrides: dict[str, Any] | None = None,
        run_id: str | None = None,
        trace_id: str | None = None,
    ) -> AgentRunRequest:
        """Snapshot an `Agent` ORM row into a request.

        Must be called on the thread that owns the Session — see the module
        docstring on capability snapshotting.
        """
        tools = [
            ToolSpec(
                name=t.name,
                description=t.description,
                tool_type=getattr(t, "tool_type", "function"),
                input_schema=getattr(t, "input_schema", None),
                config=getattr(t, "config", None) or {},
                timeout_s=int(getattr(t, "timeout_s", 15) or 15),
                annotations=getattr(t, "annotations", None) or {},
            ).model_dump()
            for t in (agent.tools or [])
        ]
        skills = [
            SkillSpec(
                name=s.name,
                description=s.description,
                body_markdown=getattr(s, "body_markdown", "") or "",
                allowed_tools=getattr(s, "allowed_tools", None),
            ).model_dump()
            for s in (agent.skills or [])
        ]
        return cls(
            objective=objective,
            agent_id=str(agent.id),
            agent_name=agent.name,
            run_id=run_id or str(uuid.uuid4()),
            trace_id=trace_id or str(uuid.uuid4()),
            system_prompt=agent.system_prompt,
            model_name=getattr(agent, "model_name", "default") or "default",
            language=language,
            tenant_id=str(agent.tenant_id) if getattr(agent, "tenant_id", None) else None,
            project_id=project_id,
            conversation_id=conversation_id,
            user_id=user_id,
            tools=tools,
            skills=skills,
            context_documents=context_documents or [],
            config=AgentRuntimeConfig.from_agent(agent, config_overrides),
        )

    def to_state(self) -> AgentState:
        state = new_state(
            run_id=self.run_id,
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            objective=self.objective,
            trace_id=self.trace_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            language=self.language,
            system_prompt=self.system_prompt,
            available_tools=self.tools,
            available_skills=self.skills,
            context_documents=self.context_documents,
        )
        # The model route travels in the scratchpad rather than as a channel
        # of its own: it is an execution detail every node reads and none
        # writes, and adding a channel per such detail bloats every checkpoint.
        state["scratchpad"] = {"model_route": self.model_name}
        return state


class AgentRunResult(BaseModel):
    """The finished run, flattened for callers who don't want the raw state."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    status: RunStatus
    phase: RunPhase
    final_answer: str
    revisions: int = 0
    replans: int = 0
    plan_step_count: int = 0
    critic_verdict: str | None = None
    critic_score: float | None = None
    needs_human_review: bool = False
    error: dict[str, Any] | None = None
    token_usage: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    #: The full terminal state, for callers that need more than the summary.
    state: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_state(cls, state: AgentState, *, duration_ms: int) -> AgentRunResult:
        plan = get_plan(state)
        critique = get_critique(state)
        return cls(
            run_id=str(state.get("run_id") or ""),
            status=RunStatus(state.get("status") or RunStatus.FAILED.value),
            phase=RunPhase(state.get("phase") or RunPhase.DONE.value),
            final_answer=str(state.get("final_answer") or state.get("draft_answer") or ""),
            revisions=int(state.get("revision") or 0),
            replans=int(state.get("replan_count") or 0),
            plan_step_count=len(plan.steps) if plan else 0,
            critic_verdict=critique.verdict.value if critique else None,
            critic_score=critique.score if critique else None,
            needs_human_review=bool(state.get("needs_human_review")),
            error=state.get("error"),
            token_usage=dict(state.get("token_usage") or {}),
            duration_ms=duration_ms,
            transcript=list(state.get("transcript") or []),
            state=dict(state),
        )


class AgentRuntime:
    """Orchestrates one run of the Planner → Executor → Critic graph."""

    def __init__(
        self,
        *,
        llm: LLMProvider | None = None,
        checkpointer: Any = None,
    ) -> None:
        self._llm = llm
        self._checkpointer = checkpointer

    def _provider(self) -> LLMProvider:
        return self._llm or get_llm_provider()

    async def _compiled(self, request: AgentRunRequest) -> Any:
        """Compile a graph for this request's config.

        Not cached across requests: `AgentRuntimeConfig` is per-agent and is
        baked into the agent instances (budgets, timeouts, whether tools may
        execute), so a shared compiled graph would silently apply one agent's
        budgets to another's run. Compilation is cheap relative to a single
        model round-trip; correctness wins here.
        """
        return await compile_graph(
            llm=self._provider(),
            config=request.config,
            tool_invoker=build_tool_invoker(execute_tools=request.config.execute_tools),
            checkpointer=self._checkpointer,
        )

    def _graph_config(self, request: AgentRunRequest, sink: EventSink) -> dict[str, Any]:
        return {
            "configurable": {
                "thread_id": request.thread_id or request.run_id,
                "event_sink": sink,
            },
            "recursion_limit": request.config.effective_recursion_limit(),
        }

    # --- non-streaming ------------------------------------------------------

    async def run(
        self,
        request: AgentRunRequest,
        *,
        sink: EventSink | None = None,
    ) -> AgentRunResult:
        """Execute a run to completion.

        Used by the Temporal activity path and by any caller that wants the
        answer rather than the stream. Enforces the whole-run timeout, which
        `stream()` cannot (a stream's caller controls consumption pace).
        """
        started = time.monotonic()
        sink = sink or NullEventSink()
        graph = await self._compiled(request)
        try:
            final_state = await asyncio.wait_for(
                graph.ainvoke(request.to_state(), config=self._graph_config(request, sink)),
                timeout=request.config.run_timeout_s,
            )
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning(
                "Run %s exceeded its %ss budget",
                request.run_id,
                request.config.run_timeout_s,
            )
            return self._timeout_result(request, started)
        return AgentRunResult.from_state(
            final_state, duration_ms=int((time.monotonic() - started) * 1000)
        )

    # --- streaming ----------------------------------------------------------

    async def stream(
        self,
        request: AgentRunRequest,
        *,
        extra_sink: EventSink | None = None,
    ) -> AsyncIterator[LifecycleEvent]:
        """Yield lifecycle events as the run progresses, ending with RUN_END.

        `extra_sink` is fanned in alongside the internal queue — that's how
        the persistence sink writes step rows while the same events are being
        streamed to the browser, with neither knowing about the other.
        """
        queue: asyncio.Queue = asyncio.Queue()
        sink: EventSink = QueueEventSink(queue)
        if extra_sink is not None:
            sink = CompositeEventSink(sink, extra_sink)

        started = time.monotonic()
        graph = await self._compiled(request)
        result_holder: dict[str, Any] = {}

        async def _drive() -> None:
            try:
                result_holder["state"] = await graph.ainvoke(
                    request.to_state(), config=self._graph_config(request, sink)
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — becomes a terminal event
                logger.exception("Agent run %s failed", request.run_id)
                result_holder["error"] = exc
            finally:
                await queue.put(_DONE)

        task = asyncio.create_task(_drive())

        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                if isinstance(item, LifecycleEvent):
                    yield item
        finally:
            # Covers the generator being closed early (client disconnect):
            # without this the graph task would keep burning tokens for a
            # response nobody is reading.
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        error = result_holder.get("error")
        if error is not None:
            yield LifecycleEvent(
                type=EventType.RUN_END,
                run_id=request.run_id,
                agent_id=request.agent_id,
                agent_name=request.agent_name,
                trace_id=request.trace_id,
                phase=RunPhase.DONE.value,
                data={
                    "status": RunStatus.FAILED.value,
                    "error": {"error_type": type(error).__name__, "message": str(error)},
                    "final_answer": (
                        "This request could not be completed because the agent runtime "
                        "encountered an unexpected error."
                    ),
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )
            return

        # The graph's own finalize_node already emitted RUN_END with the
        # status; this final event carries the assembled result so the caller
        # doesn't have to reconstruct it from the state dict.
        state = result_holder.get("state")
        if state is not None:
            result = AgentRunResult.from_state(
                state, duration_ms=int((time.monotonic() - started) * 1000)
            )
            self._last_result = result
            yield LifecycleEvent(
                type=EventType.RUN_END,
                run_id=request.run_id,
                agent_id=request.agent_id,
                agent_name=request.agent_name,
                trace_id=request.trace_id,
                phase=result.phase.value,
                revision=result.revisions,
                data={
                    "status": result.status.value,
                    "final_answer": result.final_answer,
                    "critic_verdict": result.critic_verdict,
                    "critic_score": result.critic_score,
                    "needs_human_review": result.needs_human_review,
                    "token_usage": result.token_usage,
                    "duration_ms": result.duration_ms,
                    "final": True,
                },
            )

    @property
    def last_result(self) -> AgentRunResult | None:
        """The result of the most recent `stream()` call on this instance.

        A runtime instance is created per turn, so this is not shared state
        between requests — it exists because an async generator cannot return
        a value alongside its yields, and the SSE adapter needs the full
        result (token usage, verdict) after the stream ends.
        """
        return getattr(self, "_last_result", None)

    # --- helpers ------------------------------------------------------------

    def _timeout_result(self, request: AgentRunRequest, started: float) -> AgentRunResult:
        state = request.to_state()
        state["status"] = RunStatus.FAILED.value
        state["phase"] = RunPhase.DONE.value
        state["error"] = {
            "error_type": "AgentTimeoutError",
            "message": f"Run exceeded its {request.config.run_timeout_s}s budget",
            "retryable": True,
            "terminal": True,
        }
        state["final_answer"] = (
            "This request took longer than the configured time budget and was stopped."
        )
        return AgentRunResult.from_state(
            state, duration_ms=int((time.monotonic() - started) * 1000)
        )
