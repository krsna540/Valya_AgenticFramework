# KN_Valya — Agent Runtime Architecture (Admin Configuration + User Execution)

> **Status — FROZEN as of 2026-07-02.** Companion to `ARCHITECTURE.md` (admin flow, frozen 2026-07-02). All decisions in §8 (Locked Decisions), the registry/config/dashboard design (§4–§6), the user execution flow (§7), and Appendices A–B are locked. Post-freeze changes require an ADR (Architecture Decision Record) and a version bump on this document — same discipline as `ARCHITECTURE.md`. This freeze resolves the "agent authoring UI" item the frozen admin table lists as a post-freeze deferral; `ARCHITECTURE.md` has been updated to point here. **All agent/tool/skill/persona/hook configuration lives in the Admin flow; the User flow is execution-only**, operating strictly within what an admin has enabled and frozen for that project.
>
> Items explicitly out of scope for this freeze are listed in §15 (Post-Freeze Deferrals) — revisit only via ADR.
>
> **Superseded by `docs/KN_Valya_Complete_Architecture.md`.** That file is the consolidated reference going forward, including **ADR-002 (2026-07-05)**: the agentic memory backend (decision #9 below) changes from Mem0-default to memU-default, Mem0 retained as a pluggable adapter alongside Zep/Graphiti. This file is kept for historical context of the pre-merge content and is not updated further — read the complete-architecture doc for anything memory-related.

Every architectural choice is backed by a cited source in **Appendix B**. Nothing here is asserted on vibes.

---

## 0. Relationship to the Frozen Admin Flow

- Extends `agents` (table 18, `config_db_scripts/001_create_schema.sql`) and reuses the exact versioned/draft/active/deprecated lifecycle already locked for `pipelines` (`ARCHITECTURE.md` decision #4, §5.5).
- Reuses the existing datasource→project attachment flow (`ARCHITECTURE.md` §5.4) as the upstream step in one continuous admin journey: **onboard datasources → attach to project → enable agents/tools/skills/personas for that project (new) → freeze → grant role access (new) → users execute.**
- Retrieval Service, Qdrant knowledge-base collections, and the ingestion pipeline are untouched.

---

## 1. Functional Split — Admin Configures, Users Execute

The core redesign. Registries (agent/persona/tool/skill/hook) now have one clear owner:

| Responsibility | Owner | Where |
|---|---|---|
| Define agent skeletons (tools, hooks, memory policy, planning strategy) | Tenant/project admin | Admin — Agent & Registry Console |
| Define personas (prompt + data scope + tool allowlist) | Tenant/project admin | Admin — Agent & Registry Console |
| Register native tools + internal MCP servers | Tenant admin | Admin — Agent & Registry Console |
| Author/approve skills (incl. feedback-loop candidates) | Project admin | Admin — Agent & Registry Console |
| Configure hooks (guardrail bindings) | Tenant admin | Admin — Agent & Registry Console |
| Select which agents/personas/tools/skills apply to a project | Project admin | Admin — Project Agent Configuration |
| Map roles to allowed agents/personas/tools | Project admin | Admin — Project Agent Configuration |
| Freeze a project's agent configuration (v1, v2, ...) | Project admin | Admin — Project Agent Configuration |
| View usage stats + quality metrics, per item and per project | Tenant/project admin | Admin — Agent Observatory (dashboard) |
| Approve/reject feedback-loop prompt optimizations and candidate skills | Project admin | Admin — Agent Observatory (dashboard) |
| Pick project, agent, persona, language; run agent; give feedback | End user | User flow — execution only |

A user's `GET /agents?project={p}` call (`ARCHITECTURE.md` §7.1) now returns strictly the subset in that project's **active** (frozen) configuration, further filtered by the user's role — not the tenant's full registry. This tightens that endpoint's semantics without touching any locked admin-flow row. Users never create, modify, or enable a registry item.

---

## 2. System at a Glance

```
┌─────────────────────────────── ADMIN — CONFIGURATION PLANE ───────────────────────────────┐
│                                                                                              │
│  Agent & Registry Console                    Project Agent Configuration                    │
│  ┌────────────┬────────────┬─────────────┐   ┌──────────────────────────────────────────┐  │
│  │ Agent reg. │ Persona    │ Tools reg.   │   │ Select enabled: agents[] personas[]        │  │
│  │ (skeleton  │ registry   │ (native+MCP, │   │ tools[] skills[]  (from tenant registry)   │  │
│  │ + prompt_  │            │ internal)    │   │ Role → allowlist mapping (role_permissions)│  │
│  │ ref)       │            │              │   │ Draft → Dry-run/Preview → PROMOTE (freeze) │  │
│  ├────────────┼────────────┼─────────────┤   │ → previous version deprecated               │  │
│  │ Skills reg.│ Hooks reg. │              │   │  = project_agent_configs (versioned)         │  │
│  │ (incl.     │            │              │   │                                              │  │
│  │ candidates)│            │              │   │                                              │  │
│  └────────────┴────────────┴─────────────┘   └──────────────────────────────────────────┘  │
│                                                                                              │
│  Agent Observatory (dashboard)                                                               │
│  ┌────────────────────────────────────────────────────────────────────────────────────────┐│
│  │ Stats: enablement count, invocations, error rate, p95 latency, cost (usage_ledger)       ││
│  │ Quality: RAGAS, RLC, persona-consistency, feedback rate, eval-regression history          ││
│  │ Approval queue: prompt-optimization candidates, skill candidates (feedback loop, §10)     ││
│  └────────────────────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────┬───────────────────────────────────────────────┘
                                                 │ freeze/promote → active project_agent_config
                                                 ▼
┌─────────────────────────────── USER — EXECUTION PLANE ────────────────────────────────────┐
│  React UI: project picker → agent picker (frozen subset only) → persona → language → chat   │
│                                                  │ HTTPS/JWT (tenant_id, user_id, groups[])   │
│                                                  ▼                                           │
│  Agent Gateway (FastAPI): RBAC check against role_permissions (admin-configured, read-only    │
│  here) · rate-limit check · session bootstrap                                                │
│                                                  ▼                                           │
│  Temporal (durable envelope — long tasks, HITL pauses, retries)                              │
│                                                  ▼                                           │
│  LangGraph Runtime (per session)                                                             │
│    Hooks: SessionStart → PreAgentCall → PreToolUse → [tool] → PostToolUse → PostAgentCall     │
│    → ... → SessionEnd                                                                        │
│    Planning: ReAct | Plan-and-Execute | ReWOO | LLM Compiler | Reflexion (risk-gated)          │
│    Topology: Supervisor + parallel workers (complexity-gated fan-out)                          │
│       ↓                    ↓                   ↓                    ↓                       │
│  Tools registry        Skills registry      Agentic memory       Retrieval Service            │
│  (read-only lookup)    (read-only lookup)   (Mem0/Qdrant,        (existing, §7.3               │
│                                              CoALA-mapped,        ARCHITECTURE.md)              │
│                                              pluggable)                                        │
│                                                  ↓                                           │
│  MLflow 3.10 (Tracing, Evaluation, Prompt Registry, AI Gateway) — OTel-native, GenAI            │
│  semantic conventions ── rollup ──► usage_ledger + feedback (Postgres) ──► Agent Observatory   │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The dashed boundary matters: everything above the line is admin-authored config; everything below reads that config but never writes it.

---

## 3. Component Inventory

| Component | Role | Tech | Owner |
|---|---|---|---|
| Agent & Registry Console | CRUD for agents/personas/tools/skills/hooks | React admin UI + FastAPI | Admin |
| Project Agent Configuration | Select/bind registry items to a project, role mapping, freeze | React admin UI + FastAPI | Admin |
| Agent Observatory | Usage stats, quality metrics, approval queue | React admin UI, MLflow-backed | Admin |
| Agent Gateway | AuthN/RBAC/rate-limit entry point for chat | FastAPI | Backend (User-facing) |
| Durable envelope | Long-running agent tasks, HITL pauses, retries | Temporal (reused from ingestion) | Backend |
| Reasoning runtime | Per-session graph execution, checkpointing, streaming | LangGraph | Backend |
| Hooks layer | Deterministic guardrail/observability injection | Custom middleware, framework-independent | Backend |
| Agentic memory | Working/episodic/semantic/procedural (CoALA-mapped) | Mem0 default on Qdrant, pluggable adapter | Backend |
| Prompt management | Versioned prompt content, alias-based instant rollout | MLflow Prompt Registry | Admin authors, backend reads |
| Observability | Tracing, evaluation, GenAI OTel export | MLflow 3.10 | Backend, surfaced in Admin |
| Access control | Role → permission → allowlist(agents, personas, tools) | Simple RBAC (Sandhu model), no ABAC | Admin authors, backend enforces |
| Rate limiting | Token-bucket per user/project/tenant | Redis, fed by metering events | Backend |
| Metering | Multi-dimensional usage attribution, chargeback source of truth | Postgres `usage_ledger` + Redis counters | Backend, surfaced in Admin |
| Feedback loop | Signal collection → prompt/memory/skill improvement | MLflow GEPA optimizer + rollup job | Backend generates, Admin approves |
| Multi-org marketplace | Cross-org agent publish/discover, A2A, sandboxing | — | **Deferred** |

---

## 4. Admin — Agent & Registry Console

Tenant-scoped CRUD, one screen per registry, all following the same versioned/immutable-per-version discipline as `pipelines`:

| Registry | Admin actions | Notes |
|---|---|---|
| **Agent registry** | Create/edit skeleton (tools, hooks, memory policy, planning strategy), point `prompt_ref` at an MLflow Prompt Registry entry, version, activate/deprecate | Skeleton changes require a new version (session-pinned); prompt content inside an already-enabled agent can update immediately via MLflow alias without a new skeleton version or project refreeze |
| **Persona registry** | Create/edit (`prompt_ref`, `data_scope`, `tool_allowlist`), version | Reusable across multiple agents/projects |
| **Tools registry** | Register native functions; register internal MCP servers (capability manifest, connection info); semantic index over tool descriptions | No public MCP registry reach — internal catalog only |
| **Skills registry** | Author skills directly, or review/approve candidate skills surfaced by the feedback loop (§10) | Candidate → active promotion requires explicit admin approval, never auto-published |
| **Hooks registry** | Configure hook bindings (matcher pattern → action) | Tenant-wide by default; project-level overrides allowed |

---

## 5. Admin — Project Agent Configuration (the freeze workflow)

The new binding layer connecting tenant-wide registries to a specific project — the exact analog of the existing **pipeline binding** pattern (`(project, datasource, doc_type) → pipeline`, `ARCHITECTURE.md` §5.5), applied to agents:

**`(project) → {enabled agents[], personas[], tools[], skills[]} + role_permissions`**, versioned.

### 5.1 Workflow

1. **Draft** — project admin selects, from the tenant's registries, the subset of agents/personas/tools/skills this project needs. A validation pass checks referential integrity: an enabled agent's skeleton must only reference tools/skills also enabled for the project.
2. **Role mapping** — admin assigns which project roles (from `project_memberships`) may use which agents/personas/tools, populating `role_permissions`.
3. **Dry-run / preview** — admin runs a test session as a given role/persona before promoting, same spirit as the Pipeline Editor's dry-run against a sample document.
4. **Promote (freeze v1)** — `status = 'active'`, `activated_at` stamped; the prior active configuration flips to `deprecated`. From this point, users see and can only invoke what's in the active configuration.
5. **Iterate** — a later change is a new draft → dry-run → promote cycle (`v2`, `v3`, ...). Prompt-content-only changes (via MLflow alias) don't require a new version.

### 5.2 Why versioned, not live-edited

Same reasoning as pipelines and agent skeletons: "which agents could this user access, under which role, on this date" must be answerable from an immutable record, not reconstructed from an edit log.

---

## 6. Admin — Agent Observatory (Dashboard)

New admin screen, sibling to the existing Run Observatory (`ARCHITECTURE.md` §5.8), for the agent runtime instead of ingestion. Pairs aggregate stats with quality/eval signal in one screen, per the enterprise agent-monitoring convention of not splitting operational and quality monitoring across separate tools.

### 6.1 Stats (availability + usage)

| Metric | Source | Grain |
|---|---|---|
| Enablement count (how many projects have this item active) | `project_registry_bindings` | Per agent/persona/tool/skill |
| Invocation count, active sessions | MLflow trace rollup | Per agent, per project |
| Error rate, p95 latency | MLflow trace rollup | Per tool/skill |
| Token/cost consumption | `usage_ledger` | Per agent/project/user (chargeback view) |
| Availability status | Registry tables (`active`/`deprecated`/`candidate`) | Per item |

### 6.2 Quality

| Metric | Source | Grain |
|---|---|---|
| Faithfulness, answer relevancy, context precision/recall | RAGAS via MLflow Evaluation (LLM-as-judge) | Per agent |
| Response Language Correctness (RLC) | Custom scorer | Per agent × language |
| Persona-consistency score (PersonaGym-style, multi-turn) | Custom scorer | Per persona |
| Tool-call accuracy / task-completion (τ-bench-style, end-state correctness) | Custom scorer against connector state | Per agent, tool-write-capable only |
| Feedback thumbs-up rate, citation-wrong rate | `feedback` table | Per agent/persona |
| Eval-regression pass/fail history | MLflow Evaluation, tied to prompt-optimization promotions | Per prompt version |

### 6.3 Approval queue

Where the feedback loop (§10) surfaces work for a human: pending GEPA-optimized prompt candidates awaiting an eval-gate + admin sign-off before their `production` alias moves, and pending candidate skills awaiting approval before entering the active Skills Registry. Keeps the self-improvement loop visible and admin-controlled rather than a silent background process.

---

## 7. User Flow (execution only)

1. User authenticates → JWT carries `tenant_id`, `user_id`, `groups[]`.
2. `GET /projects` (existing, filtered by membership).
3. `GET /agents?project={p}` — returns only the active `project_agent_configs` subset, filtered further by the user's role via `role_permissions`.
4. User picks agent, persona (same filtered list), language.
5. Chat proceeds: Temporal envelope → LangGraph runtime → hooks → tools/skills/memory/retrieval → MLflow tracing.
6. Feedback buttons write to `feedback`, feeding the Admin-side Agent Observatory and the feedback loop — the user generates signal, only an admin acts on it.

---

## 8. Locked Decisions

The following are the final agent-runtime contract, admin-side and user-side. Any implementation deviating from them is a bug, not a variant.

| # | Decision | Locked Choice | Reversibility |
|---|---|---|---|
| 1 | Reasoning framework | LangGraph — explicit state graph, checkpointing, streaming, interrupt/resume | Hard |
| 2 | Durable execution split | Temporal = outer task envelope; LangGraph checkpointer = inner reasoning loop | Medium |
| 3 | Multi-agent topology | Supervisor/orchestrator-worker only; debate/mixture-of-agents narrowly as a risk-gated verification step | Easy |
| 4 | Default planning pattern | ReAct; ReWOO/LLM Compiler for decomposable/parallel multi-tool turns; Reflexion risk-gated; ToT reserved for genuine multi-path search | Easy |
| 5 | Tool access pattern | Model-invoked, tools registry with semantic retrieval, not full-catalog context stuffing | Easy |
| 6 | Tool registry scope | Native + internal MCP servers only. No public MCP registry reach | Easy to expand later |
| 7 | Agent config split | Skeleton (version-pinned per session) vs. prompt content (MLflow alias, reflects immediately) | Easy |
| 8 | Memory taxonomy | CoALA-mapped: working=LangGraph state, episodic=Mem0, semantic=Mem0/Qdrant, procedural=Skills Registry | Medium |
| 9 | Memory backend | Mem0 on existing Qdrant, default; pluggable adapter for Zep/Graphiti per project | Easy |
| 10 | Memory organization | A-MEM-style structured/linked notes, not flat vectors | Easy |
| 11 | Language handling | No document translation; target-language generation instruction per-turn; RLC required eval metric | Trivial |
| 12 | Persona model | Prompt-level (MLflow alias) + data-scope narrowing + tool-allowlist subset; can only narrow access | Easy |
| 13 | Access control | **Simple RBAC** (Sandhu model) — role → static allowlist, enforced at `PreToolUse`/`PreAgentCall`. No ABAC for now | Easy to upgrade later |
| 14 | Rate limiting | Token-bucket per user/project/tenant, Redis, fed by metering events | Easy |
| 15 | Metering | Tag at `SessionStart`, propagate through hooks; MLflow trace = raw truth; `usage_ledger` = rollup/chargeback truth | Trivial |
| 16 | Observability | MLflow 3.10 — Tracing, Evaluation, Prompt Registry, AI Gateway | Hard |
| 17 | Feedback loop | Explicit + implicit signals → rollup → prompt optimization / episodic write-back / procedural candidates, all gated before promotion | Medium |
| 18 | Multi-org marketplace | Out of scope — see §15 | Deferred |
| 19 | **Configuration ownership** | **All registry CRUD and project-agent binding lives in Admin. User flow is execution-only** | Hard |
| 20 | **Project freeze mechanism** | `project_agent_configs`, versioned draft → dry-run → active → deprecated, mirrors pipeline binding exactly | Medium |
| 21 | **Dashboard** | Agent Observatory — stats + quality + approval queue, one screen, admin-only | Easy |

---

## 9. Agentic Memory — Detail

### 9.1 CoALA Mapping

CoALA (Sumers et al., 2023) is the organizing frame — Appendix B.4. Four memory types, each mapped to existing infrastructure:

| CoALA type | KN_Valya component | Backend |
|---|---|---|
| Working | LangGraph state, checkpointed | Postgres checkpointer (chunk text passed by reference only — never store retrieved payloads in graph state, per the write-amplification failure mode in Appendix B.9) |
| Episodic | Session transcripts + distilled insights (ExpeL/Reflexion-style) | Mem0 |
| Semantic | Long-term facts, preferences, persona history | Mem0 on Qdrant, collection namespace `mem_{tenant}_{project}` — separate from retrieval collections `project_{uuid}` |
| Procedural | Skills Registry, growable via feedback loop (Voyager-style) | Postgres |

### 9.2 Pluggable Backend Interface

```
write(memory_type, content, metadata) -> memory_id
search(query, memory_type, filters) -> [memory_note]
consolidate(scope) -> summary
```

Default: Mem0. A project needing temporal-fact reasoning can swap in Zep/Graphiti behind the same interface via `memory_policy.backend` in the agent YAML (configured in Admin — Agent & Registry Console) — no agent-code change. Precedent: MemEngine's unified memory-slot paradigm and LangGraph's own `BaseStore` abstraction.

### 9.3 Note Structure

Each semantic/episodic write follows an A-MEM-style structured note (context description, keywords, tags, links to related notes), and retrieval is scored by relevance **and** recency/importance (Generative Agents precedent), not cosine similarity alone.

---

## 10. Feedback Loop — Detail

Follows the four-stage loop from the self-evolving-agents survey (Appendix B.5): **signal collection → evaluation → update → gated redeployment**.

1. **Collect** — explicit (`feedback` table) + implicit (rephrase-after-answer, `PostToolUse` validation failure, HITL rejection), tagged with the same identifiers as metering.
2. **Evaluate** — periodic rollup job buckets feedback into (a) reranker tuning signal [existing, `ARCHITECTURE.md` §7.6], (b) a GEPA training set per agent/persona.
3. **Update** — prompt content via `mlflow.genai.optimize_prompts()` (GEPA); episodic memory via distilled insight write (not raw transcript); procedural memory via candidate skills from successful multi-tool sequences.
4. **Gated redeployment** — nothing promotes automatically. Optimized prompts pass an eval regression check; candidate skills require admin approval — both surfaced in the **Agent Observatory approval queue (§6.3)**, not a silent background process.

---

## 11. Hooks

| Hook | Fires | Role |
|---|---|---|
| `SessionStart` | Session bootstrap | Stamp metering/tracing identifiers, load persona + language + agent version |
| `PreAgentCall` | Before any subagent/handoff | RBAC allowlist check, language directive injection |
| `PreToolUse` | Before any tool/skill call | RBAC allowlist check, rate-limit check, ACL scoping, block/deny/rewrite/escalate |
| `PostToolUse` | After tool/skill returns | Citation-grounding validation, telemetry, feedback-signal capture on failure |
| `PostAgentCall` | After subagent/handoff returns | Plan-validity logging, duplication check |
| `OnError` | Any failure | Retry/escalate/dead-letter, mirrors ingestion DLQ pattern |
| `SessionEnd` | Session close | Memory write-back (episodic), metering finalization, feedback rollup trigger |

Hook bindings are admin-configured (§4); the hook contract itself is framework-independent, wrapping a LangGraph node call or a Temporal activity identically.

---

## 12. Access Control & Rate Limiting

- `project_memberships` (existing) gives role assignment.
- `role_permissions`: `(role, allowed_agent_ids[], allowed_persona_ids[], allowed_tool_ids[])` — **now explicitly authored by the project admin as part of the Project Agent Configuration freeze workflow (§5.1 step 2)**, not a separate standalone table users or backend processes populate independently.
- Enforcement is a set-membership lookup inside `PreToolUse`/`PreAgentCall` — no rule engine, no attribute evaluation.
- Upgradeable later: enforcement already lives at the hook layer, so swapping in ABAC/OPA/Cerbos is a hook-body change, not an architecture change.

Rate limiting: token-bucket per `(user, project, tenant)` scope in Redis, fed by the same tagged events that feed metering.

---

## 13. Metering

- Every span carries `{tenant_id, project_id, user_id, persona_id, agent_id, agent_version, session_id, feature}`, stamped at `SessionStart`, propagated through every hook.
- MLflow trace is the raw source of truth.
- Rollup job aggregates into `usage_ledger` (Postgres) — hourly for the Agent Observatory, daily as the chargeback source of truth.
- Redis counters (shared with rate limiting) give sub-second enforcement without waiting on the rollup.

---

## 14. Data Model Additions

Extends `config_db_scripts/001_create_schema.sql` table 18 (`agents`) and adds new tables. Sketch, not final DDL:

```
agents                     -- extend: add prompt_ref (MLflow URI), planning_strategy, memory_policy JSONB
personas                   -- id, tenant_id, project_id, name, prompt_ref, data_scope JSONB, tool_allowlist[], version
tools                      -- id, tenant_id, name, kind ('native'|'mcp'), schema JSONB, connection_info JSONB, version
skills                     -- id, tenant_id, project_id, name, spec, version, status ('candidate'|'active')
hooks                      -- id, tenant_id, hook_type, matcher_pattern, action_ref, version
role_permissions           -- role, allowed_agent_ids[], allowed_persona_ids[], allowed_tool_ids[]
project_registry_bindings  -- project_id, item_type ('agent'|'persona'|'tool'|'skill'), item_id,
                               item_version, enabled, bound_at, bound_by
project_agent_configs      -- project_id, version, status ('draft'|'active'|'deprecated'),
                               bindings_snapshot JSONB, role_permissions_snapshot JSONB,
                               activated_at, activated_by
usage_ledger                -- tenant_id, project_id, user_id, agent_id, agent_version, period,
                               tokens_in, tokens_out, tool_calls, cost
feedback                    -- (existing) extend with agent_id, agent_version, persona_id, session_id
```

`project_agent_configs` is the freeze artifact — the versioned snapshot, same pattern as `pipelines`. All tables follow the existing versioned-immutable-per-version discipline.

---

## 15. Post-Freeze Deferrals

- **Multi-org agent marketplace** — A2A protocol, signed Agent Cards, cross-org registry/discovery, publisher billing.
- **Sandboxing / isolation** — Firecracker microVMs, gVisor, third-party code execution isolation.
- **ABAC / policy engine** (OPA, Cerbos) — simple RBAC covers the current need; hook-layer enforcement is ready for this upgrade without an architecture change.
- **Public MCP registry reach** — internal tools registry only.

---

## Appendix A — Glossary

- **Skeleton vs. prompt content** — an agent's structural definition (tools, hooks, memory policy, planning strategy — version-pinned per session) vs. its behavioral prompt (system prompt, persona instructions — MLflow Prompt Registry alias, mutable without a new session).
- **Project Agent Configuration** — the versioned, freezable binding `(project) → {enabled agents, personas, tools, skills, role_permissions}`, the exact analog of pipeline binding applied to agents.
- **Freeze (v1, v2, ...)** — promoting a draft Project Agent Configuration to `active`; the only configuration users can execute against until the next promotion.
- **Agent Observatory** — the admin dashboard pairing usage stats with quality/eval metrics per registry item and per project, plus the feedback-loop approval queue.
- **CoALA memory taxonomy** — working / episodic / semantic / procedural.
- **Candidate skill/insight** — a feedback-loop-generated artifact awaiting eval-gate or admin approval before promotion to active/production status.
- **Hook** — a deterministic middleware interception point, independent of the underlying orchestration framework.

---

## Appendix B — Research Backing

### B.1 Reasoning & Planning Patterns

| Pattern | Citation | Finding |
|---|---|---|
| ReAct | Yao et al., 2022, [arXiv:2210.03629](https://arxiv.org/abs/2210.03629) | Interleaved reason+act reduces hallucination vs. pure CoT; +34%/+10% success on ALFWorld/WebShop |
| ReWOO | Xu et al., 2023, [arXiv:2305.18323](https://arxiv.org/abs/2305.18323) | Decoupled planning: 5x token efficiency, +4% accuracy on HotpotQA, robust to tool failure |
| LLM Compiler | Kim et al., 2023, [arXiv:2312.04511](https://arxiv.org/abs/2312.04511), ICML 2024 | Parallel DAG execution: 3.7x latency, 6.7x cost, ~9% accuracy improvement over ReAct |
| Reflexion | Shinn et al., 2023, [arXiv:2303.11366](https://arxiv.org/abs/2303.11366), NeurIPS 2023 | Verbal self-reflection stored in episodic buffer improves subsequent trials |
| Tree of Thoughts | Yao et al., 2023, [arXiv:2305.10601](https://arxiv.org/abs/2305.10601), NeurIPS 2023 | Proposer+evaluator branch/prune search; best for genuine multi-path problems |
| Plan-and-Solve | Wang et al., 2023, [arXiv:2305.04091](https://arxiv.org/abs/2305.04091), ACL 2023 | "Understand → plan → execute" beats zero-shot CoT on math/reasoning |

### B.2 Multi-Agent Topology

- AutoGen — Wu et al., 2023, [arXiv:2308.08155](https://arxiv.org/abs/2308.08155) — composable conversation patterns, grounding for supervisor message-passing.
- MetaGPT — SOP-encoded roles reduce hallucination in complex multi-step tasks.
- Multi-Agent Debate — Du et al., 2023; Mixture-of-Agents — Wang et al., 2024, [arXiv:2406.04692](https://arxiv.org/abs/2406.04692) — reserved for bounded verification steps, not default topology.
- Survey — Guo et al., 2024, [arXiv:2402.01680](https://arxiv.org/abs/2402.01680).

### B.3 Tool Use

- Toolformer — Schick et al., 2023, [arXiv:2302.04761](https://arxiv.org/abs/2302.04761) — self-supervised tool-call decision-making.
- Gorilla — Patil et al., 2023, [arXiv:2305.15334](https://arxiv.org/abs/2305.15334).
- ToolLLM/ToolBench — Qin et al., 2023, [arXiv:2307.16789](https://arxiv.org/abs/2307.16789) — retrieval-augmented tool selection outperforms full-catalog context stuffing at scale.

### B.4 Agentic Memory

- CoALA — Sumers et al., 2023, [arXiv:2309.02427](https://arxiv.org/abs/2309.02427) — working/episodic/semantic/procedural taxonomy.
- MemGPT — Packer et al., 2023, [arXiv:2310.08560](https://arxiv.org/abs/2310.08560) — OS-inspired tiered memory.
- Generative Agents — Park et al., 2023, [arXiv:2304.03442](https://arxiv.org/abs/2304.03442) — recency + importance + relevance-weighted retrieval.
- Mem0 — Chhikara et al., 2025, [arXiv:2504.19413](https://arxiv.org/abs/2504.19413) — benchmarked on LOCOMO; graph-variant available.
- A-MEM — Xu et al., 2025, [arXiv:2502.12110](https://arxiv.org/abs/2502.12110) — Zettelkasten-style dynamic note organization.
- MemEngine — Zhang et al., 2025 — unified memory-slot paradigm, pluggable storage/retrieval.

### B.5 Feedback Loop / Self-Improvement

- ExpeL — Zhao et al., 2023, [arXiv:2308.10144](https://arxiv.org/abs/2308.10144), AAAI 2024 — distilled insights, not raw transcripts.
- Voyager — Wang et al., 2023, [arXiv:2305.16291](https://arxiv.org/abs/2305.16291) — ever-growing skill library via iterative environment-feedback prompting.
- Self-Refine — Madaan et al., 2023, [arXiv:2303.17651](https://arxiv.org/abs/2303.17651), NeurIPS 2023.
- Self-Evolving Agents Survey — Fang et al., 2025, [arXiv:2508.07407](https://arxiv.org/abs/2508.07407) — signal→evaluation→update→redeploy framework.
- MLflow GEPA prompt optimization — `mlflow.genai.optimize_prompts()` ([MLflow docs](https://mlflow.org/docs/latest/genai/prompt-registry/optimize-prompts/)).

### B.6 Multilingual Generation

- QTT-RAG — Moon et al., 2025, [arXiv:2510.23070](https://arxiv.org/abs/2510.23070), ACL MRL 2025 — KN_Valya avoids the document-translation failure mode entirely by generating directly in the target language from English context.

### B.7 Persona

- Character-LLM — Shao et al., 2023, [arXiv:2310.10158](https://arxiv.org/abs/2310.10158), EMNLP 2023 — profile/experience-conditioning sufficient, no fine-tuning needed.
- RoleLLM — ACL 2024 Findings; PersonaGym — [arXiv:2407.18416](https://arxiv.org/abs/2407.18416) — persona-consistency evaluation methodology.

### B.8 Evaluation

- RAGAS — Es et al., 2023, [arXiv:2309.15217](https://arxiv.org/abs/2309.15217).
- AgentBench — Liu et al., 2023, [arXiv:2308.03688](https://arxiv.org/abs/2308.03688).
- τ-bench — Yao et al., 2024, [arXiv:2406.12045](https://arxiv.org/abs/2406.12045) — tool-agent-user interaction scored by end system-state correctness.

### B.9 Orchestration & Durable Execution

- LangGraph vs. Google ADK — production comparisons, 2026 — explicit state graph vs. code-driven workflow engine; LangGraph chosen for conditional-edge flexibility and lighter dependency footprint given non-GCP stack.
- LangGraph + Postgres checkpoint bloat at scale — documented write-amplification failure mode; mitigated by reference-only state, consistent with `ARCHITECTURE.md` §11 principle 1.
- Temporal for durable AI agent execution — deterministic workflows coordinating non-deterministic activities; industry adoption (OpenAI, Replit, Lovable, ADP) as of 2026.

### B.10 RBAC

- Sandhu, Coyne, Feinstein & Youman, "Role-Based Access Control Models," *IEEE Computer* 29(2), 1996 — foundational RBAC model, basis for §12.

### B.11 MLflow / Observability

- MLflow 3.10 GenAI docs — [mlflow.org/docs/latest/genai](https://mlflow.org/docs/latest/genai/) — Tracing (OTel-native, GenAI semantic conventions), Evaluation (LLM-as-judge), Prompt Registry (alias-based lifecycle management), AI Gateway.
- MLflow Prompt Registry lifecycle via aliases — [mlflow.org/docs/latest/genai/prompt-registry/manage-prompt-lifecycles-with-aliases](https://mlflow.org/docs/latest/genai/prompt-registry/manage-prompt-lifecycles-with-aliases/) — changes take effect immediately by loading prompts at runtime from the registry.

### B.12 Admin Governance & Catalog Patterns

- Google Cloud Agent Platform — Agent Identity, **Agent Registry**, and **Agent Gateway** as the enterprise pattern for centralized, trackable agent governance across internally-built and partner-sourced agents (2026 product architecture).
- Microsoft's governed agent stack — agents follow a **draft/live lifecycle**: builders iterate privately, publish when ready, published agents automatically inherit governance policy (version-controlled, auditable before deployment) — direct precedent for the draft → dry-run → promote (freeze) workflow in §5.
- Enterprise agent observability convention (Braintrust, Galileo, Groundcover, 2026 buyer guides) — dashboards should pair aggregate stats with per-agent quality/eval scores in one place — basis for combining §6.1 and §6.2 into a single Observatory screen.

---

*Frozen 2026-07-02. Post-freeze changes to any section require an ADR and a version bump on this document, per the discipline stated at the top.*
