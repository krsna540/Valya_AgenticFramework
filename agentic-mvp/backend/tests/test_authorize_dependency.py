"""Tests for the FastAPI dependency layer in app/api/deps.py —
`authorize()`, `authorize_tenant()`, `require_super_admin()`. These are the
OPA-backed replacement for the old binary `require_admin` gate (see
docs/AUTHORIZATION.md). No live OPA/TestClient (project convention, no
docker in this sandbox): `app.core.opa.authorize` is monkeypatched so each
dependency's own logic — 403 on deny, the super_admin tenant-scoped-write
400 guard, tenant_id passed to OPA — is exercised in isolation from the
real Rego decision. Dependency functions are called directly with
`current_user=` since `Depends(get_current_user)` is just an unused
default when invoked this way (not through FastAPI's request pipeline).
"""
import uuid

import pytest
from fastapi import HTTPException

from app.api import deps
from app.core import opa


class _FakeUser:
    def __init__(self, role, tenant_id=None):
        self.id = uuid.uuid4()
        self.role = role
        self.tenant_id = tenant_id


# --- authorize() ---------------------------------------------------------


def test_authorize_allows_when_opa_allows(monkeypatch):
    monkeypatch.setattr(opa, "authorize", lambda *a, **k: True)
    user = _FakeUser("admin", uuid.uuid4())
    dep = deps.authorize("skill", "read")
    assert dep(current_user=user) is user


def test_authorize_403_when_opa_denies(monkeypatch):
    monkeypatch.setattr(opa, "authorize", lambda *a, **k: False)
    user = _FakeUser("user", uuid.uuid4())
    dep = deps.authorize("skill", "create")
    with pytest.raises(HTTPException) as exc_info:
        dep(current_user=user)
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("action", ["create", "update", "delete", "freeze", "unfreeze", "deploy"])
def test_authorize_super_admin_write_action_is_400_not_403(monkeypatch, action):
    # OPA's super_admin rule is an unconditional allow, so without this
    # guard a super_admin (tenant_id=None) would sail through OPA and then
    # the route body would try to insert a row with tenant_id=NULL.
    monkeypatch.setattr(opa, "authorize", lambda *a, **k: True)
    user = _FakeUser("super_admin", tenant_id=None)
    dep = deps.authorize("project", action)
    with pytest.raises(HTTPException) as exc_info:
        dep(current_user=user)
    assert exc_info.value.status_code == 400


@pytest.mark.parametrize("action", ["read", "list"])
def test_authorize_super_admin_read_action_passes_through(monkeypatch, action):
    monkeypatch.setattr(opa, "authorize", lambda *a, **k: True)
    user = _FakeUser("super_admin", tenant_id=None)
    dep = deps.authorize("project", action)
    assert dep(current_user=user) is user


def test_authorize_non_super_admin_write_action_not_blocked_by_400_guard(monkeypatch):
    # The 400 guard is keyed on tenant_id is None, not on the action alone
    # — a normal admin/user with a real tenant_id must sail through.
    monkeypatch.setattr(opa, "authorize", lambda *a, **k: True)
    user = _FakeUser("admin", tenant_id=uuid.uuid4())
    dep = deps.authorize("project", "create")
    assert dep(current_user=user) is user


def test_authorize_passes_callers_own_tenant_id_to_opa(monkeypatch):
    captured = {}

    def _fake_opa_authorize(user, resource_type, action, *, tenant_id=None, target_role=None):
        captured["tenant_id"] = tenant_id
        captured["resource_type"] = resource_type
        captured["action"] = action
        return True

    monkeypatch.setattr(opa, "authorize", _fake_opa_authorize)
    tenant_id = uuid.uuid4()
    user = _FakeUser("admin", tenant_id=tenant_id)
    deps.authorize("hook", "update")(current_user=user)
    assert captured == {"tenant_id": tenant_id, "resource_type": "hook", "action": "update"}


# --- authorize_tenant() ---------------------------------------------------


def test_authorize_tenant_always_passes_tenant_id_none(monkeypatch):
    captured = {}

    def _fake_opa_authorize(user, resource_type, action, *, tenant_id=None, target_role=None):
        captured["resource_type"] = resource_type
        captured["tenant_id"] = tenant_id
        return True

    monkeypatch.setattr(opa, "authorize", _fake_opa_authorize)
    # Even though this admin has a real tenant_id, authorize_tenant() must
    # ignore it — Tenant rows aren't scoped by a "tenant's tenant_id".
    user = _FakeUser("admin", tenant_id=uuid.uuid4())
    deps.authorize_tenant("read")(current_user=user)
    assert captured == {"resource_type": "tenant", "tenant_id": None}


def test_authorize_tenant_403_when_opa_denies(monkeypatch):
    monkeypatch.setattr(opa, "authorize", lambda *a, **k: False)
    user = _FakeUser("admin", tenant_id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc_info:
        deps.authorize_tenant("delete")(current_user=user)
    assert exc_info.value.status_code == 403


def test_authorize_tenant_no_400_guard_for_super_admin(monkeypatch):
    # Unlike authorize(), authorize_tenant() has no tenant-scoped-write
    # guard — Tenant creation is exactly the one write a tenant-less
    # super_admin legitimately performs.
    monkeypatch.setattr(opa, "authorize", lambda *a, **k: True)
    user = _FakeUser("super_admin", tenant_id=None)
    assert deps.authorize_tenant("create")(current_user=user) is user


# --- require_super_admin() ------------------------------------------------


def test_require_super_admin_allows_super_admin():
    user = _FakeUser("super_admin", tenant_id=None)
    assert deps.require_super_admin(current_user=user) is user


@pytest.mark.parametrize("role", ["admin", "user"])
def test_require_super_admin_denies_everyone_else(role):
    user = _FakeUser(role, tenant_id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc_info:
        deps.require_super_admin(current_user=user)
    assert exc_info.value.status_code == 403
