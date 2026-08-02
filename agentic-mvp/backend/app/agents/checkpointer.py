"""LangGraph checkpointer provisioning.

A checkpointer is what makes a run *resumable*: LangGraph writes the state
after every super-step, so a crashed or interrupted run picks up from the
last completed node rather than from the objective. That is also what makes
human-in-the-loop pauses possible — an interrupt is just a checkpoint nobody
has resumed yet.

Two implementations, and the choice is a deployment decision, not a code one:

  * `AsyncPostgresSaver` — durable, survives a restart, and puts every
    checkpoint in the same database as the run records. The real answer.
  * `InMemorySaver` — per-process, lost on restart. Correct for tests and for
    a laptop without a database.

**Why it degrades rather than raises.** If Postgres checkpointing is asked
for and can't be provisioned (driver missing, database unreachable, the
`psycopg` extra not installed), this falls back to in-memory with a loud
warning. A chat endpoint that 500s because *durability* is unavailable trades
a working degraded feature for a broken one — the run still completes, it
just isn't resumable, and the warning says so.

**Lifecycle.** `AsyncPostgresSaver.from_conn_string` is an async context
manager owning a connection pool, so it's held open in a module-level
`AsyncExitStack` for the process lifetime and released by `close_checkpointer()`
from the FastAPI shutdown handler. Creating one per request would open a
connection pool per chat turn.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any

from app.core.config import settings

logger = logging.getLogger("agentic_mvp.agents.checkpointer")

_stack: AsyncExitStack | None = None
_checkpointer: Any = None
_lock = asyncio.Lock()


def _postgres_conn_string() -> str:
    """psycopg3 DSN. `settings.database_url` is SQLAlchemy's
    `postgresql+psycopg2://` form, which psycopg cannot parse — so the
    driver marker is stripped rather than a second URL being configured and
    left to drift out of sync with the first."""
    return settings.database_url.replace("postgresql+psycopg2://", "postgresql://")


async def get_checkpointer() -> Any:
    """Return the process-wide checkpointer, provisioning it on first use.

    Guarded by a lock: two concurrent first requests would otherwise each
    build a pool and one would be silently orphaned.
    """
    global _stack, _checkpointer

    if _checkpointer is not None:
        return _checkpointer

    async with _lock:
        if _checkpointer is not None:  # another coroutine won the race
            return _checkpointer

        kind = (settings.agent_checkpointer or "memory").lower()
        if kind == "postgres":
            checkpointer = await _build_postgres_checkpointer()
            if checkpointer is not None:
                _checkpointer = checkpointer
                return _checkpointer
            logger.warning(
                "Falling back to in-memory checkpointing; runs will not be resumable "
                "across a restart"
            )

        from langgraph.checkpoint.memory import InMemorySaver

        _checkpointer = InMemorySaver()
        return _checkpointer


async def _build_postgres_checkpointer() -> Any | None:
    """Open the Postgres saver and run its schema setup. Returns None on any
    failure — the caller decides what to do about it."""
    global _stack
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:
        logger.warning(
            "Postgres checkpointing requested but unavailable (%s). "
            "Install langgraph-checkpoint-postgres and psycopg[binary].",
            exc,
        )
        return None

    try:
        stack = AsyncExitStack()
        saver = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(_postgres_conn_string())
        )
        # Idempotent: creates the checkpoint tables if they aren't there.
        # Owned by LangGraph, deliberately outside Alembic — letting Alembic
        # manage a third party's schema means every upgrade of that package
        # becomes a migration to hand-write.
        await saver.setup()
        _stack = stack
        logger.info("LangGraph Postgres checkpointer ready")
        return saver
    except Exception as exc:  # noqa: BLE001 — degrade, never fail the app
        logger.warning("Could not provision the Postgres checkpointer: %s", exc)
        return None


async def close_checkpointer() -> None:
    """Release the connection pool. Called from the FastAPI shutdown hook."""
    global _stack, _checkpointer
    if _stack is not None:
        try:
            await _stack.aclose()
        except Exception:  # noqa: BLE001
            logger.exception("Error closing the checkpointer")
        _stack = None
    _checkpointer = None


def reset_for_tests() -> None:
    """Drop the cached checkpointer without awaiting teardown. Tests only."""
    global _stack, _checkpointer
    _stack = None
    _checkpointer = None
