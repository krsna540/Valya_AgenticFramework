import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    """Public signup — bootstraps a brand-new Tenant. The signing-up user
    becomes that tenant's first 'admin'; everyone after them is created by
    an admin via POST /admin/users (AdminUserCreate below), inside the
    admin's own tenant, never via this route."""

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=72)
    # Optional; defaults to "{full_name}'s Workspace" if omitted. This is
    # the *only* place a Tenant is named at creation time in this MVP —
    # renaming happens later via PUT /tenants/me.
    tenant_name: str | None = Field(default=None, min_length=1, max_length=255)


class AdminUserCreate(BaseModel):
    """Admin-only: create another user inside the admin's own tenant. No
    invite-email flow in this MVP — the admin sets the initial password
    directly and shares it out of band.

    role is restricted to "user" at the schema level — an Admin can never
    create a fellow Admin (or a Super Admin) through this endpoint, even
    before OPA gets a say (backend/policies/authz.rego's
    _privileged_user_write denies it too, defense in depth). Assigning
    admins to a tenant is a Super Admin action — see POST
    /platform/tenants/{tenant_id}/admins."""

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=72)
    role: str = Field(default="user", pattern="^user$")


class AdminUserUpdate(BaseModel):
    """role is intentionally omitted here (see AdminUserCreate's docstring)
    — an Admin can rename/deactivate/reset the password of a user in their
    tenant, but role changes go through Super Admin's
    PUT /platform/users/{id}/role instead."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=72)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class SuperAdminBootstrap(BaseModel):
    """POST /auth/bootstrap-super-admin — only works while zero super_admin
    rows exist in the whole database (self-disables after first use, see
    the route). No tenant_name here: super_admin belongs to no tenant."""

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=72)


class PlatformAdminCreate(BaseModel):
    """Super Admin-only: POST /platform/tenants/{tenant_id}/admins —
    "assigning admins to tenants" via account creation. role is implicitly
    "admin"; there's no role field here because this endpoint's whole
    purpose is creating one."""

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=72)


class PlatformUserRoleUpdate(BaseModel):
    """Super Admin-only: PUT /platform/users/{user_id}/role. Promotes or
    demotes any user, in any tenant, to any role — including minting
    additional super admins (the ongoing mechanism for that, once
    /auth/bootstrap-super-admin has self-disabled — see its docstring).

    tenant_id is required when the new role is "admin"/"user" and the
    target user currently has none (i.e. they're being demoted *from*
    super_admin) — there's no sensible default tenant to place them in.
    It's ignored when the new role is "super_admin" (tenant_id is always
    cleared to None for that role, see the route)."""

    role: str = Field(pattern="^(super_admin|admin|user)$")
    tenant_id: uuid.UUID | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_active: bool
    tenant_id: uuid.UUID | None
    role: str
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead
