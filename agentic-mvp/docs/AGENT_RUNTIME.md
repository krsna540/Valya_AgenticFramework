# Agent Runtime — Planner → Executor → Critic

Implements the reasoning runtime from `docs/agent_runtime_architecture.md` §2:
a **LangGraph** state graph inside a **Temporal** durable envelope. It replaces
the deterministic stub that used to live in `app/services/agent_runner.py`;
that module is now a thin SSE adapter over this package.

`api/routes/chat.py` was **not modified** — the adapter preserves the existing
generator signature and event contract exactly.

---

## 1. The three roles

| Role | Phase | Responsibility | Fails how |
|---|---|---|---|
| **Planner** | `PLANNING` | Decompose the objective into 2–8 validated steps | Re-prompts itself with the validator's complaint (2 repairs), then fails the run |
| **Executor** | `EXECUTING` | Run each step (tool / skill / reasoning), then synthesise the answer | A failed step becomes a `FAILED` StepResult; the run continues |
| **Critic** | `CRITIQUING` | Judge the draft, emit a verdict that *routes the graph* | Fails **open** — accepts with a low score. A broken reviewer must not swallow a good answer |

All three extend `BaseAgent` (`app/agents/base.py`), which owns the lifecycle:

```
guard → validate → enter (phase transition) → invoke (@instrumented) → exit → isolate
```

`__call__` never raises except on cancellation. A LangGraph node that raises
aborts the whole run and discards the checkpoint, the partial answer and the
audit trail; converting failure into `state["error"] + status` lets the router
finalize instead.

Adding a fourth role = one `AgentRole` member + one `@register_agent`-decorated
class. `graph.py` reads the registry, never the concrete classes.

---

## 2. Topology

```
initialize → planner → executor → critic ─┬─ accept/escalate → finalize → END
                ▲          ▲              ├─ revise  → revise  ─┘ (back to executor)
                └── replan ┴──────────────┴─ replan  → replan
```

Three points that have wrong-looking simpler alternatives:

- **All roads lead to `finalize`.** No node routes to `END`. Finalize is the
  single place the terminal status is decided and `RUN_END` fires.
- **`revise` / `replan` are nodes, not router side effects.** A LangGraph
  router must be pure; incrementing the revision counter is a state write.
- **Budgets are enforced in the critic, not the router.** The critic downgrades
  a verdict it can't afford, so the router only ever sees a routable verdict.
  Checking in both places is how a loop runs one more time than the budget says.

---

## 3. State management

`AgentState` is a TypedDict where **every channel declares an explicit
reducer** — LangGraph's default is last-write-wins, which is silently wrong for
anything accumulative:

| Channel | Reducer | Why |
|---|---|---|
| `transcript`, `step_results`, `feedback_log` | `append_all` | Audit trail; a parallel branch must not clobber another's appends |
| `revision`, `replan_count` | `take_max` | A counter that can't move backwards is what makes a budget a budget |
| `scratchpad`, `token_usage` | `merge_dict` | Key-wise accumulation |
| everything else | `keep_last` | Written out explicitly rather than left implicit |

Phase transitions go through `transition()`, validated against
`_ALLOWED_TRANSITIONS`. An illegal transition raises — it's always a wiring bug,
and without the guard a mis-wired edge produces a run that *looks* fine in the
database but skipped critique.

**Terminal statuses are not collapsed:**

- `SUCCEEDED` — the critic accepted it (or was skipped by the risk gate).
- `DEGRADED` — there's an answer, but it never cleared the bar (budget forced
  the acceptance). Tracked via `Critique.budget_forced`; without it, every run
  that exhausts its budget reports as SUCCEEDED and the acceptance-rate metric
  measures budget exhaustion instead of quality.
- `FAILED` — no usable answer. `AWAITING_HUMAN`, `HALTED`, `CANCELLED`.

---

## 4. Decorators

```python
@instrumented          # == traced(time_bounded(retryable(f)))
```

The order is load-bearing: `retryable` inside `time_bounded` so the timeout
covers *all* attempts (otherwise 3 × 90s silently becomes 270s), and `traced`
outermost so one span covers the retries.

`retryable` only retries errors whose class says `retryable = True`
(`app/agents/errors.py`). The same classification feeds Temporal's
`non_retryable_error_types`, so one taxonomy governs both layers.

Other decorators: `@register_agent(role)`, `@builtin_hook` (existing engine),
`@workflow.defn` / `@activity.defn` / `@workflow.signal` / `@workflow.query`.

---

## 5. Ports (abstract classes)

| Port | Implementations | Default |
|---|---|---|
| `LLMProvider` | `GatewayLLMProvider` (MLflow AI Gateway, httpx), `StubLLMProvider` | **stub** |
| `ToolInvoker` | `HttpToolInvoker`, `DescribeOnlyToolInvoker` | **describe-only** |
| `EventSink` | `Queue`, `Composite`, `Collecting`, `Persisting`, `Null` | — |
| `DurableRunner` | `LocalRunner`, `TemporalRunner` | **local** |
| `BaseAgent` | Planner / Executor / Critic | — |

