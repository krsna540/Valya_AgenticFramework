import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import authorize
from app.core.database import get_db
from app.core.security import hash_password
from app.core.tenant_scope import apply_own_tenant, is_visible
from app.models.user import User
from app.schemas.user import AdminUserCreate, AdminUserUpdate, UserRead
from app.services import audit

router = APIRouter(prefix="/admin/users", tags=["admin-users"])

# "Users under tenants" CRUD, scoped hard to the calling admin's own
# tenant_id at every step — an admin can never see or touch another
# tenant's users, even by guessing a UUID. role is always "user" here
# (AdminUserCreate/Update enforce that at the schema level) — assigning
# admins to a tenant is a Super Admin action, see
# POST /platform/tenants/{tenant_id}/admins and
# PUT /platform/users/{id}/role.


@router.get("", response_model=list[UserRead])
def list_users(current_admin: User = Depends(authorize("user", "list")), db: Session = Depends(get_db)) -> list[UserRead]:
    users = apply_own_tenant(db.query(User), User.tenant_id, current_admin).order_by(User.created_at.desc()).all()
    return [UserRead.model_validate(u) for u in users]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: AdminUserCreate,
    current_admin: User = Depends(authorize("user", "create")),
    db: Session = Depends(get_db),
) -> UserRead:
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        tenant_id=current_admin.tenant_id,
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    audit.record(db, actor=current_admin, action="user.create", resource_type="user", resource_id=user.id, extra={"email": user.email})
    return UserRead.model_validate(user)


def _get_tenant_user(db: Session, current_admin: User, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.tenant_id != current_admin.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserRead)
def update_user(
    user_id: uuid.UUID,
    payload: AdminUserUpdate,
    current_admin: User = Depends(authorize("user", "update")),
    db: Session = Depends(get_db),
) -> UserRead:
    user = _get_tenant_user(db, current_admin, user_id)
    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        password = data.pop("password")
        if password:
            user.hashed_password = hash_password(password)
    for field, value in data.items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: uuid.UUID,
    current_admin: User = Depends(authorize("user", "delete")),
    db: Session = Depends(get_db),
) -> None:
    if user_id == current_admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")
    user = _get_tenant_user(db, current_admin, user_id)
    email = user.email
    db.delete(user)
    db.commit()
    audit.record(db, actor=current_admin, action="user.delete", resource_type="user", resource_id=user_id, extra={"email": email})
    return None
