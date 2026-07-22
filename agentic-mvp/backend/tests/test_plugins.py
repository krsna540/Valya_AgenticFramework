"""Schema-level tests for Plugin's export validation (app/schemas/plugin.py).
Pure pydantic — no DB, no app framework — same style as test_platform_pillars.py.

exports_hooks is checked against the fixed BUILTIN_HOOKS catalog.
exports_skills is NOT checked against anything here — skills used to be
handler_key-bound to a fixed catalog (same shape as hooks) but that system
was retired in favor of the SKILL.md-folder format, which is dynamic,
user-uploaded, tenant-scoped content with no fixed in-process registry to
validate against. See app/schemas/plugin.py's module docstring.
"""
import pytest
from pydantic import ValidationError

from app.schemas.plugin import PluginCreate, PluginUpdate
from app.services.hooks import BUILTIN_HOOKS


def test_plugin_create_accepts_known_hook_export():
    known_hook = next(iter(BUILTIN_HOOKS))
    plugin = PluginCreate(name="security_baseline", exports_hooks=[known_hook])
    assert plugin.exports_hooks == [known_hook]


def test_plugin_create_accepts_any_skill_export():
    # Advisory only — any string is accepted, unlike exports_hooks.
    plugin = PluginCreate(name="my_plugin", exports_skills=["some-uploaded-skill"])
    assert plugin.exports_skills == ["some-uploaded-skill"]


def test_plugin_create_rejects_unknown_hook_export():
    with pytest.raises(ValidationError, match="exports_hooks"):
        PluginCreate(name="bad_plugin", exports_hooks=["not_a_real_hook"])


def test_plugin_create_defaults_are_empty():
    plugin = PluginCreate(name="empty_plugin")
    assert plugin.exports_skills == []
    assert plugin.exports_hooks == []
    assert plugin.exports_tools == []
    assert plugin.exports_commands == []
    assert plugin.requires_permissions == []
    assert plugin.requires_env == []


def test_plugin_update_allows_partial_payload_without_reexports():
    # Updating just the name shouldn't force exports_hooks to be
    # re-declared or fail validation against an empty list.
    update = PluginUpdate(name="renamed")
    assert update.exports_skills is None
    assert update.exports_hooks is None


def test_plugin_update_rejects_unknown_hook_export_when_changed():
    with pytest.raises(ValidationError, match="exports_hooks"):
        PluginUpdate(exports_hooks=["not_a_real_hook"])


def test_plugin_update_accepts_known_hook_export_when_changed():
    known_hook = next(iter(BUILTIN_HOOKS))
    update = PluginUpdate(exports_hooks=[known_hook])
    assert update.exports_hooks == [known_hook]
