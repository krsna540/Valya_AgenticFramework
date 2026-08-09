"""Agent state machine — the single source of truth for a run.

Three separate things live in this module and it's worth keeping them
distinct in your head:

1. **The phase machine** (`RunPhase`) — where the run is. Advanced only by
   `transition()`, which enforces `_ALLOWED_TRANSITIONS`. An illegal
   transition is a bug in graph wiring, so it raises rather than silently
   correcting: without this, a mis-wired conditional edge produces a run
   that *looks* fine in the DB but skipped critique.

2. **The channel schema** (`AgentState`) — what LangGraph stores and
   checkpoints. Every key carries an explicit reducer via `Annotated[...]`,
   because LangGraph's default reducer is last-write-wins and that is
   silently wrong for anything accumulative. `transcript` and `step_results`
   are append-only; `scratchpad` merges; `revision` takes the max (so two
   concurrent writers can never move a counter backwards). Getting this
   wrong is the classic LangGraph bug — a parallel branch clobbers the
   other branch's appends and the loss is invisible until you read a
   transcript with holes in it.

3. **The domain objects** (`Plan`, `PlanStep`, `Critique`) — Pydantic
   models rather than loose dicts, so the boundary where an LLM's JSON
   becomes program state is validated in exactly one place. They are stored
   in the state as plain dicts (`model_dump()`) because everything in
   `AgentState` must survive a msgpack round-trip through a LangGraph
   checkpointer and a Temporal payload converter.

Note on immutability: LangGraph nodes return *partial* state updates
(a dict of only the channels they touched), never a mutated copy of the
whole state. All the helpers below follow that convention and return
partials — see `BaseAgent.__call__` in base.py.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing_extensions import TypedDict


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Enumerations -----------------------------------------------------------


class RunPhase(str, enum.Enum):
    """Where the run currently is. Mirrors the graph's node topology one
    phase per node, plus the two entry/exit phases that have no node."""

    PENDING = "pending"
    INITIALIZING = "initializing"
    PLANNING = "planning"
    EXECUTING = "executing"
    CRITIQUING = "critiquing"
    REVISING = "revising"
    FINALIZING = "finalizing"
    DONE = "done"


class RunStatus(str, enum.Enum):
    """The run's terminal disposition. Only meaningful once phase == DONE,
    except for RUNNING which is the value while it's still in flight."""

    RUNNING = "running"
    #: Critic accepted the answer.
    SUCCEEDED = "succeeded"
    #: Answer produced, but the critic never accepted it and the revision
    #: budget ran out. Distinct from FAILED: there *is* an answer to show,
    #: it just didn't clear the quality bar. The Observatory needs to be
    #: able to tell these apart to compute a meaningful acceptance rate.
    DEGRADED = "degraded"
    #: An unrecoverable error; there is no usable answer.
    FAILED = "failed"
    #: A guardrail hook denied the turn.
    HALTED = "halted"
    #: Paused awaiting a human decision (Temporal signal / LangGraph resume).
    AWAITING_HUMAN = "awaiting_human"
    CANCELLED = "cancelled"


class StepStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class Verdict(str, enum.Enum):
    """The critic's decision, which is also the graph's routing key out of
    the critic node — one enum, so a verdict the router doesn't handle is a
    static error rather than a run that silently falls through to END."""

    #: Good enough. → finalize
    ACCEPT = "accept"
    #: Execution was flawed but the plan is sound. → re-execute
    REVISE = "revise"
    #: The plan itself was wrong. → re-plan
    REPLAN = "replan"
    #: Needs a human. → finalize, flagged for review
    ESCALATE = "escalate"


#: Legal phase transitions. Anything not listed here raises in `transition()`.
_ALLOWED_TRANSITIONS: dict[RunPhase, frozenset[RunPhase]] = {
    RunPhase.PENDING: frozenset({RunPhase.INITIALIZING, RunPhase.DONE}),
    RunPhase.INITIALIZING: frozenset({RunPhase.PLANNING, RunPhase.FINALIZING, RunPhase.DONE}),
    RunPhase.PLANNING: frozenset({RunPhase.EXECUTING, RunPhase.FINALIZING, RunPhase.DONE}),
    RunPhase.EXECUTING: frozenset({RunPhase.CRITIQUING, RunPhase.FINALIZING, RunPhase.DONE}),
    RunPhase.CRITIQUING: frozenset(
        {RunPhase.REVISING, RunPhase.PLANNING, RunPhase.FINALIZING, RunPhase.DONE}
    ),
    RunPhase.REVISING: frozenset({RunPhase.EXECUTING, RunPhase.PLANNING, RunPhase.FINALIZING}),
    RunPhase.FINALIZING: frozenset({RunPhase.DONE}),
    RunPhase.DONE: frozenset(),
}

