import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import authorize, get_current_user
from app.models.agent import Agent
from app.models.datasource import Datasource
from app.models.hook import Hook
from app.models.persona import Persona, UserPersonaMapping
from app.models.plugin import Plugin
from app.models.project import Project, project_datasources, project_users
from app.models.project_intelligence_binding import ProjectIntelligenceBinding
from app.models.skill import Skill
from app.models.tool import Tool
from app.models.user import User
from app.core.database import get_db
from app.schemas.project import (
    BindingCreate,
    BindingRead,
    ProjectCreate,
    ProjectDatasourceAdd,
    ProjectRead,
    ProjectTopology,
    ProjectUpdate,
    ProjectUserAdd,
    TopologyComponent,
    TopologyDatasource,
    TopologyMappedUser,
)
from app.services import audit

router = APIRouter(prefix="/projects", tags=["projects"])

_COMPONENT_MODELS: dict[str, type] = {
    "agent": Agent,
    "tool": Tool,
    "hook": Hook,
    "skill": Skill,
    "plugin": Plugin,
}


def _component_model(component_type: str) -> type:
    model = _COMPONENT_MODELS.get(component_type)
    if model is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown component_type '{component_type}'")
    return model


def _get_project(db: Session, current_user: User, project_id: uuid.UUID, *, require_member: bool = True) -> Project:
    project = db.get(Project, project_id)
    # super_admin has no tenant_id of its own (see docs/AUTHORIZATION.md) —
    # it sees every tenant's projects, everyone else only their own.
    if project is None or (current_user.role != "super_admin" and project.tenant_id != current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    # Admins (and super_admins) see every project in the tenant; a plain
    # "user" only sees projects they're explicitly mapped to — same
    # membership check as before OPA existed, OPA just decides *whether
    # this role gets to call this endpoint at all* (see authorize() on
    # each route below), not this per-row membership detail.
    if require_member and current_user.role not in ("admin", "super_admin"):
        is_member = db.query(project_users).filter(
            project_users.c.project_id == project_id, project_users.c.user_id == current_user.id
        ).first()
        if is_member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _require_draft(project: Project) -> None:
    if project.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Project is '{project.status}' — unfreeze it before editing its composition",
        )


# --- Project CRUD ------------------------------------------------------------


@router.get("", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(authorize("project", "list"))) -> list[ProjectRead]:
    # super_admin sees every tenant's projects; everyone else only their
    # own tenant's, further narrowed to just the ones they're mapped to if
    # they're a plain "user" (not admin/super_admin).
    query = db.query(Project)
    if current_user.role != "super_admin":
        query = query.filter(Project.tenant_id == current_user.tenant_id)
    if current_user.role not in ("admin", "super_admin"):
        query = query.join(project_users, project_users.c.project_id == Project.id).filter(
            project_users.c.user_id == current_user.id
        )
    projects = query.order_by(Project.created_at.desc()).all()
    return [ProjectRead.model_validate(p) for p in projects]


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("project", "create")),
) -> ProjectRead:
    project = Project(tenant_id=current_admin.tenant_id, created_by=current_admin.id, **payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectRead.model_validate(project)


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("project", "read"))) -> ProjectRead:
    return ProjectRead.model_validate(_get_project(db, current_user, project_id))


@router.put("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("project", "update")),
) -> ProjectRead:
    project = _get_project(db, current_admin, project_id, require_member=False)
    _require_draft(project)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return ProjectRead.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("project", "delete")),
) -> None:
    project = _get_project(db, current_admin, project_id, require_member=False)
    name = project.name
    db.delete(project)
    db.commit()
    audit.record(db, actor=current_admin, action="project.delete", resource_type="project", resource_id=project_id, extra={"name": name})
    return None


# --- Mapped users ------------------------------------------------------------


@router.get("/{project_id}/users", response_model=list[str])
def list_project_users(project_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("project", "read"))) -> list[str]:
    project = _get_project(db, current_user, project_id)
    return [str(u.id) for u in project.users]


@router.post("/{project_id}/users", status_code=status.HTTP_201_CREATED)
def add_project_user(
    project_id: uuid.UUID,
    payload: ProjectUserAdd,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("project", "update")),
) -> dict:
    project = _get_project(db, current_admin, project_id, require_member=False)
    _require_draft(project)
    target = db.get(User, payload.user_id)
    if target is None or target.tenant_id != current_admin.tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User not found in this tenant")
    if target in project.users:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already mapped to this project")
    project.users.append(target)
    db.commit()
    return {"project_id": str(project_id), "user_id": str(payload.user_id)}


@router.delete("/{project_id}/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_user(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("project", "update")),
) -> None:
    project = _get_project(db, current_admin, project_id, require_member=False)
    _require_draft(project)
    target = db.get(User, user_id)
    if target and target in project.users:
        project.users.remove(target)
        db.commit()
    return None


# --- Connected datasources ----------------------------------------------------


