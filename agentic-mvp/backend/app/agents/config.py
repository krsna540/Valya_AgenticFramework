"""Per-run tuning knobs for the agent runtime.

Separate from `app.core.config.Settings` on purpose. Settings holds
*deployment* configuration (which gateway URL, is Temporal on); this holds
*run* configuration, which an admin can vary per Agent row via
`Agent.runtime_config` and which therefore has to be validated on the way in
from JSON. Mixing the two would mean either a tenant can edit the gateway URL
or an admin can't change a revision budget without a redeploy.

Precedence, lowest to highest:

    class defaults  <  Settings (deployment-wide)  <  Agent.runtime_config JSON

`from_agent()` implements exactly that, and drops unknown keys rather than
raising — an Agent row written by a newer version of the app must not break
a rolling deploy of an older one.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentRuntimeConfig(BaseModel):
    """Budgets and strategy switches for a single run."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    # --- loop budgets -------------------------------------------------------
    #: How many times the critic may send the answer back for re-execution.
    #: 2 is the pragmatic default: the first revision fixes most real defects,
    #: the second catches what the first introduced, and beyond that the
    #: marginal quality gain stops paying for the latency and tokens.
    max_revisions: int = Field(default=2, ge=0, le=10)
    #: How many times the critic may reject the *plan* itself. Lower than
    #: max_revisions because a second bad plan usually means the objective is
    #: underspecified, and re-planning is the expensive failure mode.
    max_replans: int = Field(default=1, ge=0, le=5)
    #: Hard ceiling on plan size, enforced at validation time. Also the guard
    #: that stops a runaway planner from producing 200 steps.
    max_plan_steps: int = Field(default=8, ge=1, le=50)
    #: LangGraph's own super-step ceiling. Must exceed the worst-case path
    #: through the graph or a legitimate run dies with GraphRecursionError;
    #: `effective_recursion_limit()` derives a safe value from the budgets
    #: above rather than trusting whatever an admin typed here.
    recursion_limit: int = Field(default=0, ge=0, le=200)

    # --- time budgets -------------------------------------------------------
    #: Wall-clock ceiling for one node. Enforced by @time_bounded in
    #: lifecycle.py, and mirrored as Temporal's start_to_close_timeout.
    node_timeout_s: float = Field(default=90.0, gt=0, le=3600)
    #: Ceiling for the whole run.
    run_timeout_s: float = Field(default=600.0, gt=0, le=86_400)

    # --- retry --------------------------------------------------------------
    #: In-node retry attempts for a retryable error, before the run's own
    #: revision loop (or Temporal's activity retry) takes over. Kept small:
    #: this is the "transient blip" layer, not the durability layer.
    max_attempts_per_node: int = Field(default=3, ge=1, le=10)
    retry_backoff_s: float = Field(default=0.5, gt=0, le=60)
    retry_backoff_multiplier: float = Field(default=2.0, ge=1.0, le=10.0)

    # --- strategy switches --------------------------------------------------
    #: Run the critic at all. Off = plan-and-execute with no reflection,
    #: which is the right trade for cheap, low-risk turns.
    enable_critic: bool = True
    #: Skip the critic when the planner rates complexity below this. This is
    #: the "risk-gated Reflexion" from docs/agent_runtime_architecture.md
    #: §8 decision #4 — reflection costs a full extra model round-trip, so
    #: it is spent on hard turns, not on "what's the capital of France".
    critic_complexity_threshold: int = Field(default=2, ge=1, le=5)
    #: Minimum critic score to accept without revision.
    acceptance_score: float = Field(default=0.7, ge=0.0, le=1.0)
    #: Actually invoke registry tools, versus recording the intended call and
    #: returning a described result. Defaults off to match this codebase's
    #: standing invariant that registry rows are metadata, not stored code
    #: (see app/models/skill.py and app/services/mcp_client.py) — turning it
    #: on is a deliberate operator decision to allow outbound calls.
    execute_tools: bool = False
    #: Emit token-level SSE while the executor drafts. Off = one block per node.
    stream_tokens: bool = True
    #: Ceiling on how many plan steps the executor runs concurrently overall
    #: (see Plan.dependency_edges — steps start as soon as their own
    #: dependencies finish, not in lock-step batches). 1 recovers the old
    #: fully-sequential behaviour; the default lets an independent-steps plan
    #: finish in roughly one step's latency instead of N, while still
    #: bounding fan-out against a model gateway's own rate limits.
    max_step_concurrency: int = Field(default=4, ge=1, le=20)
    #: Escalate to a human instead of degrading when the budget runs out.
    escalate_on_budget_exhausted: bool = False

    def effective_recursion_limit(self) -> int:
        """LangGraph super-step ceiling, derived from the loop budgets.

        Worst case per pass is planner→executor→critic→revise = 4 nodes, plus
        init and finalize, plus a replan restart. The 1.5x/+10 headroom
        absorbs graph changes without anyone remembering to bump a constant.
        """
        if self.recursion_limit:
            return self.recursion_limit
        passes = (self.max_revisions + 1) * (self.max_replans + 1)
        return int(passes * 4 * 1.5) + 10

    @classmethod
    def from_agent(cls, agent: Any, overrides: dict[str, Any] | None = None) -> AgentRuntimeConfig:
        """Build a config from an Agent row's `runtime_config` JSON plus
        per-request overrides.

        Tolerant by design: a malformed `runtime_config` yields defaults
        rather than a 500, because a bad admin edit should degrade one
        agent's tuning, not take chat down.
        """
        raw: dict[str, Any] = {}
        candidate = getattr(agent, "runtime_config", None)
        if isinstance(candidate, dict):
            raw.update(candidate)
        if overrides:
            raw.update(overrides)
        try:
            return cls.model_validate(raw)
        except Exception:  # noqa: BLE001 — defaults beat a broken chat endpoint
            return cls()
