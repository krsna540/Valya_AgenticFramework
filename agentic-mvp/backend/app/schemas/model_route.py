import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.model_route import MODEL_KINDS, MODEL_STATUSES


class ModelRouteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=100)
    route: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="chat", pattern="^(" + "|".join(MODEL_KINDS) + ")$")
    input_cost_per_1m: float = Field(default=0.0, ge=0)
    output_cost_per_1m: float | None = Field(default=None, ge=0)
    status: str = Field(default="eval", pattern="^(" + "|".join(MODEL_STATUSES) + ")$")
    gateway_configured: bool = False
    cost_meter_registered: bool = False
    eval_faithfulness_threshold: float = 0.92
    eval_task_completion_threshold: float = 0.85


class ModelRouteUpdate(BaseModel):
    provider: str | None = Field(default=None, max_length=100)
    route: str | None = Field(default=None, max_length=120)
    input_cost_per_1m: float | None = Field(default=None, ge=0)
    output_cost_per_1m: float | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, pattern="^(" + "|".join(MODEL_STATUSES) + ")$")
    gateway_configured: bool | None = None
    cost_meter_registered: bool | None = None
    eval_faithfulness: float | None = Field(default=None, ge=0, le=1)
    eval_task_completion: float | None = Field(default=None, ge=0, le=1)
    eval_security_redteam_passed: bool | None = None
    is_active: bool | None = None


class ModelGates(BaseModel):
    gateway_configured: bool
    cost_meter_registered: bool
    faithfulness_passed: bool
    task_completion_passed: bool
    security_redteam_passed: bool
    all_passed: bool


class ModelRouteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    provider: str
    route: str
    kind: str
    input_cost_per_1m: float
    output_cost_per_1m: float | None
    status: str
    gateway_configured: bool
    cost_meter_registered: bool
    eval_faithfulness: float | None
    eval_faithfulness_threshold: float
    eval_task_completion: float | None
    eval_task_completion_threshold: float
    eval_security_redteam_passed: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    gates: ModelGates
