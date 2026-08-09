import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolAnnotations(BaseModel):
    """MCP tool annotation hints (spec 2025-06-18) — client display/behavior
    hints only, never a security boundary. See docs/SKILL_STANDARD.md."""

    title: str | None = Field(default=None, max_length=255)
    readOnlyHint: bool = False
    destructiveHint: bool = False
    idempotentHint: bool = False
    openWorldHint: bool = True


class ToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    config: dict = Field(default_factory=dict)
    version: str = Field(default="1.0.0", max_length=30)
    status: str = Field(default="Active", pattern="^(Active|Experimental|Deprecated)$")

    tool_type: str = Field(default="function", pattern="^(function|mcp)$")
    mcp_transport: str | None = Field(default=None, pattern="^(sse|stdio)$")
    mcp_endpoint: str | None = Field(default=None, max_length=500)
    mcp_command: str | None = Field(default=None, max_length=500)
    mcp_tool_name: str | None = Field(default=None, max_length=255)

    # Manifest metadata (adopted from NexusClaw's manifest.json shape — see
    # docs/SKILL_STANDARD.md). input_schema follows JSON Schema Draft-07,
    # same convention as Skill's handler_key catalog.
    input_schema: dict | None = None
    permissions: list[str] = Field(default_factory=list)
    rate_limit_per_min: int = Field(default=60, ge=1)
    timeout_s: int = Field(default=15, ge=1)
    tags: list[str] = Field(default_factory=list)
    annotations: ToolAnnotations = Field(default_factory=ToolAnnotations)

    @model_validator(mode="after")
    def _validate_mcp(self) -> "ToolCreate":
        from app.services.mcp_client import validate_mcp_config

        errors = validate_mcp_config(self.tool_type, self.mcp_transport, self.mcp_endpoint, self.mcp_command)
        if errors:
            raise ValueError("; ".join(errors))
        return self


class ToolUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    config: dict | None = None
    version: str | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, pattern="^(Active|Experimental|Deprecated)$")
    tool_type: str | None = Field(default=None, pattern="^(function|mcp)$")
    mcp_transport: str | None = Field(default=None, pattern="^(sse|stdio)$")
    mcp_endpoint: str | None = Field(default=None, max_length=500)
    mcp_command: str | None = Field(default=None, max_length=500)
    mcp_tool_name: str | None = Field(default=None, max_length=255)

    input_schema: dict | None = None
    permissions: list[str] | None = None
    rate_limit_per_min: int | None = Field(default=None, ge=1)
    timeout_s: int | None = Field(default=None, ge=1)
    tags: list[str] | None = None
    annotations: ToolAnnotations | None = None


class ToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    name: str
    description: str | None
    is_active: bool
    config: dict
    access_class: str = "custom"
    visibility: str = "private"
    forked_from_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    version: str
    status: str
    tool_type: str
    mcp_transport: str | None
    mcp_endpoint: str | None
    mcp_command: str | None
    mcp_tool_name: str | None
    input_schema: dict | None
    permissions: list[str]
    rate_limit_per_min: int
    timeout_s: int
    tags: list[str]
    annotations: ToolAnnotations
    created_at: datetime
    updated_at: datetime
