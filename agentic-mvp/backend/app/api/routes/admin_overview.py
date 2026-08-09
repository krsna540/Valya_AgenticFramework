"""Backs admin-app.html's "Overview" screen: the stat strip, "Waiting on a
person" panel, and "Recent work" list. A thin aggregation over rows every
other route already owns (Project/User/Datasource/AgentRun) — no new
tables, this is purely a read-side convenience so the frontend doesn't have
to fire four separate list calls and stitch them together on every render.
"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import authorize
from app.core.database import get_db
from app.models.agent import Agent
from app.models.agent_run import AgentRun
from app.models.datasource import Datasource
from app.models.project import Project
from app.models.user import User

router = APIRouter(prefix="/admin/overview", tags=["admin-overview"])


class ApprovalItem(BaseModel):
    id: uuid.UUID
    title: str
    detail: str
    project_name: str | None
    created_at: str | None


class RecentItem(BaseModel):
    id: uuid.UUID
    time: str | None
    summary: str
    context: str
    status: str


class AdminOverview(BaseModel):
    workspaces_active_7d: int
    work_finished_7d: int
    waiting_on_person: int
    sources_connected: int
    approvals: list[ApprovalItem]
    recent: list[RecentItem]


@router.get("", response_model=AdminOverview)
def get_admin_overview(db: Session = Depends(get_db), current_user: User = Depends(authorize("project", "list"))) -> AdminOverview:
    tenant_filter = (Project.tenant_id == current_user.tenant_id) if current_user.role != "super_admin" else True

    workspaces_active = db.query(func.count(Project.id)).filter(tenant_filter).scalar() or 0

    run_tenant_filter = (AgentRun.tenant_id == current_user.tenant_id) if current_user.role != "super_admin" else True
    finished = (
        db.query(func.count(AgentRun.id))
        .filter(run_tenant_filter, AgentRun.status.in_(["succeeded", "degraded"]))
        .scalar()
        or 0
    )

    awaiting = (
        db.query(AgentRun)
        .filter(run_tenant_filter, AgentRun.needs_human_review == True)  # noqa: E712
        .order_by(AgentRun.created_at.desc())
        .limit(20)
        .all()
    )
    approvals = []
    for run in awaiting:
        project = db.get(Project, run.project_id) if run.project_id else None
        agent = db.get(Agent, run.agent_id) if run.agent_id else None
        approvals.append(
            ApprovalItem(
                id=run.id,
                title=run.objective[:120],
                detail=f"Raised by {agent.name if agent else 'an agent'} — waiting for a decision before it can continue.",
                project_name=project.name if project else None,
                created_at=run.created_at.isoformat() if getattr(run, "created_at", None) else None,
            )
        )

    ds_filter = (Datasource.tenant_id == current_user.tenant_id) if current_user.role != "super_admin" else True
    sources_connected = db.query(func.count(Datasource.id)).filter(ds_filter, Datasource.auth_status == "connected").scalar() or 0

    recent_runs = (
        db.query(AgentRun)
        .filter(run_tenant_filter)
        .order_by(AgentRun.created_at.desc())
        .limit(10)
        .all()
    )
    recent = []
    for run in recent_runs:
        project = db.get(Project, run.project_id) if run.project_id else None
        recent.append(
            RecentItem(
                id=run.id,
                time=run.created_at.isoformat() if getattr(run, "created_at", None) else None,
                summary=run.objective[:160],
                context=project.name if project else "—",
                status=run.status,
            )
        )

    return AdminOverview(
        workspaces_active_7d=workspaces_active,
        work_finished_7d=finished,
        waiting_on_person=len(approvals),
        sources_connected=sources_connected,
        approvals=approvals,
        recent=recent,
    )