@router.post("/{project_id}/datasources", status_code=status.HTTP_201_CREATED)
def add_project_datasource(
    project_id: uuid.UUID,
    payload: ProjectDatasourceAdd,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("project", "update")),
) -> dict:
    project = _get_project(db, current_admin, project_id, require_member=False)
    _require_draft(project)
    ds = db.get(Datasource, payload.datasource_id)
    if ds is None or ds.tenant_id != current_admin.tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Datasource not found in this tenant")
    if ds in project.datasources:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Datasource already connected to this project")
    project.datasources.append(ds)
    db.commit()
    return {"project_id": str(project_id), "datasource_id": str(payload.datasource_id)}


@router.delete("/{project_id}/datasources/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project_datasource(
    project_id: uuid.UUID,
    datasource_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("project", "update")),
) -> None:
    project = _get_project(db, current_admin, project_id, require_member=False)
    _require_draft(project)
    ds = db.get(Datasource, datasource_id)
    if ds and ds in project.datasources:
        project.datasources.remove(ds)
        db.commit()
    return None


# --- Intelligence-to-Project association matrix ------------------------------


@router.get("/{project_id}/bindings", response_model=list[BindingRead])
def list_bindings(project_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("project", "read"))) -> list[BindingRead]:
    project = _get_project(db, current_user, project_id)
    bindings = db.query(ProjectIntelligenceBinding).filter(ProjectIntelligenceBinding.project_id == project.id).all()
    results = []
    for b in bindings:
        model = _COMPONENT_MODELS.get(b.component_type)
        item = db.get(model, b.component_id) if model else None
        results.append(
            BindingRead(
                id=b.id,
                project_id=b.project_id,
                component_type=b.component_type,
                component_id=b.component_id,
                version_pinned=b.version_pinned,
                is_active=b.is_active,
                created_at=b.created_at,
                component_name=item.name if item else "(deleted)",
                component_version=getattr(item, "version", None) if item else None,
            )
        )
    return results


@router.post("/{project_id}/bindings", response_model=BindingRead, status_code=status.HTTP_201_CREATED)
def create_binding(
    project_id: uuid.UUID,
    payload: BindingCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("project", "update")),
) -> BindingRead:
    project = _get_project(db, current_admin, project_id, require_member=False)
    _require_draft(project)
    model = _component_model(payload.component_type)
    item = db.get(model, payload.component_id)
    if item is None or (getattr(item, "tenant_id", None) not in (None, current_admin.tenant_id)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{payload.component_type} not found or not visible to this tenant")
    existing = (
        db.query(ProjectIntelligenceBinding)
        .filter(
            ProjectIntelligenceBinding.project_id == project_id,
            ProjectIntelligenceBinding.component_type == payload.component_type,
            ProjectIntelligenceBinding.component_id == payload.component_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already bound to this project")
    binding = ProjectIntelligenceBinding(project_id=project_id, **payload.model_dump())
    db.add(binding)
    db.commit()
    db.refresh(binding)
    return BindingRead(
        id=binding.id,
        project_id=binding.project_id,
        component_type=binding.component_type,
        component_id=binding.component_id,
        version_pinned=binding.version_pinned,
        is_active=binding.is_active,
        created_at=binding.created_at,
        component_name=item.name,
        component_version=getattr(item, "version", None),
    )


@router.delete("/{project_id}/bindings/{binding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_binding(
    project_id: uuid.UUID,
    binding_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("project", "update")),
) -> None:
    project = _get_project(db, current_admin, project_id, require_member=False)
    _require_draft(project)
    binding = db.get(ProjectIntelligenceBinding, binding_id)
    if binding is None or binding.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Binding not found")
    db.delete(binding)
    db.commit()
    return None


@router.get("/{project_id}/available-agents")
def list_available_agents(project_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("project", "read"))) -> list[dict]:
    """Agents actually usable in this Project's chat — bound via the
    association matrix (or, before anything is bound / for unscoped chat,
    this route is simply not called by the frontend; see ChatPage)."""
    project = _get_project(db, current_user, project_id)
    bindings = (
        db.query(ProjectIntelligenceBinding)
        .filter(
            ProjectIntelligenceBinding.project_id == project.id,
            ProjectIntelligenceBinding.component_type == "agent",
            ProjectIntelligenceBinding.is_active == True,  # noqa: E712
        )
        .all()
    )
    agent_ids = [b.component_id for b in bindings]
    if not agent_ids:
        return []
    agents = db.query(Agent).filter(Agent.id.in_(agent_ids), Agent.is_active == True).all()  # noqa: E712
    return [{"id": str(a.id), "name": a.name, "version": a.version} for a in agents]


# --- Topology resolver + Freeze / Unfreeze / Deploy --------------------------


def _resolve_topology(db: Session, project: Project) -> ProjectTopology:
    mapped_users: list[TopologyMappedUser] = []
    for u in project.users:
        mapping = (
            db.query(UserPersonaMapping)
            .filter(UserPersonaMapping.user_id == u.id)
            .filter(
                (UserPersonaMapping.project_id == project.id) | (UserPersonaMapping.project_id.is_(None))
            )
            .order_by(UserPersonaMapping.project_id.desc().nullslast(), UserPersonaMapping.is_default.desc())
            .first()
        )
        persona = db.get(Persona, mapping.persona_id) if mapping else None
        mapped_users.append(
            TopologyMappedUser(
                user_id=u.id,
                full_name=u.full_name,
                email=u.email,
                persona_id=persona.id if persona else None,
                persona_name=persona.name if persona else None,
            )
        )

    datasources = [
        TopologyDatasource(
            datasource_id=ds.id,
            name=ds.name,
            connector_type=ds.connector_type,
            security_classification=ds.security_classification,
            sync_status=ds.sync_status,
        )
        for ds in project.datasources
    ]

    bindings = (
        db.query(ProjectIntelligenceBinding)
        .filter(ProjectIntelligenceBinding.project_id == project.id, ProjectIntelligenceBinding.is_active == True)  # noqa: E712
        .all()
    )
    intelligence: list[TopologyComponent] = []
    for b in bindings:
        model = _COMPONENT_MODELS.get(b.component_type)
        item = db.get(model, b.component_id) if model else None
        if item is None:
            continue
        intelligence.append(
            TopologyComponent(
                component_type=b.component_type,
                component_id=b.component_id,
                name=item.name,
                version=b.version_pinned or getattr(item, "version", "1.0.0"),
            )
        )

    return ProjectTopology(
        project_id=project.id,
        project_name=project.name,
        status=project.status,
        execution_mode=project.execution_mode,
        schedule_cron=project.schedule_cron,
        webhook_slug=project.webhook_slug,
        mapped_users=mapped_users,
        datasources=datasources,
        intelligence=intelligence,
        resolved_at=datetime.now(timezone.utc),
    )


@router.get("/{project_id}/topology", response_model=ProjectTopology)
def get_topology(project_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("project", "read"))) -> ProjectTopology:
    """Live resolution of the current composition — what the Freeze Screen
    shows *before* freezing. Once status != 'draft', the frontend should
    prefer the immutable Project.frozen_snapshot instead (returned as-is by
    GET /projects/{id}, not recomputed) so a later registry edit can't make
    a deployed project's displayed topology drift from what was approved."""
    project = _get_project(db, current_user, project_id)
    return _resolve_topology(db, project)


