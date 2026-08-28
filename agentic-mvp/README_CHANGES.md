# Changes — DAG step execution & full Temporal orchestration

Two workstreams, both in `backend/app/agents/` and `backend/app/services/`:

1. **[Plan steps now execute as a real DAG](#1-plan-steps-execute-as-a-real-dag)** — a step starts the moment *its own*
   dependencies finish, instead of waiting for a whole dependency "wave" to drain.
2. **[Every run goes through Temporal, with full event visibility](#2-every-run-goes-through-temporal)** — including interactive chat, which
   previously bypassed it entirely.

Neither workstream changes the SSE wire contract the frontend consumes, the
graph's routing, or any database schema. No migrations.

---

## 1. Plan steps execute as a real DAG

### What was actually there

The original request was to replace "sequential" step execution with a DAG.
Reading the code first turned up something different and worth recording: the
executor was **already** dependency-aware. `PlanStep.depends_on`, a topological
sort (`ordered_steps()`), level-batching (`execution_waves()`), and a
concurrency semaphore all existed.

The real defect was subtler. Execution ran in **level-synchronized waves** —
one `asyncio.gather` per dependency level, with a hard barrier between levels.
So a step blocked on any unrelated step that merely happened to sit at the same
dependency depth:

```
X (fast, no deps) ──> Y (depends on X)
Z (slow, no deps)            # unrelated to both

wave 0 = [X, Z]   <-- barrier: Y cannot start until Z finishes too
wave 1 = [Y]
```

`Y` waited on `Z` despite having no relationship to it. That is the latency a
wave barrier leaves on the table, and it grows with the slowest step per level.

### What changed

| File | Change |
|---|---|
| [`state.py`](backend/app/agents/state.py) | Extracted the level-assignment logic into a shared `_level_map()`; added `dependency_edges()` (cycle-safe direct deps per step) and `transitive_dependencies()` (full ancestor closure per step). `execution_waves()` kept, unchanged in behavior. |
| [`executor.py`](backend/app/agents/executor.py) | Replaced the wave-gather loop with per-step event-driven scheduling. |
| [`config.py`](backend/app/agents/config.py) | Updated the `max_step_concurrency` comment — it is now an overall ceiling, not a per-wave one. |

Each step gets an `asyncio.Event`. A step awaits only the events of its own
`depends_on`, then runs under the pre-existing semaphore. `max_step_concurrency`
still bounds total fan-out (and `1` still recovers fully-sequential behavior).

### The correctness question this raised

Once steps start independently, **two unrelated steps genuinely race**. The old
code took one `snapshot` of completed results per wave, which was safe precisely
*because* of the barrier. Carrying that pattern forward — snapshotting "whatever
has finished so far" — would have made each step's prompt depend on scheduling
timing: whichever of two independent steps happened to finish first would
nondeterministically leak into the other's context.

So a step's visible context is instead its **transitive dependency closure**,
computed once up front, before any task starts:

```python
visible_ids = ancestor_ids[step.id] | carried_ids
```

A step sees exactly what it depends on (plus results carried forward from an
earlier revision) — never a step that merely finished earlier in wall-clock
time. Deterministic regardless of timing, and strictly more correct than the
wave version, which showed a step everything at earlier depths whether it
depended on it or not.

Cycles keep the existing "don't crash, make best-effort progress" contract:
`_level_map()` drops the offending edge exactly where `ordered_steps()` already
falls back to declaration order, rather than raising.

### Verified

All 59 existing agent-runtime tests pass unchanged, including the concurrency-cap
test and the "sees its dependency but not its wave sibling" test. A scratch
timing test confirmed the fix — with `X→Y` fast and `Z` slow and unrelated:

```
x_start 0.000  z_start 0.000  x_end 0.051  y_start 0.053  y_end 0.064  z_end 0.501
```

`Y` completes at ~0.06s instead of waiting until ~0.50s for `Z`.

---

## 2. Every run goes through Temporal

### What was actually there

Also not greenfield. `backend/app/agents/durable/` already contained a complete,
working Temporal integration: client, `AgentRunWorkflow`, three activities, a
standalone worker entrypoint, human-in-the-loop signals, cancellation, and
`temporal` / `temporal-ui` / `agent-worker` services in `docker-compose.yml`.

Three specific gaps kept it from being what "run everything on Temporal" implies:

1. **Chat never used it.** `agent_runner.py` hardcoded `get_runner(prefer_local=True)`.
2. **Durable runs were less observable than chat runs.** The activity wired only
   `_HeartbeatSink`, so a Temporal run's events reached Temporal's own heartbeat
   history but never the `events` / `agent_run_steps` tables or Redis.
3. **No live relay existed**, so simply switching chat over would have downgraded
   token-by-token streaming to 1-second phase polling.

One thing that looked like a gap and wasn't: `compile_graph()` already falls back
to the process-wide `get_checkpointer()` when `AgentRuntime` is built with
`checkpointer=None` — which is how both runners build it. A retried Temporal
activity therefore **already** resumed LangGraph from its last completed
super-step once Postgres checkpointing was on. No per-node-activity redesign was
needed, and none was done.

### What changed

| File | Change |
|---|---|
| [`durable/activities.py`](backend/app/agents/durable/activities.py) | `execute_agent_graph` now builds `CompositeEventSink(_HeartbeatSink, PersistingEventSink, PostgresEventSink)` instead of heartbeat-only, so a durable run writes the same audit trail a chat run does. Imports are deferred into the function body, matching the file's existing convention. |
| [`event_persistence.py`](backend/app/agents/event_persistence.py) | The Redis-published payload now carries `phase` and `revision` alongside `type`/`data` — both are read by the `agent_status` wire mapping and were previously dropped. |
| [`core/redis_client.py`](backend/app/core/redis_client.py) | Added `subscribe_run_events(run_id)`, the live-relay counterpart to the existing `publish_run_event`. |
| [`services/agent_runner.py`](backend/app/services/agent_runner.py) | Chat routes through Temporal; added `_merge_event_streams` / `_stream_events`; `_to_wire_event` signature change; conditional run-row creation (see below). |

### How streaming survives the switch

Temporal has no push stream from an in-flight activity — heartbeat details go to
the service, not to a client. `TemporalRunner.stream()` therefore polls the
workflow's `status` query once a second, which is far too coarse for chat.

So a Temporal-routed chat turn fans in **two** sources:

| Source | Provides |
|---|---|
| `subscribe_run_events(run_id)` (Redis) | Live tokens, tool/skill calls, step progress — the granularity polling can't give |
| `runner.stream(...)` (Temporal) | `RUN_START`, phase transitions, human-review pauses, and the **authoritative** final `RUN_END` built from the completed `AgentRunResult` |

`_merge_event_streams` pumps both into one queue — the same fan-in shape
`api/routes/chat.py` already uses for multi-agent turns, reused rather than
reinvented.

There is no ambiguity about which `RUN_END` is the real one: the per-node
`RUN_END` from `graph.py::finalize_node` (which now also reaches Redis) never
sets `data["final"]`. Only the runners' own synthetic end-of-run events do, and
that flag is what `stream_agent_response` already keyed on.

Redis stays the *accelerator*, never the record — the durable Postgres write
happens alongside each publish, so a dropped relay message costs a UI update,
never correctness.

### A real bug this surfaced

Chat unconditionally called `agent_run_store.create_run(...)` before starting the
run. Once chat routes through Temporal, that races the workflow's own
`persist_run_start` activity — and `create_run` has **no update-on-conflict
path**, so the duplicate primary key hits a blanket `except Exception: return None`.

The consequence would have been silent and nasty: chat's row (with
`workflow_id=None`) wins, the workflow's insert no-ops, and `workflow_id` stays
`None` forever. That breaks the `if run.workflow_id:` branch in
[`api/routes/runs.py`](backend/app/api/routes/runs.py)`::decide_run` — meaning
**human-in-the-loop approval would silently stop working for every
Temporal-routed chat run**.

Fixed by letting whichever side owns the row create it:

```python
if runner.name != "temporal":
    agent_run_store.create_run(...)   # in-process path only
```

The durable path's own `persist_run_start` activity owns it otherwise — and it
stamps the real `workflow_id`.

The terminal write follows the same split: `TemporalRunner` exposes no `.runtime`
attribute, so `finalize_run` is correctly skipped for durable runs (the
workflow's `persist_run_finish` activity writes it), and the wire's
`revisions` / `critic_verdict` / `needs_human_review` are now read off the
authoritative final event instead of silently defaulting to zero.

### Configuration

Already correct — **no change was needed**. `docker-compose.yml` and
`.env.example` already default both flags for the `backend` and `agent-worker`
services:

```
AGENT_CHECKPOINTER=postgres      # LangGraph resumability across a restart
TEMPORAL_ENABLED=true            # route runs through the durable envelope
```

The class-level Python fallbacks in `app/core/config.py` (`memory` / `False`)
were **deliberately left alone**. There is no `backend/.env` and no `conftest.py`,
so the test suite inherits those fallbacks — flipping them would make every
chat-streaming test attempt a real network call to a Temporal server that does
not exist in CI, for no benefit, since real deployments already get `true` from
compose.

---

## Testing

```bash
cd backend && python -m pytest tests/ -q
```

**239 passed** (234 pre-existing + 5 new), ~14s.

New coverage:

| Test | Guards |
|---|---|
| [`test_durable_activities.py`](backend/tests/test_durable_activities.py) (2 tests) | The activity composes the persistence + episodic sinks, not just the heartbeat sink; tolerates absent tenant/project |
| `test_a_temporal_routed_run_does_not_pre_create_the_run_row` | Regression guard for the `workflow_id` bug above |
| `test_a_temporal_routed_run_reports_the_authoritative_final_fields` | Final fields come from the authoritative event when there is no `last_result` |
| `test_to_wire_event_maps_type_and_data_pairs_directly` | The wire allowlist is unchanged by the signature refactor |

`mypy` on all touched files reports the **same 9 pre-existing errors** as the
pre-change baseline — no new ones. (One round-trip was needed: the new
`_stream_events` generator initially yielded `str | None` for `phase` against a
`str` annotation.)

### Known unrelated failures

25 errors in `test_platform_routes.py` / `test_tenant_scope.py`, all
`CompileError: ... can't render element of type JSONB` — SQLite can't compile
Postgres `JSONB`. Pre-existing on `main`, untouched by this work.

### Not verified here

The end-to-end durability proof needs a running stack and was **not** run:

```bash
docker compose up
```

Then: send a chat message → confirm a workflow appears in the Temporal UI
(`localhost:8080`) keyed to the run id → confirm tokens still stream live →
confirm `events` / `agent_run_steps` gain rows → **stop the `agent-worker`
container mid-run** and confirm Temporal retries on the next worker and the run
completes from where it stopped.

That last step is the actual "restart where it stops" proof.

---

## Deliberately out of scope

- **Per-step Temporal activities** — unnecessary, since the existing
  single-activity design already resumes at the LangGraph super-step level.
  Splitting further would duplicate routing logic that `activities.py` explains
  avoiding.
- **A standalone `app/stream.py`** — referenced in some docstrings but never
  built. The relay lives in `agent_runner.py`, which already owns chat's SSE
  translation.
- **`Settings` class-default changes** — see [Configuration](#configuration).
