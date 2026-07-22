"""Plugin schemas. Not built on the generic RegistryCreate/Update/Read
(app/schemas/registry.py) — Plugin now carries structured exports/requires
fields (see app/models/plugin.py) that the generic registry schemas don't
know about, the same reason Tool and Hook have their own schemas.

Validation mirrors NexusClaw's PluginRegistry.install() transactional check
("any malformed component aborts the install") but adapted to this app's
no-stored-code invariant — with one asymmetry worth noting: `exports_hooks`
is still checked against a fixed Python catalog (BUILTIN_HOOKS), but
`exports_skills` is NOT checked against anything here anymore. Skills used
to be handler_key-bound to a fixed BaseSkill/SKILL_REGISTRY catalog (the
same shape as hooks) — that system was retired in favor of the SKILL.md-
folder format (app/models/skill.py), which is user-uploaded, tenant-scoped,
dynamic content, not a fixed in-process registry a pydantic validator can
check against without a DB session. `exports_skills` is therefore advisory
today, same as `exports_tools`/`exports_commands` always were.
"""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _validate_exports_hooks(exports_hooks: list[str]) -> None:
    from app.services.hooks import BUILTIN_HOOKS

    unknown_hooks = [h for h in exports_hooks if h not in BUILTIN_HOOKS]
    if unknown_hooks:
        raise ValueError(f"exports_hooks references unknown handler_key(s): {unknown_hooks}")


class PluginCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    config: dict = Field(default_factory=dict)
    version: str = Field(default="1.0.0", max_length=30)
    status: str = Field(default="Active", pattern="^(Active|Experimental|Deprecated)$")

    exports_skills: list[str] = Field(default_factory=list)
    exports_hooks: list[str] = Field(default_factory=list)
    exports_tools: list[str] = Field(default_factory=list)
    exports_commands: list[str] = Field(default_factory=list)
    requires_permissions: list[str] = Field(default_factory=list)
    requires_env: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate(self) -> "PluginCreate":
        _validate_exports_hooks(self.exports_hooks)
        return self


class PluginUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    config: dict | None = None
    version: str | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, pattern="^(Active|Experimental|Deprecated)$")

    exports_skills: list[str] | None = None
    exports_hooks: list[str] | None = None
    exports_tools: list[str] | None = None
    exports_commands: list[str] | None = None
    requires_permissions: list[str] | None = None
    requires_env: list[str] | None = None

    @model_validator(mode="after")
    def _validate(self) -> "PluginUpdate":
        if self.exports_hooks is not None:
            _validate_exports_hooks(self.exports_hooks)
        return self


class PluginRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    name: str
    description: str | None
    is_active: bool
    config: dict
    version: str
    status: str
    exports_skills: list[str]
    exports_hooks: list[str]
    exports_tools: list[str]
    exports_commands: list[str]
    requires_permissions: list[str]
    requires_env: list[str]
    created_at: datetime
    updated_at: datetime