@router.post("/{project_id}/freeze", response_model=ProjectTopology)
def freeze_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("project", "freeze")),
) -> ProjectTopology:
    project = _get_project(db, current_admin, project_id, require_member=False)
    _require_draft(project)
    if not project.users:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Map at least one user before freezing")
    has_agent_binding = (
        db.query(ProjectIntelligenceBinding)
        .filter(ProjectIntelligenceBinding.project_id == project.id, ProjectIntelligenceBinding.component_type == "agent")
        .first()
    )
    if not has_agent_binding:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bind at least one Agent before freezing")

    topology = _resolve_topology(db, project)
    project.frozen_snapshot = topology.model_dump(mode="json")
    project.frozen_at = datetime.now(timezone.utc)
    project.frozen_by = current_admin.id
    project.status = "frozen"
    db.commit()
    audit.record(db, actor=current_admin, action="project.freeze", resource_type="project", resource_id=project.id)
    return topology


@router.post("/{project_id}/unfreeze", response_model=ProjectRead)
def unfreeze_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("project", "unfreeze")),
) -> ProjectRead:
    project = _get_project(db, current_admin, project_id, require_member=False)
    if project.status == "deployed":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot unfreeze a deployed project")
    if project.status != "frozen":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project is not frozen")
    project.status = "draft"
    project.frozen_snapshot = None
    project.frozen_at = None
    project.frozen_by = None
    db.commit()
    db.refresh(project)
    return ProjectRead.model_validate(project)


@router.post("/{project_id}/deploy", response_model=ProjectRead)
def deploy_project(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("project", "deploy")),
) -> ProjectRead:
    """'Confirm & Deploy': locks the configuration matrix (already immutable
    since freeze) and marks the project live. No real event listeners,
    database connectors, or cron scheduler are actually provisioned by this
    MVP — see Project.__doc__ and the module docstring in
    app/services/mcp_client.py for the same scaffold-vs-real boundary
    applied to Runtime execution."""
    project = _get_project(db, current_admin, project_id, require_member=False)
    if project.status != "frozen":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Freeze the project before deploying")
    project.status = "deployed"
    project.deployed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(project)
    audit.record(db, actor=current_admin, action="project.deploy", resource_type="project", resource_id=project.id)
    return ProjectRead.model_validate(project)


@router.post("/{project_id}/webhook/{webhook_slug}", status_code=status.HTTP_202_ACCEPTED)
def receive_webhook(project_id: uuid.UUID, webhook_slug: str, db: Session = Depends(get_db)) -> dict:
    """Stub receiver for Event-Driven execution mode (e.g. 'a file landing
    in a SharePoint directory triggers an agent pipeline'). Accepts and
    acknowledges any payload for a deployed, event_driven project with a
    matching webhook_slug; does not actually invoke an agent run — there is
    no real event listener/queue wired to this endpoint yet."""
    project = db.get(Project, project_id)
    if (
        project is None
        or project.status != "deployed"
        or project.execution_mode != "event_driven"
        or project.webhook_slug != webhook_slug
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching deployed event-driven project")
    return {"received": True, "project_id": str(project_id)}
