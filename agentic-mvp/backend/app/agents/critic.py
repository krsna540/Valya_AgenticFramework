"""Critic — reviews the draft and decides what happens next.

The critic is the only node whose output is *control flow*: its `verdict`
is the routing key the graph's conditional edge reads (see graph.py). That
makes it the highest-leverage node and the one most worth constraining.

**Budget enforcement lives here, not in the router.** The critic knows the
revision and replan counts, so it downgrades its own verdict when a budget is
exhausted — `revise` with no revisions left becomes `accept` (or `escalate`,
per config) rather than a route the graph would have to reject. Splitting
that logic between the critic and the router is how you end up with a loop
that runs one more time than the budget says, in the one code path nobody
tested.

**Failure is not rejection.** If the critic itself errors (bad JSON, provider
down, timeout), `_invoke`'s fallback accepts the draft with a low score and
a note. A broken reviewer must not swallow a perfectly good answer — this is
a quality gate, not a correctness gate, and failing open is the right
direction for it.

**Risk-gating.** `should_run()` lets the graph skip the critic entirely for
low-complexity turns. Reflection costs a full extra model round-trip; spending
it on "what's the capital of France" is pure latency. This implements the
"Reflexion, risk-gated" decision in docs/agent_runtime_architecture.md §8 #4.
"""
from __future__ import annotations

import logging

from pydantic import ValidationError

from app.agents.base import AgentOutcome, AgentRole, BaseAgent
from app.agents.errors import AgentRuntimeError
from app.agents.lifecycle import EventType
from app.agents.llm import LLMMessage, LLMRequest
from app.agents.prompts import (
    CRITIQUE_SCHEMA_HINT,
    critic_system_prompt,
    critic_user_prompt,
)
from app.agents.registry import register_agent
from app.agents.state import (
    AgentState,
    Critique,
    RunPhase,
    Verdict,
    get_plan,
    latest_step_results,
)

logger = logging.getLogger("agentic_mvp.agents.critic")