#: Statuses after which nothing further may run.
TERMINAL_STATUSES: frozenset[RunStatus] = frozenset(
    {
        RunStatus.SUCCEEDED,
        RunStatus.DEGRADED,
        RunStatus.FAILED,
        RunStatus.HALTED,
        RunStatus.CANCELLED,
    }
)


class IllegalTransitionError(RuntimeError):
    """Raised when the graph tries to move between two phases that aren't
    adjacent in `_ALLOWED_TRANSITIONS`. Always a wiring bug, never data."""


def transition(current: RunPhase, target: RunPhase) -> RunPhase:
    """Validate and perform a phase transition.

    Self-transitions are allowed (a node re-entered by the revision loop
    stays in its own phase) but every other move must be declared.
    """
    if current == target:
        return target
    allowed = _ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise IllegalTransitionError(
            f"Illegal phase transition {current.value} -> {target.value}; "
            f"allowed from {current.value}: {sorted(p.value for p in allowed) or '(terminal)'}"
        )
    return target


# --- Reducers ---------------------------------------------------------------
#
# LangGraph calls these to merge each node's partial update into the channel's
# existing value. They must be pure, associative where order doesn't matter,
# and total (never raise) — a reducer that throws corrupts the checkpoint.


def append_all(existing: list[Any] | None, incoming: list[Any] | Any) -> list[Any]:
    """Append-only accumulation. Accepts a bare item as a convenience so a
    node can return `{"transcript": entry}` instead of `{"transcript": [entry]}`."""
    base = list(existing or [])
    if incoming is None:
        return base
    if isinstance(incoming, list):
        base.extend(incoming)
    else:
        base.append(incoming)
    return base


def merge_dict(existing: dict[str, Any] | None, incoming: dict[str, Any] | None) -> dict[str, Any]:
    """Shallow key-wise merge; incoming wins per key. Shallow on purpose —
    a deep merge makes "unset this key" impossible to express."""
    merged = dict(existing or {})
    merged.update(incoming or {})
    return merged


def take_max(existing: int | None, incoming: int | None) -> int:
    """Monotonic counter. Guarantees a counter can never move backwards even
    if two branches write it concurrently — which is what makes the revision
    budget a real budget rather than a suggestion."""
    return max(existing or 0, incoming or 0)


def keep_last(existing: Any, incoming: Any) -> Any:
    """Explicit last-write-wins. Same as LangGraph's default, written out so
    that every channel below states its merge semantics rather than leaving
    the reader to infer them from an absence."""
    return incoming if incoming is not None else existing


# --- Domain objects ---------------------------------------------------------


class PlanStep(BaseModel):
    """One unit of work the executor performs. Deliberately coarse: the
    planner decomposes into ~2-6 of these, not into individual API calls."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    title: str
    #: What the executor should actually do, in natural language.
    instruction: str
    #: Registry Tool name this step wants, or None for a reasoning-only step.
    tool_name: str | None = None
    #: Registry Skill name whose SKILL.md should be loaded as context.
    skill_name: str | None = None
    #: Step ids that must complete first. Used for ordering and, later, for
    #: parallel fan-out of independent steps.
    depends_on: list[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING

    @field_validator("title", "instruction")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v.strip()


class Plan(BaseModel):
    """The planner's output. `revision` records which revision produced it,
    so a run's plan history is reconstructible from the transcript."""

    model_config = ConfigDict(extra="ignore")

    objective: str
    steps: list[PlanStep] = Field(default_factory=list)
    #: Planner's own read of how hard this is; the runtime uses it to decide
    #: whether the critic runs at all (see AgentRuntimeConfig.critic_threshold).
    complexity: int = Field(default=1, ge=1, le=5)
    rationale: str | None = None
    revision: int = 0

    @field_validator("steps")
    @classmethod
    def _at_least_one_step(cls, v: list[PlanStep]) -> list[PlanStep]:
        if not v:
            raise ValueError("a plan must contain at least one step")
        return v

    def step_by_id(self, step_id: str) -> PlanStep | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def ordered_steps(self) -> list[PlanStep]:
        """Steps in dependency order (stable topological sort).

        Falls back to declaration order for any step caught in a cycle
        rather than raising: a cyclic `depends_on` from an LLM is a plan
        quality problem for the critic to catch, not a reason to crash the
        run. Cycle members are appended in their original order so the
        executor still makes progress.
        """
        by_id = {s.id: s for s in self.steps}
        resolved: list[PlanStep] = []
        seen: set[str] = set()

        def visit(step: PlanStep, path: frozenset[str]) -> None:
            if step.id in seen or step.id in path:
                return
            for dep_id in step.depends_on:
                dep = by_id.get(dep_id)
                if dep is not None:
                    visit(dep, path | {step.id})
            if step.id not in seen:
                seen.add(step.id)
                resolved.append(step)

        for step in self.steps:
            visit(step, frozenset())
        # Anything dropped by a cycle guard gets appended in declaration order.
        resolved.extend(s for s in self.steps if s.id not in seen)
        return resolved


