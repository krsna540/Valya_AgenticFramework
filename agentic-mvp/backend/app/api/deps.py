import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core import opa
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
# Same bearer scheme but non-raising, so routes can fall back to a query-param
# token (see get_current_user_flexible) for contexts that can't set headers.
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def _resolve_user(token: str | None, db: Session) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    subject = decode_access_token(token)
    if subject is None:
        raise credentials_exception
    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        raise credentials_exception

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    return _resolve_user(token, db)


def get_current_user_flexible(
    access_token: str | None = None,
    header_token: str | None = Depends(oauth2_scheme_optional),
    db: Session = Depends(get_db),
) -> User:
    """Accepts the JWT via Authorization header (normal case) OR an
    `access_token` query param. Only used for the file-content route, which
    browsers may load via plain <img src>/<a href> where custom headers can't
    be set."""
    return _resolve_user(header_token or access_token, db)


# Actions that insert/mutate a row scoped to "the caller's own tenant" —
# meaningless for a super_admin, who has no tenant of their own. Reads
# (list/read) are fine: those routes are expected to broaden what they
# return for a super_admin (see docs/AUTHORIZATION.md's cross-tenant read
# visibility section) rather than reject the request outright.
_TENANT_SCOPED_WRITE_ACTIONS = {"create", "update", "delete", "freeze", "unfreeze", "deploy"}


def authorize(resource_type: str, action: str):
    """Dependency factory — the OPA-backed replacement for the old
    `require_admin` gate. Returns a FastAPI dependency that asks
    backend/policies/authz.rego whether `current_user` may perform
    `action` on a resource of `resource_type`, scoped to the caller's own
    tenant (`current_user.tenant_id` — None for super_admin, whose policy
    branch ignores tenant scoping entirely, so OPA alone would happily
    wave a super_admin through every one of these routes). 403s on denial.

    Because OPA's super_admin rule is unconditional, this dependency adds
    one guard OPA can't express on its own: a super_admin calling a
    *write* action through one of these generic per-tenant routes (create
    a Project, an Agent, a user, ...) with no tenant context at all would
    otherwise insert a row with tenant_id=NULL, which is nonsensical for
    every one of these tenant-scoped models. That's a 400 (bad request —
    "this ID doesn't mean anything for your account"), not a 403 (which
    would incorrectly imply a permissions problem). A super_admin manages
    tenant contents by creating/assigning that tenant's Admin
    (POST /platform/tenants/{id}/admins) rather than by directly writing
    into arbitrary tenants' registries through these routes.

    This answers the coarse "is this role even allowed to attempt this
    kind of action" question. Per-row tenant scoping (e.g. "does this
    specific Project actually belong to my tenant") still happens exactly
    as before, in each route's own SQL query / `_visible_or_404`-style
    helper — OPA and the data layer are deliberately separate concerns,
    not a replacement for one another. See docs/AUTHORIZATION.md.

    Not suitable for endpoints where the authorization decision depends on
    a value only known after the request body is parsed or an existing
    row is fetched (e.g. "who is this User resource's target_role,
    'admin' or 'user'?") — those routes call `app.core.opa.authorize(...)`
    directly instead. See app/api/routes/platform.py.
    """

    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if not opa.authorize(current_user, resource_type, action, tenant_id=current_user.tenant_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        if current_user.tenant_id is None and action in _TENANT_SCOPED_WRITE_ACTIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Super admin has no tenant of their own — manage a tenant's contents via its Admin instead",
            )
        return current_user

    return _dependency


def authorize_tenant(action: str):
    """Like `authorize()`, but for resource_type == "tenant" — Tenant rows
    aren't themselves scoped to a tenant (there's no "tenant's tenant_id"),
    so this always passes `tenant_id=None` rather than the caller's own.
    Only super_admin's policy branch ever allows this resource type."""

    def _dependency(current_user: User = Depends(get_current_user)) -> User:
        if not opa.authorize(current_user, "tenant", action, tenant_id=None):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
        return current_user

    return _dependency


def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    """A handful of /platform endpoints (cross-tenant user listing, role
    promotion) don't map cleanly onto a single (resource_type, action,
    tenant_id) tuple — this is the plain role gate for those. Prefer
    `authorize()`/`authorize_tenant()` (OPA-backed) wherever the action
    does fit that shape."""
    if current_user.role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin role required")
    return current_user
