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
    """Two groups of fields, added at different times for different readers.

    The `when_to_use` / `canonical_steps` / `required_criteria` /
    `known_assumptions` / `supporting_stats` group (migration 0017) is the
    §11.5 *procedural memory* contract — what the Planner selects and scores
    a playbook on.

    The `objective` / `target_persona` / `out_of_scope` / `inputs` /
    `guardrails` / `approval_gates` / `few_shot_examples` group (migration
    0019) is the *authoring* surface — the seven components a human
    operations author actually writes when they sit down to define a
    playbook. Both groups describe the same artifact from opposite ends;
    neither is derived from the other, and the authoring group is entirely
    optional so a mined/promoted playbook that only has the §11.5 fields is
    still a valid row.
    """

    __tablename__ = "playbooks"

    # --- §11.5 procedural memory (migration 0017) --------------------------

    when_to_use: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # [{title, detail, condition?, else_detail?}, ...] — canonical_steps.
    # `condition`/`else_detail` are OPTIONAL and were added in migration 0019
    # for IF/ELSE branching; a step with neither is an unconditional step,
    # which is exactly the shape every pre-0019 row already has. Widening the
    # JSON shape rather than adding a parallel column keeps "the ordered list
    # of steps" in one place for both the Planner and the author.
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

    # --- authoring components (migration 0019) -----------------------------

    # The single sentence answering "what must the agent achieve in this
    # interaction". Distinct from `when_to_use`, which answers "when should
    # the Planner reach for this playbook at all" — a selection signal, not
    # a goal.
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Tone/voice instruction ("polite, empathetic, short conversational
    # sentences"). Free text rather than a Persona FK on purpose: a playbook
    # describes how to sound *while running this process*, which is narrower
    # than and independent of the tenant's Persona registry.
    target_persona: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # [{topic, handoff_to}, ...] — explicit boundary. `handoff_to` is free
    # text (usually another playbook's name) and deliberately not an FK:
    # authors routinely name a playbook that does not exist yet, and a
    # dangling FK would block them from writing down a boundary they already
    # know about.
    out_of_scope: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # [{name, kind, description, ref_id}, ...] — approved knowledge bases,
    # tools and data properties. `kind` is one of datasource/tool/skill/
    # data_property (validated in app/schemas/playbook.py). `ref_id` may
    # point at a real Datasource/Tool/Skill row, but is an untyped UUID
    # string for the same reason ProjectIntelligenceBinding.component_id is:
    # it must survive the referenced row being archived.
    inputs: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # [{rule, severity}, ...] — banned moves. severity is block|warn: `block`
    # is the author asserting this must never happen, `warn` that it needs a
    # note in the transcript. NOTE: these are stored and displayed, they are
    # NOT yet enforced at runtime — enforcement belongs to the Hook engine
    # (app/services/hooks.py) and is not wired to playbooks in this build.
    guardrails: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # [{name, condition, approver, threshold}, ...] — where the run must
    # pause for a human. The ESCALATE/awaiting-human touchpoint that would
    # consume these already exists (app/models/agent_run.py + the "decide"
    # action in backend/policies/authz.rego); binding a gate to it is
    # runtime wiring not done here, same honest caveat as `guardrails`.
    approval_gates: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # [{title, exchanges: [{role, content, internal_note}]}, ...] — sample
    # dialogue showing ideal tone and error recovery. `role` is user|agent;
    # `internal_note` is the "(Internal Tool Check: ...)" aside that shows
    # the reasoning without being part of the spoken turn.
    few_shot_examples: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
