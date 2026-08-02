"""In-process `DurableRunner`.

The default, and the correct choice for interactive chat: the caller is
already holding an open SSE connection, so a durable envelope would add a
round-trip and a serialization boundary without buying survivability that
anything downstream could use.

"Local" does not mean "no durability at all" — when the Postgres checkpointer
is configured, a run still checkpoints after every super-step and can be
resumed by `thread_id`. What Temporal adds on top is the *scheduling*
guarantee: something restarts the run without a client asking. That is the
distinction the two adapters draw.

`start()` fires a background task and returns. It is genuinely fire-and-
forget: a run started this way survives only as long as the process, which
is why the returned handle reports `durable=False`. A caller that needs the
stronger guarantee should be using `TemporalRunner`, and the handle says so
rather than leaving them to guess.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from app.agents.durable.base import DurableRunner, RunHandle
from app.agents.lifecycle import EventSink, LifecycleEvent
from app.agents.runtime import AgentRunRequest, AgentRunResult, AgentRuntime

logger = logging.getLogger("agentic_mvp.agents.durable.local")


class LocalRunner(DurableRunner):
    """Runs the graph in this process."""

    name = "local"

    def __init__(self, runtime: AgentRuntime | None = None) -> None:
        self._runtime = runtime or AgentRuntime()
        # Strong references to in-flight background tasks. asyncio only holds
        # a weak reference to a running task, so without this a fire-and-
        # forget run can be garbage-collected mid-execution — a well-known
        # and very confusing failure mode.
        self._background: set[asyncio.Task] = set()

    async def start(self, request: AgentRunRequest) -> RunHandle:
        task = asyncio.create_task(self._runtime.run(request))
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return RunHandle(run_id=request.run_id, durable=False)

    async def run(
        self, request: AgentRunRequest, *, sink: EventSink | None = None
    ) -> AgentRunResult:
        return await self._runtime.run(request, sink=sink)

    def stream(
        self, request: AgentRunRequest, *, extra_sink: EventSink | None = None
    ) -> AsyncIterator[LifecycleEvent]:
        return self._runtime.stream(request, extra_sink=extra_sink)

    @property
    def runtime(self) -> AgentRuntime:
        """Exposed so the SSE adapter can read `last_result` after streaming."""
        return self._runtime
