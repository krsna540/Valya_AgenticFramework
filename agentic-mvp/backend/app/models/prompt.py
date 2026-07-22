from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import RegistryMixin, TenantScopedMixin


class Prompt(RegistryMixin, TenantScopedMixin, Base):
    """A reusable prompt template, surfaced in chat via the '/' command menu.

    Structure adopted from market-standard prompt management conventions
    (Langfuse/LangSmith Hub/PromptLayer — see docs/SKILL_STANDARD.md's
    Prompts section): a prompt is chat-style `messages` with `{{variable}}`
    placeholders, a declared `variables` contract, and its own `model_config`
    — versioned as one unit (Langfuse: "versioning of the entire context,
    including logic, model settings, parameters"), same as this app's other
    Intelligence Layer entities via TenantScopedMixin (tenant_id/version/
    status). `label` mirrors Langfuse's "labels" / MLflow's "aliases"
    (e.g. "production", "staging", "latest") for promoting a version without
    renaming it.

    This previously had a single flat `content: Text` column with no
    tenant_id at all (any authenticated user, any tenant, could edit any
    prompt) — TenantScopedMixin closes that gap; content was backfilled into
    messages by the migration that added these columns.
    """

    __tablename__ = "prompts"

    # [{role: "system"|"user"|"assistant", content: str}, ...]
    messages: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # [{name, description, default, required}, ...] — declares the
    # {{variable}} placeholders used across `messages`.
    variables: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # {model, temperature, max_tokens, top_p, stop: [str, ...]}. Named
    # `model_params`, not `model_config` — the latter is a reserved
    # attribute name on every pydantic BaseModel (used for pydantic's own
    # ConfigDict), so the API-layer schema can't call a field that anyway,
    # and this column stays consistent with it rather than diverging.
    model_params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # Free-text promotion label a la Langfuse labels / MLflow aliases —
    # "production"/"staging"/"latest" are the common ones but not enforced.
    label: Mapped[str] = mapped_column(default="latest", nullable=False)
