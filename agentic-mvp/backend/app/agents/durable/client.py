"""Temporal client provisioning.

One module so the client and the worker are guaranteed to agree on the two
things they must agree on: the **data converter** and the **task queue**. A
converter mismatch is the classic Temporal deployment bug — the client
serializes a Pydantic model one way, the worker deserializes it another, and
the failure surfaces as an opaque decode error inside a workflow task rather
than at the call site.

The connection is cached process-wide and created lazily under a lock: a
`Client.connect` per chat turn would open a gRPC channel per turn.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger("agentic_mvp.agents.durable.client")

_client: Any = None
_lock = asyncio.Lock()


def data_converter() -> Any:
    """Pydantic-aware converter, used identically by client and worker.

    Required because the activity/workflow signatures exchange
    `AgentRunRequest` / `AgentRunResult`, which the default JSON converter
    cannot round-trip.
    """
    from temporalio.contrib.pydantic import pydantic_data_converter

    return pydantic_data_converter


async def get_client() -> Any:
    """Connect (once) to the Temporal frontend."""
    global _client
    if _client is not None:
        return _client

    async with _lock:
        if _client is not None:
            return _client
        from temporalio.client import Client

        logger.info(
            "Connecting to Temporal at %s (namespace=%s)",
            settings.temporal_host,
            settings.temporal_namespace,
        )
        _client = await Client.connect(
            settings.temporal_host,
            namespace=settings.temporal_namespace,
            data_converter=data_converter(),
        )
        return _client


async def close_client() -> None:
    """Drop the cached client. Called from the FastAPI shutdown hook."""
    global _client
    _client = None
