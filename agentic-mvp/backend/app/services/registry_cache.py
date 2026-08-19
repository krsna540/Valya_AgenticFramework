"""Process-local cache of an Agent's flattened tool/skill/playbook specs.

`app/agents/` is deliberately ORM-free (see runtime.py's module docstring),
so this lives in `app/services/` — the layer that already sits between the
ORM and that package — rather than inside `app/agents/` itself.

**What this is actually solving.** `stream_message` (api/routes/chat.py)
builds a fresh SQLAlchemy Session per HTTP request, so SQLAlchemy's own
relationship cache never survives across chat turns: every message in a
conversation re-runs the `agent_tools`/`agent_skills`/`agent_playbooks` join
queries, even though an agent's registry associations change on the order of
admin edits, not per turn. This cache sits one layer above the Session and
is keyed by agent id, so the second and every subsequent turn against the
same agent within `_TTL_SECONDS` skip those joins entirely.

**Correctness boundary.** A TTL is a blunt invalidation tool — it bounds
staleness after a Skill/Tool/Playbook row is edited directly (nobody chases
that dependency graph here), but it cannot promise "immediately fresh" the
way a query would. `invalidate()` closes the one gap that matters most in
practice: an admin changing *which* tools/skills/playbooks are attached to
an agent (api/routes/agents.py's update/delete) is exact and immediate, not
bounded by the TTL.

**Concurrency note.** `get_capabilities` must be called once, synchronously,
before any concurrent per-agent task starts (mirrors the existing
`_ = (agent.skills, agent.tools, ...)` eager-touch this replaces in
chat.py) — a cache miss touches the ORM relationships exactly as that line
did, and doing that from two concurrent tasks against a shared Session is
the hazard this module must not reintroduce.
"""
from __future__ import annotations

import time
from typing import Any

from app.agents.tools import PlaybookSpec, SkillSpec, ToolSpec

#: How long a warm entry is trusted before the next call re-touches the ORM,
#: bounding staleness from a direct Skill/Tool/Playbook content edit (see
#: module docstring). Short enough that a stale skill body doesn't linger
#: through a whole support shift, long enough to skip the join queries for
#: the overwhelming majority of turns in a conversation.
_TTL_SECONDS = 120.0

_CACHE: dict[str, tuple[float, dict[str, list[dict[str, Any]]]]] = {}


def _flatten(agent: Any) -> dict[str, list[dict[str, Any]]]:
    tools = [
        ToolSpec(
            name=t.name,
            description=t.description,
            tool_type=getattr(t, "tool_type", "function"),
            input_schema=getattr(t, "input_schema", None),
            config=getattr(t, "config", None) or {},
            timeout_s=int(getattr(t, "timeout_s", 15) or 15),
            annotations=getattr(t, "annotations", None) or {},
        ).model_dump()
        for t in (agent.tools or [])
    ]
    skills = [
        SkillSpec(
            name=s.name,
            description=s.description,
            body_markdown=getattr(s, "body_markdown", "") or "",
            allowed_tools=getattr(s, "allowed_tools", None),
        ).model_dump()
        for s in (agent.skills or [])
    ]
    playbooks = [
        PlaybookSpec(
            name=p.name,
            description=p.description,
            when_to_use=getattr(p, "when_to_use", "") or "",
            canonical_steps=getattr(p, "canonical_steps", None) or [],
            required_criteria=getattr(p, "required_criteria", None) or [],
            known_assumptions=getattr(p, "known_assumptions", None) or [],
        ).model_dump()
        for p in (getattr(agent, "playbooks", None) or [])
    ]
    return {"tools": tools, "skills": skills, "playbooks": playbooks}


def get_capabilities(agent: Any) -> dict[str, list[dict[str, Any]]]:
    """Return `{"tools": [...], "skills": [...], "playbooks": [...]}` for
    `agent`, from cache if warm and not expired.

    Must be called on the thread/task that owns the current Session on a
    cache miss — see the module docstring's concurrency note.
    """
    key = str(agent.id)
    cached = _CACHE.get(key)
    now = time.monotonic()
    if cached is not None and cached[0] > now:
        return cached[1]

    snapshot = _flatten(agent)
    _CACHE[key] = (now + _TTL_SECONDS, snapshot)
    return snapshot


def invalidate(agent_id: Any) -> None:
    """Drop `agent_id`'s cached snapshot immediately.

    Called from api/routes/agents.py whenever an agent's tool/skill/playbook
    associations are edited, so that change is visible on the very next chat
    turn rather than waiting out `_TTL_SECONDS`.
    """
    _CACHE.pop(str(agent_id), None)


def clear() -> None:
    """Drop every cached entry. Test-only — production code has no reason to
    clear the whole cache rather than one agent's entry."""
    _CACHE.clear()


__all__ = ["get_capabilities", "invalidate", "clear"]
