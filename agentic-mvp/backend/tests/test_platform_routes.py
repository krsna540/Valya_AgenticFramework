"""Tests for app/api/routes/platform.py's route *logic* — the Super
Admin-exclusive tenant lifecycle + admin-assignment endpoints. No
TestClient/live Postgres in this sandbox (project convention): route
functions are called directly against an in-memory SQLite session, the
same way tests/test_authorize_dependency.py calls dependency functions
directly. The `_: User = Depends(authorize_tenant(...))` / `Depends(
require_super_admin)` parameter is auth-only and unused inside every route
body, so it's passed as `None` here — the OPA/role gating itself is
already covered by test_authorize_dependency.py; this file is only about
what each route *does* once past that gate.
"""
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes import platform
from app.core.database import Base
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.tenant import TenantCreate, TenantUpdate
from app.schemas.user import PlatformAdminCreate, PlatformUserRoleUpdate


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Tenant.__table__, User.__table__])
    session = Session(engine)
    yield session
    session.close()


def _make_tenant(db, name="Acme"):
    return platform.create_tenant(TenantCreate(name=name), db=db, _=None)


# --- Tenant lifecycle ------------------------------------------------------


def test_create_tenant_derives_slug(db):
    result = _make_tenant(db, "Acme Corp")
    assert result.name == "Acme Corp"
    assert "acme" in result.slug
    assert result.is_active is True


def test_create_tenant_unique_slugs_on_name_collision(db):
    a = _make_tenant(db, "Acme")
    b = _make_tenant(db, "Acme")
    assert a.slug != b.slug


def test_list_tenants_returns_all(db):
    _make_tenant(db, "One")
    _make_tenant(db, "Two")
    results = platform.list_tenants(db=db, _=None)
    assert {t.name for t in results} == {"One", "Two"}


def test_get_tenant_by_id(db):
    created = _make_tenant(db, "Acme")
    fetched = platform.get_tenant(created.id, db=db, _=None)
    assert fetched.id == created.id


def test_get_tenant_404_when_missing(db):
    with pytest.raises(HTTPException) as exc_info:
        platform.get_tenant(uuid.uuid4(), db=db, _=None)
    assert exc_info.value.status_code == 404


def test_update_tenant_partial_fields(db):
    created = _make_tenant(db, "Acme")
    updated = platform.update_tenant(created.id, TenantUpdate(is_active=False), db=db, _=None)
    assert updated.is_active is False
    assert updated.name == "Acme"  # untouched field preserved


def test_delete_tenant_removes_row(db):
    created = _make_tenant(db, "Acme")
    platform.delete_tenant(created.id, db=db, _=None)
    with pytest.raises(HTTPException) as exc_info:
        platform.get_tenant(created.id, db=db, _=None)
    assert exc_info.value.status_code == 404


# --- Assigning admins to tenants --------------------------------------------


def test_create_tenant_admin_sets_role_and_tenant(db):
    tenant = _make_tenant(db, "Acme")
    payload = PlatformAdminCreate(email="admin@acme.com", full_name="New Admin", password="password123")
    user = platform.create_tenant_admin(tenant.id, payload, db=db, _=None)
    assert user.role == "admin"
    assert user.tenant_id == tenant.id


def test_create_tenant_admin_404_for_missing_tenant(db):
    payload = PlatformAdminCreate(email="admin@acme.com", full_name="New Admin", password="password123")
    with pytest.raises(HTTPException) as exc_info:
        platform.create_tenant_admin(uuid.uuid4(), payload, db=db, _=None)
    assert exc_info.value.status_code == 404


def test_create_tenant_admin_409_on_duplicate_email(db):
    tenant = _make_tenant(db, "Acme")
    payload = PlatformAdminCreate(email="dupe@acme.com", full_name="A", password="password123")
    platform.create_tenant_admin(tenant.id, payload, db=db, _=None)
    with pytest.raises(HTTPException) as exc_info:
        platform.create_tenant_admin(tenant.id, payload, db=db, _=None)
    assert exc_info.value.status_code == 409


# --- Cross-tenant role management -------------------------------------------


