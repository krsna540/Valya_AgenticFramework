import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

project_users = Table(
    "project_users",
    Base.metadata,
    Column("project_id", UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    # Reserved for future per-project role differentiation; every mapped user
    # currently gets the same (chat + insights) access described in the
    # "User flow" of the project brief. Kept as a plain string, not an enum,
    # so it can grow without a migration.
    Column("role_in_project", String(20), nullable=False, server_default="member"),
)

project_datasources = Table(
    "project_datasources",
    Base.metadata,
    Column("project_id", UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("datasource_id", UUID(as_uuid=True), ForeignKey("datasources.id", ondelete="CASCADE"), primary_key=True),
)


class Project(Base):
    """The deployment wrapper: an admin-created workspace that binds a
    tenant's Datasources, mapped Users(+Personas), and a specific slice of
    the Intelligence Layer (via ProjectIntelligenceBinding) together under
    one runtime configuration, then "freezes" that configuration into an
    immutable snapshot before deploying it.

    status is the project's own lifecycle, distinct from is_active:
      draft    -> being configured, everything below is still mutable
      frozen   -> frozen_snapshot captured (see topology resolver in
                  app/api/routes/projects.py); components/users/datasources
                  are locked from further edits until unfrozen
      deployed -> confirmed past frozen; runtime "provisioning" is a no-op
                  in this MVP (no real event listeners/schedulers are
                  started), deployed_at is just a timestamp + audit marker
      archived -> retired, hidden from the default project list
    """

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    # event_driven | real_time_chat | scheduled — see Operational Modes.
    # schedule_cron is only meaningful when execution_mode == "scheduled"
    # (cron expression, e.g. "0 17 * * FRI"); webhook_slug is only
    # meaningful when execution_mode == "event_driven" (this MVP exposes a
    # POST /projects/{id}/webhook/{webhook_slug} stub receiver, but nothing
    # actually listens to an external SharePoint/etc. webhook yet).
    execution_mode: Mapped[str] = mapped_column(String(30), nullable=False, default="real_time_chat")
    schedule_cron: Mapped[str | None] = mapped_column(String(100), nullable=True)
    webhook_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Captured by POST /projects/{id}/freeze — the exact JSON shape returned
    # live by GET /projects/{id}/topology at freeze time (personas/users,
    # datasources, intelligence composition, runtime engine). Rendered
    # read-only by the frontend's Freeze Screen once status != "draft".
    frozen_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    frozen_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tenant = relationship("Tenant")
    users = relationship("User", secondary=project_users)
    datasources = relationship("Datasource", secondary=project_datasources)
