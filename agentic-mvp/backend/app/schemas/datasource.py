import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.datasource import AUTH_TYPES, CONNECTOR_TYPES, SECURITY_TIERS, SYNC_MODES


class DatasourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    connector_type: str = Field(pattern="^(" + "|".join(CONNECTOR_TYPES) + ")$")
    connection_config: dict = Field(default_factory=dict)
    auth_config: dict = Field(default_factory=dict)
    auth_type: str = Field(default="none", pattern="^(" + "|".join(AUTH_TYPES) + ")$")
    security_classification: str = Field(default="Internal", pattern="^(" + "|".join(SECURITY_TIERS) + ")$")
    chunking_policy: dict = Field(default_factory=lambda: {"strategy": "token", "chunk_size": 800, "overlap": 100})
    embedding_policy: dict = Field(default_factory=lambda: {"model_name": "text-embedding-3-small", "dimensions": 1536})
    sync_mode: str = Field(default="full_refresh", pattern="^(" + "|".join(SYNC_MODES) + ")$")
    sync_schedule_cron: str | None = Field(default=None, max_length=100)
    is_active: bool = True


class DatasourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    connection_config: dict | None = None
    auth_config: dict | None = None
    auth_type: str | None = Field(default=None, pattern="^(" + "|".join(AUTH_TYPES) + ")$")
    security_classification: str | None = Field(default=None, pattern="^(" + "|".join(SECURITY_TIERS) + ")$")
    chunking_policy: dict | None = None
    embedding_policy: dict | None = None
    sync_mode: str | None = Field(default=None, pattern="^(" + "|".join(SYNC_MODES) + ")$")
    sync_schedule_cron: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None


class DatasourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    connector_type: str
    connection_config: dict
    auth_status: str
    auth_config: dict
    auth_type: str
    security_classification: str
    sync_status: str
    last_synced_at: datetime | None
    chunking_policy: dict
    embedding_policy: dict
    sync_mode: str
    sync_schedule_cron: str | None
    is_active: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