class StepResult(BaseModel):
    """What the executor produced for one PlanStep."""

    model_config = ConfigDict(extra="ignore")

    step_id: str
    status: StepStatus
    output: str = ""
    tool_name: str | None = None
    tool_result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    attempts: int = 1
    duration_ms: int = 0
    revision: int = 0


class Critique(BaseModel):
    """The critic's structured judgement. `verdict` drives graph routing;
    `feedback` is fed back into the next executor/planner prompt verbatim,
    which is the whole point of having a critic (Reflexion, arXiv:2303.11366
    — verbal self-reflection in the episodic buffer improves later trials)."""

    model_config = ConfigDict(extra="ignore")

    verdict: Verdict
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    feedback: str = ""
    #: Specific, addressable defects. Rendered as a checklist in the retry
    #: prompt rather than dumped as prose.
    issues: list[str] = Field(default_factory=list)
    #: Which step ids the critic wants redone; empty means "all of them".
    target_step_ids: list[str] = Field(default_factory=list)
    revision: int = 0
    #: True when `verdict` was downgraded by `CriticAgent._apply_budgets`
    #: because the run could no longer afford the verdict the critic actually
    #: reached — e.g. a `revise` with no revisions left becomes `accept`.
    #:
    #: Load-bearing for reporting, not just bookkeeping: without it,
    #: `finalize_node` cannot tell a genuine acceptance from a forced one, and
    #: every run that exhausts its budget is recorded as SUCCEEDED. That makes
    #: the Observatory's acceptance rate measure "did we run out of budget"
    #: rather than "was the answer any good".
    budget_forced: bool = False


class TranscriptEntry(BaseModel):
    """One append-only line in the run's audit trail. Everything a node does
    that a human might later ask "why did it do that?" about lands here."""

    model_config = ConfigDict(extra="ignore")

    seq: int = 0
    at: datetime = Field(default_factory=_utcnow)
    role: str  # planner | executor | critic | system
    phase: RunPhase
    revision: int = 0
    summary: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


# --- The LangGraph channel schema -------------------------------------------


class AgentState(TypedDict, total=False):
    """The graph's state. Every key declares its reducer explicitly.

    `total=False` because nodes return partial updates; `new_state()` below
    is the only place a complete, valid initial state is constructed, so
    treat it as the constructor and this class as the schema.
    """

    # --- identity (written once at init, never merged) ---
    run_id: Annotated[str, keep_last]
    tenant_id: Annotated[str | None, keep_last]
    project_id: Annotated[str | None, keep_last]
    conversation_id: Annotated[str | None, keep_last]
    user_id: Annotated[str | None, keep_last]
    agent_id: Annotated[str, keep_last]
    agent_name: Annotated[str, keep_last]
    trace_id: Annotated[str, keep_last]

    # --- inputs (immutable for the life of the run) ---
    objective: Annotated[str, keep_last]
    language: Annotated[str, keep_last]
    system_prompt: Annotated[str | None, keep_last]
    #: Capability catalogue resolved from the Agent's registry associations,
    #: snapshotted at run start so a mid-run registry edit can't change what
    #: this run was allowed to do — the same "session-pinned skeleton"
    #: discipline docs/agent_runtime_architecture.md §4 locks for agents.
    available_tools: Annotated[list[dict[str, Any]], keep_last]
    available_skills: Annotated[list[dict[str, Any]], keep_last]
    context_documents: Annotated[list[dict[str, Any]], keep_last]

    # --- control (the state machine proper) ---
    phase: Annotated[str, keep_last]
    status: Annotated[str, keep_last]
    revision: Annotated[int, take_max]
    replan_count: Annotated[int, take_max]

    # --- working memory ---
    plan: Annotated[dict[str, Any] | None, keep_last]
    step_results: Annotated[list[dict[str, Any]], append_all]
    draft_answer: Annotated[str, keep_last]
    critique: Annotated[dict[str, Any] | None, keep_last]
    #: Accumulated critic feedback across revisions, oldest first. Append-only
    #: so revision N can see what revisions 1..N-1 were told — without this
    #: the loop happily re-makes a mistake it was already corrected on.
    feedback_log: Annotated[list[str], append_all]

    # --- outputs ---
    final_answer: Annotated[str, keep_last]
    citations: Annotated[list[dict[str, Any]], keep_last]
    needs_human_review: Annotated[bool, keep_last]
    error: Annotated[dict[str, Any] | None, keep_last]

    # --- observability ---
    transcript: Annotated[list[dict[str, Any]], append_all]
    scratchpad: Annotated[dict[str, Any], merge_dict]
    token_usage: Annotated[dict[str, Any], merge_dict]
    started_at: Annotated[str, keep_last]


