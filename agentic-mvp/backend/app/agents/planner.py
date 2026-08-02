"""Planner — decomposes the objective into an executable plan.

Responsibilities, and deliberately nothing else:

  1. Ask the model for a decomposition, as JSON.
  2. Validate that decomposition against what this run is actually allowed
     to do — the tool/skill snapshot taken at run start.
  3. On failure, re-prompt with the validation error fed back in, up to a
     small repair budget, then give up with a typed error.

**Why validation lives here rather than in the executor.** A step naming a
tool the agent doesn't have is a plan defect, and catching it at plan time
costs one cheap re-prompt. Catching it at execution time costs a failed step,
a critique, and a full revision pass — and the critic's feedback ("that tool
doesn't exist") is a much weaker signal than a validator's.

**Why the repair loop is separate from `@retryable`.** The decorator retries
the *same* call after a transient error. This loop makes a *different* call:
same conversation plus the validator's complaint. Conflating them would mean
re-sending an identical prompt and expecting a different answer.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.agents.base import AgentOutcome, AgentRole, BaseAgent
from app.agents.errors import PlanValidationError, ProviderError
from app.agents.lifecycle import EventType
from app.agents.llm import LLMMessage, LLMRequest
from app.agents.prompts import (
    PLAN_SCHEMA_HINT,
    planner_system_prompt,
    planner_user_prompt,
)
from app.agents.registry import register_agent
from app.agents.state import (
    AgentState,
    Plan,
    RunPhase,
    get_critique,
    get_plan,
)
from app.agents.tools import SkillSpec, ToolSpec

logger = logging.getLogger("agentic_mvp.agents.planner")

#: How many times the planner re-prompts itself after a *validation* failure
#: (as opposed to a transport failure, which `@retryable` owns). Two is
#: enough for the realistic cases — a hallucinated tool name and a malformed
#: step — and a third attempt on the same prompt almost never converges.
MAX_REPAIR_ATTEMPTS = 2


@register_agent(AgentRole.PLANNER)
class PlannerAgent(BaseAgent):
    """Produces a validated `Plan` for the executor to carry out."""

    role = AgentRole.PLANNER
    phase = RunPhase.PLANNING

    def validate_input(self, state: AgentState) -> None:
        super().validate_input(state)
        # Nothing further: the planner is the entry point and needs only the
        # objective its base class already checked.

    async def _invoke(self, state: AgentState) -> AgentOutcome:
        tools = [ToolSpec.model_validate(t) for t in state.get("available_tools") or []]
        skills = [SkillSpec.model_validate(s) for s in state.get("available_skills") or []]
        revision = int(state.get("revision") or 0)
        replan_count = int(state.get("replan_count") or 0)

        system = planner_system_prompt(
            agent_name=str(state.get("agent_name") or "agent"),
            system_prompt=state.get("system_prompt"),
            tools=tools,
            skills=skills,
            max_steps=self.config.max_plan_steps,
            language=str(state.get("language") or "en"),
        )
        user = planner_user_prompt(
            objective=str(state.get("objective") or ""),
            context_documents=state.get("context_documents") or [],
            feedback_log=list(state.get("feedback_log") or []),
            critique=get_critique(state),
            # Only shown on a replan — on the first pass there is nothing to
            # show, and on a plain revision the plan was explicitly not the
            # problem, so re-litigating it invites unnecessary churn.
            previous_plan=get_plan(state) if replan_count > 0 else None,
        )

        messages = [
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ]

        plan, tokens = await self._plan_with_repair(state, messages, tools, skills, revision)

        await self._sink.emit(
            self._ctx.event(
                EventType.PLAN_READY,
                step_count=len(plan.steps),
                complexity=plan.complexity,
                steps=[{"id": s.id, "title": s.title} for s in plan.steps],
            )
        )

        return AgentOutcome(
            updates={
                "plan": plan.model_dump(mode="json"),
                "token_usage": tokens,
                # A new plan invalidates the previous pass's critique: leaving
                # it in place would have the executor "fixing" objections to a
                # plan that no longer exists.
                "critique": None,
            },
            summary=f"Planned {len(plan.steps)} step(s), complexity {plan.complexity}",
            payload={
                "objective": plan.objective,
                "complexity": plan.complexity,
                "steps": [s.model_dump(mode="json") for s in plan.steps],
            },
            next_phase=RunPhase.PLANNING,
        )

    # --- internals ----------------------------------------------------------

    async def _plan_with_repair(
        self,
        state: AgentState,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        skills: list[SkillSpec],
        revision: int,
    ) -> tuple[Plan, dict[str, Any]]:
        """Prompt → validate → re-prompt-with-the-complaint, up to the repair
        budget. Returns the plan and this node's token accounting."""
        tool_names = {t.name for t in tools}
        skill_names = {s.name for s in skills}
        conversation = list(messages)
        tokens = {"input": 0, "output": 0, "calls": 0}
        last_error: PlanValidationError | None = None

        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 2):
            request = LLMRequest(
                messages=conversation,
                model=str(state.get("scratchpad", {}).get("model_route") or "default"),
                purpose="planner",
                temperature=0.1,  # planning wants consistency, not creativity
                max_tokens=1200,
            )
            try:
                raw = await self.llm.complete_json(request, schema_hint=PLAN_SCHEMA_HINT)
            except ProviderError:
                # Transport-shaped; let @retryable on the node handle it
                # rather than burning a repair attempt on a network blip.
                raise

            tokens["calls"] += 1

            try:
                plan = self._validate_plan(raw, tool_names, skill_names, revision)
            except PlanValidationError as exc:
                last_error = exc
                logger.warning(
                    "Planner produced an invalid plan (attempt %d/%d): %s",
                    attempt,
                    MAX_REPAIR_ATTEMPTS + 1,
                    exc.message,
                )
                if attempt > MAX_REPAIR_ATTEMPTS:
                    break
                conversation = [
                    *conversation,
                    LLMMessage(role="assistant", content=str(raw)[:2000]),
                    LLMMessage(
                        role="user",
                        content=(
                            f"That plan was rejected: {exc.message}\n"
                            "Return a corrected plan as a single JSON object. "
                            "Only use the tools and skills that were listed."
                        ),
                    ),
                ]
                continue

            return plan, tokens

        raise last_error or PlanValidationError("Planner failed to produce a valid plan")

    def _validate_plan(
        self,
        raw: dict[str, Any],
        tool_names: set[str],
        skill_names: set[str],
        revision: int,
    ) -> Plan:
        """Turn raw JSON into a `Plan` this run is permitted to execute.

        Two classes of check, and the difference matters:

        * **Structural** (Pydantic) — shape, types, non-empty steps. Hard
          failure; there is nothing to salvage.
        * **Referential** — does each step name a real, available tool or
          skill? Also a hard failure, and *not* silently repaired by dropping
          the reference: a step whose tool quietly vanished still claims in
          its instruction that it will use one, so the executor would produce
          a confidently unsupported result. Better to make the planner say
          what it actually means.
        """
        try:
            plan = Plan.model_validate({**raw, "revision": revision})
        except ValidationError as exc:
            raise PlanValidationError(
                f"Plan did not match the required schema: {exc.errors()[:3]}",
                raw_preview=str(raw)[:300],
            ) from exc

        if len(plan.steps) > self.config.max_plan_steps:
            raise PlanValidationError(
                f"Plan has {len(plan.steps)} steps but at most "
                f"{self.config.max_plan_steps} are allowed",
                step_count=len(plan.steps),
            )

        seen_ids: set[str] = set()
        for step in plan.steps:
            if step.id in seen_ids:
                raise PlanValidationError(f"Duplicate step id {step.id!r}", step_id=step.id)
            seen_ids.add(step.id)
            if step.tool_name and step.tool_name not in tool_names:
                raise PlanValidationError(
                    f"Step {step.id!r} references unavailable tool {step.tool_name!r}; "
                    f"available: {sorted(tool_names) or 'none'}",
                    step_id=step.id,
                    tool_name=step.tool_name,
                )
            if step.skill_name and step.skill_name not in skill_names:
                raise PlanValidationError(
                    f"Step {step.id!r} references unavailable skill {step.skill_name!r}; "
                    f"available: {sorted(skill_names) or 'none'}",
                    step_id=step.id,
                    skill_name=step.skill_name,
                )

        # Dangling dependencies are repaired rather than rejected: they cost
        # only ordering (the topological sort ignores unknown ids), and
        # spending a repair attempt on one is a poor trade against the risk
        # of the retry coming back worse in some other respect.
        for step in plan.steps:
            unknown = [d for d in step.depends_on if d not in seen_ids]
            if unknown:
                logger.info("Dropping unknown dependencies %s from step %s", unknown, step.id)
                step.depends_on = [d for d in step.depends_on if d in seen_ids]

        return plan
