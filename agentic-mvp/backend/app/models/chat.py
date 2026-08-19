import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Optional Project scope — when set, the "User flow" from the project
    # brief applies: the agent below must be bound to this project (see
    # GET /projects/{id}/available-agents), and access requires the current
    # user to be mapped to the project via project_users. NULL keeps the
    # original unscoped chat behavior (pick any agent you own/can see).
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    # Primary/anchor agent: drives the linear thread backbone (title, continuation).
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    # Extra agents compared side-by-side in split-screen mode. Full active set
    # for a turn = [agent_id] + secondary_agent_ids. Responses from secondary
    # agents are leaves (the thread never continues *through* them) — see
    # app/services/thread.py for the traversal rationale.
    secondary_agent_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="New conversation", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    agent = relationship("Agent", foreign_keys=[agent_id])
    messages = relationship(
        "Message", back_populates="conversation", order_by="Message.created_at", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # Self-referential tree: null parent = a root turn. Editing a user message
    # or regenerating an agent response creates a *sibling* (same parent_message_id
    # + same agent_id "slot"), not a child — see is_active_branch.
    parent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=True
    )
    # Set for assistant messages so multi-agent (split-screen) responses to the
    # same parent can be told apart. Null for user/system messages.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant" | "system"
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Within the sibling group (parent_message_id, agent_id), exactly one
    # message is_active_branch=True at a time. Rendering the conversation
    # walks the tree following only active-branch messages; switching branches
    # just flips this flag, the alternates stay in the DB.
    is_active_branch: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    citations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    file_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # User-submitted feedback on an assistant reply — "like" | "dislike" | null.
    # Mutually exclusive by construction (single column, not two booleans).
    feedback: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Optional reason chip/free-text captured when feedback == "dislike".
    feedback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    conversation = relationship("Conversation", back_populates="messages")
    agent = relationship("Agent", foreign_keys=[agent_id])
