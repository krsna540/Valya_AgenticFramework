"""The manifest — PLATFORM_ARCHITECTURE.md §6, the bridge between the
control plane (this table) and the data plane (the agent runtime, which
receives only `manifest_id`, never the body — §6.3's "the workflow receives
one hash").

Deduplicated by content hash: resolving the same project/prompt/skill/tool/
hook/policy combination twice returns the same manifest_id and does not
insert a second row (see app/services/manifest.py::compile_manifest). That
is what makes "these two runs used identical configuration" a row-equality
check instead of a deep-diff.

This table is the durable copy (§6.2 step 10); the fast handoff copy lives
in Redis under `manifest:{session_id}` with a short TTL (step 11) — see
app/core/redis_client.py. Session rows point at a manifest_id, never embed
it, so many sessions can share one manifest row.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Manifest(Base):
    __tablename__ = "manifests"

    # sha256 of the RFC-8785-canonicalized body — the primary key IS the
    # content hash (§6.2 step 9), so INSERT ... ON CONFLICT DO NOTHING is
    # the entire dedup mechanism (see manifest.py).
    manifest_id: Mapped[str] = mapped_column(String(71), primary_key=True)  # "sha256:" + 64 hex chars

    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[int] = mapped_column(nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ManifestSession(Base):
    """One row per compiled session (§6.2 step 10's "sessions row"). Kept
    separate from Manifest itself so the many-sessions-per-manifest
    relationship (§6.3's "ten thousand sessions... share one manifest row")
    is explicit rather than implied by a foreign key on a table that is
    supposed to be pure content.
    """

    __tablename__ = "manifest_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    manifest_id: Mapped[str] = mapped_column(String(71), ForeignKey("manifests.manifest_id", ondelete="CASCADE"), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False, default="en")

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active|ended
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
