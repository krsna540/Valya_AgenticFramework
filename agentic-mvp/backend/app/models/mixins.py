import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

# The two access-modifier axes described in PLATFORM_ARCHITECTURE.md §7.2,
# applied to every registry kind (skills/prompts/tools/hooks/plugins).
# Axis 1 (access_class) says who may MUTATE a row; axis 2 (visibility) says
# who may SEE/USE it. They are independent — see RegistryAccessMixin below.
ACCESS_CLASSES = ("default", "custom")
VISIBILITIES = ("public", "protected", "private")


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


class RegistryAccessMixin:
    """The two independent access-modifier axes from
    PLATFORM_ARCHITECTURE.md §7.2, added 2026-08-08 (migration 0016) on top
    of every registry kind — skills/prompts/tools/hooks/plugins/agents.

    access_class — who may MUTATE this row:
      "default" -> platform-shipped baseline (tenant_id IS NULL). Writable
                   by super_admin only, regardless of visibility.
      "custom"  -> tenant-authored. Writable by super_admin and that
                   tenant's admins.

    visibility — who may SEE/USE this row (meaningless for access_class=
    "default", which is implicitly readable by every tenant via the existing
    tenant_id-IS-NULL convention):
      "public"    -> every tenant may read + fork it
      "protected" -> every project inside the OWNING tenant may use it
      "private"   -> only projects it is explicitly bound to, plus its owner

    forked_from_id / forked_from_version record provenance when a row was
    created by forking a default or public entity (§7.5) — never a foreign
    key, deliberately: the source row can live in the same table (a normal
    self-fork) but the column is kept untyped-UUID so it survives the source
    being archived, same reasoning as ProjectIntelligenceBinding.component_id
    not being an FK.

    owner_user_id is the named human invariant M3 requires before anything
    reaches LIVE (Frozen Spec §6.2) — nullable here only because it is
    backfilled NULL for rows that existed before this migration; the write
    path requires it going forward (see app/schemas/registry_access.py).
    """

    access_class: Mapped[str] = mapped_column(String(20), nullable=False, default="custom")
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="private")
    forked_from_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    forked_from_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class TenantScopedMixin(RegistryAccessMixin):
    """Adds tenant_id + SemVer version + lifecycle status to an "Intelligence
    Layer" registry entity (Agent/Skill/Tool/Plugin/SkillPackage — Hook
    already defined version/status itself before this mixin existed, so it
    isn't retrofitted onto Hook to avoid duplicate columns; Hook instead
    inherits RegistryAccessMixin directly — see app/models/hook.py).

    tenant_id is nullable by design: NULL means "platform-shared" — visible
    to every tenant's registry views (read-only for non-admins of the
    tenant that doesn't own it). A non-NULL tenant_id is a tenant-private
    item, writable only by that tenant's admins. This lets a fresh tenant
    start with a non-empty catalog without seeding per-tenant copies.

    As of migration 0016, tenant_id IS NULL is exactly access_class=
    "default" — the two are kept in sync at the write path (see
    app/services/registry_access.py::assign_access_class), not merged into
    one column, so existing tenant_id-based queries throughout the app keep
    working unchanged.
    """

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    version: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0.0")
    # Active | Experimental | Deprecated — same vocabulary as Hook.status.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Active")