def new_state(
    *,
    run_id: str,
    agent_id: str,
    agent_name: str,
    objective: str,
    trace_id: str | None = None,
    tenant_id: str | None = None,
    project_id: str | None = None,
    conversation_id: str | None = None,
    user_id: str | None = None,
    language: str = "en",
    system_prompt: str | None = None,
    available_tools: list[dict[str, Any]] | None = None,
    available_skills: list[dict[str, Any]] | None = None,
    context_documents: list[dict[str, Any]] | None = None,
) -> AgentState:
    """Build a complete, valid initial state. The only supported way to
    construct one — nodes must never hand-roll a state dict, or a channel
    added later silently arrives as missing rather than as its zero value."""
    return AgentState(
        run_id=run_id,
        tenant_id=tenant_id,
        project_id=project_id,
        conversation_id=conversation_id,
        user_id=user_id,
        agent_id=agent_id,
        agent_name=agent_name,
        trace_id=trace_id or str(uuid.uuid4()),
        objective=objective,
        language=language,
        system_prompt=system_prompt,
        available_tools=available_tools or [],
        available_skills=available_skills or [],
        context_documents=context_documents or [],
        phase=RunPhase.PENDING.value,
        status=RunStatus.RUNNING.value,
        revision=0,
        replan_count=0,
        plan=None,
        step_results=[],
        draft_answer="",
        critique=None,
        feedback_log=[],
        final_answer="",
        citations=[],
        needs_human_review=False,
        error=None,
        transcript=[],
        scratchpad={},
        token_usage={"input": 0, "output": 0, "calls": 0},
        started_at=_utcnow().isoformat(),
    )


# --- Typed accessors --------------------------------------------------------
#
# The state stores plain dicts (checkpointer/Temporal serialization), so
# these are the one place that dict<->model conversion happens. Every node
# reads through them; nothing else should touch `state["plan"]` directly.


def get_phase(state: AgentState) -> RunPhase:
    return RunPhase(state.get("phase") or RunPhase.PENDING.value)


def get_status(state: AgentState) -> RunStatus:
    return RunStatus(state.get("status") or RunStatus.RUNNING.value)


def resolve_model_route(state: AgentState, role: str) -> str:
    """The gateway route (or stub model name) the given role should call.

    `scratchpad["model_routes"]` is a per-role dict set once in
    `AgentRunRequest.to_state()` (app/agents/runtime.py) — see that
    function's docstring for how it's populated: an agent with an explicit
    `model_name` uses that one model for every role (today's behaviour,
    unchanged); an agent left on "default" gets the role-split routes from
    settings (planner/critic -> the strong-reasoning route, executor -> the
    fast route) per PLATFORM_ARCHITECTURE.md's provider-split decision.

    Falls back to the legacy flat `scratchpad["model_route"]` key, then to
    "default", so a checkpoint written before this change (or a state built
    by a test that only sets the old key) still resolves to something.
    """
    scratchpad = state.get("scratchpad") or {}
    routes = scratchpad.get("model_routes")
    if isinstance(routes, dict) and routes.get(role):
        return str(routes[role])
    return str(scratchpad.get("model_route") or "default")


def get_plan(state: AgentState) -> Plan | None:
    raw = state.get("plan")
    if not raw:
        return None
    try:
        return Plan.model_validate(raw)
    except Exception:  # noqa: BLE001 — a corrupt checkpoint must not crash a read
        return None


def get_critique(state: AgentState) -> Critique | None:
    raw = state.get("critique")
    if not raw:
        return None
    try:
        return Critique.model_validate(raw)
    except Exception:  # noqa: BLE001
        return None


def get_step_results(state: AgentState) -> list[StepResult]:
    out: list[StepResult] = []
    for raw in state.get("step_results") or []:
        try:
            out.append(StepResult.model_validate(raw))
        except Exception:  # noqa: BLE001
            continue
    return out


def latest_step_results(state: AgentState) -> list[StepResult]:
    """Only the results from the current revision. `step_results` is
    append-only across the whole run (so the audit trail keeps every
    attempt), but the answer must be assembled from the newest pass only."""
    revision = int(state.get("revision") or 0)
    return [r for r in get_step_results(state) if r.revision == revision]


def make_transcript_entry(
    state: AgentState,
    *,
    role: str,
    phase: RunPhase,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the next transcript line. `seq` is derived from the current
    transcript length rather than a counter channel, which keeps it correct
    under the append-only reducer without a second channel to keep in sync."""
    entry = TranscriptEntry(
        seq=len(state.get("transcript") or []),
        role=role,
        phase=phase,
        revision=int(state.get("revision") or 0),
        summary=summary,
        payload=payload or {},
    )
    return entry.model_dump(mode="json")
