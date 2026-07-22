import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

USAGE_EVENT_TYPES = ("chat_turn", "tool_call", "skill_call")
USAGE_EVENT_STATUSES = ("ok", "error")


class UsageEvent(Base):
    """One real, recorded unit of agent usage — written by
    app/api/routes/chat.py at the end of every streamed turn (see
    app/services/agent_runner.py::stream_agent_response). Backs the Super
    Admin's cost/billing and platform-health views: the token counts and
    latency here are the same numbers the chat turn itself produced
    (tokens = actual streamed word-chunks, latency = wall-clock duration
    of the generator), nothing is fabricated after the fact.

    model_route_id is resolved by matching the responding Agent's
    model_name against ModelRoute.name (see app/services/pricing.py); left
    NULL when no catalog entry matches, in which case cost_usd falls back
    to a flat default rate rather than silently being left at 0 — see
    pricing.py's DEFAULT_COST_PER_1M.
    """

    __tablename__ = "usage_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    model_route_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("model_routes.id", ondelete="SET NULL"), nullable=True)

    event_type: Mapped[str] = mapped_column(String(20), nullable=False, default="chat_turn")
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
