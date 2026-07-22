import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Default shape of Tenant.settings — the Admin Norms tab's rate-limit
# numbers and guardrail toggles read/write this blob directly (PUT
# /tenants/me with a `settings` key — see app/api/routes/tenants.py).
# Kept as one JSONB document rather than a table of individual settings
# rows since every key here is a single tenant-wide scalar, not something
# that needs its own audit history or per-row CRUD (Policy, below, is the
# one Norms concept that does).
DEFAULT_TENANT_SETTINGS: dict = {
    "rate_limits": {
        "per_user_rpm": 60,
        "per_tenant_rpm": 1200,
        "tokens_per_day": 250_000,
    },
    "guardrails": {
        "pii_redaction": True,
        "prompt_injection_screening": True,
        "groundedness_check": True,
        "topic_blocklist": False,
    },
}


class Tenant(Base):
    """An organization. Every User belongs to exactly one Tenant, created
    automatically at signup (the signing-up user becomes that tenant's first
    'admin'). Projects/Personas/Datasources are all tenant-scoped; the
    existing Agents/Skills/Tools/Plugins/Hooks/SkillPackages registries carry
    a *nullable* tenant_id instead (NULL = platform-shared catalog item
    visible to every tenant, non-NULL = private to that tenant) — see
    app/models/mixins.py::TenantScopedMixin.
    """

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Rate limits + guardrail toggles shown in the Admin Norms tab — see
    # DEFAULT_TENANT_SETTINGS above for the expected shape (validated
    # server-side by app/schemas/tenant.py::TenantSettings, stored
    # schema-less so a new guardrail doesn't need a migration).
    settings: Mapped[dict] = mapped_column(JSONB, default=lambda: dict(DEFAULT_TENANT_SETTINGS), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
