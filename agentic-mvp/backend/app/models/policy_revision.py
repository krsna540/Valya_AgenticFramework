"""Platform rules — the superadmin-app.html "Platform rules" screen.

Distinct from the existing tenant-scoped `Policy` rows (app/models/
policy.py, the Admin Norms tab's per-tenant OPA/Rego display records): a
PolicyRevision is the platform-wide floor every tenant inherits and cannot
loosen (PLATFORM_ARCHITECTURE.md §7.4's super_admin-owned "policy source").
Modeled as numbered, append-only revisions — "rev 214", never edited in
place — mirroring how the Frozen Spec's OPA bundle is versioned (§3.9): a
change is a new revision, rollback is re-pointing "current" at an older one,
never a mutation of history.

`rules` is a JSON snapshot of the named invariants (see
app/services/platform_rules.py::DEFAULT_RULES for the seed content mirrored
from the mockup: "nothing crosses between organisations", "results follow
existing access", etc.) rather than compiled Rego, because this app's real
OPA instance (backend/policies/authz.rego) answers a different, coarser
question — see app/models/policy.py's docstring for the same
display-vs-live-infrastructure boundary applied one level up.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PolicyRevision(Base):
    __tablename__ = "policy_revisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rules: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    tests_passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    published_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
