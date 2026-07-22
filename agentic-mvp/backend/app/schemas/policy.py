import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.policy import POLICY_MODES


class PolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    rule_expression: str = Field(min_length=1, max_length=500)
    mode: str = Field(default="dry_run", pattern="^(" + "|".join(POLICY_MODES) + ")$")
    is_active: bool = True


class PolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    rule_expression: str | None = Field(default=None, min_length=1, max_length=500)
    mode: str | None = Field(default=None, pattern="^(" + "|".join(POLICY_MODES) + ")$")
    is_active: bool | None = None


class PolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    rule_expression: str
    mode: str
    is_active: bool
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class PolicyMappingCreate(BaseModel):
    user_id: uuid.UUID
    policy_id: uuid.UUID


class PolicyMappingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    policy_id: uuid.UUID
    created_at: datetime
