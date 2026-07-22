import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

POLICY_MODES = ("enforced", "dry_run")


class Policy(Base):
    """A tenant's named access-control rule, shown in the Admin Norms tab
    ("Access policies (OPA / Rego)"). This is a *display/management*
    record only — the strings in `rule_expression` are not compiled into
    real Qdrant payload filters or evaluated against live retrieval, since
    this app has no retrieval pipeline of its own (that lives in the
    sibling milestone-based codebase). It documents tenant intent the same
    way Datasource.connection_config documents a connector's shape without
    a live connector behind it — see that model's docstring for the same
    scaffold-vs-real boundary. The actual OPA instance this app talks to
    (backend/policies/authz.rego, app/core/opa.py) answers a different,
    unrelated question — coarse role/resource-type authorization — and is
    not affected by rows in this table.
    """

    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_expression: Mapped[str] = mapped_column(String(500), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="dry_run")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tenant = relationship("Tenant")


class UserPolicyMapping(Base):
    """Binds a User to a Policy that specifically applies to them — the
    Norms tab's "Users & assignments" panel, alongside the equivalent
    UserPersonaMapping (app/models/persona.py). Most policies are meant to
    apply tenant-wide (that's what Policy.is_active + mode already convey);
    this table is for the narrower case of a policy an admin wants to call
    out as applying to one specific person (e.g. a contractor-scope-limit
    policy only relevant to contractor accounts) — same
    display/management-only scaffold boundary as Policy itself, see that
    model's docstring.
    """

    __tablename__ = "user_policy_mappings"
    __table_args__ = (UniqueConstraint("user_id", "policy_id", name="uq_user_policy"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("policies.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", foreign_keys=[user_id])
    policy = relationship("Policy")
