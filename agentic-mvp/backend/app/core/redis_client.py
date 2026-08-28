"""Redis — PLATFORM_ARCHITECTURE.md §3.7, "the lossy accelerator". Three of
its four documented jobs are wired here:

  1. Manifest handoff  — SET manifest:{session_id}, short TTL (§6.2 step 11)
  2. Event fan-out      — PUBLISH run:{run_id}:events, read by app/stream.py
  3. Pure-tool cache    — GET/SET tool:{hash(tool, args, manifest_id)}

The fourth (the loop-signature runaway guard) is a runtime-loop concern for
the Scheduler-as-code refactor (PLATFORM_ARCHITECTURE.md §17.4's #4 — not
built this session, see docs' gap map) and isn't wired yet.

One process-wide async client, created lazily and closed on shutdown — same
lifecycle pattern app/agents/checkpointer.py and app/agents/durable/client.py
already use for the Postgres checkpointer and the Temporal client, so
main.py's shutdown handler has one more resource to release in the same
list rather than a new pattern.

Redis is licensed AGPLv3 as of Redis 8 (May 2025) — OSI-approved, hence
usable under this project's OSS-only constraint; see
docs/PLATFORM_ARCHITECTURE.md §3.7/§4. `redis:8-alpine` in docker-compose,
never 7.x (still SSPL/RSALv2).
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as redis_async

from app.core.config import settings

logger = logging.getLogger("agentic_mvp.redis")

_client: redis_async.Redis | None = None

# Short — a handoff buffer, not storage (§6.2 step 11's "not storage").
# Postgres (the `manifests`/`manifest_sessions` tables) holds the durable
# copy, so a cold cache costs one extra query, never a broken session.
MANIFEST_TTL_SECONDS = 900

# Pure-tool cache entries are keyed with the manifest hash baked in (see
# app/services/manifest.py), so a stale entry can't outlive the config that
# produced it — the TTL here is purely about bounding memory, not staleness.
TOOL_CACHE_TTL_SECONDS = 3600


def get_redis() -> redis_async.Redis:
    global _client
    if _client is None:
        _client = redis_async.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# --- manifest handoff (§6.2 step 11) ----------------------------------------


async def cache_manifest_session(session_id: str, manifest_body: dict[str, Any]) -> None:
    try:
        await get_redis().set(f"manifest:{session_id}", json.dumps(manifest_body), ex=MANIFEST_TTL_SECONDS)
    except Exception:  # noqa: BLE001 — Redis is lossy by design; never block the caller
        logger.warning("Failed to cache manifest for session %s in Redis (non-fatal)", session_id, exc_info=True)


async def get_cached_manifest_session(session_id: str) -> dict[str, Any] | None:
    try:
        raw = await get_redis().get(f"manifest:{session_id}")
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        logger.warning("Failed to read cached manifest for session %s from Redis (non-fatal)", session_id, exc_info=True)
        return None


# --- event fan-out (§2.1 Path A / §3.7 job 2) -------------------------------


def run_channel(run_id: str) -> str:
    return f"run:{run_id}:events"


async def publish_run_event(run_id: str, event: dict[str, Any]) -> None:
    try:
        await get_redis().publish(run_channel(run_id), json.dumps(event))
    except Exception:  # noqa: BLE001 — a lost publish costs a UI update, never correctness
        logger.warning("Failed to publish event for run %s (non-fatal, client will replay)", run_id, exc_info=True)


async def subscribe_run_events(run_id: str) -> AsyncIterator[dict[str, Any]]:
    """Live relay of one run's events, published by `publish_run_event`.

    The accelerator, not the record: a subscriber that connects late or
    drops a message sees a gap, never a wrong answer, because the durable
    write (the `events` table, via `PostgresEventSink`) happens alongside
    this publish, not instead of it. A caller that needs completeness reads
    the table; this is for a client that wants the next event as soon as
    possible.
    """
    pubsub = get_redis().pubsub()
    channel = run_channel(run_id)
    try:
        await pubsub.subscribe(channel)
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                yield json.loads(message["data"])
            except (TypeError, ValueError):
                logger.warning("Dropping malformed event on %s (non-fatal)", channel)
    except Exception:  # noqa: BLE001 — a broken relay must not break the caller's run
        logger.warning("Event relay for run %s ended unexpectedly (non-fatal)", run_id, exc_info=True)
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:  # noqa: BLE001
            pass


# --- pure-tool result cache (§6.1) ------------------------------------------


async def get_cached_tool_result(cache_key: str) -> Any | None:
    try:
        raw = await get_redis().get(f"tool:{cache_key}")
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


async def set_cached_tool_result(cache_key: str, result: Any) -> None:
    try:
        await get_redis().set(f"tool:{cache_key}", json.dumps(result), ex=TOOL_CACHE_TTL_SECONDS)
    except Exception:  # noqa: BLE001
        logger.debug("Failed to cache tool result for key %s (non-fatal)", cache_key, exc_info=True)
