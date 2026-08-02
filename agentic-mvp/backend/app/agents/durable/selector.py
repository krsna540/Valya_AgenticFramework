"""Runner selection — the one place the local/Temporal decision is made.

Kept out of `__init__.py` so that importing the package doesn't import the
Temporal adapter (and through it `temporalio`, which loads a native
extension). With `TEMPORAL_ENABLED=false` the dependency is never touched.

Selection is per-call rather than a module-level singleton: `prefer_local` lets
an interactive chat turn take the in-process path — where token streaming
actually exists — while a background job on the same deployment goes through
the durable envelope. Forcing one choice per process would mean either no
token streaming or no durability.
"""
from __future__ import annotations

import logging

from app.agents.durable.base import DurableRunner
from app.agents.durable.local import LocalRunner
from app.core.config import settings

logger = logging.getLogger("agentic_mvp.agents.durable")


def get_runner(*, prefer_local: bool = False) -> DurableRunner:
    """Return the runner for this call.

    Falls back to `LocalRunner` — with a warning — if Temporal is enabled but
    its client can't be imported. A missing optional dependency should
    degrade durability, not take chat down; the warning and the run row's
    NULL `workflow_id` both record that it happened.
    """
    if prefer_local or not settings.temporal_enabled:
        return LocalRunner()

    try:
        from app.agents.durable.temporal_runner import TemporalRunner
    except ImportError as exc:
        logger.warning(
            "TEMPORAL_ENABLED is set but temporalio is unavailable (%s); "
            "running in-process instead",
            exc,
        )
        return LocalRunner()

    return TemporalRunner()
