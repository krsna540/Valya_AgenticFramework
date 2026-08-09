"""Pydantic shapes for the Platform rules screen. See
app/models/policy_revision.py and app/services/platform_rules.py for the
data model and seed content this wraps."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PolicyRule(BaseModel):
    name: str
    detail: str
    bound: str


class PolicyRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    revision_number: int
    summary: str
    rules: list[PolicyRule]
    tests_passed: int
    is_current: bool
    published_by_name: str | None = None
    created_at: datetime


class PolicyRevisionPublish(BaseModel):
    summary: str
    rules: list[PolicyRule]
