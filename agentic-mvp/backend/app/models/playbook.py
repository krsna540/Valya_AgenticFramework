"""Playbook registry — PLATFORM_ARCHITECTURE.md §11.5 / §7. The sixth
registry kind the Frozen Spec calls for and this codebase did not yet have
(see the gap map in docs/PLATFORM_ARCHITECTURE.md §17.2): a canonical
decomposition for a recurring process — `when_to_use`, `canonical_steps`,
`required_criteria`, and `known_assumptions` (the things that historically
break, per Frozen Spec §12's "the highest-value artifact the whole system
produces is an assumption that repeatedly fired").

Shares the same RegistryMixin/TenantScopedMixin shape (and therefore the
same access_class/visibility/fork machinery in
app/services/registry_access.py) as Skill/Prompt/Tool/Plugin — a Playbook is
governed the same way procedural memory is governed everywhere else in the
spec. Read by the Planner only per §11.5 — never the Executor — which is a
runtime-wiring concern for a later stage, not a storage concern here.
"""
from sqlalchemy import JSON, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import RegistryMixin, TenantScopedMixin


class Playbook(RegistryMixin, TenantScopedMixin, Base):
    __tablename__ = "playbooks"

    when_to_use: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # [{title, detail}, ...] — canonical_steps
    canonical_steps: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # [str, ...] — required_criteria, non-empty enforced at the schema layer
    # (app/schemas/playbook.py), same "no empty rubric" reasoning as the
    # Frozen Spec's invariant I6 for verdicts.
    required_criteria: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # [{assumption, evidence_note}, ...] — the scar-tissue field; starts
    # empty and is meant to be filled by the (not-yet-built) promotion
    # ladder mining job, or by a human who noticed a recurring failure.
    known_assumptions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Supporting run statistics an owner reviews before promoting a
    # mined candidate (Frozen Spec §9's "promotion requires evidence, not
    # frequency alone") — {acceptance_rate, replan_rate, mean_cost_usd,
    # sample_size}. Empty for hand-authored playbooks.
    supporting_stats: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
