import uuid

from sqlalchemy import JSON, Column, ForeignKey, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import RegistryMixin, TenantScopedMixin

# agent_skills lives in app/models/skill.py — imported there so Agent.skills
# can reference it via the secondary= string lookup below without a
# circular import (same pattern as the historical agent_skill_packages).

agent_tools = Table(
    "agent_tools",
    Base.metadata,
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("tool_id", UUID(as_uuid=True), ForeignKey("tools.id", ondelete="CASCADE"), primary_key=True),
)

agent_plugins = Table(
    "agent_plugins",
    Base.metadata,
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("plugin_id", UUID(as_uuid=True), ForeignKey("plugins.id", ondelete="CASCADE"), primary_key=True),
)

agent_hooks = Table(
    "agent_hooks",
    Base.metadata,
    Column("agent_id", UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
    Column("hook_id", UUID(as_uuid=True), ForeignKey("hooks.id", ondelete="CASCADE"), primary_key=True),
)


class Agent(RegistryMixin, TenantScopedMixin, Base):
    __tablename__ = "agents"

    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(String(255), default="stub-echo", nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    # Per-agent tuning for the Planner -> Executor -> Critic runtime: revision
    # and replan budgets, node timeouts, whether the critic runs at all,
    # whether tools may actually be invoked. Validated into an
    # `AgentRuntimeConfig` at run start (app/agents/config.py), which drops
    # unknown keys and falls back to defaults on a malformed value — a bad
    # admin edit degrades one agent's tuning rather than 500-ing chat.
    #
    # Empty dict = "use the defaults", which is what every existing row gets
    # from the migration. Deployment-wide settings (gateway URL, whether
    # Temporal is on) deliberately live in app/core/config.py instead, so a
    # tenant admin can tune budgets without being able to repoint the model
    # gateway.
    runtime_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    owner = relationship("User")
    skills = relationship("Skill", secondary="agent_skills")
    tools = relationship("Tool", secondary=agent_tools)
    plugins = relationship("Plugin", secondary=agent_plugins)
    hooks = relationship("Hook", secondary=agent_hooks)
