"""Tests for the Planner → Executor → Critic runtime.

Driven by `ScriptedLLMProvider` rather than mocks: the graph's interesting
behaviour is *conditional on model output* (a verdict routes the graph, a
malformed plan triggers the repair loop), so the tests script that output
directly and assert on the resulting control flow. Patching internals would
test the patch instead of the state machine.

No database, no network, no Temporal — `InMemorySaver` for checkpoints and
scripted responses for generation. That is deliberate: this is the layer that
must stay fast enough to run on every commit.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest
from pydantic import ValidationError

from app.agents.base import AgentOutcome, AgentRole, BaseAgent
from app.agents.config import AgentRuntimeConfig
from app.agents.critic import CriticAgent
from app.agents.errors import (
    BudgetExceededError,
    PlanValidationError,
    ProviderError,
)
from app.agents.graph import (
    NODE_FINALIZE,
    NODE_REPLAN,
    NODE_REVISE,
    route_after_critique,
    route_after_plan,
)
from app.agents.lifecycle import CollectingEventSink, EventType
from app.agents.llm import (
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    StubLLMProvider,
    coerce_json_object,
)
from app.agents.registry import get_agent, list_agents
from app.agents.runtime import AgentRunRequest, AgentRuntime
from app.agents.state import (
    Critique,
    IllegalTransitionError,
    Plan,
    RunPhase,
    RunStatus,
    StepStatus,
    Verdict,
    append_all,
    merge_dict,
    new_state,
    take_max,
    transition,
)
from app.agents.tools import DescribeOnlyToolInvoker, SkillSpec, ToolInvocation, ToolSpec

AGENT_ID = "11111111-1111-1111-1111-111111111111"


# --- helpers ----------------------------------------------------------------


class ScriptedLLMProvider(LLMProvider):
    """Returns a caller-supplied response per purpose, in order.

    Falls back to the deterministic stub when a purpose runs out of scripted
    responses, so a test only has to script the calls it cares about.
    """

    name = "scripted"

    def __init__(self, **scripts: list[str]) -> None:
        self._scripts = {k: list(v) for k, v in scripts.items()}
        self._fallback = StubLLMProvider()
        self.calls: list[tuple[str, str]] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        prompt = "\n".join(m.content for m in request.messages)
        self.calls.append((request.purpose, prompt))
        queue = self._scripts.get(request.purpose)
        if queue:
            text = queue.pop(0)
            return LLMResponse(text=text, model=request.model, output_tokens=len(text.split()))
        return await self._fallback.complete(request)

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        response = await self.complete(request)

        async def _iter() -> AsyncIterator[str]:
            for word in response.text.split(" "):
                yield word + " "

        return _iter()

    def calls_for(self, purpose: str) -> int:
        return sum(1 for p, _ in self.calls if p == purpose)


def plan_json(*, steps: int = 2, complexity: int = 3, tool: str | None = None) -> str:
    return json.dumps(
        {
            "objective": "test objective",
            "complexity": complexity,
            "rationale": "scripted",
            "steps": [
                {
                    "id": f"step_{i + 1}",
                    "title": f"Step {i + 1}",
                    "instruction": f"Do part {i + 1}",
                    "tool_name": tool if i == 0 else None,
                    "skill_name": None,
                    "depends_on": [f"step_{i}"] if i else [],
                }
                for i in range(steps)
            ],
        }
    )


def critique_json(verdict: str, *, score: float = 0.5, targets: list[str] | None = None) -> str:
    return json.dumps(
        {
            "verdict": verdict,
            "score": score,
            "feedback": f"scripted {verdict}",
            "issues": [f"issue for {verdict}"],
            "target_step_ids": targets or [],
        }
    )


def make_request(**overrides) -> AgentRunRequest:
    payload = {
        "objective": "Explain the revenue drivers.",
        "agent_id": AGENT_ID,
        "agent_name": "Test Agent",
        "config": AgentRuntimeConfig(
            max_revisions=2,
            max_replans=1,
            critic_complexity_threshold=1,
            node_timeout_s=5,
            run_timeout_s=30,
            retry_backoff_s=0.001,
        ),
    }
    payload.update(overrides)
    return AgentRunRequest(**payload)


async def run_graph(provider: LLMProvider, request: AgentRunRequest):
    from langgraph.checkpoint.memory import InMemorySaver

    runtime = AgentRuntime(llm=provider, checkpointer=InMemorySaver())
    sink = CollectingEventSink()
    events = [e async for e in runtime.stream(request, extra_sink=sink)]
    return runtime.last_result, events, sink


# --- state: reducers --------------------------------------------------------


def test_append_all_accumulates_and_accepts_bare_items():
    assert append_all(["a"], ["b", "c"]) == ["a", "b", "c"]
    assert append_all(["a"], "b") == ["a", "b"]
    assert append_all(None, None) == []


def test_take_max_never_moves_a_counter_backwards():
    """The property that makes the revision budget a real budget."""
    assert take_max(3, 1) == 3
    assert take_max(1, 3) == 3
    assert take_max(None, 0) == 0


def test_merge_dict_is_key_wise_and_incoming_wins():
    assert merge_dict({"a": 1, "b": 2}, {"b": 3}) == {"a": 1, "b": 3}


# --- state: phase machine ---------------------------------------------------


def test_legal_transitions_are_allowed():
    assert transition(RunPhase.PENDING, RunPhase.INITIALIZING) == RunPhase.INITIALIZING
    assert transition(RunPhase.CRITIQUING, RunPhase.REVISING) == RunPhase.REVISING
    assert transition(RunPhase.REVISING, RunPhase.EXECUTING) == RunPhase.EXECUTING


def test_self_transition_is_allowed():
    """A node re-entered by the revision loop stays in its own phase."""
    assert transition(RunPhase.EXECUTING, RunPhase.EXECUTING) == RunPhase.EXECUTING


def test_illegal_transition_raises():
    """Skipping execution would produce a run that looks fine but never ran."""
    with pytest.raises(IllegalTransitionError):
        transition(RunPhase.PLANNING, RunPhase.CRITIQUING)
    with pytest.raises(IllegalTransitionError):
        transition(RunPhase.DONE, RunPhase.PLANNING)


# --- state: domain objects --------------------------------------------------


def test_plan_requires_at_least_one_step():
    with pytest.raises(ValidationError):
        Plan(objective="x", steps=[])


def test_ordered_steps_respects_dependencies():
    plan = Plan.model_validate(
        {
            "objective": "x",
            "steps": [
                {"id": "c", "title": "C", "instruction": "c", "depends_on": ["b"]},
                {"id": "a", "title": "A", "instruction": "a", "depends_on": []},
                {"id": "b", "title": "B", "instruction": "b", "depends_on": ["a"]},
            ],
        }
    )
    assert [s.id for s in plan.ordered_steps()] == ["a", "b", "c"]


def test_ordered_steps_survives_a_dependency_cycle():
    """A cyclic plan is a quality problem for the critic, not a crash."""
    plan = Plan.model_validate(
        {
            "objective": "x",
            "steps": [
                {"id": "a", "title": "A", "instruction": "a", "depends_on": ["b"]},
                {"id": "b", "title": "B", "instruction": "b", "depends_on": ["a"]},
            ],
        }
    )
    assert {s.id for s in plan.ordered_steps()} == {"a", "b"}


# --- llm: JSON coercion -----------------------------------------------------


def test_coerce_json_handles_fenced_and_prefixed_output():
    assert coerce_json_object('{"a": 1}') == {"a": 1}
    assert coerce_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert coerce_json_object('Sure! Here you go:\n{"a": 1}\nHope that helps.') == {"a": 1}


def test_coerce_json_wraps_a_bare_array():
    assert coerce_json_object("[1, 2]") == {"items": [1, 2]}


def test_the_stub_provider_selects_offered_tools_and_skills():
    """Otherwise the whole activation path — tool_call/skill_call events, the
    PreToolUse gate, ToolInvoker — is dead code for anyone running the
    default offline provider, which is most people."""
    from app.agents.prompts import planner_system_prompt

    system = planner_system_prompt(
        agent_name="a",
        system_prompt=None,
        tools=[ToolSpec(name="sql_query", description="SQL")],
        skills=[SkillSpec(name="exec-summary", description="Summarise")],
        max_steps=5,
        language="en",
    )
    request = LLMRequest(
        messages=[
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content="Objective:\nDo the thing."),
        ],
        model="m",
        purpose="planner",
    )
    tools, skills = StubLLMProvider._capabilities(request)
    assert tools == ["sql_query"]
    assert skills == ["exec-summary"]

    plan = Plan.model_validate(StubLLMProvider()._plan(request))
    assert plan.steps[0].tool_name == "sql_query"
    assert plan.steps[-1].skill_name == "exec-summary"


def test_coerce_json_raises_a_retryable_error_on_garbage():
    with pytest.raises(ProviderError) as excinfo:
        coerce_json_object("not json at all")
    assert excinfo.value.retryable is True


# --- errors -----------------------------------------------------------------


def test_error_taxonomy_flags_drive_retry_and_routing():
    assert PlanValidationError("x").retryable is True
    assert PlanValidationError("x").terminal is False
    assert BudgetExceededError("x").terminal is True
    assert BudgetExceededError("x").retryable is False


# --- registry ---------------------------------------------------------------


def test_all_three_roles_are_registered():
    registered = list_agents()
    assert set(registered) == set(AgentRole)
    assert get_agent(AgentRole.PLANNER).__name__ == "PlannerAgent"


def test_registering_a_duplicate_role_without_replace_raises():
    from app.agents.registry import register_agent

    with pytest.raises(ValueError, match="already registered"):

        @register_agent(AgentRole.PLANNER)
        class _Duplicate(BaseAgent):
            role = AgentRole.PLANNER
            phase = RunPhase.PLANNING

            async def _invoke(self, state):
                return AgentOutcome()


def test_subclass_without_role_fails_at_import_time():
    with pytest.raises(TypeError, match="class-level"):

        class _Incomplete(BaseAgent):
            async def _invoke(self, state):
                return AgentOutcome()


# --- routers ----------------------------------------------------------------


def test_route_after_plan_finalizes_when_there_is_no_plan():
    state = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="o")
    assert route_after_plan(state) == NODE_FINALIZE


def test_route_after_critique_maps_every_verdict():
    base = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="o")
    cases = {
        Verdict.REVISE: NODE_REVISE,
        Verdict.REPLAN: NODE_REPLAN,
        Verdict.ACCEPT: NODE_FINALIZE,
        Verdict.ESCALATE: NODE_FINALIZE,
    }
    for verdict, expected in cases.items():
        state = dict(base)
        state["critique"] = Critique(verdict=verdict).model_dump(mode="json")
        assert route_after_critique(state) == expected


def test_route_after_critique_finalizes_a_terminal_run():
    state = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="o")
    state["status"] = RunStatus.FAILED.value
    state["critique"] = Critique(verdict=Verdict.REVISE).model_dump(mode="json")
    assert route_after_critique(state) == NODE_FINALIZE


# --- planner ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_rejects_a_plan_referencing_an_unavailable_tool_then_repairs():
    """The repair loop re-prompts with the validator's complaint rather than
    re-sending the identical prompt."""
    provider = ScriptedLLMProvider(
        planner=[plan_json(tool="nonexistent_tool"), plan_json(tool="sql_query")]
    )
    request = make_request(
        tools=[ToolSpec(name="sql_query", description="SQL").model_dump()],
    )
    result, _, _ = await run_graph(provider, request)

    assert provider.calls_for("planner") == 2
    assert "nonexistent_tool" in provider.calls[1][1]
    assert result.status in (RunStatus.SUCCEEDED, RunStatus.DEGRADED)
    assert result.plan_step_count == 2


@pytest.mark.asyncio
async def test_planner_gives_up_after_the_repair_budget_and_the_run_fails_cleanly():
    provider = ScriptedLLMProvider(planner=["not json"] * 6)
    result, _, _ = await run_graph(provider, make_request())

    assert result.status == RunStatus.FAILED
    assert result.error is not None
    # A failed run still returns something renderable rather than an empty body.
    assert result.final_answer


@pytest.mark.asyncio
async def test_planner_enforces_the_max_plan_steps_budget():
    # Enough scripted responses to outlast repair attempts x node retries
    # (3 x 3); ScriptedLLMProvider falls back to the *valid* stub plan once a
    # queue empties, which would otherwise let the run succeed by accident.
    provider = ScriptedLLMProvider(planner=[plan_json(steps=8)] * 12)
    request = make_request()
    request = request.model_copy(
        update={"config": request.config.model_copy(update={"max_plan_steps": 3})}
    )
    result, _, _ = await run_graph(provider, request)
    assert result.status == RunStatus.FAILED


# --- executor ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_emits_a_tool_call_and_a_step_per_plan_step():
    provider = ScriptedLLMProvider(planner=[plan_json(steps=2, tool="sql_query")])
    request = make_request(tools=[ToolSpec(name="sql_query", description="SQL").model_dump()])
    _, _, sink = await run_graph(provider, request)

    assert len(sink.of_type(EventType.STEP_START)) == 2
    assert len(sink.of_type(EventType.STEP_END)) == 2
    tool_calls = sink.of_type(EventType.TOOL_CALL)
    assert [e.data["tool_name"] for e in tool_calls] == ["sql_query"]


@pytest.mark.asyncio
async def test_executor_activates_a_skill_without_executing_it():
    """Skills are instructional context in this codebase, never code."""
    plan = json.loads(plan_json(steps=1))
    plan["steps"][0]["skill_name"] = "exec-summary"
    provider = ScriptedLLMProvider(planner=[json.dumps(plan)])
    request = make_request(
        skills=[
            SkillSpec(
                name="exec-summary", description="Be brief", body_markdown="# Keep it short"
            ).model_dump()
        ]
    )
    _, _, sink = await run_graph(provider, request)

    assert [e.data["skill_name"] for e in sink.of_type(EventType.SKILL_CALL)] == ["exec-summary"]
    # The SKILL.md body reached the executor's prompt.
    assert any(
        "Keep it short" in prompt
        for purpose, prompt in provider.calls
        if purpose == "executor"
    )


@pytest.mark.asyncio
async def test_a_failed_step_does_not_fail_the_run():
    class ExplodingInvoker(DescribeOnlyToolInvoker):
        async def invoke(self, spec, invocation):
            raise RuntimeError("tool exploded")

    from app.agents.executor import ExecutorAgent

    agent = ExecutorAgent(
        llm=ScriptedLLMProvider(),
        config=AgentRuntimeConfig(retry_backoff_s=0.001),
        tool_invoker=ExplodingInvoker(),
    )
    state = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="o")
    state["plan"] = json.loads(plan_json(steps=1, tool="sql_query"))
    state["available_tools"] = [ToolSpec(name="sql_query").model_dump()]
    state["phase"] = RunPhase.PLANNING.value

    update = await agent(state)

    assert update["status"] != RunStatus.FAILED.value if "status" in update else True
    assert update["step_results"][0]["status"] == StepStatus.FAILED.value
    assert update["draft_answer"]


@pytest.mark.asyncio
async def test_describe_only_invoker_marks_results_as_simulated():
    """A silently-faked tool result would be worse than none at all."""
    result = await DescribeOnlyToolInvoker().invoke(
        ToolSpec(name="t"), ToolInvocation(tool_name="t", arguments={"a": 1})
    )
    assert result.simulated is True
    assert "simulated" in result.output.lower()


# --- critic + revision loop -------------------------------------------------


@pytest.mark.asyncio
async def test_a_revise_verdict_runs_the_executor_again_and_increments_the_revision():
    provider = ScriptedLLMProvider(
        planner=[plan_json(steps=1)],
        critic=[critique_json("revise"), critique_json("accept", score=0.9)],
    )
    result, _, sink = await run_graph(provider, make_request())

    assert result.revisions == 1
    assert result.critic_verdict == Verdict.ACCEPT.value
    assert result.status == RunStatus.SUCCEEDED
    assert len(sink.of_type(EventType.REVISION_START)) == 1
    # The plan was sound, so it was not re-planned.
    assert provider.calls_for("planner") == 1


@pytest.mark.asyncio
async def test_critic_feedback_reaches_the_next_executor_prompt_as_a_checklist():
    provider = ScriptedLLMProvider(
        planner=[plan_json(steps=1)],
        critic=[critique_json("revise"), critique_json("accept", score=0.9)],
    )
    await run_graph(provider, make_request())

    executor_prompts = [p for purpose, p in provider.calls if purpose == "executor"]
    assert any("Fix every item below" in p for p in executor_prompts)
    assert any("scripted revise" in p for p in executor_prompts)


@pytest.mark.asyncio
async def test_the_revision_budget_is_enforced_and_the_run_degrades():
    """Exhausting the budget yields DEGRADED — there is an answer, it just
    never cleared the bar. Distinct from FAILED, which has no answer."""
    provider = ScriptedLLMProvider(
        planner=[plan_json(steps=1)], critic=[critique_json("revise")] * 8
    )
    request = make_request()
    request = request.model_copy(
        update={"config": request.config.model_copy(update={"max_revisions": 1})}
    )
    result, _, _ = await run_graph(provider, request)

    assert result.revisions == 1
    assert result.status == RunStatus.DEGRADED
    assert result.final_answer


@pytest.mark.asyncio
async def test_a_replan_verdict_returns_to_the_planner():
    provider = ScriptedLLMProvider(
        planner=[plan_json(steps=1), plan_json(steps=2)],
        critic=[critique_json("replan"), critique_json("accept", score=0.9)],
    )
    result, _, _ = await run_graph(provider, make_request())

    assert provider.calls_for("planner") == 2
    assert result.replans == 1
    assert result.status == RunStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_an_escalate_verdict_flags_the_run_for_human_review():
    provider = ScriptedLLMProvider(
        planner=[plan_json(steps=1)], critic=[critique_json("escalate")]
    )
    result, _, sink = await run_graph(provider, make_request())

    assert result.needs_human_review is True
    assert result.status == RunStatus.AWAITING_HUMAN
    assert sink.of_type(EventType.HUMAN_REVIEW_REQUIRED)


@pytest.mark.asyncio
async def test_a_broken_critic_fails_open_and_accepts_the_draft():
    """A quality gate that breaks must not swallow a good answer."""
    provider = ScriptedLLMProvider(
        planner=[plan_json(steps=1)], critic=["this is not json"] * 4
    )
    result, _, _ = await run_graph(provider, make_request())

    assert result.status == RunStatus.SUCCEEDED
    assert result.critic_verdict == Verdict.ACCEPT.value


def test_critic_downgrades_a_verdict_it_cannot_afford():
    critic = CriticAgent(
        llm=StubLLMProvider(), config=AgentRuntimeConfig(max_revisions=1, max_replans=0)
    )
    state = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="o")
    state["revision"] = 1  # budget already spent

    downgraded = critic._apply_budgets(Critique(verdict=Verdict.REVISE), state)
    assert downgraded.verdict == Verdict.ACCEPT
    assert "budget" in downgraded.feedback.lower()
    # Marked as forced so finalize_node reports DEGRADED, not SUCCEEDED.
    assert downgraded.budget_forced is True


def test_critic_escalates_instead_of_accepting_when_configured():
    critic = CriticAgent(
        llm=StubLLMProvider(),
        config=AgentRuntimeConfig(max_revisions=1, escalate_on_budget_exhausted=True),
    )
    state = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="o")
    state["revision"] = 1

    downgraded = critic._apply_budgets(Critique(verdict=Verdict.REVISE), state)
    assert downgraded.verdict == Verdict.ESCALATE


def test_critic_risk_gate_skips_low_complexity_runs():
    """Reflection costs a full model round-trip; it is spent on hard turns."""
    critic = CriticAgent(
        llm=StubLLMProvider(), config=AgentRuntimeConfig(critic_complexity_threshold=3)
    )
    state = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="o")
    state["plan"] = json.loads(plan_json(complexity=1))
    assert critic.should_run(state) is False

    state["plan"] = json.loads(plan_json(complexity=4))
    assert critic.should_run(state) is True


@pytest.mark.asyncio
async def test_the_critic_is_skipped_entirely_when_disabled():
    provider = ScriptedLLMProvider(planner=[plan_json(steps=1)])
    request = make_request()
    request = request.model_copy(
        update={"config": request.config.model_copy(update={"enable_critic": False})}
    )
    result, _, _ = await run_graph(provider, request)

    assert provider.calls_for("critic") == 0
    assert result.critic_verdict is None
    # A skipped critic is a risk-gate decision, not a quality failure.
    assert result.status == RunStatus.SUCCEEDED


# --- BaseAgent lifecycle ----------------------------------------------------


@pytest.mark.asyncio
async def test_a_node_never_raises_it_returns_a_failure_state():
    from app.agents.planner import PlannerAgent

    class Exploding(PlannerAgent):
        async def _invoke(self, state):
            raise RuntimeError("boom")

    agent = Exploding(
        llm=StubLLMProvider(),
        config=AgentRuntimeConfig(max_attempts_per_node=1, retry_backoff_s=0.001),
    )
    state = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="o")
    state["phase"] = RunPhase.INITIALIZING.value

    update = await agent(state)

    assert update["status"] == RunStatus.FAILED.value
    assert update["phase"] == RunPhase.FINALIZING.value
    assert update["error"]["message"]


@pytest.mark.asyncio
async def test_a_node_is_a_no_op_once_the_run_is_terminal():
    from app.agents.planner import PlannerAgent

    agent = PlannerAgent(llm=StubLLMProvider(), config=AgentRuntimeConfig())
    state = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="o")
    state["status"] = RunStatus.HALTED.value

    assert await agent(state) == {}


@pytest.mark.asyncio
async def test_the_retry_decorator_retries_only_retryable_errors():
    from app.agents.planner import PlannerAgent

    attempts = {"retryable": 0, "terminal": 0}

    class RetryableFail(PlannerAgent):
        async def _invoke(self, state):
            attempts["retryable"] += 1
            raise PlanValidationError("bad plan")

    class TerminalFail(PlannerAgent):
        async def _invoke(self, state):
            attempts["terminal"] += 1
            raise BudgetExceededError("out of budget")

    config = AgentRuntimeConfig(max_attempts_per_node=3, retry_backoff_s=0.001)
    state = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="o")
    state["phase"] = RunPhase.INITIALIZING.value

    await RetryableFail(llm=StubLLMProvider(), config=config)(dict(state))
    await TerminalFail(llm=StubLLMProvider(), config=config)(dict(state))

    assert attempts["retryable"] == 3
    assert attempts["terminal"] == 1


@pytest.mark.asyncio
async def test_a_node_timeout_is_reported_as_a_typed_error():
    from app.agents.planner import PlannerAgent

    class Slow(PlannerAgent):
        async def _invoke(self, state):
            await asyncio.sleep(5)
            return AgentOutcome()

    agent = Slow(
        llm=StubLLMProvider(),
        config=AgentRuntimeConfig(
            node_timeout_s=0.05, max_attempts_per_node=1, retry_backoff_s=0.001
        ),
    )
    state = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="o")
    state["phase"] = RunPhase.INITIALIZING.value

    update = await agent(state)
    assert update["error"]["error_type"] == "AgentTimeoutError"


@pytest.mark.asyncio
async def test_validate_input_rejects_a_run_with_no_objective():
    from app.agents.planner import PlannerAgent

    agent = PlannerAgent(llm=StubLLMProvider(), config=AgentRuntimeConfig())
    state = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="")

    update = await agent(state)
    assert update["error"]["message"] == "Run has no objective"


@pytest.mark.asyncio
async def test_the_executor_requires_a_plan():
    from app.agents.executor import ExecutorAgent

    agent = ExecutorAgent(llm=StubLLMProvider(), config=AgentRuntimeConfig())
    state = new_state(run_id="r", agent_id=AGENT_ID, agent_name="a", objective="o")

    update = await agent(state)
    assert "requires a plan" in update["error"]["message"]


# --- end-to-end -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_full_run_produces_an_ordered_transcript_and_an_answer():
    provider = ScriptedLLMProvider(
        planner=[plan_json(steps=2)], critic=[critique_json("accept", score=0.9)]
    )
    result, events, sink = await run_graph(provider, make_request())

    roles = [entry["role"] for entry in result.transcript]
    assert roles == ["system", "planner", "executor", "critic", "system"]
    assert [entry["seq"] for entry in result.transcript] == [0, 1, 2, 3, 4]

    # The stream carries token-level output, not just node boundaries.
    assert sink.of_type(EventType.TOKEN)
    assert sink.of_type(EventType.PLAN_READY)
    assert sink.of_type(EventType.CRITIQUE_READY)
    assert events[-1].type == EventType.RUN_END
    assert events[-1].data["final"] is True
    assert result.final_answer


@pytest.mark.asyncio
async def test_step_results_accumulate_across_revisions_for_the_audit_trail():
    provider = ScriptedLLMProvider(
        planner=[plan_json(steps=1)],
        critic=[critique_json("revise"), critique_json("accept", score=0.9)],
    )
    result, _, _ = await run_graph(provider, make_request())

    revisions = [r["revision"] for r in result.state["step_results"]]
    # Both passes are retained; the synthesis reads only the latest.
    assert 0 in revisions and 1 in revisions


@pytest.mark.asyncio
async def test_the_runtime_config_snapshot_survives_a_malformed_agent_row():
    class FakeAgent:
        runtime_config = "not a dict"

    config = AgentRuntimeConfig.from_agent(FakeAgent())
    assert config.max_revisions == AgentRuntimeConfig().max_revisions


def test_effective_recursion_limit_covers_the_worst_case_path():
    config = AgentRuntimeConfig(max_revisions=3, max_replans=2)
    # 4 passes x 3 replan cycles x 4 nodes = 48 super-steps at worst.
    assert config.effective_recursion_limit() > (3 + 1) * (2 + 1) * 4