The **stub provider is a first-class implementation, not a test mock**: it
produces structurally valid plans and critiques, so the graph, revision loop,
hook pipeline, persistence and SSE contract all run end-to-end with no
credentials. That's the difference between a runtime you can regression-test and
one you can only smoke-test in staging.

`DescribeOnlyToolInvoker` is the default because this codebase has a standing
invariant that registry rows are metadata, never stored code. It marks every
result `simulated=True` — a silently-faked tool result is worse than none.

---

## 6. Durability

| | `LocalRunner` | `TemporalRunner` |
|---|---|---|
| Token streaming | ✅ (direct) | ✅ (via the Redis relay) |
| Survives restart | ❌ | ✅ |
| HITL pause | ❌ | ✅ (signal, up to 3 days) |
| Retry policy | in-node only | + activity-level |

**Interactive chat runs through Temporal too** when `TEMPORAL_ENABLED=true`
(the docker-compose default). It used to be pinned to `LocalRunner` via
`prefer_local=True`, because Temporal has no push stream from an in-flight
activity — `TemporalRunner.stream()` polls the workflow's `status` query about
once a second, which is far too coarse for chat.

That is now solved by fanning in two sources rather than downgrading the UX:
the Redis channel `PostgresEventSink` publishes to carries live tokens and
step progress, while `runner.stream()` still supplies `RUN_START`, phase
transitions, and the authoritative final `RUN_END`. See
`services/agent_runner.py::_stream_events` and `README_CHANGES.md`.

Only one side may create the `agent_runs` row: for a durable run the
workflow's own `persist_run_start` activity owns it (it stamps `workflow_id`),
so `agent_runner.py` skips its direct `create_run` call. Creating it on both
sides strands `workflow_id` at `NULL` and silently breaks HITL signalling.

The workflow runs the **whole graph as one activity**, not one activity per
node. Per-node activities would force the routing logic to be reimplemented in
the workflow and kept in sync with `graph.py`, while LangGraph's checkpointer
already provides within-run resumability. Temporal's job is the envelope:
retry, time-bound, keep visible, and pause for a human.

```bash
docker compose up      # temporal + temporal-ui + agent-worker start with everything else
```

There are no compose profiles — every service starts by default, and both
`TEMPORAL_ENABLED=true` and `AGENT_CHECKPOINTER=postgres` are already the
compose/`.env.example` defaults, so runs route through the durable envelope
out of the box. The class-level fallbacks in `app/core/config.py` stay
`False`/`memory` so the test suite never reaches for a Temporal server.

---

## 7. Persistence

Two separate stores, on purpose:

- **LangGraph checkpoints** (`AsyncPostgresSaver`) — opaque resume state, keyed
  by `thread_id`, owned by the library and created by its own `setup()`.
  Deliberately outside Alembic: managing a third party's schema means every
  upgrade of that package becomes a hand-written migration.
- **`agent_runs` / `agent_run_steps`** (migration `0015`) — the queryable audit
  trail for the Observatory. Grain is the *node*, so "did revising actually
  help" is answerable.

Checkpointing degrades to in-memory with a warning if Postgres can't be
provisioned. A chat endpoint that 500s because *durability* is unavailable
trades a working degraded feature for a broken one.

---

## 8. Configuration

**Deployment** settings (`app/core/config.py`): `AGENT_LLM_PROVIDER`,
`AGENT_LLM_GATEWAY_URL`, `AGENT_CHECKPOINTER`, `TEMPORAL_*`.

**Per-run** settings (`agents.runtime_config` JSON → `AgentRuntimeConfig`):
`max_revisions` (2), `max_replans` (1), `max_plan_steps` (8), `node_timeout_s`,
`enable_critic`, `critic_complexity_threshold` (risk-gated Reflexion),
`execute_tools` (off), `stream_tokens`.

Split so a tenant admin can tune budgets without being able to repoint the model
gateway. A malformed `runtime_config` yields defaults rather than a 500.

---

## 9. Hook compatibility

All ten lifecycle stages fire where they did before; every existing Hook row
keeps working. The improvement: `PreToolUse` now fires per *real* activation the
agents chose, where the stub fired it once against a hardcoded "first attached
tool".

One honest limitation, documented at `_ToolGateSink`: the gate observes the
`tool_call` event asynchronously, so a `Deny` records and surfaces the denial but
does not roll back a call already in flight. Fine while `execute_tools=false`
(nothing leaves the process); for real tool execution the gate belongs inside
`ToolInvoker.invoke`, where it can genuinely refuse.

---

## 10. Tests

`tests/test_agent_runtime.py` (47) — state machine, reducers, plan validation
and repair, revision/replan loops, budget enforcement, risk gate, zero-crash
contract, retry classification, timeouts.

`tests/test_agent_runner_adapter.py` (12) — the SSE wire contract and hook
wiring the chat route depends on.

Driven by a `ScriptedLLMProvider` rather than mocks: the interesting behaviour
is conditional on model output, so the tests script that output and assert on
the resulting control flow. No database, no network, no Temporal.

```bash
pytest tests/test_agent_runtime.py tests/test_agent_runner_adapter.py
```
