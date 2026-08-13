"""Playbook contracts.

Two field groups, mirroring app/models/playbook.py's class docstring: the
§11.5 procedural-memory group the Planner reads, and the seven authoring
components a human writes. Only `name`, `when_to_use` and
`required_criteria` are mandatory on create — everything in the authoring
group defaults empty, so a playbook mined by the (not-yet-built) promotion
ladder is still a valid row without a human having filled in a persona or
few-shot dialogue.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core.core_schema import ValidationInfo

# --- nested component models -------------------------------------------------


class PlaybookStep(BaseModel):
    """One entry in the ordered execution workflow.

    `condition` / `else_detail` are what make a step conditional. Left unset
    (the pre-migration-0019 shape, and the common case) the step is a plain
    numbered instruction. Set, they read as:

        IF <condition> THEN <detail> ELSE <else_detail>

    Modelled as two optional strings rather than a nested branch tree
    deliberately — real authored playbooks branch one level and then
    rejoin, and a tree would make the editor considerably harder to use for
    a case nobody has needed yet.
    """

    title: str = Field(min_length=1, max_length=255)
    detail: str = Field(default="", max_length=2000)
    condition: str | None = Field(default=None, max_length=1000)
    else_detail: str | None = Field(default=None, max_length=2000)


class PlaybookAssumption(BaseModel):
    """PLATFORM_ARCHITECTURE.md §11.5/§12 — the `known_assumptions` field:
    "the things that historically break". `evidence_note` is free text
    today (a human summarizing what happened); once the promotion-ladder
    mining job exists (Frozen Spec §9, not built this session — see the
    gap map) it becomes the place a candidate's supporting run stats land.
    """

    assumption: str = Field(min_length=1, max_length=1000)
    evidence_note: str = Field(default="", max_length=2000)


class PlaybookOutOfScope(BaseModel):
    """An explicit boundary: a topic this playbook must NOT handle, and
    where it goes instead. `handoff_to` is free text (usually another
    playbook's name) — see the model column comment for why it is not an
    FK."""

    topic: str = Field(min_length=1, max_length=500)
    handoff_to: str = Field(default="", max_length=255)


class PlaybookInput(BaseModel):
    """An approved knowledge base, tool, or data property the agent may
    reference. Anything not listed here is, by the playbook's own
    contract, not available to it."""

    name: str = Field(min_length=1, max_length=255)
    # datasource   -> a connected source (Confluence space, SQL table, ...)
    # tool         -> a callable Tool/MCP tool
    # skill        -> a Skill package
    # data_property-> a field on the session/user record (e.g. User_Profile)
    kind: str = Field(default="data_property", pattern="^(datasource|tool|skill|data_property)$")
    description: str = Field(default="", max_length=2000)
    # Optional pointer at the real registry row. Untyped string, not a UUID
    # field: it must tolerate the referenced row being archived or renamed,
    # and authors legitimately reference things by label before the
    # datasource is connected.
    ref_id: str | None = Field(default=None, max_length=100)


class PlaybookGuardrail(BaseModel):
    """A banned move. `severity` records the author's intent, but note that
    nothing enforces it at runtime yet — see the model column comment."""

    rule: str = Field(min_length=1, max_length=1000)
    severity: str = Field(default="block", pattern="^(block|warn)$")


class PlaybookApprovalGate(BaseModel):
    """A point where the run must pause for validation or human sign-off.

    `threshold` is free text rather than a number because real gates are
    stated in mixed units — "₹1,500", "3 refunds in 24h", "any enterprise
    account" — and forcing a numeric type would push authors into encoding
    the unit in a second field nobody reads.
    """

    name: str = Field(min_length=1, max_length=255)
    condition: str = Field(default="", max_length=1000)
    # Who signs off — a role name ("Owners only", "Billing supervisor").
    # Free text for the same reason handoff_to is: the org chart this refers
    # to is not modelled in this system.
    approver: str = Field(default="", max_length=255)
    threshold: str = Field(default="", max_length=255)


class PlaybookExchange(BaseModel):
    """One turn of sample dialogue. `internal_note` is the parenthetical
    "(Internal Tool Check: ...)" aside — shown to whoever reads the
    playbook to explain the reasoning behind the reply, never part of the
    spoken content itself."""

    role: str = Field(default="user", pattern="^(user|agent)$")
    content: str = Field(min_length=1, max_length=4000)
    internal_note: str = Field(default="", max_length=2000)


class PlaybookExample(BaseModel):
    """A named few-shot scenario: a title plus the ordered exchanges that
    demonstrate ideal tone, execution and error recovery."""

    title: str = Field(min_length=1, max_length=255)
    exchanges: list[PlaybookExchange] = Field(default_factory=list)


# --- create / update / read --------------------------------------------------


class PlaybookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    version: str = Field(default="1.0.0", max_length=30)
    status: str = Field(default="Active", pattern="^(Active|Experimental|Deprecated)$")

    # §11.5 procedural memory
    when_to_use: str = Field(min_length=1, max_length=4000)
    canonical_steps: list[PlaybookStep] = Field(default_factory=list)
    # Non-empty per Frozen Spec's "no empty rubric" pattern (invariant I6
    # applied to playbooks rather than verdicts) — a playbook nobody can
    # tell whether it succeeded is not a playbook.
    required_criteria: list[str] = Field(min_length=1)
    known_assumptions: list[PlaybookAssumption] = Field(default_factory=list)

    # Authoring components — all optional, see module docstring.
    objective: str = Field(default="", max_length=4000)
    target_persona: str = Field(default="", max_length=2000)
    out_of_scope: list[PlaybookOutOfScope] = Field(default_factory=list)
    inputs: list[PlaybookInput] = Field(default_factory=list)
    guardrails: list[PlaybookGuardrail] = Field(default_factory=list)
    approval_gates: list[PlaybookApprovalGate] = Field(default_factory=list)
    few_shot_examples: list[PlaybookExample] = Field(default_factory=list)


class PlaybookUpdate(BaseModel):
    """Every field optional — the route applies `exclude_unset=True`, so an
    omitted key leaves the stored value alone rather than clearing it. A
    caller that genuinely wants to empty a list sends `[]` explicitly."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    version: str | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, pattern="^(Active|Experimental|Deprecated)$")

    when_to_use: str | None = Field(default=None, min_length=1, max_length=4000)
    canonical_steps: list[PlaybookStep] | None = None
    required_criteria: list[str] | None = Field(default=None, min_length=1)
    known_assumptions: list[PlaybookAssumption] | None = None

    objective: str | None = Field(default=None, max_length=4000)
    target_persona: str | None = Field(default=None, max_length=2000)
    out_of_scope: list[PlaybookOutOfScope] | None = None
    inputs: list[PlaybookInput] | None = None
    guardrails: list[PlaybookGuardrail] | None = None
    approval_gates: list[PlaybookApprovalGate] | None = None
    few_shot_examples: list[PlaybookExample] | None = None


class PlaybookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    name: str
    description: str | None
    is_active: bool
    version: str
    status: str

    when_to_use: str
    canonical_steps: list[PlaybookStep]
    required_criteria: list[str]
    known_assumptions: list[PlaybookAssumption]
    supporting_stats: dict

    # Defaulted so a row written before migration 0019 (or read from a
    # database where the migration has not run) still validates rather than
    # 500-ing the list endpoint.
    objective: str = ""
    target_persona: str = ""
    out_of_scope: list[PlaybookOutOfScope] = Field(default_factory=list)
    inputs: list[PlaybookInput] = Field(default_factory=list)
    guardrails: list[PlaybookGuardrail] = Field(default_factory=list)
    approval_gates: list[PlaybookApprovalGate] = Field(default_factory=list)
    few_shot_examples: list[PlaybookExample] = Field(default_factory=list)

    access_class: str = "custom"
    visibility: str = "private"
    forked_from_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator(
        "objective",
        "target_persona",
        "out_of_scope",
        "inputs",
        "guardrails",
        "approval_gates",
        "few_shot_examples",
        "access_class",
        "visibility",
        mode="before",
    )
    @classmethod
    def _null_to_declared_default(cls, value: object, info: ValidationInfo) -> object:
        """Coerce NULL to the field's declared default.

        A `= ""` / `default_factory=list` default only applies when the key
        is ABSENT. Under `from_attributes=True` the attribute is always
        present, so a row carrying NULL in one of these columns reaches the
        validator as None and would raise instead of falling back — which
        would 500 the whole list endpoint over one bad row.

        NULL genuinely occurs here in two situations: a Playbook object
        built in Python but not yet flushed (SQLAlchemy applies column
        defaults at flush, not at __init__), and any row written before the
        column's migration landed. Neither is worth an error.
        """
        if value is not None:
            return value
        field = cls.model_fields[info.field_name] if info.field_name else None
        return field.get_default(call_default_factory=True) if field is not None else value
