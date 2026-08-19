import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import authorize, get_current_user
from app.core.database import get_db
from app.core.tenant_scope import apply_shared_or_own_tenant, is_visible
from app.models.agent import Agent
from app.models.hook import Hook
from app.models.playbook import Playbook
from app.models.plugin import Plugin
from app.models.skill import Skill
from app.models.tool import Tool
from app.models.user import User
from app.schemas.registry import AgentCreate, AgentRead, AgentUpdate
from app.services import registry_cache

router = APIRouter(prefix="/agents", tags=["agents"])


def _fetch_by_ids(db: Session, model, ids: list[uuid.UUID], tenant_id: uuid.UUID):
    if not ids:
        return []
    items = (
        db.query(model)
        .filter(model.id.in_(ids), or_(model.tenant_id.is_(None), model.tenant_id == tenant_id))
        .all()
    )
    found_ids = {item.id for item in items}
    missing = set(ids) - found_ids
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{model.__name__} id(s) not found or not visible to this tenant: {', '.join(str(m) for m in missing)}",
        )
    return items


def _visible_or_404(db: Session, current_user: User, agent_id: uuid.UUID) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None or not is_visible(agent.tenant_id, current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


@router.get("", response_model=list[AgentRead])
def list_agents(db: Session = Depends(get_db), current_user: User = Depends(authorize("agent", "list"))) -> list[AgentRead]:
    agents = (
        apply_shared_or_own_tenant(db.query(Agent), Agent.tenant_id, current_user)
        .order_by(Agent.created_at.desc())
        .all()
    )
    return [AgentRead.from_orm_agent(a) for a in agents]


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
def create_agent(
    payload: AgentCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("agent", "create")),
) -> AgentRead:
    agent = Agent(
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
        system_prompt=payload.system_prompt,
        model_name=payload.model_name,
        version=payload.version,
        status=payload.status,
        owner_id=current_admin.id,
        tenant_id=current_admin.tenant_id,
    )
    agent.skills = _fetch_by_ids(db, Skill, payload.skill_ids, current_admin.tenant_id)
    agent.tools = _fetch_by_ids(db, Tool, payload.tool_ids, current_admin.tenant_id)
    agent.plugins = _fetch_by_ids(db, Plugin, payload.plugin_ids, current_admin.tenant_id)
    agent.hooks = _fetch_by_ids(db, Hook, payload.hook_ids, current_admin.tenant_id)
    agent.playbooks = _fetch_by_ids(db, Playbook, payload.playbook_ids, current_admin.tenant_id)

    db.add(agent)
    db.commit()
    db.refresh(agent)
    return AgentRead.from_orm_agent(agent)


@router.get("/{agent_id}", response_model=AgentRead)
def get_agent(agent_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("agent", "read"))) -> AgentRead:
    return AgentRead.from_orm_agent(_visible_or_404(db, current_user, agent_id))


@router.put("/{agent_id}", response_model=AgentRead)
def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("agent", "update")),
) -> AgentRead:
    agent = _visible_or_404(db, current_admin, agent_id)
    if agent.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be edited")

    data = payload.model_dump(exclude_unset=True)
    if "skill_ids" in data:
        agent.skills = _fetch_by_ids(db, Skill, data.pop("skill_ids"), current_admin.tenant_id)
    if "tool_ids" in data:
        agent.tools = _fetch_by_ids(db, Tool, data.pop("tool_ids"), current_admin.tenant_id)
    if "plugin_ids" in data:
        agent.plugins = _fetch_by_ids(db, Plugin, data.pop("plugin_ids"), current_admin.tenant_id)
    if "hook_ids" in data:
        agent.hooks = _fetch_by_ids(db, Hook, data.pop("hook_ids"), current_admin.tenant_id)
    if "playbook_ids" in data:
        agent.playbooks = _fetch_by_ids(db, Playbook, data.pop("playbook_ids"), current_admin.tenant_id)
    for field, value in data.items():
        setattr(agent, field, value)

    db.commit()
    db.refresh(agent)
    # The chat path caches this agent's flattened tool/skill/playbook specs
    # across turns (app/services/registry_cache.py) precisely to avoid
    # re-touching these relationships every message; an association edit
    # here must not be served stale for the rest of that cache's TTL.
    registry_cache.invalidate(agent.id)
    return AgentRead.from_orm_agent(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(agent_id: uuid.UUID, db: Session = Depends(get_db), current_admin: User = Depends(authorize("agent", "delete"))) -> None:
    agent = _visible_or_404(db, current_admin, agent_id)
    if agent.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be deleted")
    db.delete(agent)
    db.commit()
    registry_cache.invalidate(agent_id)
    return None
