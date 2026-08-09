import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PlaybookStep(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    detail: str = Field(default="", max_length=2000)


class PlaybookAssumption(BaseModel):
    """PLATFORM_ARCHITECTURE.md §11.5/§12 — the `known_assumptions` field:
    "the things that historically break". `evidence_note` is free text
    today (a human summarizing what happened); once the promotion-ladder
    mining job exists (Frozen Spec §9, not built this session — see the
    gap map) it becomes the place a candidate's supporting run stats land.
    """

    assumption: str = Field(min_length=1, max_length=1000)
    evidence_note: str = Field(default="", max_length=2000)


class PlaybookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    version: str = Field(default="1.0.0", max_length=30)
    status: str = Field(default="Active", pattern="^(Active|Experimental|Deprecated)$")
    when_to_use: str = Field(min_length=1, max_length=4000)
    canonical_steps: list[PlaybookStep] = Field(default_factory=list)
    # Non-empty per Frozen Spec's "no empty rubric" pattern (invariant I6
    # applied to playbooks rather than verdicts) — a playbook nobody can
    # tell whether it succeeded is not a playbook.
    required_criteria: list[str] = Field(min_length=1)
    known_assumptions: list[PlaybookAssumption] = Field(default_factory=list)


class PlaybookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    version: str | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, pattern="^(Active|Experimental|Deprecated)$")
    when_to_use: str | None = Field(default=None, min_length=1, max_length=4000)
    canonical_steps: list[PlaybookStep] | None = None
    required_criteria: list[str] | None = Field(default=None, min_length=1)
    known_assumptions: list[PlaybookAssumption] | None = None


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
    access_class: str = "custom"
    visibility: str = "private"
    forked_from_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
