"""Real execution engine for custom (non-python) hook handler types.

app/services/hooks.py's built-in `python` handlers are the safe path: a
handler_key only ever resolves to a vetted, code-reviewed function already
in this repo. The three handler types implemented here — `http`, `command`,
`mcp_tool` — are the opposite: they call out to a URL, run a local script,
or hit an MCP server, all specified by whatever operator configured the
Hook record. That is real, intentional code/network execution outside this
process's own codebase, chosen deliberately (see README's "Hook handler
types" section) over a safer config-only alternative. There is no sandbox
here beyond a timeout and a fail-open/fail-closed fallback — treat any
Hook with handler_type != "python" as equivalent in trust to giving
whoever can create Hook records the ability to run code on this host.

Every handler type funnels into the same `HookOutcome` contract so
HookManager doesn't need to know which one produced it:

    {"directive": "Allow"|"Deny"|"Modify"|"InjectContext"|"SilentLog",
     "data": <optional replacement payload>,
     "context_updates": <optional dict merged into HookContext.metadata>,
     "reason": <optional string, surfaced on Deny / logged otherwise>}

A `command` script should print exactly this JSON object to stdout. An
`http` handler should return it as the JSON response body. An `mcp_tool`
handler is a simplified adapter (a plain HTTP POST, not a spec-compliant
MCP client — building a full MCP transport was out of scope here) that
expects the same shape back.

Before any of the three actually run, `static_gate` can short-circuit the
call entirely based on `execution_policy.blocked_keywords` /
`.allowed_tools` — this is what lets a Hook block "rm -rf" without ever
making a network call or spawning a process for the common case.
"""
import asyncio
import json
import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("agentic_mvp.hooks.handlers")

DIRECTIVES = {"Allow", "Deny", "Modify", "InjectContext", "SilentLog"}


class HookOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    directive: str = "Allow"
    data: Any = None
    context_updates: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


def _serialize(data: Any) -> str:
    if isinstance(data, str):
        return data
    try:
        return json.dumps(data, default=str)
    except TypeError:
        return str(data)


def static_gate(data: Any, execution_policy: dict[str, Any]) -> HookOutcome | None:
    """Checks execution_policy.blocked_keywords / .allowed_tools against the
    payload before any handler runs. Returns a settled HookOutcome if one of
    these fires (the YAML sample's on_match/on_clean return_directives),
    else None to let the real handler run."""
    return_directives = execution_policy.get("return_directives") or {}
    on_match = return_directives.get("on_match", "Deny")

    blocked = execution_policy.get("blocked_keywords") or []
    if blocked:
        haystack = _serialize(data).lower()
        for kw in blocked:
            if str(kw).lower() in haystack:
                return HookOutcome(directive=on_match, reason=f"blocked_keyword matched: {kw!r}")

    allowed_tools = execution_policy.get("allowed_tools") or []
    if allowed_tools and isinstance(data, dict):
        tool_name = data.get("tool_name") or data.get("skill_name")
        if tool_name and tool_name not in allowed_tools:
            return HookOutcome(directive=on_match, reason=f"tool {tool_name!r} not in allowed_tools")

    return None


async def _call_http(handler_config: dict[str, Any], stage: str, data: Any, context_dict: dict[str, Any]) -> HookOutcome:
    endpoint = handler_config.get("endpoint")
    if not endpoint:
        raise ValueError("http handler_config missing 'endpoint'")
    method = (handler_config.get("method") or "POST").upper()
    headers = handler_config.get("headers") or {}

    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method,
            endpoint,
            headers=headers,
            json={"stage": stage, "data": data, "context": context_dict},
        )
    resp.raise_for_status()
    body = resp.json()
    outcome = HookOutcome(**body)
    if outcome.directive not in DIRECTIVES:
        raise ValueError(f"http handler returned unknown directive {outcome.directive!r}")
    return outcome


async def _call_command(handler_config: dict[str, Any], stage: str, data: Any, context_dict: dict[str, Any]) -> HookOutcome:
    script_path = handler_config.get("script_path")
    if not script_path:
        raise ValueError("command handler_config missing 'script_path'")
    runtime = handler_config.get("runtime") or "python3"
    args = handler_config.get("args") or []

    payload = json.dumps({"stage": stage, "data": data, "context": context_dict}).encode("utf-8")

    proc = await asyncio.create_subprocess_exec(
        runtime,
        script_path,
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(payload)
    if proc.returncode != 0:
        raise RuntimeError(f"command handler exited {proc.returncode}: {stderr.decode('utf-8', 'replace')[:500]}")

    body = json.loads(stdout.decode("utf-8"))
    outcome = HookOutcome(**body)
    if outcome.directive not in DIRECTIVES:
        raise ValueError(f"command handler printed unknown directive {outcome.directive!r}")
    return outcome


async def _call_mcp(handler_config: dict[str, Any], stage: str, data: Any, context_dict: dict[str, Any]) -> HookOutcome:
    """Simplified MCP adapter: a plain HTTP POST carrying {tool_name,
    parameters}, not a spec-compliant MCP JSON-RPC/stdio client. A real MCP
    server would need a small shim in front of it speaking this contract."""
    server_url = handler_config.get("mcp_server_url")
    tool_name = handler_config.get("tool_name")
    if not server_url or not tool_name:
        raise ValueError("mcp_tool handler_config missing 'mcp_server_url' or 'tool_name'")
    parameters = {**(handler_config.get("parameters") or {}), "stage": stage, "data": data, "context": context_dict}

    async with httpx.AsyncClient() as client:
        resp = await client.post(server_url, json={"tool_name": tool_name, "parameters": parameters})
    resp.raise_for_status()
    body = resp.json()
    outcome = HookOutcome(**body)
    if outcome.directive not in DIRECTIVES:
        raise ValueError(f"mcp_tool handler returned unknown directive {outcome.directive!r}")
    return outcome


_DISPATCH = {"http": _call_http, "command": _call_command, "mcp_tool": _call_mcp}


async def run_custom_handler(
    handler_type: str,
    handler_config: dict[str, Any],
    execution_policy: dict[str, Any],
    stage: str,
    data: Any,
    context_dict: dict[str, Any],
) -> HookOutcome:
    """Entry point used by app/services/hooks.py for any handler_type other
    than "python". Applies the static keyword/allowlist gate first, then
    dispatches to the real handler with a timeout, falling back to
    execution_policy.fallback_strategy ("Block" default, or "Allow" to fail
    open) if the handler errors, times out, or returns something we can't
    parse into a HookOutcome."""
    gate = static_gate(data, execution_policy)
    if gate is not None:
        return gate

    fn = _DISPATCH.get(handler_type)
    if fn is None:
        raise ValueError(f"Unknown handler_type {handler_type!r}")

    timeout_s = execution_policy.get("timeout_ms", 3500) / 1000
    try:
        return await asyncio.wait_for(fn(handler_config, stage, data, context_dict), timeout=timeout_s)
    except Exception as e:  # noqa: BLE001 — any handler failure funnels through fallback_strategy
        fallback = execution_policy.get("fallback_strategy", "Block")
        logger.warning("Custom hook handler (%s) failed for stage %s: %s", handler_type, stage, e)
        if fallback == "Allow":
            return HookOutcome(directive="Allow", reason=f"handler failed, fallback_strategy=Allow: {e}")
        return HookOutcome(directive="Deny", reason=f"handler failed, fallback_strategy=Block: {e}")
