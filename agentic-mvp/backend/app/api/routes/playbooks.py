"""Playbooks — PLATFORM_ARCHITECTURE.md §11.5, the sixth registry kind.
Same shape as prompts.py (custom fields the generic registry_factory
doesn't know about), same access-model machinery as every other registry
(app/services/registry_access.py's fork_row).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import authorize
from app.core.database import get_db
from app.core.tenant_scope import apply_shared_or_own_tenant, is_visible
from app.models.playbook import Playbook
from app.models.user import User
from app.schemas.playbook import PlaybookCreate, PlaybookRead, PlaybookUpdate
from app.services.registry_access import fork_row

router = APIRouter(prefix="/playbooks", tags=["playbooks"])


def _visible_or_404(db: Session, current_user: User, playbook_id: uuid.UUID) -> Playbook:
    playbook = db.get(Playbook, playbook_id)
    if playbook is None or not is_visible(playbook.tenant_id, current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playbook not found")
    return playbook


@router.get("", response_model=list[PlaybookRead])
def list_playbooks(db: Session = Depends(get_db), current_user: User = Depends(authorize("playbook", "list"))) -> list[PlaybookRead]:
    playbooks = (
        apply_shared_or_own_tenant(db.query(Playbook).filter(Playbook.is_active == True), Playbook.tenant_id, current_user)  # noqa: E712
        .order_by(Playbook.updated_at.desc())
        .all()
    )
    return [PlaybookRead.model_validate(p) for p in playbooks]


@router.post("", response_model=PlaybookRead, status_code=status.HTTP_201_CREATED)
def create_playbook(payload: PlaybookCreate, db: Session = Depends(get_db), current_admin: User = Depends(authorize("playbook", "create"))) -> PlaybookRead:
    playbook = Playbook(
        **payload.model_dump(exclude={"canonical_steps", "known_assumptions"}),
        canonical_steps=[s.model_dump() for s in payload.canonical_steps],
        known_assumptions=[a.model_dump() for a in payload.known_assumptions],
        tenant_id=current_admin.tenant_id,
        owner_user_id=current_admin.id,
    )
    db.add(playbook)
    db.commit()
    db.refresh(playbook)
    return PlaybookRead.model_validate(playbook)


@router.get("/{playbook_id}", response_model=PlaybookRead)
def get_playbook(playbook_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("playbook", "read"))) -> PlaybookRead:
    return PlaybookRead.model_validate(_visible_or_404(db, current_user, playbook_id))


@router.put("/{playbook_id}", response_model=PlaybookRead)
def update_playbook(
    playbook_id: uuid.UUID,
    payload: PlaybookUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("playbook", "update")),
) -> PlaybookRead:
    playbook = _visible_or_404(db, current_admin, playbook_id)
    if playbook.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be edited")
    data = payload.model_dump(exclude_unset=True)
    if "canonical_steps" in data and data["canonical_steps"] is not None:
        data["canonical_steps"] = [s if isinstance(s, dict) else s for s in data["canonical_steps"]]
    if "known_assumptions" in data and data["known_assumptions"] is not None:
        data["known_assumptions"] = [a if isinstance(a, dict) else a for a in data["known_assumptions"]]
    for field, value in data.items():
        setattr(playbook, field, value)
    db.commit()
    db.refresh(playbook)
    return PlaybookRead.model_validate(playbook)


@router.delete("/{playbook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_playbook(playbook_id: uuid.UUID, db: Session = Depends(get_db), current_admin: User = Depends(authorize("playbook", "delete"))) -> None:
    playbook = _visible_or_404(db, current_admin, playbook_id)
    if playbook.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be deleted")
    db.delete(playbook)
    db.commit()
    return None


@router.post("/{playbook_id}/fork", response_model=PlaybookRead, status_code=status.HTTP_201_CREATED)
def fork_playbook(playbook_id: uuid.UUID, db: Session = Depends(get_db), current_admin: User = Depends(authorize("playbook", "create"))) -> PlaybookRead:
    source = _visible_or_404(db, current_admin, playbook_id)
    if current_admin.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Super admin has no tenant of their own to fork into")
    forked = fork_row(source, new_tenant_id=current_admin.tenant_id, owner_user_id=current_admin.id, model_cls=Playbook)
    db.add(forked)
    db.commit()
    db.refresh(forked)
    return PlaybookRead.model_validate(forked)
