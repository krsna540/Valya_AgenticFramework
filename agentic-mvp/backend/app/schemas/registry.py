import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegistryBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    config: dict = Field(default_factory=dict)
    # SemVer + lifecycle status — part of the Intelligence Layer
    # formalization (every registry entry must support strict SemVer).
    version: str = Field(default="1.0.0", max_length=30)
    status: str = Field(default="Active", pattern="^(Active|Experimental|Deprecated)$")


class RegistryCreate(RegistryBase):
    pass


class RegistryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    config: dict | None = None
    version: str | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, pattern="^(Active|Experimental|Deprecated)$")


class RegistryRead(RegistryBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    # migration 0016 — PLATFORM_ARCHITECTURE.md §7.2's two access-modifier
    # axes, exposed on every registry Read schema that derives from this
    # base (Hook, and any future make_registry_router() adopter).
    access_class: str = "custom"
    visibility: str = "private"
    forked_from_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class HookCreate(RegistryCreate):
    scope: str = Field(default="agent", pattern="^(global|agent)$")
    lifecycle_event: str = Field(min_length=1, max_length=50)
    handler_type: str = Field(default="python", pattern="^(python|http|command|mcp_tool)$")
    handler_key: str | None = Field(default=None, min_length=1, max_length=100)
    handler_config: dict = Field(default_factory=dict)
    execution_policy: dict = Field(default_factory=dict)
    version: str = Field(default="1.0.0", max_length=30)
    status: str = Field(default="Active", pattern="^(Active|Experimental|Deprecated)$")
    tags: list[str] = Field(default_factory=list)
    author: str | None = Field(default=None, max_length=255)


class HookUpdate(RegistryUpdate):
    scope: str | None = Field(default=None, pattern="^(global|agent)$")
    lifecycle_event: str | None = Field(default=None, min_length=1, max_length=50)
    handler_type: str | None = Field(default=None, pattern="^(python|http|command|mcp_tool)$")
    handler_key: str | None = Field(default=None, min_length=1, max_length=100)
    handler_config: dict | None = None
    execution_policy: dict | None = None
    version: str | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, pattern="^(Active|Experimental|Deprecated)$")
    tags: list[str] | None = None
    author: str | None = Field(default=None, max_length=255)


class HookRead(RegistryRead):
    scope: str
    lifecycle_event: str
    handler_type: str
    handler_key: str | None
    handler_config: dict
    execution_policy: dict
    version: str
    status: str
    tags: list[str]
    author: str | None


class HookHandlerInfo(BaseModel):
    key: str
    stage: str
    description: str


class LifecycleEventInfo(BaseModel):
    """One entry from GET /hooks/lifecycle-events — the full taxonomy, with
    a flag for whether this app currently has a real trigger point wired up
    for it (see app/services/hooks.py's module docstring)."""

    key: str
    wired: bool


# Skill schemas now live in app/schemas/skill.py — the handler_key-bound
# Skill/BaseSkill/SKILL_REGISTRY catalog this module used to serve
# (SkillCreate/SkillUpdate/SkillRead/SkillHandlerInfo/SkillExecuteRequest/
# SkillExecuteResponse) was retired; the folder-based format
# (SKILL.md + skill.json + scripts/references/assets) is now the only way a
# skill is defined. See docs/SKILL_STANDARD.md.


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    system_prompt: str | None = None
    model_name: str = "stub-echo"
    version: str = Field(default="1.0.0", max_length=30)
    status: str = Field(default="Active", pattern="^(Active|Experimental|Deprecated)$")
    skill_ids: list[uuid.UUID] = Field(default_factory=list)
    tool_ids: list[uuid.UUID] = Field(default_factory=list)
    plugin_ids: list[uuid.UUID] = Field(default_factory=list)
    hook_ids: list[uuid.UUID] = Field(default_factory=list)
    playbook_ids: list[uuid.UUID] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    system_prompt: str | None = None
    model_name: str | None = None
    version: str | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, pattern="^(Active|Experimental|Deprecated)$")
    skill_ids: list[uuid.UUID] | None = None
    tool_ids: list[uuid.UUID] | None = None
    plugin_ids: list[uuid.UUID] | None = None
    hook_ids: list[uuid.UUID] | None = None
    playbook_ids: list[uuid.UUID] | None = None


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID | None
    name: str
    description: str | None
    is_active: bool
    system_prompt: str | None
    model_name: str
    version: str
    status: str
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    skill_ids: list[uuid.UUID] = Field(default_factory=list)
    tool_ids: list[uuid.UUID] = Field(default_factory=list)
    plugin_ids: list[uuid.UUID] = Field(default_factory=list)
    hook_ids: list[uuid.UUID] = Field(default_factory=list)
    playbook_ids: list[uuid.UUID] = Field(default_factory=list)

    @classmethod
    def from_orm_agent(cls, agent) -> "AgentRead":
        return cls(
            id=agent.id,
            tenant_id=agent.tenant_id,
            name=agent.name,
            description=agent.description,
            is_active=agent.is_active,
            system_prompt=agent.system_prompt,
            model_name=agent.model_name,
            version=agent.version,
            status=agent.status,
            owner_id=agent.owner_id,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
            skill_ids=[s.id for s in agent.skills],
            tool_ids=[t.id for t in agent.tools],
            plugin_ids=[p.id for p in agent.plugins],
            hook_ids=[h.id for h in agent.hooks],
            playbook_ids=[p.id for p in agent.playbooks],
        )
