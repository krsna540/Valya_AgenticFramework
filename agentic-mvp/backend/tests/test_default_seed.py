"""Tests for app/skills/default_seed.py — the one place a Skill row is
created outside POST /skills/upload (seeded per-tenant at signup). No real
DB/TestClient (project convention, no docker/live Postgres in this
sandbox): a minimal fake Session stands in for SQLAlchemy's, recording
`.add()` calls and letting `seed_default_skill`'s idempotency check be
driven explicitly per test.
"""
import uuid

from app.models.skill import Skill
from app.skills.default_seed import _BUNDLED_SKILL_PATH, _DEFAULT_SKILL_DIR_NAME, seed_default_skill


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeSession:
    def __init__(self, existing: Skill | None = None):
        self._existing = existing
        self.added: list[Skill] = []

    def query(self, *args, **kwargs):
        return _FakeQuery(self._existing)

    def add(self, obj):
        self.added.append(obj)


def test_bundled_skill_folder_exists_and_is_valid():
    # Sanity check on the bundled asset itself, independent of seed_default_skill's
    # own file-existence guard — catches a corrupted/missing bundle early.
    assert (_BUNDLED_SKILL_PATH / "SKILL.md").is_file()
    assert (_BUNDLED_SKILL_PATH / "skill.json").is_file()
    assert (_BUNDLED_SKILL_PATH / "scripts" / "text_case.py").is_file()


def test_seed_default_skill_creates_skill(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "skill_packages_dir", str(tmp_path))
    db = _FakeSession(existing=None)
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    result = seed_default_skill(db, tenant_id=tenant_id, uploaded_by=user_id)

    assert result is not None
    assert result.name == _DEFAULT_SKILL_DIR_NAME
    assert result.tenant_id == tenant_id
    assert result.uploaded_by == user_id
    assert result.is_active is True
    assert "SKILL.md body" not in "".join(result.file_manifest)  # sanity: not a warning string
    assert set(result.file_manifest) == {"SKILL.md", "skill.json", "scripts/text_case.py"}
    assert result.triggers["intents"] == ["text_transformation"]
    assert result.hooks == []
    assert db.added == [result]


def test_seed_default_skill_is_idempotent(tmp_path, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "skill_packages_dir", str(tmp_path))
    already_there = Skill(
        id=uuid.uuid4(),
        name=_DEFAULT_SKILL_DIR_NAME,
        description="x",
        skill_md_raw="---\nname: text-case-converter\ndescription: x\n---\n",
        body_markdown="",
        dir_path="/tmp/wherever",
        uploaded_by=uuid.uuid4(),
    )
    db = _FakeSession(existing=already_there)

    result = seed_default_skill(db, tenant_id=uuid.uuid4(), uploaded_by=uuid.uuid4())

    assert result is already_there
    assert db.added == []  # nothing new inserted
