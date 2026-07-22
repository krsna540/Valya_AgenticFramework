import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Every user belongs to exactly one tenant, EXCEPT super_admin, which is
    # platform-level and belongs to none (nullable for that reason — see
    # docs/AUTHORIZATION.md). Created automatically at signup (see auth.py)
    # — the signing-up user becomes that tenant's first "admin". Additional
    # users are created by an admin via /admin/users (always inside the
    # admin's own tenant, and only as role="user" — see
    # backend/policies/authz.rego's _privileged_user_write) or by a
    # super_admin via /platform (any tenant, any role).
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)
    # The three OPA-backed authorization flows (backend/policies/authz.rego,
    # app/core/opa.py) — this column is the "subject.role" input to every
    # authorization decision in the app:
    #   "super_admin" -> unrestricted; the only role that can manage Tenant
    #                    rows themselves or assign admins to tenants.
    #                    tenant_id is always NULL for this role.
    #   "admin"       -> full CRUD on everything within their own tenant
    #                    (users [but not other admins/super admins],
    #                    projects incl. freeze/deploy, agents, skills,
    #                    hooks, plugins, prompts, personas, datasources,
    #                    tools).
    #   "user"        -> agents (read-only) + chat only. (Was "member"
    #                    before the three-role model — see migration 0012.)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tenant = relationship("Tenant")
