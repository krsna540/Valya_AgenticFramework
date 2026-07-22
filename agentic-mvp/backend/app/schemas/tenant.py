import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RateLimitSettings(BaseModel):
    per_user_rpm: int = Field(default=60, ge=1)
    per_tenant_rpm: int = Field(default=1200, ge=1)
    tokens_per_day: int = Field(default=250_000, ge=1)


class GuardrailSettings(BaseModel):
    pii_redaction: bool = True
    prompt_injection_screening: bool = True
    groundedness_check: bool = True
    topic_blocklist: bool = False


class TenantSettings(BaseModel):
    """Shape of Tenant.settings — see DEFAULT_TENANT_SETTINGS in
    app/models/tenant.py. Rendered/edited from the Admin Norms tab's
    "Rate limits" and "Guardrails" cards via PUT /tenants/me."""

    rate_limits: RateLimitSettings = Field(default_factory=RateLimitSettings)
    guardrails: GuardrailSettings = Field(default_factory=GuardrailSettings)


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    is_active: bool
    settings: dict
    created_at: datetime


class TenantSummary(TenantRead):
    """What the Super Admin's Tenants table renders — TenantRead plus
    everything computed at query time in GET /platform/tenants (see that
    route for how each field is derived). Nothing here is stored on the
    Tenant row itself."""

    admin_count: int
    user_count: int
    workspace_count: int
    mtd_cost_usd: float
    layer_knowledge: bool
    layer_expertise: bool
    layer_norms: bool
    status_label: str


class TenantUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    settings: TenantSettings | None = None


class TenantCreate(BaseModel):
    """Super Admin-only (POST /platform/tenants) — the counterpart to
    /auth/signup's implicit tenant creation, for when a Super Admin is
    provisioning a tenant up front rather than a customer signing
    themselves up. Slug is auto-derived from name (same _unique_slug
    logic as signup), not settable directly."""

    name: str = Field(min_length=1, max_length=255)
