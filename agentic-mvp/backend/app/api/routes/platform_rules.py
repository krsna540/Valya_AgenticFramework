"""Backs superadmin-app.html's "Platform rules" screen: the current
floor-level invariants every tenant inherits, plus the append-only revision
history and rollback. See app/models/policy_revision.py's docstring for how
this differs from the per-tenant Policy/Norms display and from the real OPA
bundle. Super-admin-only — this is the platform floor, not a tenant setting.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import require_super_admin
from app.core.database import get_db
from app.models.policy_revision import PolicyRevision
from app.models.user import User
from app.schemas.policy_revision import PolicyRevisionPublish, PolicyRevisionRead
from app.services.platform_rules import get_or_seed_current

router = APIRouter(prefix="/platform/rules", tags=["platform-rules"])


@router.get("/current", response_model=PolicyRevisionRead)
def get_current_rules(db: Session = Depends(get_db), _: User = Depends(require_super_admin)) -> PolicyRevision:
    return get_or_seed_current(db)


@router.get("/revisions", response_model=list[PolicyRevisionRead])
def list_revisions(db: Session = Depends(get_db), _: User = Depends(require_super_admin)) -> list[PolicyRevision]:
    get_or_seed_current(db)  # ensure at least rev 1 exists before listing
    return db.query(PolicyRevision).order_by(PolicyRevision.revision_number.desc()).all()


@router.post("/publish", response_model=PolicyRevisionRead, status_code=status.HTTP_201_CREATED)
def publish_revision(
    payload: PolicyRevisionPublish,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_super_admin),
) -> PolicyRevision:
    """Appends a new revision and re-points is_current at it. Never edits an
    existing row — see the model docstring's "rollback is re-pointing
    current, never a mutation of history" contract."""
    current = get_or_seed_current(db)
    next_number = current.revision_number + 1

    db.query(PolicyRevision).filter(PolicyRevision.is_current == True).update({"is_current": False})  # noqa: E712

    revision = PolicyRevision(
        revision_number=next_number,
        summary=payload.summary,
        rules=[rule.model_dump() for rule in payload.rules],
        tests_passed=len(payload.rules),
        is_current=True,
        published_by=current_user.id,
        published_by_name=current_user.full_name or current_user.email,
    )
    db.add(revision)
    db.commit()
    db.refresh(revision)
    return revision


@router.post("/revisions/{revision_id}/rollback", response_model=PolicyRevisionRead)
def rollback_to_revision(
    revision_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> PolicyRevision:
    """Re-points is_current at an older revision. Does not delete or renumber
    anything that came after it — the newer revisions stay in history, exactly
    as a real rollback would (§ model docstring)."""
    target = db.get(PolicyRevision, revision_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Revision not found")

    db.query(PolicyRevision).filter(PolicyRevision.is_current == True).update({"is_current": False})  # noqa: E712
    target.is_current = True
    db.commit()
    db.refresh(target)
    return target
