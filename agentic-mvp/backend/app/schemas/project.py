import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.project_intelligence_binding import COMPONENT_TYPES

EXECUTION_MODES = ("event_driven", "real_time_chat", "scheduled")


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    cost_center: str | None = Field(default=None, max_length=100)
    execution_mode: str = Field(default="real_time_chat", pattern="^(" + "|".join(EXECUTION_MODES) + ")$")
    schedule_cron: str | None = Field(default=None, max_length=100)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    cost_center: str | None = Field(default=None, max_length=100)
    execution_mode: str | None = Field(default=None, pattern="^(" + "|".join(EXECUTION_MODES) + ")$")
    schedule_cron: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    cost_center: str | None
    status: str
    execution_mode: str
    schedule_cron: str | None
    webhook_slug: str | None
    frozen_at: datetime | None
    deployed_at: datetime | None
    is_active: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ProjectUserAdd(BaseModel):
    user_id: uuid.UUID
    role_in_project: str = Field(default="member", max_length=20)


class ProjectDatasourceAdd(BaseModel):
    datasource_id: uuid.UUID


class BindingCreate(BaseModel):
    component_type: str = Field(pattern="^(" + "|".join(COMPONENT_TYPES) + ")$")
    component_id: uuid.UUID
    version_pinned: str | None = Field(default=None, max_length=30)


class BindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    component_type: str
    component_id: uuid.UUID
    version_pinned: str | None
    is_active: bool
    created_at: datetime
    # Resolved denormalized display fields — filled in by the route, not the
    # ORM row (component_id isn't a real FK, see the model docstring).
    component_name: str | None = None
    component_version: str | None = None


class TopologyMappedUser(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str
    persona_id: uuid.UUID | None = None
    persona_name: str | None = None


class TopologyDatasource(BaseModel):
    datasource_id: uuid.UUID
    name: str
    connector_type: str
    security_classification: str
    sync_status: str


class TopologyComponent(BaseModel):
    component_type: str
    component_id: uuid.UUID
    name: str
    version: str


class ProjectTopology(BaseModel):
    """The exact shape rendered by the Freeze Screen, and what freeze_project
    persists verbatim into Project.frozen_snapshot."""

    project_id: uuid.UUID
    project_name: str
    status: str
    execution_mode: str
    schedule_cron: str | None
    webhook_slug: str | None
    mapped_users: list[TopologyMappedUser]
    datasources: list[TopologyDatasource]
    intelligence: list[TopologyComponent]
    resolved_at: datetime
