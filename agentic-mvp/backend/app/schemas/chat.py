import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConversationCreate(BaseModel):
    agent_id: uuid.UUID
    secondary_agent_ids: list[uuid.UUID] = Field(default_factory=list)
    title: str = Field(default="New conversation", max_length=255)
    # Optional Project scope — the "User flow": pick a project you're mapped
    # to, then only agents bound to that project (via the association
    # matrix) may be used. Omit for the original unscoped chat behavior.
    project_id: uuid.UUID | None = None


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    secondary_agent_ids: list[uuid.UUID]
    title: str
    project_id: uuid.UUID | None = None
    created_at: datetime


class Citation(BaseModel):
    id: str
    source: str
    snippet: str


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    parent_message_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    role: str
    content: str
    is_active_branch: bool
    citations: list[Citation]
    file_ids: list[uuid.UUID]
    created_at: datetime


class ConversationWithMessages(ConversationRead):
    messages: list[MessageRead] = Field(default_factory=list)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    file_ids: list[uuid.UUID] = Field(default_factory=list)
    # Set when editing an earlier message / regenerating: the parent to attach
    # the new sibling to. Omit to append to the current active thread tip.
    parent_message_id: uuid.UUID | None = None
    # Override which agents respond to this turn. Omit to use the
    # conversation's configured agent_id + secondary_agent_ids.
    agent_ids: list[uuid.UUID] | None = None
    # Task-specific hook scope: extra hooks active for just this one request,
    # in addition to global hooks and the responding agent's attached hooks.
    # Not persisted anywhere — exists only for the duration of this call.
    hook_ids: list[uuid.UUID] = Field(default_factory=list)


class SiblingInfo(BaseModel):
    id: uuid.UUID
    is_active_branch: bool
    created_at: datetime


class SiblingGroup(BaseModel):
    parent_message_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    active_index: int
    siblings: list[SiblingInfo]


class SelectBranchRequest(BaseModel):
    message_id: uuid.UUID


class TitleResponse(BaseModel):
    title: str
