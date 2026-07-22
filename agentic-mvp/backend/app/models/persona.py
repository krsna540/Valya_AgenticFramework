import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Persona(Base):
    """An AI behavioral template a user can adopt when working inside a
    Project. `traits` is a single JSONB document holding the 9 free-form
    trait categories from the spec (everything except Identity/Archetype,
    which gets its own `archetype` column since it's used for filtering/
    display, and Safety & Compliance's tier, which also gets its own column
    for the same reason). See app/schemas/persona.py::PersonaTraits for the
    documented shape of each key — validated server-side but stored schema-
    less so new trait fields don't need a migration.

    Expected `traits` keys: core_objectives, target_audience,
    capabilities_tools, knowledge_domain, guardrails_boundaries, tone_voice,
    personality_quirks, interaction_style, safety_compliance (full object;
    safety_compliance_tier below is a denormalized summary field of just
    one part of it, matching the reference DDL).
    """

    __tablename__ = "personas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # Identity & Archetype's headline field, e.g. "Senior Financial Auditor".
    archetype: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Base model this persona is aligned to (Identity & Archetype vector).
    base_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    traits: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # Denormalized out of traits.safety_compliance for quick filtering/badges
    # (e.g. "Strict", "Standard", "Relaxed") — matches the reference DDL.
    safety_compliance_tier: Mapped[str] = mapped_column(String(50), nullable=False, default="Standard")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tenant = relationship("Tenant")


class UserPersonaMapping(Base):
    """Binds a User to a Persona they're allowed to adopt. Optionally scoped
    to a single Project (a persona chosen "for this project only"); NULL
    project_id means the mapping is tenant-wide. is_default marks which
    persona a user should land on when entering a project with no explicit
    per-conversation override."""

    __tablename__ = "user_persona_mappings"
    __table_args__ = (UniqueConstraint("user_id", "persona_id", "project_id", name="uq_user_persona_project"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    persona_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("personas.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", foreign_keys=[user_id])
    persona = relationship("Persona")
