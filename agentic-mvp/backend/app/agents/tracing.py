"""MLflow tracing — OpenTelemetry-based spans over agent execution.

MLflow's tracing feature (2.14+, and what the `mlflow[genai]` package this
repo already depends on ships) is built directly on the OpenTelemetry data
model: every `mlflow.start_span()` produces a real OTel span, propagated
through `contextvars` so spans opened across `await` points inside the same
asyncio task still parent correctly. That is what lets one call into
`AgentRuntime.run()`/`stream()` produce a single trace tree — run root ->
planner/executor/critic AGENT spans -> individual LLM spans — instead of a
scatter of unrelated top-level traces.

Traces are logged to the `mlflow` service already in docker-compose
(tracking-server backed by the same Postgres this app uses), not a separate
OpenTelemetry collector — see the reasoning already applied once this build
to the AI Gateway question: check what the infra already running can do
before adding a new service for it.

**Fault isolation.** Every public function here follows the same contract as
`EventSink.emit` (see lifecycle.py) and the hook engine: tracing must never
raise into, slow down materially, or otherwise affect the run it observes.
`mlflow` failing to import, the tracking server being unreachable, or a
span's own bookkeeping call raising are all logged and swallowed. The one
thing this module never swallows is an exception raised by the *wrapped*
business logic — `traced_span`'s yield sits outside every try/except that
could catch it, so a real `ProviderError` from an LLM call still propagates
to the retry logic in lifecycle.py exactly as it would with tracing off.
"""
from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import Iterator
from typing import Any

from app.core.config import settings

logger = logging.getLogger("agentic_mvp.agents.tracing")

try:
    import mlflow

    _MLFLOW_IMPORTED = True
except ImportError:  # pragma: no cover - mlflow is a real dependency, but
    # tracing must degrade gracefully if it's ever missing from an
    # environment (e.g. a slim worker image), same as every other optional
    # infra client in this codebase (redis_client.py, minio_client.py).
    mlflow = None  # type: ignore[assignment]
    _MLFLOW_IMPORTED = False

_initialized = False


def tracing_enabled() -> bool:
    return _MLFLOW_IMPORTED and settings.mlflow_tracing_enabled


def init_tracing() -> None:
    """Point the MLflow tracing client at the tracking server and select the
    experiment traces are logged under.

    Idempotent and safe to call from both the API process (main.py startup)
    and the Temporal worker process (durable/worker.py startup) — each is a
    separate process with its own copy of this module-level state. Never
    raises: called from a startup hook, and a tracing misconfiguration must
    not be the reason `docker compose up` fails to bring the backend up.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True
    if not tracing_enabled():
        if not _MLFLOW_IMPORTED:
            logger.info("mlflow package not importable; agent execution tracing disabled")
        else:
            logger.info("MLFLOW_TRACING_ENABLED=false; agent execution tracing disabled")
        return
    try:
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(settings.mlflow_experiment_name)
        logger.info(
            "MLflow tracing initialized: uri=%s experiment=%s",
            settings.mlflow_tracking_uri,
            settings.mlflow_experiment_name,
        )
    except Exception:  # noqa: BLE001 - tracing setup must never block startup
        logger.exception(
            "MLflow tracing init failed (tracking_uri=%s); continuing with tracing disabled",
            settings.mlflow_tracking_uri,
        )
        _initialized = True


def _truncate(value: Any, limit: int = 2000) -> Any:
    """Trace payloads are for debugging, not storage — cap anything
    string-shaped so a long prompt or completion can't bloat a span (or, for
    a very chatty run, the trace) unboundedly."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"... [truncated, {len(value)} chars total]"
    return value


@contextlib.contextmanager
def traced_span(
    name: str,
    *,
    span_type: str = "AGENT",
    inputs: dict[str, Any] | None = None,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Best-effort MLflow span. Yields the live span object (so the caller
    can `set_outputs`/`set_attributes` once the wrapped call finishes), or
    `None` if tracing is disabled or unavailable — callers must handle that.

    Deliberately does *not* wrap the `yield` in a try/except that could catch
    the caller's own exception: only span setup/teardown calls are isolated.
    An exception raised by the code inside the `with` block is re-raised
    unchanged after a best-effort attempt to close the span with error
    status, so tracing never masks or alters a real failure.
    """
    if not tracing_enabled():
        yield None
        return

    span_cm: Any = None
    span: Any = None
    try:
        span_cm = mlflow.start_span(name=name, span_type=span_type)
        span = span_cm.__enter__()
        if inputs is not None:
            with contextlib.suppress(Exception):
                span.set_inputs({k: _truncate(v) for k, v in inputs.items()})
        if attributes:
            with contextlib.suppress(Exception):
                span.set_attributes(attributes)
    except Exception:  # noqa: BLE001 - span *creation* must never block the call
        logger.debug("Failed to start MLflow span %r; continuing untraced", name, exc_info=True)
        span_cm = None
        span = None

    try:
        yield span
    except BaseException:
        if span_cm is not None:
            with contextlib.suppress(Exception):
                span_cm.__exit__(*sys.exc_info())
        raise
    else:
        if span_cm is not None:
            with contextlib.suppress(Exception):
                span_cm.__exit__(None, None, None)


def set_span_outputs(span: Any | None, outputs: dict[str, Any]) -> None:
    """Best-effort `span.set_outputs`, tolerant of `span` being `None`
    (tracing disabled) so call sites don't need an `if span:` guard around
    every one of these."""
    if span is None:
        return
    with contextlib.suppress(Exception):
        span.set_outputs({k: _truncate(v) for k, v in outputs.items()})


def set_span_attributes(span: Any | None, attributes: dict[str, Any]) -> None:
    if span is None:
        return
    with contextlib.suppress(Exception):
        span.set_attributes(attributes)


def update_current_trace(*, tags: dict[str, str] | None = None) -> None:
    """Attach run-identifying tags (run_id, agent_id, tenant_id) to whatever
    trace is currently active, so a run can be found in the MLflow UI by
    those fields without opening it. Called once, from the root span at
    `AgentRuntime.run`/`stream` — safe to call even with tracing disabled or
    no active trace (mlflow no-ops / raises, both handled)."""
    if not tracing_enabled() or not tags:
        return
    with contextlib.suppress(Exception):
        mlflow.update_current_trace(tags=tags)
