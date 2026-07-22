"""Tenant-scoped access policies — the Admin Norms tab's "Access policies"
list. Admin CRUD within their own tenant, via the same generic authorize()
pattern as Personas/Datasources (see app/api/deps.py::authorize and
backend/policies/authz.rego — "policy" isn't a platform-shared resource
type, so the plain admin-own-tenant read/write rules cover it with no Rego
changes needed).

Route order matters here: the static "/mappings" paths must be declared
before the dynamic "/{policy_id}" paths, or FastAPI/Starlette's
first-match routing would try to bind "mappings" to the policy_id: UUID
parameter (and 422 before ever reaching the real mappings handler).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import authorize
from app.core.database import get_db
from app.core.tenant_scope import apply_own_tenant, is_visible
from app.models.policy import Policy, UserPolicyMapping
from app.models.user import User
from app.schemas.policy import PolicyCreate, PolicyMappingCreate, PolicyMappingRead, PolicyRead, PolicyUpdate
from app.services import audit

router = APIRouter(prefix="/policies", tags=["policies"])


def _get_tenant_policy(db: Session, current_user: User, policy_id: uuid.UUID) -> Policy:
    policy = db.get(Policy, policy_id)
    if policy is None or not is_visible(policy.tenant_id, current_user, shared_ok=False):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    return policy


@router.get("", response_model=list[PolicyRead])
def list_policies(db: Session = Depends(get_db), current_user: User = Depends(authorize("policy", "list"))) -> list[PolicyRead]:
    policies = apply_own_tenant(db.query(Policy), Policy.tenant_id, current_user).order_by(Policy.created_at.desc()).all()
    return [PolicyRead.model_validate(p) for p in policies]


@router.post("", response_model=PolicyRead, status_code=status.HTTP_201_CREATED)
def create_policy(
    payload: PolicyCreate, db: Session = Depends(get_db), current_admin: User = Depends(authorize("policy", "create"))
) -> PolicyRead:
    policy = Policy(tenant_id=current_admin.tenant_id, created_by=current_admin.id, **payload.model_dump())
    db.add(policy)
    db.commit()
    db.refresh(policy)
    audit.record(db, actor=current_admin, action="policy.create", resource_type="policy", resource_id=policy.id, extra={"name": policy.name})
    return PolicyRead.model_validate(policy)


# --- User <-> Policy mappings (Norms tab "Users & assignments") -------------
# Declared before "/{policy_id}" — see module docstring.


@router.get("/mappings", response_model=list[PolicyMappingRead])
def list_policy_mappings(db: Session = Depends(get_db), current_admin: User = Depends(authorize("policy", "list"))) -> list[PolicyMappingRead]:
    mappings = apply_own_tenant(
        db.query(UserPolicyMapping).join(Policy, Policy.id == UserPolicyMapping.policy_id),
        Policy.tenant_id,
        current_admin,
    ).all()
    return [PolicyMappingRead.model_validate(m) for m in mappings]


@router.post("/mappings", response_model=PolicyMappingRead, status_code=status.HTTP_201_CREATED)
def create_policy_mapping(
    payload: PolicyMappingCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("policy", "update")),
) -> PolicyMappingRead:
    _get_tenant_policy(db, current_admin, payload.policy_id)
    target_user = db.get(User, payload.user_id)
    if target_user is None or target_user.tenant_id != current_admin.tenant_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User not found in this tenant")
    existing = (
        db.query(UserPolicyMapping)
        .filter(UserPolicyMapping.user_id == payload.user_id, UserPolicyMapping.policy_id == payload.policy_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Mapping already exists")
    mapping = UserPolicyMapping(**payload.model_dump())
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    audit.record(
        db,
        actor=current_admin,
        action="policy.assign_user",
        resource_type="policy",
        resource_id=payload.policy_id,
        extra={"user_id": str(payload.user_id)},
    )
    return PolicyMappingRead.model_validate(mapping)


@router.delete("/mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy_mapping(
    mapping_id: uuid.UUID, db: Session = Depends(get_db), current_admin: User = Depends(authorize("policy", "update"))
) -> None:
    mapping = db.get(UserPolicyMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    policy = db.get(Policy, mapping.policy_id)
    if policy is None or policy.tenant_id != current_admin.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found")
    db.delete(mapping)
    db.commit()
    return None


# --- Single-policy CRUD (dynamic "/{policy_id}" — must stay after the
# static "/mappings" routes above) -------------------------------------------


@router.get("/{policy_id}", response_model=PolicyRead)
def get_policy(policy_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("policy", "read"))) -> PolicyRead:
    return PolicyRead.model_validate(_get_tenant_policy(db, current_user, policy_id))


@router.put("/{policy_id}", response_model=PolicyRead)
def update_policy(
    policy_id: uuid.UUID,
    payload: PolicyUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("policy", "update")),
) -> PolicyRead:
    policy = _get_tenant_policy(db, current_admin, policy_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)
    db.commit()
    db.refresh(policy)
    audit.record(db, actor=current_admin, action="policy.update", resource_type="policy", resource_id=policy.id)
    return PolicyRead.model_validate(policy)


@router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_policy(
    policy_id: uuid.UUID, db: Session = Depends(get_db), current_admin: User = Depends(authorize("policy", "delete"))
) -> None:
    policy = _get_tenant_policy(db, current_admin, policy_id)
    db.delete(policy)
    db.commit()
    audit.record(db, actor=current_admin, action="policy.delete", resource_type="policy", resource_id=policy_id)
    return None
