import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import authorize, get_current_user
from app.core.database import get_db
from app.models.agent import Agent
from app.models.chat import Conversation, Message
from app.models.file import UploadedFile
from app.models.project import Project, project_users
from app.models.project_intelligence_binding import ProjectIntelligenceBinding
from app.models.usage_event import UsageEvent
from app.models.user import User
from app.services import pricing
from app.schemas.chat import (
    ConversationCreate,
    ConversationRead,
    ConversationWithMessages,
    MessageFeedbackRequest,
    MessageRead,
    SelectBranchRequest,
    SendMessageRequest,
    SiblingGroup,
    SiblingInfo,
    TitleResponse,
)
from app.services import registry_cache
from app.services.agent_runner import stream_agent_response
from app.services.hooks import HookContext, build_pipeline_for_agent, current_hook_context
from app.services.thread import create_message, get_active_thread, get_siblings, select_branch

logger = logging.getLogger("agentic_mvp.chat")

router = APIRouter(prefix="/chat", tags=["chat"])


def _sse(event_type: str, payload: dict[str, Any]) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload, default=str)}\n\n"


def _owned_conversation(db: Session, conversation_id: uuid.UUID, user: User) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


@router.get("/conversations", response_model=list[ConversationRead])
def list_conversations(
    db: Session = Depends(get_db),
    current_user: User = Depends(authorize("chat", "list")),
) -> list[Conversation]:
    return (
        db.query(Conversation)
        .filter(Conversation.user_id == current_user.id)
        .order_by(Conversation.created_at.desc())
        .all()
    )


@router.post("/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(authorize("chat", "create")),
) -> Conversation:
    agent_ids = [payload.agent_id, *payload.secondary_agent_ids]
    agents = db.query(Agent).filter(Agent.id.in_(agent_ids), Agent.is_active == True).all()  # noqa: E712
    found_ids = {a.id for a in agents}
    missing = set(agent_ids) - found_ids
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent id(s) not found or inactive: {', '.join(str(m) for m in missing)}",
        )

    if payload.project_id is not None:
        project = db.get(Project, payload.project_id)
        if project is None or (current_user.role != "super_admin" and project.tenant_id != current_user.tenant_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if current_user.role not in ("admin", "super_admin"):
            is_member = db.query(project_users).filter(
                project_users.c.project_id == project.id, project_users.c.user_id == current_user.id
            ).first()
            if is_member is None:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this project")
        bound_agent_ids = {
            b.component_id
            for b in db.query(ProjectIntelligenceBinding).filter(
                ProjectIntelligenceBinding.project_id == project.id,
                ProjectIntelligenceBinding.component_type == "agent",
                ProjectIntelligenceBinding.is_active == True,  # noqa: E712
            )
        }
        unbound = set(agent_ids) - bound_agent_ids
        if unbound:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Agent id(s) not bound to this project: {', '.join(str(m) for m in unbound)}. "
                "See GET /projects/{id}/available-agents.",
            )

    conversation = Conversation(
        user_id=current_user.id,
        agent_id=payload.agent_id,
        secondary_agent_ids=[str(i) for i in payload.secondary_agent_ids],
        title=payload.title,
        project_id=payload.project_id,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    # SessionStart: fires once per new conversation, one pipeline pass per
    # agent attached to it. Best-effort — a SessionStart hook failing (or a
    # Deny, which has no meaningful effect once the conversation already
    # exists) must never block conversation creation.
    async def _fire_session_start() -> None:
        for agent in agents:
            manager = build_pipeline_for_agent(db, agent)
            context = HookContext(agent_name=agent.name, conversation_id=str(conversation.id), user_id=str(current_user.id))
            try:
                await manager.trigger_pipeline(
                    "SessionStart", {"conversation_id": str(conversation.id), "agent_id": str(agent.id)}, context
                )
            except Exception:  # noqa: BLE001 — SessionStart must never block conversation creation
                logger.exception("SessionStart pipeline failed for agent %s", agent.id)

    try:
        asyncio.run(_fire_session_start())
    except Exception:  # noqa: BLE001
        logger.exception("SessionStart dispatch failed")

    return conversation


@router.get("/conversations/{conversation_id}", response_model=ConversationWithMessages)
def get_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(authorize("chat", "read")),
) -> ConversationWithMessages:
    conversation = _owned_conversation(db, conversation_id, current_user)
    thread = get_active_thread(db, conversation_id)
    return ConversationWithMessages(
        id=conversation.id,
        agent_id=conversation.agent_id,
        secondary_agent_ids=[uuid.UUID(i) for i in conversation.secondary_agent_ids],
        title=conversation.title,
        project_id=conversation.project_id,
        created_at=conversation.created_at,
        messages=thread,
    )


