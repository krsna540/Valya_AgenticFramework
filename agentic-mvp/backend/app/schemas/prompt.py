import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

_VARIABLE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class PromptMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1, max_length=20000)


class PromptVariable(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern="^[a-zA-Z_][a-zA-Z0-9_]*$")
    description: str | None = Field(default=None, max_length=500)
    default: str | None = None
    required: bool = True


class PromptModelParams(BaseModel):
    """Generation parameters versioned together with the prompt text —
    Langfuse/LangSmith convention (see docs/SKILL_STANDARD.md)."""

    model: str | None = Field(default=None, max_length=255)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=200000)
    top_p: float | None = Field(default=None, ge=0, le=1)
    stop: list[str] = Field(default_factory=list)


def _validate_messages_and_variables(messages: list[PromptMessage], variables: list[PromptVariable]) -> None:
    if not messages:
        raise ValueError("messages must contain at least one entry")

    referenced: set[str] = set()
    for m in messages:
        referenced |= set(_VARIABLE_PATTERN.findall(m.content))

    declared = {v.name for v in variables}
    undeclared = referenced - declared
    if undeclared:
        raise ValueError(
            f"messages reference {{{{variable}}}} placeholder(s) not declared in variables: {sorted(undeclared)}"
        )


class PromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    version: str = Field(default="1.0.0", max_length=30)
    status: str = Field(default="Active", pattern="^(Active|Experimental|Deprecated)$")
    label: str = Field(default="latest", min_length=1, max_length=50)
    tags: list[str] = Field(default_factory=list)

    messages: list[PromptMessage] = Field(min_length=1)
    variables: list[PromptVariable] = Field(default_factory=list)
    model_params: PromptModelParams = Field(default_factory=PromptModelParams)

    @model_validator(mode="after")
    def _validate(self) -> "PromptCreate":
        _validate_messages_and_variables(self.messages, self.variables)
        return self


class PromptUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    version: str | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, pattern="^(Active|Experimental|Deprecated)$")
    label: str | None = Field(default=None, min_length=1, max_length=50)
    tags: list[str] | None = None

    messages: list[PromptMessage] | None = Field(default=None, min_length=1)
    variables: list[PromptVariable] | None = None
    model_params: PromptModelParams | None = None

    @model_validator(mode="after")
    def _validate(self) -> "PromptUpdate":
        # messages/variables are cross-referenced (every {{var}} in messages
        # must be declared in variables), so unlike Plugin's independent
        # exports_skills/exports_hooks, a PATCH can't safely validate one
        # against the *stored* value of the other — partial info could
        # produce a false-positive "undeclared variable" reject. Instead,
        # require both together whenever either changes; the frontend form
        # always holds and resubmits the full prompt anyway (same pattern as
        # every other registry form in this app), so this is never a real
        # constraint in practice.
        if (self.messages is None) != (self.variables is None):
            raise ValueError("messages and variables must be updated together")
        if self.messages is not None and self.variables is not None:
            _validate_messages_and_variables(self.messages, self.variables)
        return self


class PromptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    name: str
    description: str | None
    is_active: bool
    version: str
    status: str
    label: str
    tags: list[str]
    messages: list[PromptMessage]
    variables: list[PromptVariable]
    model_params: PromptModelParams
    # migration 0016 — PLATFORM_ARCHITECTURE.md §7.2
    access_class: str = "custom"
    visibility: str = "private"
    forked_from_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
