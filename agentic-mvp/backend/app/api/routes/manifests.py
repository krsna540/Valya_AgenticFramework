"""The manifest compiler endpoint — PLATFORM_ARCHITECTURE.md §6, the
touchpoint between the control plane (this route) and the data plane (the
agent runtime, which receives only a manifest_id — see
app/services/manifest.py's module docstring for exactly which of the
twelve resolution steps are wired this session).

This is the "start a session" step in user-app.html's flow: the user picks
a workspace (Project) and a language, POSTs here, and gets back a
manifest_id to hand to the existing chat-streaming endpoint
(POST /chat/conversations/{id}/messages/stream) alongside the objective.
Chat streaming itself is untouched — this is additive capability-resolution
bookkeeping in front of it, not a replacement for the working streaming
path (see docs/PLATFORM_ARCHITECTURE.md §17.3's note on why the existing
in-process SSE is left alone this session).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import authorize
from app.core.database import get_db
from app.core.redis_client import cache_manifest_session
from app.models.project import Project, project_users
from app.models.user import User
from app.services.manifest import compile_manifest, create_session, persist_manifest

router = APIRouter(prefix="/manifests", tags=["manifests"])


class ManifestResolveRequest(BaseModel):
    project_id: uuid.UUID
    locale: str = "en"


class ManifestResolveResponse(BaseModel):
    session_id: uuid.UUID
    manifest_id: str
    stream_hint: str = "Use this manifest_id as context when starting a chat conversation for this project."


def _get_member_project(db: Session, current_user: User, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None or (current_user.role != "super_admin" and project.tenant_id != current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if current_user.role not in ("admin", "super_admin"):
        is_member = (
            db.query(project_users)
            .filter(project_users.c.project_id == project_id, project_users.c.user_id == current_user.id)
            .first()
        )
        if is_member is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.post("/resolve", response_model=ManifestResolveResponse, status_code=status.HTTP_201_CREATED)
async def resolve_manifest(
    payload: ManifestResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(authorize("manifest", "create")),
) -> ManifestResolveResponse:
    project = _get_member_project(db, current_user, payload.project_id)

    body = compile_manifest(db, project=project, user_id=current_user.id, locale=payload.locale)
    manifest = persist_manifest(db, tenant_id=project.tenant_id, project_id=project.id, body=body)
    session_row = create_session(
        db, manifest_id=manifest.manifest_id, tenant_id=project.tenant_id, project_id=project.id, user_id=current_user.id, locale=payload.locale
    )
    await cache_manifest_session(str(session_row.id), body)

    return ManifestResolveResponse(session_id=session_row.id, manifest_id=manifest.manifest_id)


@router.get("/{manifest_id}")
def get_manifest(manifest_id: str, db: Session = Depends(get_db), current_user: User = Depends(authorize("manifest", "read"))) -> dict:
    from app.models.manifest import Manifest

    manifest = db.get(Manifest, manifest_id)
    if manifest is None or (current_user.role != "super_admin" and manifest.tenant_id != current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manifest not found")
    return manifest.body
