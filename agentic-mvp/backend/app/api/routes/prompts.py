import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import authorize, get_current_user
from app.core.database import get_db
from app.core.tenant_scope import apply_shared_or_own_tenant, is_visible
from app.models.prompt import Prompt
from app.models.user import User
from app.schemas.prompt import PromptCreate, PromptRead, PromptUpdate

router = APIRouter(prefix="/prompts", tags=["prompts"])

# Same platform-shared-vs-tenant-private convention as every other registry
# (app/api/routes/registry_factory.py's module docstring): NULL tenant_id is
# visible to everyone but editable by nobody in this MVP, a non-NULL
# tenant_id is private to that tenant. Prompt didn't have tenant_id at all
# before this — any authenticated user, any tenant, could edit any prompt —
# see app/models/prompt.py's class docstring.


def _visible_or_404(db: Session, current_user: User, prompt_id: uuid.UUID) -> Prompt:
    prompt = db.get(Prompt, prompt_id)
    if prompt is None or not is_visible(prompt.tenant_id, current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prompt not found")
    return prompt


@router.get("", response_model=list[PromptRead])
def list_prompts(db: Session = Depends(get_db), current_user: User = Depends(authorize("prompt", "list"))) -> list[PromptRead]:
    prompts = (
        apply_shared_or_own_tenant(
            db.query(Prompt).filter(Prompt.is_active == True),  # noqa: E712
            Prompt.tenant_id,
            current_user,
        )
        .order_by(Prompt.name)
        .all()
    )
    return [PromptRead.model_validate(p) for p in prompts]


@router.post("", response_model=PromptRead, status_code=status.HTTP_201_CREATED)
def create_prompt(payload: PromptCreate, db: Session = Depends(get_db), current_admin: User = Depends(authorize("prompt", "create"))) -> PromptRead:
    prompt = Prompt(**payload.model_dump(), tenant_id=current_admin.tenant_id)
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return PromptRead.model_validate(prompt)


@router.get("/{prompt_id}", response_model=PromptRead)
def get_prompt(prompt_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("prompt", "read"))) -> PromptRead:
    return PromptRead.model_validate(_visible_or_404(db, current_user, prompt_id))


@router.put("/{prompt_id}", response_model=PromptRead)
def update_prompt(
    prompt_id: uuid.UUID,
    payload: PromptUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("prompt", "update")),
) -> PromptRead:
    prompt = _visible_or_404(db, current_admin, prompt_id)
    if prompt.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be edited")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(prompt, field, value)

    db.commit()
    db.refresh(prompt)
    return PromptRead.model_validate(prompt)


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(prompt_id: uuid.UUID, db: Session = Depends(get_db), current_admin: User = Depends(authorize("prompt", "delete"))) -> None:
    prompt = _visible_or_404(db, current_admin, prompt_id)
    if prompt.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be deleted")
    db.delete(prompt)
    db.commit()
    return None
