import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# component_id is intentionally NOT a foreign key: it points into one of
# five different tables depending on component_type (agents/tools/hooks/
# skills/plugins), which SQLAlchemy/Postgres can't express as a single FK
# without a polymorphic-association pattern that would be overkill here.
# app/api/routes/projects.py validates component_id actually exists in the
# right table at write time instead.
#
# "skill_package" used to be a sixth, separate component_type (the
# handler_key Skill and the folder-format SkillPackage were two different
# models/tables) — retired along with the handler_key Skill system; "skill"
# now means the folder-format model exclusively. See
# [[project_agentic_mvp_nexusclaw_manifest_conventions]] /
# docs/SKILL_STANDARD.md.
COMPONENT_TYPES = ("agent", "tool", "hook", "skill", "plugin")


class ProjectIntelligenceBinding(Base):
    """The association-matrix row: "for Project X, attach Agent v1.2 / grant
    the Jira MCP Tool / apply the PII-Scrubber Hook / activate the Excel
    Generation Skill." One row per (project, component_type, component_id).

    version_pinned freezes a specific SemVer string at bind time; NULL means
    "always resolve to whatever the component's current version column
    says" (floating/latest). Either way, the *resolved* version actually
    used is captured into Project.frozen_snapshot at freeze time, so a
    frozen/deployed project's history is never ambiguous even if the
    underlying registry item's version later changes.
    """

    __tablename__ = "project_intelligence_bindings"
    __table_args__ = (
        UniqueConstraint("project_id", "component_type", "component_id", name="uq_project_component"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    component_type: Mapped[str] = mapped_column(String(20), nullable=False)
    component_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version_pinned: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
