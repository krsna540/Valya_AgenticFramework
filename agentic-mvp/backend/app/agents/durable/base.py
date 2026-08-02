"""The `DurableRunner` port.

Deliberately narrow: three operations, all expressed in terms of
`AgentRunRequest` / `AgentRunResult`, with no Temporal or LangGraph types in
the signatures. That is what lets `app/services/agent_runner.py` be written
once against this interface and work identically whether the run executes
in-process or inside a workflow.

**Streaming is part of the port, not bolted on.** A durability adapter that
can't stream would force callers into an `isinstance` check, so `stream()` is
required — the Temporal adapter satisfies it by relaying the worker's events
back rather than by pretending streaming is unavailable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from pydantic import BaseModel, ConfigDict

from app.agents.lifecycle import EventSink, LifecycleEvent
from app.agents.runtime import AgentRunRequest, AgentRunResult


class RunHandle(BaseModel):
    """A reference to a started run, for callers that don't await it inline.

    `workflow_id` is None for a local run — which is exactly the signal the
    Observatory uses to show which execution path a run took.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    workflow_id: str | None = None
    run_reference: str | None = None
    durable: bool = False


class DurableRunner(ABC):
    """Where and how an agent run executes."""

    #: Identifier recorded on the run row.
    name: str = "abstract"

    @abstractmethod
    async def start(self, request: AgentRunRequest) -> RunHandle:
        """Begin a run without waiting for it. Returns immediately."""

    @abstractmethod
    async def run(
        self, request: AgentRunRequest, *, sink: EventSink | None = None
    ) -> AgentRunResult:
        """Execute to completion and return the result."""

    @abstractmethod
    def stream(
        self, request: AgentRunRequest, *, extra_sink: EventSink | None = None
    ) -> AsyncIterator[LifecycleEvent]:
        """Execute, yielding lifecycle events as they occur."""

    async def cancel(self, handle: RunHandle) -> bool:
        """Request cancellation. Returns whether it was accepted.

        Default: not supported. An adapter with no notion of an out-of-band
        handle (LocalRunner) reports False rather than raising, so a caller
        can always ask without special-casing.
        """
        return False
