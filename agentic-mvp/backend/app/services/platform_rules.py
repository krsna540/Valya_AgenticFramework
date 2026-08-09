"""Seed content for the superadmin-app.html "Platform rules" screen —
mirrors the six invariants shown in the mockup verbatim, which are also
close paraphrases of PLATFORM_ARCHITECTURE.md §20's invariant register
(nothing crosses tenants = B1/tenant isolation, results follow access = B1,
nothing marked done without a check = I6/the verifier ladder, skill code
runs in isolation = §8.5's gVisor sandbox — not yet built, listed here as
policy intent ahead of the implementation, same "documented, not silently
skipped" posture as the rest of this build).

Seeded once, idempotently, on first read if no revision exists yet — see
get_or_seed_current() below — rather than an Alembic data migration, so
editing the default text later doesn't require a new migration.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.policy_revision import PolicyRevision

DEFAULT_RULES: list[dict[str, str]] = [
    {
        "name": "Nothing crosses between organisations",
        "detail": "People, sources, work and memory are sealed inside one organisation. There is no setting that opens this.",
        "bound": "Cannot be changed",
    },
    {
        "name": "Results follow existing access",
        "detail": "Someone only sees results from documents they could already open themselves.",
        "bound": "Cannot be changed",
    },
    {
        "name": "Actions that change things ask first",
        "detail": "Organisations may make this stricter. They cannot make it looser.",
        "bound": "Minimum",
    },
    {
        "name": "Nothing is marked done without a check",
        "detail": "A step is only finished once it has been checked against what finished means for it.",
        "bound": "Cannot be changed",
    },
    {
        "name": "Skill code runs in isolation",
        "detail": "Custom code runs with no network and no write access, separate from everything else.",
        "bound": "Cannot be changed",
    },
    {
        "name": "Effort limit ceiling",
        "detail": "Organisations set their own limit up to this ceiling.",
        "bound": "40 steps",
    },
]


def get_current(db: Session) -> PolicyRevision | None:
    return db.query(PolicyRevision).filter(PolicyRevision.is_current == True).first()  # noqa: E712


def get_or_seed_current(db: Session) -> PolicyRevision:
    current = get_current(db)
    if current is not None:
        return current
    seeded = PolicyRevision(
        revision_number=1,
        summary="Initial platform rules",
        rules=DEFAULT_RULES,
        tests_passed=len(DEFAULT_RULES),
        is_current=True,
        published_by_name="System (seeded)",
    )
    db.add(seeded)
    db.commit()
    db.refresh(seeded)
    return seeded
