import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SkillTriggers(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    intents: list[str] = Field(default_factory=list)
    lifecycle_events: list[str] = Field(default_factory=list)


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    name: str
    description: str | None
    is_active: bool
    version: str
    status: str
    license: str | None
    compatibility: str | None
    metadata: dict[str, str] = Field(alias="metadata_fields")
    allowed_tools: str | None
    body_markdown: str
    file_manifest: list[str]
    # skill.json-derived fields (see app/skills/package_spec.py) — empty/
    # default when the skill has no skill.json.
    triggers: SkillTriggers
    hooks: list[str]
    created_at: datetime
    updated_at: datetime


class SkillUpdate(BaseModel):
    is_active: bool | None = None


class SkillUploadWarnings(BaseModel):
    """Returned alongside the created skill when the parser found non-fatal
    issues (unrecognized frontmatter/skill.json fields, empty body)."""

    warnings: list[str] = Field(default_factory=list)
