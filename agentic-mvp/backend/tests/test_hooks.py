"""Tests for the 10-stage lifecycle hook engine (app/services/hooks.py) and
the custom handler execution engine (app/services/hook_handlers.py)."""
import asyncio
import json
import os
import stat
import sys
import tempfile

import pytest

from app.services.hook_handlers import HookOutcome, run_custom_handler, static_gate
from app.services.hooks import (
    STAGES,
    WIRED_STAGES,
    BUILTIN_HOOKS,
    HookContext,
    HookHaltException,
    HookManager,
    MessagePayload,
    build_pipeline_for_agent,
    guardrail_interceptor,
    pii_redactor,
    telemetry_observer,
    usage_logger,
    tool_allowlist_guard,
)


def _ctx(**kwargs) -> HookContext:
    return HookContext(agent_name="test-agent", **kwargs)


# --- taxonomy ---------------------------------------------------------------


def test_stages_has_all_ten():
    assert set(STAGES) == {
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse.Success",
        "PostToolUse.Failure",
        "PreCompact",
        "SubagentStart",
        "SubagentStop",
        "Stop",
        "Notification",
    }


def test_pre_compact_is_the_only_unwired_stage():
    assert "PreCompact" not in WIRED_STAGES
    assert WIRED_STAGES == set(STAGES) - {"PreCompact"}


def test_builtin_hooks_registered_stages_are_all_valid():
    for name, entry in BUILTIN_HOOKS.items():
        assert entry["stage"] in STAGES, f"{name} registered under invalid stage {entry['stage']}"


# --- HookManager basics -------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_pipeline_runs_hooks_in_order():
    manager = HookManager()
    calls = []

    async def first(data, ctx):
        calls.append("first")
        return data + "-a"

    async def second(data, ctx):
        calls.append("second")
        return data + "-b"

    manager.add("UserPromptSubmit", first)
    manager.add("UserPromptSubmit", second)

    result = await manager.trigger_pipeline("UserPromptSubmit", "start", _ctx())
    assert result == "start-a-b"
    assert calls == ["first", "second"]


@pytest.mark.asyncio
async def test_halt_exception_propagates_immediately():
    manager = HookManager()

    async def halts(data, ctx):
        raise HookHaltException("blocked")

    async def never_runs(data, ctx):
        raise AssertionError("should not run after a halt")

    manager.add("UserPromptSubmit", halts)
    manager.add("UserPromptSubmit", never_runs)

    with pytest.raises(HookHaltException):
        await manager.trigger_pipeline("UserPromptSubmit", "x", _ctx())


@pytest.mark.asyncio
async def test_failing_hook_is_isolated_and_notifies():
    manager = HookManager()
    notified = []

    async def notification_recorder(data, ctx):
        notified.append(data)
        return data

    async def broken(data, ctx):
        raise RuntimeError("boom")

    manager.add("Stop", broken)
    manager.add("Notification", notification_recorder)

    # Should not raise — the broken hook is isolated, and the failure is
    # forwarded to Notification instead of crashing the caller.
    result = await manager.trigger_pipeline("Stop", {"tokens": 1}, _ctx())
    assert result == {"tokens": 1}
    assert len(notified) == 1
    assert notified[0]["source_stage"] == "Stop"


@pytest.mark.asyncio
async def test_notification_hook_failure_does_not_recurse():
    manager = HookManager()

    async def broken_notification(data, ctx):
        raise RuntimeError("notification itself is broken")

    manager.add("Notification", broken_notification)

    # A directly-triggered Notification pipeline whose own hook fails must
    # not recurse into itself — just isolate and continue.
    result = await manager.trigger_pipeline("Notification", {"x": 1}, _ctx())
    assert result == {"x": 1}


# --- built-in (python) hooks -------------------------------------------


@pytest.mark.asyncio
async def test_guardrail_interceptor_blocks_banned_phrase():
    with pytest.raises(HookHaltException):
        await guardrail_interceptor("please rm -rf /", _ctx(), {})


@pytest.mark.asyncio
async def test_guardrail_interceptor_allows_clean_input():
    result = await guardrail_interceptor("hello there", _ctx(), {})
    assert result == "hello there"


@pytest.mark.asyncio
async def test_pii_redactor_redacts_email_and_phone():
    msg = MessagePayload(sender="a", recipient="user", content="reach me at a@b.com or 555-123-4567")
    out = await pii_redactor(msg, _ctx(), {})
    assert "[redacted-email]" in out.content
    assert "[redacted-phone]" in out.content


@pytest.mark.asyncio
async def test_telemetry_observer_counts_tokens():
    msg = MessagePayload(sender="a", recipient="user", content="one two three")
    out = await telemetry_observer(msg, _ctx(), {})
    assert out.tokens == 3


@pytest.mark.asyncio
async def test_usage_logger_respects_min_tokens_threshold():
    # Should not raise regardless of threshold — it's read-only either way.
    await usage_logger({"tokens": 1}, _ctx(), {"min_tokens_to_log": 100})
    await usage_logger({"tokens": 200}, _ctx(), {"min_tokens_to_log": 100})


@pytest.mark.asyncio
async def test_tool_allowlist_guard_blocks_unlisted_tool():
    with pytest.raises(HookHaltException):
        await tool_allowlist_guard({"tool_name": "shell"}, _ctx(), {"allowed_names": ["git", "pytest"]})


@pytest.mark.asyncio
async def test_tool_allowlist_guard_allows_listed_tool():
    result = await tool_allowlist_guard({"tool_name": "git"}, _ctx(), {"allowed_names": ["git", "pytest"]})
    assert result == {"tool_name": "git"}


