import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class RegistryMixin:
    """Shared columns for agents/skills/tools/plugins/hooks registry entities."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantScopedMixin:
    """Adds tenant_id + SemVer version + lifecycle status to an "Intelligence
    Layer" registry entity (Agent/Skill/Tool/Plugin/SkillPackage — Hook
    already defined version/status itself before this mixin existed, so it
    isn't retrofitted onto Hook to avoid duplicate columns).

    tenant_id is nullable by design: NULL means "platform-shared" — visible
    to every tenant's registry views (read-only for non-admins of the
    tenant that doesn't own it). A non-NULL tenant_id is a tenant-private
    item, writable only by that tenant's admins. This lets a fresh tenant
    start with a non-empty catalog without seeding per-tenant copies.
    """

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    version: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0.0")
    # Active | Experimental | Deprecated — same vocabulary as Hook.status.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Active")
