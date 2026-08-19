"""Executor — carries out the plan and drafts the answer.

Two distinct phases inside one node, and keeping them distinct is what makes
the critic's job possible:

  1. **Step execution.** `PlanStep`s run in dependency waves
     (`Plan.execution_waves`): each wave's steps run concurrently, bounded by
     `config.max_step_concurrency`, and a wave only starts once every step it
     depends on has produced a result. Within a step: optionally invoke its
     tool, optionally load its skill's SKILL.md, then ask the model to
     perform that step. Each produces a `StepResult`.
  2. **Synthesis.** Fold the step results into one answer addressed to the
     user. Streamed token-by-token when enabled, because this is the only
     part the user actually reads.

**Append-only results, revision-tagged.** `step_results` accumulates across
every revision rather than being overwritten. The audit trail then shows what
each attempt produced (which is the entire value of having a critic), and the
synthesis reads only the current revision's results via `latest_step_results`.

**Targeted revision.** When the critic names `target_step_ids`, only those
steps re-run; the rest are carried forward. A critic that objects to one
paragraph shouldn't cost N model calls to fix — and re-running a step the
critic was happy with is a good way to lose the part that was working.

**Step failures don't fail the run.** A failed step is recorded as a
`StepResult` with `status=FAILED` and execution continues. Partial results
plus a critic that can see the gap beats no answer at all; the critic is
explicitly shown failed steps and can call `revise` or `escalate` on them.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.agents.base import AgentOutcome, AgentRole, BaseAgent
from app.agents.errors import AgentRuntimeError, ToolExecutionError
from app.agents.lifecycle import EventType
from app.agents.llm import LLMMessage, LLMRequest
from app.agents.prompts import (
    executor_step_prompt,
    executor_synthesis_prompt,
    executor_system_prompt,
)
from app.agents.registry import register_agent
from app.agents.state import (
    AgentState,
    PlanStep,
    RunPhase,
    StepResult,
    StepStatus,
    get_critique,
    get_plan,
    get_step_results,
    resolve_model_route,
)
from app.agents.tools import (
    DescribeOnlyToolInvoker,
    SkillSpec,
    ToolInvocation,
    ToolResult,
    ToolSpec,
)

logger = logging.getLogger("agentic_mvp.agents.executor")


@register_agent(AgentRole.EXECUTOR)
class ExecutorAgent(BaseAgent):
    """Runs the plan's steps, then drafts the answer."""

    role = AgentRole.EXECUTOR
    phase = RunPhase.EXECUTING

    def validate_input(self, state: AgentState) -> None:
        super().validate_input(state)
        if get_plan(state) is None:
            raise AgentRuntimeError(
                "Executor requires a plan; none is present in state",
                role=self.role.value,
            )

    async def _invoke(self, state: AgentState) -> AgentOutcome:
        plan = get_plan(state)
        assert plan is not None  # guaranteed by validate_input
        revision = int(state.get("revision") or 0)
        critique = get_critique(state)

        tools = {t["name"]: ToolSpec.model_validate(t) for t in state.get("available_tools") or []}
        skills = {
            s["name"]: SkillSpec.model_validate(s) for s in state.get("available_skills") or []
        }

        steps = plan.ordered_steps()
        index_by_id = {step.id: i for i, step in enumerate(steps, start=1)}
        targeted = set(critique.target_step_ids) if critique and critique.target_step_ids else None
        carried = self._carried_forward_results(state, revision, targeted)
        carried_ids = {r.step_id for r in carried}

        tokens = {"input": 0, "output": 0, "calls": 0}
        results: list[StepResult] = list(carried)
        semaphore = asyncio.Semaphore(max(1, self.config.max_step_concurrency))

        # Run in dependency waves rather than one step at a time: everything
        # in a wave has already had its dependencies satisfied by an earlier
        # wave (Plan.execution_waves), so nothing in it can legitimately need
        # another wave member's output. `snapshot` is taken once per wave,
        # before any of its steps start, so two independent steps run
        # concurrently never see each other's result mid-flight — each sees
        # exactly what a fully sequential run would have shown it at that
        # point, no more.
        for wave in plan.execution_waves():
            runnable = [s for s in wave if targeted is None or s.id in targeted]
            if not runnable:
                continue  # every member already carried forward above
            snapshot = list(results)

            async def _run_bounded(step: PlanStep, prior: list[StepResult] = snapshot) -> StepResult:
                async with semaphore:
                    return await self._run_step(
                        state=state,
                        step=step,
                        index=index_by_id[step.id],
                        total=len(steps),
                        prior_results=prior,
                        tools=tools,
                        skills=skills,
                        revision=revision,
                        tokens=tokens,
                    )

            wave_results = await asyncio.gather(*(_run_bounded(s) for s in runnable))
            results.extend(wave_results)

        # Order the current pass's results back into plan order — carried-
        # forward steps were prepended and waves may finish out of step
        # order, so without this the synthesis prompt reads them scrambled.
        order = {s.id: i for i, s in enumerate(steps)}
        results.sort(key=lambda r: order.get(r.step_id, len(order)))

        draft, synthesis_tokens = await self._synthesise(state, results)
        for key in ("input", "output", "calls"):
            tokens[key] += synthesis_tokens.get(key, 0)

        failed = [r for r in results if r.status == StepStatus.FAILED]
        return AgentOutcome(
            updates={
                # Only this pass's newly-produced results are appended; the
                # carried-forward ones are already in the channel and
                # re-appending them would double-count the audit trail.
                "step_results": [
                    r.model_dump(mode="json") for r in results if r.step_id not in carried_ids
                ],
                "draft_answer": draft,
                "token_usage": tokens,
            },
            summary=(
                f"Executed {len(results)} step(s)"
                + (f", {len(failed)} failed" if failed else "")
                + f"; drafted {len(draft.split())} words"
            ),
            payload={
                "step_count": len(results),
                "failed_step_ids": [r.step_id for r in failed],
                "revision": revision,
            },
            next_phase=RunPhase.EXECUTING,
        )

    # --- internals ----------------------------------------------------------

    def _carried_forward_results(
        self,
        state: AgentState,
        revision: int,
        targeted: set[str] | None,
    ) -> list[StepResult]:
        """On a targeted revision, re-stamp the previous pass's untargeted
        results with the new revision so `latest_step_results` still sees a
        complete set. Without this, a targeted revision would synthesise from
        only the one step that was redone."""
        if targeted is None or revision == 0:
            return []
        previous = [
            r
            for r in _results_at_revision(state, revision - 1)
            if r.step_id not in targeted
        ]
        return [r.model_copy(update={"revision": revision}) for r in previous]

    async def _run_step(
        self,
        *,
        state: AgentState,
        step: PlanStep,
        index: int,
        total: int,
        prior_results: list[StepResult],
        tools: dict[str, ToolSpec],
        skills: dict[str, SkillSpec],
        revision: int,
        tokens: dict[str, Any],
    ) -> StepResult:
        started = time.monotonic()
        await self._sink.emit(
            self._ctx.event(
                EventType.STEP_START, step_id=step.id, title=step.title, index=index, total=total
            )
        )

        tool_result: ToolResult | None = None
        try:
            if step.tool_name and step.tool_name in tools:
                tool_result = await self._invoke_tool(tools[step.tool_name], step)

            skill = skills.get(step.skill_name) if step.skill_name else None
            if skill is not None:
                # "Activation", not execution — the SKILL.md body enters the
                # prompt. See app/agents/tools.py for why that distinction is
                # load-bearing in this codebase.
                await self._sink.emit(
                    self._ctx.event(EventType.SKILL_CALL, skill_name=skill.name, step_id=step.id)
                )

            prompt = executor_step_prompt(
                objective=str(state.get("objective") or ""),
                step_index=index,
                step_total=total,
                step_title=step.title,
                step_instruction=step.instruction,
                prior_results=prior_results,
                tool_output=tool_result.output if tool_result else None,
                skill=skill,
                context_documents=state.get("context_documents") or [],
                feedback_log=list(state.get("feedback_log") or []),
                critique=get_critique(state),
            )
            response = await self.llm.complete(
                LLMRequest(
                    messages=[
                        LLMMessage(
                            role="system",
                            content=executor_system_prompt(
                                agent_name=str(state.get("agent_name") or "agent"),
                                system_prompt=state.get("system_prompt"),
                                language=str(state.get("language") or "en"),
                            ),
                        ),
                        LLMMessage(role="user", content=prompt),
                    ],
                    model=resolve_model_route(state, "executor"),
                    purpose="executor",
                    temperature=0.3,
                    max_tokens=1200,
                )
            )
            tokens["calls"] += 1
            tokens["input"] += response.input_tokens
            tokens["output"] += response.output_tokens

            result = StepResult(
                step_id=step.id,
                status=StepStatus.SUCCEEDED,
                output=response.text,
                tool_name=step.tool_name,
                tool_result=tool_result.model_dump(mode="json") if tool_result else None,
                duration_ms=int((time.monotonic() - started) * 1000),
                revision=revision,
            )

        except Exception as exc:  # noqa: BLE001 — one bad step must not end the run
            logger.warning("Step %s failed: %s", step.id, exc)
            error = (
                exc.as_dict()
                if isinstance(exc, AgentRuntimeError)
                else {"error_type": type(exc).__name__, "message": str(exc)}
            )
            result = StepResult(
                step_id=step.id,
                status=StepStatus.FAILED,
                output=f"Step failed: {exc}",
                tool_name=step.tool_name,
                error=error,
                duration_ms=int((time.monotonic() - started) * 1000),
                revision=revision,
            )

        await self._sink.emit(
            self._ctx.event(
                EventType.STEP_END,
                step_id=step.id,
                status=result.status.value,
                duration_ms=result.duration_ms,
            )
        )
        return result

    async def _invoke_tool(self, spec: ToolSpec, step: PlanStep) -> ToolResult:
        """Invoke one tool, emitting the `tool_call` event the UI already
        renders. A tool failure is raised, not swallowed — `_run_step`'s
        boundary turns it into a failed StepResult, which keeps "the tool
        broke" visible in the audit trail instead of blending it into the
        model's prose."""
        invoker = self.tool_invoker or DescribeOnlyToolInvoker()
        await self._sink.emit(
            self._ctx.event(EventType.TOOL_CALL, tool_name=spec.name, step_id=step.id)
        )
        started = time.monotonic()
        try:
            result = await invoker.invoke(
                spec,
                ToolInvocation(
                    tool_name=spec.name,
                    arguments={"instruction": step.instruction},
                    step_id=step.id,
                ),
            )
        except ToolExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalise into our taxonomy
            raise ToolExecutionError(
                f"Tool {spec.name!r} raised {exc}", tool_name=spec.name
            ) from exc
        return result.model_copy(update={"duration_ms": int((time.monotonic() - started) * 1000)})

    async def _synthesise(
        self, state: AgentState, results: list[StepResult]
    ) -> tuple[str, dict[str, Any]]:
        """Fold the step results into the user-facing answer.

        Streams when configured — this is the only text the user reads as it
        arrives, so it is the only place token streaming is worth the
        complexity of a second code path.
        """
        request = LLMRequest(
            messages=[
                LLMMessage(
                    role="system",
                    content=executor_system_prompt(
                        agent_name=str(state.get("agent_name") or "agent"),
                        system_prompt=state.get("system_prompt"),
                        language=str(state.get("language") or "en"),
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=executor_synthesis_prompt(
                        objective=str(state.get("objective") or ""),
                        results=results,
                        context_documents=state.get("context_documents") or [],
                        feedback_log=list(state.get("feedback_log") or []),
                        critique=get_critique(state),
                    ),
                ),
            ],
            model=resolve_model_route(state, "executor"),
            purpose="executor",
            temperature=0.4,
            max_tokens=2000,
        )

        if not self.config.stream_tokens:
            response = await self.llm.complete(request)
            return response.text, {
                "calls": 1,
                "input": response.input_tokens,
                "output": response.output_tokens,
            }

        chunks: list[str] = []
        iterator = await self.llm.stream(request)
        async for delta in iterator:
            chunks.append(delta)
            await self._sink.emit(self._ctx.event(EventType.TOKEN, text=delta))
        text = "".join(chunks)
        # Streaming APIs rarely return usage, so approximate on the output
        # side. Marked approximate in the ledger rather than silently mixed
        # with exact counts — see app/services/agent_run_store.py.
        return text, {"calls": 1, "input": 0, "output": len(text.split()), "approximate": True}


def _results_at_revision(state: AgentState, revision: int) -> list[StepResult]:
    return [r for r in get_step_results(state) if r.revision == revision]


__all__ = ["ExecutorAgent"]
