"""Runs & approvals — backs three mockup screens at once: admin-app.html's
"Waiting on a person" overview panel, user-app.html's workspace approval
card, and (indirectly, via /admin/overview) the pending-approvals count.

Reads project agent_runs (app/models/agent_run.py — the existing Observatory
audit trail, not the new `events` spine). Resolving an escalation delivers a
Temporal `human_decision` signal to the run's own workflow (see
app/agents/durable/workflow.py::submit_human_decision) when the run went
through the durable envelope (workflow_id is set); an in-process run has no
workflow to signal, so this instead writes the decision directly onto the
AgentRun row and lets the caller know the run is already terminal (in-
process runs don't currently pause for human review — see
app/agents/graph.py's finalize_node — so needs_human_review on an in-process
run is informational, not currently resumable from here; documented rather
than silently handled by an incomplete signal call).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import authorize
from app.core.database import get_db
from app.core.tenant_scope import apply_own_tenant
from app.models.agent import Agent
from app.models.agent_run import AgentRun
from app.models.project import Project
from app.models.user import User

router = APIRouter(prefix="/runs", tags=["runs"])


class RunSummary(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    project_id: uuid.UUID | None
    project_name: str | None = None
    agent_id: uuid.UUID
    agent_name: str | None = None
    objective: str
    status: str
    phase: str
    needs_human_review: bool
    final_answer: str | None
    created_at: str | None = None

    class Config:
        from_attributes = True


class RunDecision(BaseModel):
    approved: bool
    note: str = ""


def _to_summary(run: AgentRun, db: Session) -> RunSummary:
    project = db.get(Project, run.project_id) if run.project_id else None
    agent = db.get(Agent, run.agent_id) if run.agent_id else None
    return RunSummary(
        id=run.id,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        project_name=project.name if project else None,
        agent_id=run.agent_id,
        agent_name=agent.name if agent else None,
        objective=run.objective,
        status=run.status,
        phase=run.phase,
        needs_human_review=run.needs_human_review,
        final_answer=run.final_answer,
        created_at=run.created_at.isoformat() if getattr(run, "created_at", None) else None,
    )


@router.get("", response_model=list[RunSummary])
def list_runs(
    status_filter: str | None = None,
    awaiting_human: bool = False,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(authorize("run", "list")),
) -> list[RunSummary]:
    """`awaiting_human=true` is what backs every "waiting on a person"
    surface across the three apps — it is a first-class filter, not a
    client-side scan, because both admin-app.html's overview and
    superadmin-app.html would otherwise have to page through every run to
    find the handful that matter."""
    query = apply_own_tenant(db.query(AgentRun), AgentRun.tenant_id, current_user)
    if project_id is not None:
        query = query.filter(AgentRun.project_id == project_id)
    if awaiting_human:
        query = query.filter(AgentRun.needs_human_review == True)  # noqa: E712
    elif status_filter:
        query = query.filter(AgentRun.status == status_filter)
    runs = query.order_by(AgentRun.created_at.desc()).limit(min(limit, 200)).all()
    return [_to_summary(r, db) for r in runs]


@router.get("/{run_id}", response_model=RunSummary)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("run", "read"))) -> RunSummary:
    run = db.get(AgentRun, run_id)
    if run is None or (current_user.role != "super_admin" and run.tenant_id != current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return _to_summary(run, db)


@router.post("/{run_id}/decision", response_model=RunSummary)
async def decide_run(
    run_id: uuid.UUID,
    payload: RunDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(authorize("run", "decide")),
) -> RunSummary:
    run = db.get(AgentRun, run_id)
    if run is None or (current_user.role != "super_admin" and run.tenant_id != current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if not run.needs_human_review:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This run is not waiting on a decision")

    if run.workflow_id:
        # Durable path (PLATFORM_ARCHITECTURE.md §15.2 step 7's HUMAN_RESOLVED
        # touchpoint): deliver the signal, let AgentRunWorkflow._await_human_
        # review resolve status/final_answer. persist_run_finish (an
        # activity inside that workflow) writes the terminal row back — see
        # workflow.py — so we don't set run.status here ourselves, only
        # record that a decision was submitted, to avoid a race between this
        # HTTP response and the workflow's own persist activity.
        from app.agents.durable.client import get_client

        client = await get_client()
        handle = client.get_workflow_handle(run.workflow_id)
        await handle.signal("human_decision", {"approved": payload.approved, "note": payload.note})
    else:
        # In-process runs have no workflow to signal — see module docstring.
        run.status = "succeeded" if payload.approved else "failed"
        run.needs_human_review = False
        if not payload.approved:
            run.final_answer = f"This response was rejected during human review. {payload.note}".strip()
        db.commit()
        db.refresh(run)

    return _to_summary(run, db)
