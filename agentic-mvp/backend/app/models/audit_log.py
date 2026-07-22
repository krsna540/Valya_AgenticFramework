import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuditLog(Base):
    """An append-only record of a state-changing action, written by
    app/services/audit.py::record() from inside the mutation routes that
    matter for the Super Admin's Audit view (tenant/admin lifecycle, user
    role changes, datasource connect/sync, policy and model-route changes,
    project freeze/deploy). Not every mutation in the app is instrumented —
    see audit.py's module docstring for exactly which routes call it; this
    is a real but intentionally non-exhaustive audit trail, not a generic
    ORM-level change-data-capture system.

    tenant_id is NULL for platform-level actions with no single owning
    tenant (e.g. a Super Admin creating a new Tenant itself). actor_email
    is a point-in-time snapshot (not a live join to User) so the log stays
    readable after an actor account is later deleted.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
