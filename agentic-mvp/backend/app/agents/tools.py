"""Tool invocation port.

The executor needs to *do* things, but this codebase has a standing
invariant that registry rows are metadata, never stored code: Skills are
SKILL.md folders whose `scripts/` are stored and never executed (see
app/models/skill.py), and Tool rows describe a call contract without this
app maintaining a live MCP client (app/services/mcp_client.py). That
invariant was arrived at deliberately — a real-code execution path was built
here once and removed at the user's request — so the executor does not get
to quietly reintroduce it.

The resolution is an explicit, operator-controlled boundary:

  * `DescribeOnlyToolInvoker` (the default) records the intended call and
    returns a structured description of it. The graph, the audit trail, and
    the SSE contract are all fully exercised; nothing leaves the process.
  * `HttpToolInvoker` performs a real outbound call, and is only reachable
    when `AgentRuntimeConfig.execute_tools` is true — a per-agent decision an
    admin makes knowingly.

Skills are handled by neither: `load_skill_context` returns SKILL.md content
for the executor's prompt. That is *activation* (progressive disclosure, per
the Agent Skills spec), not execution, and is the only thing a Skill has ever
meant in this app.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.agents.errors import ToolExecutionError

logger = logging.getLogger("agentic_mvp.agents.tools")


class ToolSpec(BaseModel):
    """A tool as the runtime sees it — flattened from a `Tool` registry row
    at run start and snapshotted into `AgentState.available_tools`, so a
    mid-run registry edit cannot change what this run may call."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None = None
    tool_type: str = "function"  # function | mcp
    input_schema: dict[str, Any] | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    timeout_s: int = 15
    #: MCP annotation hints (advisory only, never a security boundary — see
    #: app/models/tool.py). The planner is shown `destructiveHint` so it can
    #: prefer a read-only tool when either would do.
    annotations: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_destructive(self) -> bool:
        return bool(self.annotations.get("destructiveHint"))

    def prompt_line(self) -> str:
        """One line describing this tool for a planner prompt."""
        flags = " [destructive]" if self.is_destructive else ""
        return f"- {self.name}{flags}: {self.description or 'no description provided'}"


class SkillSpec(BaseModel):
    """A skill as the runtime sees it. `body_markdown` is the SKILL.md body,
    loaded only on activation — the metadata tier (name + description) is
    always visible to the planner, the body only reaches the executor when a
    step actually selects it."""

    model_config = ConfigDict(frozen=True)

    name: str
    description: str | None = None
    body_markdown: str = ""
    allowed_tools: str | None = None

    def prompt_line(self) -> str:
        return f"- {self.name}: {self.description or 'no description provided'}"


class ToolInvocation(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    step_id: str | None = None


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_name: str
    ok: bool
    output: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    #: True when the result was described rather than produced by a real
    #: call. Propagated into the run record so nobody mistakes a described
    #: result for a real one when reading the Observatory later.
    simulated: bool = False
    duration_ms: int = 0


class ToolInvoker(ABC):
    """The executor's outbound boundary."""

    @abstractmethod
    async def invoke(self, spec: ToolSpec, invocation: ToolInvocation) -> ToolResult:
        """Run one tool call. Must raise ToolExecutionError, never a bare
        transport exception, so the retry decorator can classify it."""


class DescribeOnlyToolInvoker(ToolInvoker):
    """Default invoker: records the intended call, performs none.

    Honest about what it is — `simulated=True` on every result, and the
    output says so — because a silently-faked tool result is worse than no
    tool result at all.
    """

    async def invoke(self, spec: ToolSpec, invocation: ToolInvocation) -> ToolResult:
        logger.info(
            "Tool %s invoked in describe-only mode (step=%s)", spec.name, invocation.step_id
        )
        return ToolResult(
            tool_name=spec.name,
            ok=True,
            simulated=True,
            output=(
                f"[simulated] Would call tool '{spec.name}' "
                f"({spec.tool_type}) with arguments {invocation.arguments}. "
                "Tool execution is disabled for this agent "
                "(AgentRuntimeConfig.execute_tools=false)."
            ),
            data={"arguments": invocation.arguments, "tool_type": spec.tool_type},
        )


class HttpToolInvoker(ToolInvoker):
    """Real outbound invoker for `function`-type tools with an endpoint.

    Only constructed when an admin has set `execute_tools` on the agent.
    Falls back to describe-only for anything it cannot legitimately call
    (no endpoint, or an `mcp` tool — this app has no live MCP transport, and
    pretending otherwise would be the exact silent-fake this module avoids).
    """

    def __init__(self, *, default_timeout_s: float = 15.0) -> None:
        self._default_timeout_s = default_timeout_s
        self._fallback = DescribeOnlyToolInvoker()

    async def invoke(self, spec: ToolSpec, invocation: ToolInvocation) -> ToolResult:
        endpoint = (spec.config or {}).get("endpoint")
        if spec.tool_type != "function" or not endpoint:
            return await self._fallback.invoke(spec, invocation)

        timeout = float(spec.timeout_s or self._default_timeout_s)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    endpoint,
                    json={"tool": spec.name, "arguments": invocation.arguments},
                    headers=(spec.config or {}).get("headers") or {},
                )
        except httpx.HTTPError as exc:
            raise ToolExecutionError(
                f"Tool '{spec.name}' call failed: {exc}", tool_name=spec.name
            ) from exc

        if response.status_code >= 400:
            raise ToolExecutionError(
                f"Tool '{spec.name}' returned HTTP {response.status_code}",
                # 4xx means the request itself was wrong; retrying sends the
                # same wrong request again.
                retryable=response.status_code >= 500,
                tool_name=spec.name,
                body=response.text[:500],
            )

        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text[:2000]}

        return ToolResult(
            tool_name=spec.name,
            ok=True,
            simulated=False,
            output=data.get("output") if isinstance(data, dict) else str(data),
            data=data if isinstance(data, dict) else {"result": data},
        )


def build_tool_invoker(*, execute_tools: bool) -> ToolInvoker:
    """Pick the invoker for a run. The single place that decision is made."""
    return HttpToolInvoker() if execute_tools else DescribeOnlyToolInvoker()


def load_skill_context(skill: SkillSpec, *, max_chars: int = 4000) -> str:
    """Render a skill's SKILL.md for injection into the executor's prompt.

    Truncated rather than summarised: a truncated instruction the model can
    read verbatim beats a lossy paraphrase of one, and the cut point is
    stated so the model knows content is missing.
    """
    body = (skill.body_markdown or "").strip()
    if not body:
        return f"Skill '{skill.name}' has no instruction body."
    if len(body) > max_chars:
        body = body[:max_chars] + "\n\n[... SKILL.md truncated for context budget ...]"
    return f"### Skill: {skill.name}\n{body}"