def test_update_user_role_promote_to_super_admin_clears_tenant(db):
    tenant = _make_tenant(db, "Acme")
    admin = platform.create_tenant_admin(
        tenant.id, PlatformAdminCreate(email="a@acme.com", full_name="A", password="password123"), db=db, _=None
    )
    updated = platform.update_user_role(admin.id, PlatformUserRoleUpdate(role="super_admin"), db=db, _=None)
    assert updated.role == "super_admin"
    assert updated.tenant_id is None


def test_update_user_role_demote_requires_tenant_id_when_none(db):
    tenant = _make_tenant(db, "Acme")
    admin = platform.create_tenant_admin(
        tenant.id, PlatformAdminCreate(email="a@acme.com", full_name="A", password="password123"), db=db, _=None
    )
    promoted = platform.update_user_role(admin.id, PlatformUserRoleUpdate(role="super_admin"), db=db, _=None)
    assert promoted.tenant_id is None

    with pytest.raises(HTTPException) as exc_info:
        platform.update_user_role(promoted.id, PlatformUserRoleUpdate(role="admin"), db=db, _=None)
    assert exc_info.value.status_code == 400


def test_update_user_role_demote_with_explicit_tenant_id(db):
    tenant = _make_tenant(db, "Acme")
    admin = platform.create_tenant_admin(
        tenant.id, PlatformAdminCreate(email="a@acme.com", full_name="A", password="password123"), db=db, _=None
    )
    promoted = platform.update_user_role(admin.id, PlatformUserRoleUpdate(role="super_admin"), db=db, _=None)

    demoted = platform.update_user_role(
        promoted.id, PlatformUserRoleUpdate(role="user", tenant_id=tenant.id), db=db, _=None
    )
    assert demoted.role == "user"
    assert demoted.tenant_id == tenant.id


def test_update_user_role_keeps_existing_tenant_when_tenant_id_omitted(db):
    tenant = _make_tenant(db, "Acme")
    admin = platform.create_tenant_admin(
        tenant.id, PlatformAdminCreate(email="a@acme.com", full_name="A", password="password123"), db=db, _=None
    )
    updated = platform.update_user_role(admin.id, PlatformUserRoleUpdate(role="user"), db=db, _=None)
    assert updated.role == "user"
    assert updated.tenant_id == tenant.id  # unchanged, not cleared


def test_update_user_role_404_for_missing_target_tenant(db):
    tenant = _make_tenant(db, "Acme")
    admin = platform.create_tenant_admin(
        tenant.id, PlatformAdminCreate(email="a@acme.com", full_name="A", password="password123"), db=db, _=None
    )
    with pytest.raises(HTTPException) as exc_info:
        platform.update_user_role(
            admin.id, PlatformUserRoleUpdate(role="admin", tenant_id=uuid.uuid4()), db=db, _=None
        )
    assert exc_info.value.status_code == 404


def test_update_user_role_404_for_missing_user(db):
    with pytest.raises(HTTPException) as exc_info:
        platform.update_user_role(uuid.uuid4(), PlatformUserRoleUpdate(role="admin"), db=db, _=None)
    assert exc_info.value.status_code == 404


def test_list_all_users_unfiltered(db):
    t1 = _make_tenant(db, "One")
    t2 = _make_tenant(db, "Two")
    platform.create_tenant_admin(t1.id, PlatformAdminCreate(email="a@one.com", full_name="A", password="password123"), db=db, _=None)
    platform.create_tenant_admin(t2.id, PlatformAdminCreate(email="b@two.com", full_name="B", password="password123"), db=db, _=None)

    results = platform.list_all_users(tenant_id=None, db=db, _=None)
    assert {u.email for u in results} == {"a@one.com", "b@two.com"}


def test_list_all_users_filtered_by_tenant(db):
    t1 = _make_tenant(db, "One")
    t2 = _make_tenant(db, "Two")
    platform.create_tenant_admin(t1.id, PlatformAdminCreate(email="a@one.com", full_name="A", password="password123"), db=db, _=None)
    platform.create_tenant_admin(t2.id, PlatformAdminCreate(email="b@two.com", full_name="B", password="password123"), db=db, _=None)

    results = platform.list_all_users(tenant_id=t1.id, db=db, _=None)
    assert {u.email for u in results} == {"a@one.com"}