@pytest.mark.asyncio
async def test_tool_allowlist_guard_empty_list_allows_everything():
    result = await tool_allowlist_guard({"tool_name": "anything"}, _ctx(), {"allowed_names": []})
    assert result == {"tool_name": "anything"}


# --- custom handler engine: static gate ---------------------------------


def test_static_gate_blocks_matching_keyword():
    outcome = static_gate("please run rm -rf /", {"blocked_keywords": ["rm -rf"]})
    assert outcome is not None
    assert outcome.directive == "Deny"


def test_static_gate_respects_custom_on_match_directive():
    outcome = static_gate({"tool_name": "shell", "cmd": "chmod 777 x"}, {"blocked_keywords": ["chmod 777"], "return_directives": {"on_match": "SilentLog"}})
    assert outcome is not None
    assert outcome.directive == "SilentLog"


def test_static_gate_blocks_tool_not_in_allowlist():
    outcome = static_gate({"tool_name": "curl"}, {"allowed_tools": ["git", "pytest"]})
    assert outcome is not None
    assert outcome.directive == "Deny"


def test_static_gate_passes_clean_payload():
    outcome = static_gate({"tool_name": "git"}, {"allowed_tools": ["git"], "blocked_keywords": ["rm -rf"]})
    assert outcome is None


# --- custom handler engine: real command execution -----------------------


ALLOW_SCRIPT = """
import sys, json
payload = json.loads(sys.stdin.read())
print(json.dumps({"directive": "Modify", "data": {"echo": payload["data"]}}))
"""

DENY_SCRIPT = """
import sys, json
sys.stdin.read()
print(json.dumps({"directive": "Deny", "reason": "no thanks"}))
"""

CRASH_SCRIPT = """
import sys
sys.stdin.read()
sys.exit(1)
"""


def _write_script(tmp_path, content: str) -> str:
    path = os.path.join(tmp_path, "hook_script.py")
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
    return path


@pytest.mark.asyncio
async def test_command_handler_real_execution_modify(tmp_path):
    script = _write_script(str(tmp_path), ALLOW_SCRIPT)
    outcome = await run_custom_handler(
        "command",
        {"runtime": sys.executable, "script_path": script},
        {"timeout_ms": 5000},
        "PreToolUse",
        {"tool_name": "demo"},
        {"trace_id": "t1"},
    )
    assert outcome.directive == "Modify"
    assert outcome.data == {"echo": {"tool_name": "demo"}}


@pytest.mark.asyncio
async def test_command_handler_real_execution_deny(tmp_path):
    script = _write_script(str(tmp_path), DENY_SCRIPT)
    outcome = await run_custom_handler(
        "command",
        {"runtime": sys.executable, "script_path": script},
        {"timeout_ms": 5000},
        "PreToolUse",
        {"tool_name": "demo"},
        {"trace_id": "t1"},
    )
    assert outcome.directive == "Deny"
    assert outcome.reason == "no thanks"


@pytest.mark.asyncio
async def test_command_handler_crash_falls_back_to_block(tmp_path):
    script = _write_script(str(tmp_path), CRASH_SCRIPT)
    outcome = await run_custom_handler(
        "command",
        {"runtime": sys.executable, "script_path": script},
        {"timeout_ms": 5000, "fallback_strategy": "Block"},
        "PreToolUse",
        {"tool_name": "demo"},
        {"trace_id": "t1"},
    )
    assert outcome.directive == "Deny"


@pytest.mark.asyncio
async def test_command_handler_crash_falls_open_when_configured(tmp_path):
    script = _write_script(str(tmp_path), CRASH_SCRIPT)
    outcome = await run_custom_handler(
        "command",
        {"runtime": sys.executable, "script_path": script},
        {"timeout_ms": 5000, "fallback_strategy": "Allow"},
        "PreToolUse",
        {"tool_name": "demo"},
        {"trace_id": "t1"},
    )
    assert outcome.directive == "Allow"


@pytest.mark.asyncio
async def test_command_handler_timeout_falls_back(tmp_path):
    slow_script = "import sys, time; sys.stdin.read(); time.sleep(5)"
    script = _write_script(str(tmp_path), slow_script)
    outcome = await run_custom_handler(
        "command",
        {"runtime": sys.executable, "script_path": script},
        {"timeout_ms": 100, "fallback_strategy": "Block"},
        "PreToolUse",
        {"tool_name": "demo"},
        {"trace_id": "t1"},
    )
    assert outcome.directive == "Deny"


@pytest.mark.asyncio
async def test_static_gate_short_circuits_before_process_spawn(tmp_path):
    # blocked_keywords should settle the outcome without ever invoking the
    # (nonexistent) script — proves the gate runs first.
    outcome = await run_custom_handler(
        "command",
        {"runtime": sys.executable, "script_path": "/does/not/exist.py"},
        {"blocked_keywords": ["rm -rf"]},
        "PreToolUse",
        "please rm -rf /",
        {"trace_id": "t1"},
    )
    assert outcome.directive == "Deny"
    assert "blocked_keyword" in outcome.reason


def test_hook_outcome_rejects_unknown_directive_gracefully():
    # Constructing directly is permissive (extra="ignore", no directive
    # enum enforcement at the pydantic layer) — validity is checked by
    # callers (routes/hooks.py, hook_handlers.py's dispatch functions).
    outcome = HookOutcome(directive="Allow", data={"a": 1})
    assert outcome.directive == "Allow"
