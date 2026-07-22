"""Message-tree traversal for branching chat threads.

Design (see models/chat.py for the field-level rationale):
- Every message has a `parent_message_id`. Root messages (first turn) have
  parent_message_id = NULL.
- Multiple agents can respond to the same user message (split-screen compare):
  those responses are siblings that differ by `agent_id`, and are NOT
  alternatives to each other — they render side by side.
- Editing a user message, or regenerating one agent's response, creates an
  alternative within the same (parent_message_id, agent_id) group. Exactly one
  message in that group has is_active_branch=True; the others are kept but
  hidden from the active thread.
- The "active thread" is computed by walking level by level: start at the
  active root(s), then repeatedly fetch active children of the current
  frontier. Because non-primary agent responses never gain children (the next
  user turn only ever attaches under the primary agent's response), this
  naturally yields a linear backbone with parallel agent columns fanned out at
  each assistant turn.
"""
import uuid

from sqlalchemy.orm import Session

from app.models.chat import Message


def get_active_thread(db: Session, conversation_id: uuid.UUID) -> list[Message]:
    roots = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation_id,
            Message.parent_message_id.is_(None),
            Message.is_active_branch == True,  # noqa: E712
        )
        .order_by(Message.created_at)
        .all()
    )

    thread: list[Message] = list(roots)
    frontier_ids = [m.id for m in roots]

    while frontier_ids:
        children = (
            db.query(Message)
            .filter(
                Message.parent_message_id.in_(frontier_ids),
                Message.is_active_branch == True,  # noqa: E712
            )
            .order_by(Message.created_at)
            .all()
        )
        if not children:
            break
        thread.extend(children)
        frontier_ids = [c.id for c in children]

    return thread


def get_siblings(db: Session, message_id: uuid.UUID) -> list[Message]:
    """All messages sharing (parent_message_id, agent_id) with the given message,
    i.e. the alternative-branch group it belongs to."""
    target = db.get(Message, message_id)
    if target is None:
        return []
    return (
        db.query(Message)
        .filter(
            Message.conversation_id == target.conversation_id,
            Message.parent_message_id == target.parent_message_id,
            Message.agent_id == target.agent_id,
        )
        .order_by(Message.created_at)
        .all()
    )


def select_branch(db: Session, message_id: uuid.UUID) -> Message:
    """Make `message_id` the active branch within its sibling group."""
    target = db.get(Message, message_id)
    if target is None:
        raise ValueError("message not found")

    siblings = get_siblings(db, message_id)
    for sibling in siblings:
        sibling.is_active_branch = sibling.id == target.id
    db.commit()
    db.refresh(target)
    return target


def create_message(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    parent_message_id: uuid.UUID | None,
    role: str,
    content: str,
    agent_id: uuid.UUID | None = None,
    file_ids: list[uuid.UUID] | None = None,
    citations: list[dict] | None = None,
) -> Message:
    """Insert a message, deactivating any existing sibling in the same
    (parent_message_id, agent_id) group so the new one becomes the active branch."""
    if parent_message_id is not None:
        existing_siblings = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation_id,
                Message.parent_message_id == parent_message_id,
                Message.agent_id == agent_id,
            )
            .all()
        )
        for sibling in existing_siblings:
            sibling.is_active_branch = False

    message = Message(
        conversation_id=conversation_id,
        parent_message_id=parent_message_id,
        agent_id=agent_id,
        role=role,
        content=content,
        is_active_branch=True,
        file_ids=[str(fid) for fid in (file_ids or [])],
        citations=citations or [],
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
