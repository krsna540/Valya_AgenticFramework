import uuid

from sqlalchemy import Column, ForeignKey, String, Table, Text
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

    owner = relationship("User")
    skills = relationship("Skill", secondary="agent_skills")
    tools = relationship("Tool", secondary=agent_tools)
    plugins = relationship("Plugin", secondary=agent_plugins)
    hooks = relationship("Hook", secondary=agent_hooks)
