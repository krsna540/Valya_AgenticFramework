import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

MODEL_KINDS = ("chat", "embed")
MODEL_STATUSES = ("live", "eval", "disabled")


class ModelRoute(Base):
    """A Super Admin-managed entry in the platform's LLM model catalog — one
    MLflow AI Gateway route a tenant's agents can be pointed at (see the
    "Model routing" selects in the Admin Expertise tab; app/models/agent.py's
    `model_name` is still just a free string, matched against `ModelRoute.name`
    at usage-recording time — see app/services/pricing.py).

    This app has no real MLflow Gateway integration (agent_runner.py is a
    deterministic stub, see its module docstring) — `gateway_configured` /
    `cost_meter_registered` are Super Admin-editable checklist flags, not
    live infrastructure probes, same scaffold-vs-real boundary as
    Datasource.connection_config. The eval gate scores below
    (`eval_faithfulness` / `eval_task_completion` / `eval_security_redteam_passed`)
    are likewise Super Admin-entered values (e.g. copied in from a real eval
    run elsewhere), not computed by this app.

    A route only counts as "Live" once status is manually set to "live" —
    the frontend additionally shows whether every gate is currently passing
    so an admin knows *why* it's still in eval.
    """

    __tablename__ = "model_routes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    route: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="chat")

    input_cost_per_1m: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    output_cost_per_1m: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="eval")

    gateway_configured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    cost_meter_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    eval_faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    eval_faithfulness_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.92)
    eval_task_completion: Mapped[float | None] = mapped_column(Float, nullable=True)
    eval_task_completion_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.85)
    eval_security_redteam_passed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def gates(self) -> dict:
        """The onboarding checklist shown alongside the catalog — see
        GET /platform/model-routes/{id}/gates. Purely derived from the
        columns above, recomputed on every read (nothing cached)."""
        faithfulness_ok = (self.eval_faithfulness or 0) >= self.eval_faithfulness_threshold
        task_ok = (self.eval_task_completion or 0) >= self.eval_task_completion_threshold
        return {
            "gateway_configured": self.gateway_configured,
            "cost_meter_registered": self.cost_meter_registered,
            "faithfulness_passed": faithfulness_ok,
            "task_completion_passed": task_ok,
            "security_redteam_passed": self.eval_security_redteam_passed,
            "all_passed": bool(
                self.gateway_configured
                and self.cost_meter_registered
                and faithfulness_ok
                and task_ok
                and self.eval_security_redteam_passed
            ),
        }
