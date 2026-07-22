"""Sanity checks on alembic/versions/0012_rbac_super_admin.py — the
migration introducing the three-role model (role rename member->user,
users.tenant_id made nullable for super_admin). No live Postgres in this
sandbox (project convention), so this doesn't run the migration against a
real database; it inspects the module's upgrade()/downgrade() source to
catch the kind of copy-paste/inversion mistakes that are easy to make by
hand (e.g. accidentally swapping the rename direction, or leaving a column
non-nullable) without needing a DB to do it.
"""
import importlib.util
import inspect
from pathlib import Path

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0012_rbac_super_admin.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0012", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_file_exists():
    assert _MIGRATION_PATH.is_file()


def test_revision_chain_links_to_0011():
    migration = _load_migration()
    assert migration.revision == "0012"
    assert migration.down_revision == "0011"


def test_upgrade_makes_tenant_id_nullable():
    migration = _load_migration()
    source = inspect.getsource(migration.upgrade)
    assert "tenant_id" in source
    assert "nullable=True" in source


def test_upgrade_renames_member_to_user_not_reverse():
    migration = _load_migration()
    source = inspect.getsource(migration.upgrade)
    assert "role = 'user'" in source
    assert "role = 'member'" in source
    # The UPDATE must set role TO 'user' FROM 'member' — not the reverse —
    # this is the one line that's easy to get backwards by hand.
    assert "SET role = 'user' WHERE role = 'member'" in source


def test_downgrade_reverses_both_steps():
    migration = _load_migration()
    source = inspect.getsource(migration.downgrade)
    assert "SET role = 'member' WHERE role = 'user'" in source
    assert "nullable=False" in source


def test_downgrade_is_inverse_direction_of_upgrade():
    migration = _load_migration()
    up_source = inspect.getsource(migration.upgrade)
    down_source = inspect.getsource(migration.downgrade)
    assert "nullable=True" in up_source and "nullable=False" in down_source
    assert "role = 'user' WHERE role = 'member'" in up_source
    assert "role = 'member' WHERE role = 'user'" in down_source
