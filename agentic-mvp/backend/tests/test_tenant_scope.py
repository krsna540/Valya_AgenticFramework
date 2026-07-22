"""Tests for app/core/tenant_scope.py — the "which specific rows" half of
authorization that OPA deliberately doesn't decide (see that module's
docstring). No live DB/TestClient (project convention): the SQL-building
helpers (`shared_or_own_tenant_filter`, `own_tenant_filter`,
`apply_shared_or_own_tenant`, `apply_own_tenant`) are exercised against an
in-memory SQLite session so the generated WHERE clauses can actually be
executed and their row-selection behavior checked end-to-end, rather than
just asserting on the compiled SQL string. `is_visible` is pure Python and
needs no DB at all.
"""
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.tenant_scope import (
    apply_own_tenant,
    apply_shared_or_own_tenant,
    is_visible,
    own_tenant_filter,
    shared_or_own_tenant_filter,
)
from app.models.skill import Skill
from app.models.tenant import Tenant
from app.models.user import User


class _FakeUser:
    def __init__(self, role, tenant_id=None):
        self.id = uuid.uuid4()
        self.role = role
        self.tenant_id = tenant_id


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    # Only the tables these tests touch — Base.metadata.create_all() would
    # also try to create every other registered model (e.g. Persona's
    # postgresql JSONB column), which SQLite's DDL compiler can't render.
    Base.metadata.create_all(engine, tables=[Tenant.__table__, User.__table__, Skill.__table__])
    session = Session(engine)
    yield session
    session.close()


def _make_tenant(db, name="t"):
    t = Tenant(id=uuid.uuid4(), name=name, slug=f"{name}-{uuid.uuid4().hex[:6]}")
    db.add(t)
    db.commit()
    return t


def _make_skill(db, *, tenant_id, name):
    s = Skill(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        description=None,
        skill_md_raw="---\nname: x\ndescription: x\n---\n",
        body_markdown="",
        dir_path=f"/tmp/{name}",
        uploaded_by=uuid.uuid4(),
    )
    db.add(s)
    db.commit()
    return s


# --- shared_or_own_tenant_filter / apply_shared_or_own_tenant ------------


def test_shared_or_own_tenant_sees_own_and_platform_shared(db):
    tenant_a = _make_tenant(db, "a")
    tenant_b = _make_tenant(db, "b")
    own = _make_skill(db, tenant_id=tenant_a.id, name="own")
    shared = _make_skill(db, tenant_id=None, name="shared")
    other = _make_skill(db, tenant_id=tenant_b.id, name="other")

    user = _FakeUser("admin", tenant_id=tenant_a.id)
    results = apply_shared_or_own_tenant(db.query(Skill), Skill.tenant_id, user).all()
    names = {r.name for r in results}
    assert names == {"own", "shared"}
    assert other.name not in names


def test_shared_or_own_tenant_super_admin_sees_everything(db):
    tenant_a = _make_tenant(db, "a")
    tenant_b = _make_tenant(db, "b")
    _make_skill(db, tenant_id=tenant_a.id, name="a-skill")
    _make_skill(db, tenant_id=tenant_b.id, name="b-skill")
    _make_skill(db, tenant_id=None, name="shared-skill")

    user = _FakeUser("super_admin", tenant_id=None)
    results = apply_shared_or_own_tenant(db.query(Skill), Skill.tenant_id, user).all()
    assert {r.name for r in results} == {"a-skill", "b-skill", "shared-skill"}


def test_shared_or_own_tenant_plain_user_never_sees_other_tenants(db):
    tenant_a = _make_tenant(db, "a")
    tenant_b = _make_tenant(db, "b")
    _make_skill(db, tenant_id=tenant_b.id, name="not-mine")

    user = _FakeUser("user", tenant_id=tenant_a.id)
    results = apply_shared_or_own_tenant(db.query(Skill), Skill.tenant_id, user).all()
    assert results == []


# --- own_tenant_filter / apply_own_tenant (no platform-shared concept) ---


def test_own_tenant_filter_excludes_other_tenants_users(db):
    tenant_a = _make_tenant(db, "a")
    tenant_b = _make_tenant(db, "b")
    u1 = User(id=uuid.uuid4(), email="u1@a.com", full_name="U1", hashed_password="x", tenant_id=tenant_a.id, role="user")
    u2 = User(id=uuid.uuid4(), email="u2@b.com", full_name="U2", hashed_password="x", tenant_id=tenant_b.id, role="user")
    db.add_all([u1, u2])
    db.commit()

    caller = _FakeUser("admin", tenant_id=tenant_a.id)
    results = apply_own_tenant(db.query(User), User.tenant_id, caller).all()
    assert {r.email for r in results} == {"u1@a.com"}


def test_own_tenant_filter_super_admin_sees_every_tenants_users(db):
    tenant_a = _make_tenant(db, "a")
    tenant_b = _make_tenant(db, "b")
    u1 = User(id=uuid.uuid4(), email="u1@a.com", full_name="U1", hashed_password="x", tenant_id=tenant_a.id, role="user")
    u2 = User(id=uuid.uuid4(), email="u2@b.com", full_name="U2", hashed_password="x", tenant_id=tenant_b.id, role="user")
    db.add_all([u1, u2])
    db.commit()

    caller = _FakeUser("super_admin", tenant_id=None)
    results = apply_own_tenant(db.query(User), User.tenant_id, caller).all()
    assert {r.email for r in results} == {"u1@a.com", "u2@b.com"}


# --- is_visible (single-row equivalent) -----------------------------------


def test_is_visible_super_admin_sees_any_row():
    user = _FakeUser("super_admin", tenant_id=None)
    assert is_visible(uuid.uuid4(), user) is True
    assert is_visible(None, user) is True


def test_is_visible_shared_row_visible_by_default():
    tenant_id = uuid.uuid4()
    user = _FakeUser("admin", tenant_id=tenant_id)
    assert is_visible(None, user) is True


def test_is_visible_shared_row_hidden_when_shared_ok_false():
    tenant_id = uuid.uuid4()
    user = _FakeUser("admin", tenant_id=tenant_id)
    assert is_visible(None, user, shared_ok=False) is False


def test_is_visible_own_tenant_row_visible():
    tenant_id = uuid.uuid4()
    user = _FakeUser("admin", tenant_id=tenant_id)
    assert is_visible(tenant_id, user) is True


def test_is_visible_other_tenant_row_hidden():
    user = _FakeUser("admin", tenant_id=uuid.uuid4())
    assert is_visible(uuid.uuid4(), user) is False


# --- raw filter builders (sanity: super_admin branch is trivially true) ---


def test_shared_or_own_tenant_filter_super_admin_is_unconditional_true(db):
    user = _FakeUser("super_admin", tenant_id=None)
    cond = shared_or_own_tenant_filter(Skill.tenant_id, user)
    assert db.query(Skill).filter(cond).count() == db.query(Skill).count()


def test_own_tenant_filter_super_admin_is_unconditional_true(db):
    user = _FakeUser("super_admin", tenant_id=None)
    cond = own_tenant_filter(User.tenant_id, user)
    assert db.query(User).filter(cond).count() == db.query(User).count()
