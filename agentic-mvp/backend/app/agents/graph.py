"""Graph assembly — wiring the three agents into a LangGraph StateGraph.

Topology:

                    ┌──────────────┐
                    │  initialize  │
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐◄──────────────┐
                    │   planner    │               │
                    └──────┬───────┘               │
                    (plan ok?)                     │
                     ├── no ──────────────┐        │ replan
                     ▼                    │        │
                ┌──────────┐              │   ┌────┴─────┐
        ┌──────►│ executor │              │   │  replan  │
        │       └────┬─────┘              │   └────▲─────┘
        │       (critic worth running?)   │        │
        │        ├── no ──────────────────┤        │
        │        ▼                        │        │
        │    ┌────────┐                   │        │
        │    │ critic │───────────────────┼────────┘
        │    └───┬────┘   (verdict)       │
        │        ├── accept / escalate ───┤
        │        ▼ revise                 ▼
        │   ┌─────────┐            ┌────────────┐
        └───┤ revise  │            │  finalize  │──► END
            └─────────┘            └────────────┘

Three design points worth stating, because each has a wrong-looking
alternative that seems simpler:

**All roads lead to `finalize`.** No node routes to END directly. Finalize is
where the terminal status is decided, the answer is chosen, and the RUN_END
event fires — a second exit path is a second place to forget one of those.

**`revise` and `replan` are their own nodes, not router side effects.** A
LangGraph router (`add_conditional_edges` path function) must be pure: it
returns a route and cannot write state. Incrementing the revision counter is
a state write, so it needs a node. Doing it inside the executor instead would
mean the executor couldn't tell a first pass from a retry.

**Agents are constructed per graph build, sinks are injected per run.** The
compiled graph is cached (`get_compiled_graph`) because compilation is not
free, so nothing request-scoped may be captured in a closure. The per-request
event sink travels through `config["configurable"]["event_sink"]` and is
picked up by `BaseAgent._resolve_sink`.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

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
from langgraph.graph import END, START, StateGraph

from app.agents.base import AgentRole, BaseAgent
from app.agents.config import AgentRuntimeConfig
from app.agents.critic import CriticAgent
from app.agents.lifecycle import EventSink, EventType, LifecycleEvent, NullEventSink
from app.agents.llm import LLMProvider
from app.agents.registry import get_agent
from app.agents.state import (
    AgentState,
    RunPhase,
    RunStatus,
    Verdict,
    get_critique,
    get_plan,
    get_status,
    latest_step_results,
    make_transcript_entry,
)
from app.agents.tools import ToolInvoker

logger = logging.getLogger("agentic_mvp.agents.graph")

# Node names. Referenced by the routers and by `interrupt_before`, so they are
# constants rather than repeated string literals — a typo in a route map is
# otherwise a silent dead end.
NODE_INITIALIZE = "initialize"
NODE_PLANNER = AgentRole.PLANNER.value
NODE_EXECUTOR = AgentRole.EXECUTOR.value
NODE_CRITIC = AgentRole.CRITIC.value
NODE_REVISE = "revise"
NODE_REPLAN = "replan"
NODE_FINALIZE = "finalize"


def _sink_from_config(config: Optional[RunnableConfig]) -> EventSink:  # noqa: UP045
    if isinstance(config, dict):
        sink = (config.get("configurable") or {}).get("event_sink")
        if isinstance(sink, EventSink):
            return sink
    return NullEventSink()


async def _emit(
    config: Optional[RunnableConfig],  # noqa: UP045
    state: AgentState,
    event_type: EventType,
    **data: Any,
) -> None:
    await _sink_from_config(config).emit(
        LifecycleEvent(
            type=event_type,
            run_id=str(state.get("run_id") or ""),
            agent_id=state.get("agent_id"),
            agent_name=state.get("agent_name"),
            phase=str(state.get("phase") or ""),
            revision=int(state.get("revision") or 0),
            trace_id=state.get("trace_id"),
            data=data,
        )
    )


# --- Function nodes ---------------------------------------------------------


async def initialize_node(
    state: AgentState,
    config: Optional[RunnableConfig] = None,  # noqa: UP045
) -> dict[str, Any]:
    """Entry node. Stamps the run as started and emits RUN_START.

    A node rather than work done by the caller, so that a run resumed from a
    checkpoint replays the same entry point and the transcript's first line
    is always the same shape.
    """
    await _emit(
        config,
        state,
        EventType.RUN_START,
        objective=state.get("objective"),
        agent_name=state.get("agent_name"),
        language=state.get("language"),
    )
    return {
        "phase": RunPhase.INITIALIZING.value,
        "status": RunStatus.RUNNING.value,
        "transcript": [
            make_transcript_entry(
                state,
                role="system",
                phase=RunPhase.INITIALIZING,
                summary="Run initialized",
                payload={
                    "tools": [t.get("name") for t in state.get("available_tools") or []],
                    "skills": [s.get("name") for s in state.get("available_skills") or []],
                },
            )
        ],
    }


async def revise_node(
    state: AgentState,
    config: Optional[RunnableConfig] = None,  # noqa: UP045
) -> dict[str, Any]:
    """Increment the revision counter before re-entering the executor.

    The counter lives on a `take_max` channel, so this is safe even if the
    node is retried or replayed — it can never move backwards.
    """
    revision = int(state.get("revision") or 0) + 1
    critique = get_critique(state)
    await _emit(
        config,
        state,
        EventType.REVISION_START,
        revision=revision,
        reason=critique.feedback if critique else "",
        target_step_ids=critique.target_step_ids if critique else [],
    )
    return {
        "phase": RunPhase.REVISING.value,
        "revision": revision,
        "transcript": [
            make_transcript_entry(
                state,
                role="system",
                phase=RunPhase.REVISING,
                summary=f"Starting revision {revision}",
                payload={"targets": critique.target_step_ids if critique else []},
            )
        ],
    }


async def replan_node(
    state: AgentState,
    config: Optional[RunnableConfig] = None,  # noqa: UP045
) -> dict[str, Any]:
    """Send the run back to the planner.

    Bumps `revision` as well as `replan_count`: a replan discards the
    previous plan's results, so those results must not be mistaken for the
    current pass's by `latest_step_results`.
    """
    revision = int(state.get("revision") or 0) + 1
    replan_count = int(state.get("replan_count") or 0) + 1
    critique = get_critique(state)
    await _emit(
        config,
        state,
        EventType.REVISION_START,
        revision=revision,
        replan_count=replan_count,
        reason=critique.feedback if critique else "",
        kind="replan",
    )
    return {
        "phase": RunPhase.REVISING.value,
        "revision": revision,
        "replan_count": replan_count,
        "transcript": [
            make_transcript_entry(
                state,
                role="system",
                phase=RunPhase.REVISING,
                summary=f"Re-planning (attempt {replan_count + 1})",
                payload={"reason": critique.feedback if critique else ""},
            )
        ],
    }


async def finalize_node(
    state: AgentState,
    config: Optional[RunnableConfig] = None,  # noqa: UP045
) -> dict[str, Any]:
    """The single exit. Decides the terminal status and the final answer.

    Status is derived here rather than trusted from upstream, because
    "succeeded" has a precise meaning the Observatory depends on: the critic
    accepted it. A run that ran out of revisions is DEGRADED — there is an
    answer, it just never cleared the bar — and one with no answer at all is
    FAILED. Collapsing those three into "done" makes the acceptance-rate
    metric meaningless.
    """
    status = get_status(state)
    critique = get_critique(state)
    draft = str(state.get("draft_answer") or "")
    answer = str(state.get("final_answer") or "") or draft
    needs_review = bool(state.get("needs_human_review"))

    if status in (RunStatus.HALTED, RunStatus.CANCELLED):
        final_status = status
    elif state.get("error") and not answer:
        final_status = RunStatus.FAILED
    elif critique is not None and critique.verdict == Verdict.ESCALATE:
        final_status = RunStatus.AWAITING_HUMAN
        needs_review = True
    elif critique is not None and critique.verdict == Verdict.ACCEPT:
        # A budget-forced acceptance is not a success. The critic wanted
        # another revision and the run couldn't afford one, so there is an
        # answer that never cleared the bar — which is precisely DEGRADED.
        # Reporting it as SUCCEEDED would make the acceptance-rate metric
        # measure budget exhaustion instead of quality.
        final_status = RunStatus.DEGRADED if critique.budget_forced else RunStatus.SUCCEEDED
    elif critique is None:
        # The critic was skipped by the risk gate — not a quality failure,
        # so this is a success, not a degradation.
        final_status = RunStatus.SUCCEEDED if answer else RunStatus.FAILED
    else:
        final_status = RunStatus.DEGRADED

    if not answer:
        error = state.get("error") or {}
        answer = (
            "This request could not be completed: "
            f"{error.get('message', 'the agent produced no answer.')}"
        )

    results = latest_step_results(state)
    plan = get_plan(state)

    await _emit(
        config,
        state,
        EventType.RUN_END,
        status=final_status.value,
        revision=int(state.get("revision") or 0),
        needs_human_review=needs_review,
        step_count=len(results),
    )
    if needs_review:
        await _emit(
            config,
            state,
            EventType.HUMAN_REVIEW_REQUIRED,
            reason=critique.feedback if critique else "",
        )

    return {
        "phase": RunPhase.DONE.value,
        "status": final_status.value,
        "final_answer": answer,
        "needs_human_review": needs_review,
        "transcript": [
            make_transcript_entry(
                state,
                role="system",
                phase=RunPhase.FINALIZING,
                summary=f"Run finished: {final_status.value}",
                payload={
                    "revisions": int(state.get("revision") or 0),
                    "replans": int(state.get("replan_count") or 0),
                    "plan_steps": len(plan.steps) if plan else 0,
                    "answer_chars": len(answer),
                },
            )
        ],
    }


# --- Routers ----------------------------------------------------------------
#
# Routers are pure: they read state and return a node name. They never write.
# Each returns one of the keys in its own route map so a new branch is a
# compile-time addition in two adjacent places rather than a silent fallthrough.


def route_after_plan(state: AgentState) -> str:
    if _is_terminal(state) or get_plan(state) is None:
        return NODE_FINALIZE
    return NODE_EXECUTOR


def make_route_after_execute(critic: CriticAgent) -> Any:
    """Router closed over the critic instance so the risk gate
    (`CriticAgent.should_run`) is evaluated by the critic itself rather than
    reimplemented here — one definition of "is this worth reviewing"."""

    def route_after_execute(state: AgentState) -> str:
        if _is_terminal(state):
            return NODE_FINALIZE
        if not str(state.get("draft_answer") or "").strip():
            # Nothing to review. Finalize will classify this as FAILED.
            return NODE_FINALIZE
        return NODE_CRITIC if critic.should_run(state) else NODE_FINALIZE

    return route_after_execute


def route_after_critique(state: AgentState) -> str:
    """Map the critic's verdict onto a node.

    Budgets are *not* re-checked here — the critic already downgraded any
    verdict it couldn't afford (see `CriticAgent._apply_budgets`). Checking
    in both places is how a loop ends up off by one.
    """
    if _is_terminal(state):
        return NODE_FINALIZE
    critique = get_critique(state)
    if critique is None:
        return NODE_FINALIZE
    if critique.verdict == Verdict.REVISE:
        return NODE_REVISE
    if critique.verdict == Verdict.REPLAN:
        return NODE_REPLAN
    # accept | escalate
    return NODE_FINALIZE


def _is_terminal(state: AgentState) -> bool:
    return get_status(state) in {RunStatus.FAILED, RunStatus.HALTED, RunStatus.CANCELLED}


# --- Assembly ---------------------------------------------------------------


def build_agents(
    *,
    llm: LLMProvider,
    config: AgentRuntimeConfig,
    tool_invoker: ToolInvoker | None = None,
) -> dict[AgentRole, BaseAgent]:
    """Instantiate one agent per registered role.

    Reads the registry rather than importing the three classes, so a
    deployment that replaced a role via `@register_agent(..., replace=True)`
    gets its own class here with no change to this function.
    """
    agents: dict[AgentRole, BaseAgent] = {}
    for role in AgentRole:
        cls = get_agent(role)
        agents[role] = cls(llm=llm, config=config, tool_invoker=tool_invoker)
    return agents


def build_graph(
    *,
    llm: LLMProvider,
    config: AgentRuntimeConfig,
    tool_invoker: ToolInvoker | None = None,
) -> StateGraph:
    """Build the uncompiled graph. Split from `compile_graph` so tests can
    inspect the topology without needing a checkpointer."""
    agents = build_agents(llm=llm, config=config, tool_invoker=tool_invoker)
    critic = agents[AgentRole.CRITIC]
    assert isinstance(critic, CriticAgent)

    graph: StateGraph = StateGraph(AgentState)

    graph.add_node(NODE_INITIALIZE, initialize_node)
    graph.add_node(NODE_PLANNER, agents[AgentRole.PLANNER])
    graph.add_node(NODE_EXECUTOR, agents[AgentRole.EXECUTOR])
    graph.add_node(NODE_CRITIC, critic)
    graph.add_node(NODE_REVISE, revise_node)
    graph.add_node(NODE_REPLAN, replan_node)
    graph.add_node(NODE_FINALIZE, finalize_node)

    graph.add_edge(START, NODE_INITIALIZE)
    graph.add_edge(NODE_INITIALIZE, NODE_PLANNER)

    graph.add_conditional_edges(
        NODE_PLANNER,
        route_after_plan,
        {NODE_EXECUTOR: NODE_EXECUTOR, NODE_FINALIZE: NODE_FINALIZE},
    )
    graph.add_conditional_edges(
        NODE_EXECUTOR,
        make_route_after_execute(critic),
        {NODE_CRITIC: NODE_CRITIC, NODE_FINALIZE: NODE_FINALIZE},
    )
    graph.add_conditional_edges(
        NODE_CRITIC,
        route_after_critique,
        {
            NODE_REVISE: NODE_REVISE,
            NODE_REPLAN: NODE_REPLAN,
            NODE_FINALIZE: NODE_FINALIZE,
        },
    )

    graph.add_edge(NODE_REVISE, NODE_EXECUTOR)
    graph.add_edge(NODE_REPLAN, NODE_PLANNER)
    graph.add_edge(NODE_FINALIZE, END)

    return graph


async def compile_graph(
    *,
    llm: LLMProvider,
    config: AgentRuntimeConfig,
    tool_invoker: ToolInvoker | None = None,
    checkpointer: Any = None,
    interrupt_before: list[str] | None = None,
) -> Any:
    """Compile the graph with a checkpointer.

    `interrupt_before` is how human-in-the-loop is expressed: pass
    `[NODE_EXECUTOR]` and the run checkpoints and stops before executing,
    to be resumed later with the same `thread_id`. It needs a durable
    checkpointer to be useful, which is why the two are configured together.
    """
    if checkpointer is None:
        from app.agents.checkpointer import get_checkpointer

        checkpointer = await get_checkpointer()

    graph = build_graph(llm=llm, config=config, tool_invoker=tool_invoker)
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_before or None,
        name="planner-executor-critic",
    )