@register_agent(AgentRole.CRITIC)
class CriticAgent(BaseAgent):
    """Reviews the executor's draft and emits a budget-aware verdict."""

    role = AgentRole.CRITIC
    phase = RunPhase.CRITIQUING

    def validate_input(self, state: AgentState) -> None:
        super().validate_input(state)
        if not (state.get("draft_answer") or "").strip():
            raise AgentRuntimeError(
                "Critic requires a draft answer; none is present in state",
                role=self.role.value,
            )

    def should_run(self, state: AgentState) -> bool:
        """Whether critiquing this particular run is worth the round-trip.

        Also consulted by the graph's router so the node can be bypassed
        entirely rather than entered and short-circuited — a skipped node
        leaves a cleaner transcript than one that ran and did nothing.
        """
        if not self.config.enable_critic:
            return False
        plan = get_plan(state)
        # No plan means the run got here some unexpected way — review it
        # rather than waving it through, so treat it as maximally complex.
        complexity = plan.complexity if plan else 5
        return complexity >= self.config.critic_complexity_threshold

    async def _invoke(self, state: AgentState) -> AgentOutcome:
        revision = int(state.get("revision") or 0)
        plan = get_plan(state)
        results = latest_step_results(state)
        draft = str(state.get("draft_answer") or "")

        try:
            raw = await self.llm.complete_json(
                LLMRequest(
                    messages=[
                        LLMMessage(
                            role="system",
                            content=critic_system_prompt(
                                agent_name=str(state.get("agent_name") or "agent"),
                                acceptance_score=self.config.acceptance_score,
                                language=str(state.get("language") or "en"),
                            ),
                        ),
                        LLMMessage(
                            role="user",
                            content=critic_user_prompt(
                                objective=str(state.get("objective") or ""),
                                plan=plan,
                                results=results,
                                draft_answer=draft,
                                revision=revision,
                                max_revisions=self.config.max_revisions,
                            ),
                        ),
                    ],
                    model=str(state.get("scratchpad", {}).get("model_route") or "default"),
                    purpose="critic",
                    temperature=0.0,  # a judgement should be reproducible
                    max_tokens=800,
                ),
                schema_hint=CRITIQUE_SCHEMA_HINT,
            )
            critique = self._parse_critique(raw, revision)
        except Exception as exc:  # noqa: BLE001 — fail open, see module docstring
            logger.warning("Critic failed; accepting draft by default: %s", exc)
            critique = Critique(
                verdict=Verdict.ACCEPT,
                score=0.5,
                feedback=f"Critic unavailable ({type(exc).__name__}); draft accepted unreviewed.",
                revision=revision,
            )

        critique = self._apply_budgets(critique, state)

        await self._sink.emit(
            self._ctx.event(
                EventType.CRITIQUE_READY,
                verdict=critique.verdict.value,
                score=critique.score,
                issue_count=len(critique.issues),
            )
        )

        updates: dict = {"critique": critique.model_dump(mode="json")}
        # Feedback is only worth carrying forward if there is going to be a
        # next attempt — appending an acceptance message would pollute the
        # next run's "fix these defects" checklist with a compliment.
        if critique.verdict in (Verdict.REVISE, Verdict.REPLAN) and critique.feedback:
            updates["feedback_log"] = [f"Revision {revision}: {critique.feedback}"]

        return AgentOutcome(
            updates=updates,
            summary=f"Critique: {critique.verdict.value} (score {critique.score:.2f})",
            payload={
                "verdict": critique.verdict.value,
                "score": critique.score,
                "issues": critique.issues,
                "target_step_ids": critique.target_step_ids,
            },
            next_phase=RunPhase.CRITIQUING,
        )

    # --- internals ----------------------------------------------------------

    def _parse_critique(self, raw: dict, revision: int) -> Critique:
        """Validate the critic's JSON, normalising the one field models get
        wrong most often (a verdict outside the enum)."""
        payload = dict(raw)
        payload["revision"] = revision
        verdict = str(payload.get("verdict", "")).strip().lower()
        if verdict not in {v.value for v in Verdict}:
            # An unrecognised verdict must not be guessed at — treat it as
            # "no opinion", i.e. accept, rather than inventing a revision the
            # critic didn't ask for.
            logger.info("Critic returned unknown verdict %r; treating as accept", verdict)
            payload["verdict"] = Verdict.ACCEPT.value
        try:
            return Critique.model_validate(payload)
        except ValidationError as exc:
            logger.info("Critique failed validation (%s); accepting with a low score", exc)
            return Critique(
                verdict=Verdict.ACCEPT,
                score=0.5,
                feedback="Critic response was malformed; draft accepted unreviewed.",
                revision=revision,
            )

    def _apply_budgets(self, critique: Critique, state: AgentState) -> Critique:
        """Downgrade a verdict the run can no longer afford to act on.

        Both counters are checked against the config budgets here so the
        router only ever sees a verdict it can actually route.
        """
        revision = int(state.get("revision") or 0)
        replan_count = int(state.get("replan_count") or 0)

        if critique.verdict == Verdict.REVISE and revision >= self.config.max_revisions:
            return critique.model_copy(
                update={
                    "verdict": (
                        Verdict.ESCALATE
                        if self.config.escalate_on_budget_exhausted
                        else Verdict.ACCEPT
                    ),
                    # Records that this acceptance was forced by the budget,
                    # not earned. finalize_node reads it to mark the run
                    # DEGRADED rather than SUCCEEDED.
                    "budget_forced": True,
                    "feedback": (
                        f"{critique.feedback} (Revision budget of "
                        f"{self.config.max_revisions} exhausted.)"
                    ).strip(),
                }
            )

        if critique.verdict == Verdict.REPLAN and replan_count >= self.config.max_replans:
            # Downgrade to revise rather than straight to accept: the plan
            # can't change, but one more execution attempt against the
            # critic's feedback still might help — provided that budget is
            # itself unspent.
            fallback = (
                Verdict.REVISE if revision < self.config.max_revisions else Verdict.ACCEPT
            )
            return critique.model_copy(
                update={
                    "verdict": fallback,
                    # Only an accept is "forced" — a downgrade to revise still
                    # gives the run a real chance to improve, so it isn't a
                    # degraded outcome yet.
                    "budget_forced": fallback == Verdict.ACCEPT,
                    "feedback": (
                        f"{critique.feedback} (Replan budget of "
                        f"{self.config.max_replans} exhausted.)"
                    ).strip(),
                }
            )

        return critique
