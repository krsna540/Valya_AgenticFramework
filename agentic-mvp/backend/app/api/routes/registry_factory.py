"""Generic CRUD router factory shared by the skills/tools/plugins registries.

Hooks and agents extend this pattern with their own routers since they carry
extra fields (event_type, associations) — see hooks.py and agents.py.

Tenant scoping (Intelligence Layer formalization): every model this factory
serves now carries TenantScopedMixin (tenant_id nullable + version + status
— see app/models/mixins.py). NULL tenant_id is a platform-shared catalog
item, visible/attachable by every tenant but only mutable by nobody (not
even the platform's own admins, in this MVP — there's no seed/admin UI for
platform-shared items, they'd be inserted directly). A non-NULL tenant_id
is private to that tenant: visible only to its own users, writable only by
its own admins.
"""
import uuid
from typing import Type

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import authorize, get_current_user
from app.core.database import get_db
from app.core.tenant_scope import apply_shared_or_own_tenant, is_visible
from app.models.user import User
from app.schemas.registry import RegistryCreate, RegistryRead, RegistryUpdate


def make_registry_router(*, model: Type, prefix: str, tag: str) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[tag])
    resource_type = tag[:-1] if tag.endswith("s") else tag  # e.g. "tools" -> "tool", for OPA's resource.type

    def _visible(query, current_user: User):
        return apply_shared_or_own_tenant(query, model.tenant_id, current_user)

    def _get_visible_or_404(db: Session, current_user: User, item_id: uuid.UUID):
        item = db.get(model, item_id)
        if item is None or not is_visible(item.tenant_id, current_user):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{tag[:-1].title()} not found")
        return item

    @router.get("", response_model=list[RegistryRead])
    def list_items(
        db: Session = Depends(get_db),
        current_user: User = Depends(authorize(resource_type, "list")),
    ) -> list:
        query = _visible(db.query(model), current_user)
        return query.order_by(model.created_at.desc()).all()

    @router.post("", response_model=RegistryRead, status_code=status.HTTP_201_CREATED)
    def create_item(
        payload: RegistryCreate,
        db: Session = Depends(get_db),
        current_admin: User = Depends(authorize(resource_type, "create")),
    ):
        item = model(**payload.model_dump(), tenant_id=current_admin.tenant_id)
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    @router.get("/{item_id}", response_model=RegistryRead)
    def get_item(
        item_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: User = Depends(authorize(resource_type, "read")),
    ):
        return _get_visible_or_404(db, current_user, item_id)

    @router.put("/{item_id}", response_model=RegistryRead)
    def update_item(
        item_id: uuid.UUID,
        payload: RegistryUpdate,
        db: Session = Depends(get_db),
        current_admin: User = Depends(authorize(resource_type, "update")),
    ):
        item = _get_visible_or_404(db, current_admin, item_id)
        if item.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be edited")
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        db.commit()
        db.refresh(item)
        return item

    @router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_item(
        item_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_admin: User = Depends(authorize(resource_type, "delete")),
    ) -> None:
        item = _get_visible_or_404(db, current_admin, item_id)
        if item.tenant_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be deleted")
        db.delete(item)
        db.commit()
        return None

    return router
