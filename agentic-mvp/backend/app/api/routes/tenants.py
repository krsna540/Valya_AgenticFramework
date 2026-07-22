from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import authorize
from app.core.database import get_db
from app.models.user import User
from app.schemas.tenant import TenantRead, TenantUpdate
from app.services import audit

router = APIRouter(prefix="/tenants", tags=["tenants"])

# An Admin manages exactly their own tenant's profile — GET/PUT /tenants/me
# (backend/policies/authz.rego's explicit admin-own-tenant carve-out).
# Full tenant lifecycle management — create, list every tenant, delete, or
# touch another tenant — is Super Admin-only, via /platform/tenants
# (app/api/routes/platform.py). That split is what "Creation of tenants
# and assigning admins to tenants" being a Super Admin-exclusive capability
# means in practice; see docs/AUTHORIZATION.md.


def _own_tenant_or_400(current_admin: User) -> None:
    # A super_admin has no tenant (tenant_id is None) and OPA's
    # unconditional allow means they'd otherwise sail past the dependency
    # only to hit an AttributeError below — this route is "my tenant",
    # which doesn't mean anything for a platform-level account. Super
    # Admins manage tenants via /platform/tenants instead.
    if current_admin.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Super admin has no tenant of their own — use /platform/tenants")


@router.get("/me", response_model=TenantRead)
def read_my_tenant(current_admin: User = Depends(authorize("tenant", "read")), db: Session = Depends(get_db)) -> TenantRead:
    _own_tenant_or_400(current_admin)
    return TenantRead.model_validate(current_admin.tenant)


@router.put("/me", response_model=TenantRead)
def update_my_tenant(
    payload: TenantUpdate,
    current_admin: User = Depends(authorize("tenant", "update")),
    db: Session = Depends(get_db),
) -> TenantRead:
    _own_tenant_or_400(current_admin)
    tenant = current_admin.tenant
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)
    db.commit()
    db.refresh(tenant)
    audit.record(db, actor=current_admin, action="tenant.settings_update", resource_type="tenant", resource_id=tenant.id)
    return TenantRead.model_validate(tenant)
