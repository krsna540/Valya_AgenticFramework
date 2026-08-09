"""Temporal worker entrypoint.

Run as its own process (see the `agent-worker` service in
docker-compose.yml):

    python -m app.agents.durable.worker

**Why a separate process from the API.** A worker polls Temporal
continuously and executes runs that may take minutes. Sharing a process with
uvicorn would have long agent runs competing with request handling for the
same event loop, and would tie worker capacity to web capacity — the two
scale on completely different signals.

**Sandbox passthrough.** Temporal runs workflow code in a sandbox that
re-imports modules to enforce determinism. The application package is marked
as passed-through: it is large, its import has side effects (SQLAlchemy model
registration, logging config), and re-importing it per workflow task would be
both slow and wrong. The workflow module itself contains no I/O, so the
determinism guarantee the sandbox provides is preserved by construction
rather than by isolation.

**Activity concurrency.** Bounded, because each concurrent activity is a full
agent run holding a database connection and an LLM connection. The default of
100 would exhaust the connection pool long before it exhausted the CPU.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import (
    SandboxedWorkflowRunner,
    SandboxRestrictions,
)

from app.agents.durable.activities import ALL_ACTIVITIES
from app.agents.durable.client import get_client
from app.agents.durable.workflow import AgentRunWorkflow
from app.core.config import settings

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("agentic_mvp.agents.worker")

#: Concurrent agent runs per worker. Each holds a DB connection and an
#: outbound LLM connection, so this is sized against the connection pool.
MAX_CONCURRENT_ACTIVITIES = 10


def _sandbox_runner() -> SandboxedWorkflowRunner:
    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules(
            "app",
            "pydantic",
            "pydantic_core",
        )
    )


async def main() -> None:
    # Same tracing init as the API process (app/main.py's startup hook) — a
    # durable run's agent-node/LLM spans are opened by the same base.py /
    # llm.py code whether the activity executes here or in-process, so both
    # entry points need to have pointed the mlflow client at the tracking
    # server before any run reaches them. Best-effort; never blocks worker
    # startup (see app/agents/tracing.py's fault-isolation contract).
    from app.agents.tracing import init_tracing

    init_tracing()

    client = await get_client()
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[AgentRunWorkflow],
        activities=ALL_ACTIVITIES,
        workflow_runner=_sandbox_runner(),
        max_concurrent_activities=MAX_CONCURRENT_ACTIVITIES,
    )
    logger.info(
        "Agent worker listening on task queue %r (namespace=%s)",
        settings.temporal_task_queue,
        settings.temporal_namespace,
    )
    await worker.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Agent worker stopped")
