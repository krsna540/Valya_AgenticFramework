"""PostgresEventSink — the additive bridge from the existing lifecycle-event
mechanism onto the new `events` table (PLATFORM_ARCHITECTURE.md §10/§11.3,
migration 0017).

Deliberately parallel to, not a replacement for,
app.services.agent_run_store.PersistingEventSink: that sink writes
AgentRunStep rows (the normalized Observatory reporting table this codebase
already had); this one writes the narrower, append-only, Frozen-Spec-shaped
`events` rows the architecture doc calls episodic memory. Composed together
via CompositeEventSink in app/services/agent_runner.py — every event both
sinks care about gets written to both tables, once each, from the same
LifecycleEvent, at no extra emission cost to the agents themselves (they
don't know either sink exists — see lifecycle.py's module docstring).

Same fault-isolation contract as every other sink here: a write failure is
logged and swallowed, never raised into the run it's observing.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from app.agents.lifecycle import EventSink, LifecycleEvent
from app.core.database import SessionLocal
from app.core.redis_client import publish_run_event
from app.models.event import Event

logger = logging.getLogger("agentic_mvp.agents.event_persistence")

# Maps the runtime's EventType vocabulary onto the Frozen Spec §5.2 taxonomy
# names where a clean equivalent exists. Events with no clean equivalent
# (PHASE_ENTER/PHASE_EXIT, NODE_START) are still persisted under their own
# name — the taxonomy in the spec is a floor, not a ceiling, and dropping
# events the runtime already produces would make the episodic log less
# complete than the system already is.
_ACTOR_BY_ROLE = {
    "planner": "planner",
    "executor": "executor",
    "critic": "critic",
    "system": "system",
}

# NOTE: Frozen Spec §5.3 requires an evidence_ref on every scope-changing
# event (REVISION_START/HUMAN_REVIEW_REQUIRED being this runtime's closest
# equivalents). Not enforced here — this runtime's REPLAN/ESCALATE verdicts
# don't yet carry a structured evidence_ref field to reject the absence of
# (see app/agents/state.py::Verdict) — enforcing it here would reject every
# real event this runtime currently emits. PLATFORM_ARCHITECTURE.md §9.5's
# full verifier ladder is the follow-on that closes this gap for real.


class PostgresEventSink(EventSink):
    def __init__(self, run_id: uuid.UUID, *, tenant_id: uuid.UUID | None, project_id: uuid.UUID | None = None) -> None:
        self._run_id = run_id
        self._tenant_id = tenant_id
        self._project_id = project_id
        self._seq = 0

    async def _write(self, event: LifecycleEvent) -> None:
        """EventSink's `emit()` template already wraps this in a try/except
        (lifecycle.py's ABC — see the class docstring there), so a failure
        in either the Postgres write or the Redis publish below can never
        propagate into the run being observed; no need to duplicate that
        guard here."""
        self._seq += 1
        seq = self._seq
        # Fire-and-forget the Redis publish (the token/progress fast path,
        # §2.1 Path A) alongside the durable Postgres write — neither
        # blocks the other, and a Redis failure is already non-fatal inside
        # publish_run_event itself.
        await asyncio.gather(
            asyncio.to_thread(self._insert, event, seq),
            publish_run_event(
                str(self._run_id),
                {
                    "seq": seq,
                    "type": event.type.value,
                    "ts": event.at.isoformat(),
                    "phase": event.phase,
                    "revision": event.revision,
                    "data": event.data,
                },
            ),
            return_exceptions=True,
        )

    def _insert(self, event: LifecycleEvent, seq: int) -> None:
        try:
            with SessionLocal() as db:
                db.add(
                    Event(
                        run_id=self._run_id,
                        seq=seq,
                        type=event.type.value,
                        actor=_ACTOR_BY_ROLE.get((event.role or "system"), "system"),
                        tenant_id=self._tenant_id,
                        project_id=self._project_id,
                        payload=event.data,
                        evidence_ref=None,
                        ts=event.at,
                    )
                )
                db.commit()
        except Exception:  # noqa: BLE001 — an observer must never fail the run it observes
            logger.exception("Failed to persist episodic event (run=%s seq=%s type=%s)", self._run_id, seq, event.type)