@router.get("/messages/{message_id}/siblings", response_model=SiblingGroup)
def get_message_siblings(
    message_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SiblingGroup:
    message = db.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    _owned_conversation(db, message.conversation_id, current_user)

    siblings = get_siblings(db, message_id)
    active_index = next((i for i, s in enumerate(siblings) if s.is_active_branch), 0)
    return SiblingGroup(
        parent_message_id=message.parent_message_id,
        agent_id=message.agent_id,
        active_index=active_index,
        siblings=[SiblingInfo(id=s.id, is_active_branch=s.is_active_branch, created_at=s.created_at) for s in siblings],
    )


@router.patch("/messages/{message_id}/select-branch", response_model=SiblingGroup)
def patch_select_branch(
    message_id: uuid.UUID,
    payload: SelectBranchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SiblingGroup:
    message = db.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    _owned_conversation(db, message.conversation_id, current_user)

    select_branch(db, payload.message_id)
    return get_message_siblings(message_id, db, current_user)


@router.patch("/messages/{message_id}/feedback", response_model=MessageRead)
def patch_message_feedback(
    message_id: uuid.UUID,
    payload: MessageFeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Message:
    message = db.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    _owned_conversation(db, message.conversation_id, current_user)
    if message.role != "assistant":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only assistant messages accept feedback")

    message.feedback = payload.feedback
    message.feedback_reason = payload.reason if payload.feedback == "dislike" else None
    db.commit()
    db.refresh(message)
    return message


@router.post("/conversations/{conversation_id}/title", response_model=TitleResponse)
def generate_title(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TitleResponse:
    conversation = _owned_conversation(db, conversation_id, current_user)
    thread = get_active_thread(db, conversation_id)
    first_user_message = next((m for m in thread if m.role == "user"), None)

    # Lean heuristic — swap for a real summarization call when a model is wired in.
    if first_user_message and first_user_message.content.strip():
        words = first_user_message.content.strip().split()
        title = " ".join(words[:8])
        if len(words) > 8:
            title += "…"
    else:
        title = "New conversation"

    conversation.title = title
    db.commit()
    return TitleResponse(title=title)


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: uuid.UUID,
    payload: SendMessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(authorize("chat", "create")),
) -> StreamingResponse:
    conversation = _owned_conversation(db, conversation_id, current_user)

    target_agent_ids = payload.agent_ids or [
        conversation.agent_id,
        *[uuid.UUID(i) for i in conversation.secondary_agent_ids],
    ]
    target_agents = db.query(Agent).filter(Agent.id.in_(target_agent_ids)).all()
    if not target_agents:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active agents to respond")
    # Eagerly touch relationships now, on the main sync path, so the
    # concurrent streaming tasks below never trigger their own lazy-load
    # queries against the shared session (see services/agent_runner.py).
    # tools/skills/playbooks go through registry_cache instead of a direct
    # touch: on a cache hit (the common case across a conversation's later
    # turns) this skips the agent_tools/agent_skills/agent_playbooks join
    # queries entirely rather than merely deferring them to here.
    for agent in target_agents:
        _ = (agent.plugins, agent.hooks)
        registry_cache.get_capabilities(agent)

    attached_files: list[UploadedFile] = []
    if payload.file_ids:
        attached_files = (
            db.query(UploadedFile)
            .filter(UploadedFile.id.in_(payload.file_ids), UploadedFile.uploaded_by == current_user.id)
            .all()
        )

    # Determine where this turn attaches: explicit parent for edit/regenerate,
    # otherwise the tip of the current active thread.
    parent_id = payload.parent_message_id
    if parent_id is None:
        thread = get_active_thread(db, conversation_id)
        parent_id = thread[-1].id if thread else None
        # If the current tip is an assistant message from a non-primary
        # (secondary) agent, walk back to the primary agent's reply so the
        # backbone stays anchored to one thread — see services/thread.py.
        if thread:
            primary_tip = next(
                (m for m in reversed(thread) if m.role != "assistant" or m.agent_id == conversation.agent_id),
                thread[-1],
            )
            parent_id = primary_tip.id

    user_message = create_message(
        db,
        conversation_id=conversation_id,
        parent_message_id=parent_id,
        role="user",
        content=payload.content,
        file_ids=payload.file_ids,
    )

    # One hook pipeline + context per responding agent, built up front on the
    # sync path (each does its own DB queries for global/agent/task-scoped
    # hooks) so the concurrent per-agent tasks below never touch the shared
    # session — same rationale as the eager relationship-loading above.
    pipelines: dict[str, tuple] = {}
    for agent in target_agents:
        manager = build_pipeline_for_agent(db, agent, extra_hook_ids=payload.hook_ids)
        context = HookContext(
            agent_name=agent.name,
            conversation_id=str(conversation_id),
            user_id=str(current_user.id),
        )
        pipelines[str(agent.id)] = (manager, context)

    async def event_generator() -> AsyncGenerator[str, None]:
        yield _sse("status", {"status": "connected", "user_message_id": str(user_message.id)})

        queue: asyncio.Queue = asyncio.Queue()

        async def run_one(agent: Agent) -> None:
            manager, context = pipelines[str(agent.id)]
            # asyncio.create_task snapshots the current contextvars, so this
            # assignment is only ever visible within this task (and whatever
            # it awaits) — concurrent sibling agent tasks each set their own
            # value without collision. See services/hooks.py.
            current_hook_context.set(context)
            # A non-primary agent in a multi-agent turn is the closest thing
            # this app has to a "subagent" today — bracket its execution with
            # SubagentStart/SubagentStop. Best-effort: a hook failure here
            # must never stop the agent from actually responding.
            is_subagent = agent.id != conversation.agent_id
            if is_subagent:
                try:
                    await manager.trigger_pipeline("SubagentStart", {"agent_id": str(agent.id)}, context)
                except Exception:  # noqa: BLE001
                    logger.exception("SubagentStart pipeline failed for agent %s", agent.id)
            try:
                async for event in stream_agent_response(agent, payload.content, attached_files, manager, context):
                    await queue.put(event)
            except Exception as exc:  # noqa: BLE001 — isolate a broken agent from the rest of the turn
                try:
                    await manager.trigger_pipeline("Notification", {"source_stage": "agent_execution", "error": str(exc)}, context)
                except Exception:  # noqa: BLE001
                    pass
                await queue.put({"type": "error", "agent_id": str(agent.id), "message": "Agent execution failed"})
            finally:
                if is_subagent:
                    try:
                        await manager.trigger_pipeline("SubagentStop", {"agent_id": str(agent.id)}, context)
                    except Exception:  # noqa: BLE001
                        logger.exception("SubagentStop pipeline failed for agent %s", agent.id)
                await queue.put({"type": "__agent_done__", "agent_id": str(agent.id)})

        tasks = [asyncio.create_task(run_one(agent)) for agent in target_agents]
        remaining = len(tasks)
        agents_by_id = {str(a.id): a for a in target_agents}

        try:
            while remaining > 0:
                event = await queue.get()
                if event["type"] == "__agent_done__":
                    remaining -= 1
                    continue
                if event["type"] in ("tool_call", "skill_call"):
                    # Lightweight usage record for the "tool & skill calls"
                    # series in the Super Admin's requests-per-day chart —
                    # no token/cost accounting for these (see the chat_turn
                    # ledger entry below for that).
                    try:
                        agent = agents_by_id[event["agent_id"]]
                        usage_tenant_id = current_user.tenant_id or agent.tenant_id
                        if usage_tenant_id is not None:
                            db.add(
                                UsageEvent(
                                    tenant_id=usage_tenant_id,
                                    user_id=current_user.id,
                                    project_id=conversation.project_id,
                                    agent_id=agent.id,
                                    event_type=event["type"],
                                    model_name=agent.model_name,
                                )
                            )
                            db.commit()
                    except Exception:  # noqa: BLE001 — usage recording must never break the response
                        logger.exception("Failed to record UsageEvent for %s", event["type"])
                if event["type"] == "stream_end":
                    agent = agents_by_id[event["agent_id"]]
                    manager, context = pipelines[event["agent_id"]]
                    saved = create_message(
                        db,
                        conversation_id=conversation_id,
                        parent_message_id=user_message.id,
                        role="assistant",
                        content=event["content"],
                        agent_id=agent.id,
                        citations=event["citations"],
                    )
                    event["message_id"] = str(saved.id)
                    try:
                        await manager.trigger_pipeline(
                            "Stop",
                            {
                                "tokens": event.get("tokens", 0),
                                "duration_ms": context.metadata.get("duration_ms"),
                                "message_id": str(saved.id),
                                "blocked": event.get("blocked", False),
                            },
                            context,
                        )
                    except Exception:  # noqa: BLE001 — Stop must never break the response
                        pass

                    # Real usage/cost ledger entry for this turn — see
                    # app/models/usage_event.py and app/services/pricing.py.
                    # Best-effort: a ledger-write failure must never break
                    # the response the user is already receiving.
                    try:
                        # UsageEvent.tenant_id is required — a super_admin
                        # (tenant_id None) chatting against a platform-shared
                        # agent (also tenant_id None) has no tenant to bill,
                        # so that combination is skipped rather than forced.
                        usage_tenant_id = current_user.tenant_id or agent.tenant_id
                        if usage_tenant_id is not None:
                            model_route = pricing.find_model_route(db, agent.model_name)
                            output_tokens = int(event.get("tokens", 0) or 0)
                            input_tokens = len(payload.content.split())
                            cost_usd = pricing.estimate_cost_usd(model_route, input_tokens, output_tokens)
                            db.add(
                                UsageEvent(
                                    tenant_id=usage_tenant_id,
                                    user_id=current_user.id,
                                    project_id=conversation.project_id,
                                    agent_id=agent.id,
                                    model_route_id=model_route.id if model_route else None,
                                    event_type="chat_turn",
                                    model_name=agent.model_name,
                                    input_tokens=input_tokens,
                                    output_tokens=output_tokens,
                                    cost_usd=cost_usd,
                                    latency_ms=context.metadata.get("duration_ms"),
                                    status="error" if event.get("blocked", False) else "ok",
                                )
                            )
                            db.commit()
                    except Exception:  # noqa: BLE001 — usage recording must never break the response
                        logger.exception("Failed to record UsageEvent for agent %s", agent.id)
                yield _sse(event["type"], event)
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        yield _sse("stream_complete", {"conversation_id": str(conversation_id)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
