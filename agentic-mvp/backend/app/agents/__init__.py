"""Planner → Executor → Critic agent runtime.

This package is the real reasoning runtime described in
`docs/agent_runtime_architecture.md` §2 ("LangGraph Runtime (per session)"
sitting inside a "Temporal durable envelope"). It replaces the deterministic
stub that used to live in `app/services/agent_runner.py`; that module is now
a thin streaming adapter over `AgentRuntime` (see its docstring).

Layering — each layer only depends on the ones above it:

    contracts   state.py, errors.py, config.py     pure data, no I/O
    ports       llm.py, tools.py, lifecycle.py     abstract boundaries
    agents      base.py, planner/executor/critic   the three roles
    assembly    registry.py, graph.py              wiring
    orchestration runtime.py                       the public facade
    durability  durable/                           Temporal / in-process

Public surface (everything else is an implementation detail):

    AgentRuntime            — run/stream a turn, the one entry point
    AgentRunRequest         — what a caller asks for
    AgentState / RunPhase   — the state machine
    BaseAgent               — extend this to add a fourth role
    register_agent          — decorator that puts it in the graph
"""

from app.agents.base import AgentOutcome, AgentRole, BaseAgent
from app.agents.config import AgentRuntimeConfig
from app.agents.errors import (
    AgentRuntimeError,
    AgentTimeoutError,
    PlanValidationError,
    ProviderError,
)
from app.agents.lifecycle import EventSink, LifecycleEvent, NullEventSink, QueueEventSink
from app.agents.registry import get_agent, list_agents, register_agent
from app.agents.runtime import AgentRunRequest, AgentRuntime
from app.agents.state import (
    AgentState,
    Critique,
    Plan,
    PlanStep,
    RunPhase,
    RunStatus,
    StepStatus,
    Verdict,
    new_state,
)

__all__ = [
    "AgentOutcome",
    "AgentRole",
    "AgentRunRequest",
    "AgentRuntime",
    "AgentRuntimeConfig",
    "AgentRuntimeError",
    "AgentState",
    "AgentTimeoutError",
    "BaseAgent",
    "Critique",
    "EventSink",
    "LifecycleEvent",
    "NullEventSink",
    "Plan",
    "PlanStep",
    "PlanValidationError",
    "ProviderError",
    "QueueEventSink",
    "RunPhase",
    "RunStatus",
    "StepStatus",
    "Verdict",
    "get_agent",
    "list_agents",
    "new_state",
    "register_agent",
]
