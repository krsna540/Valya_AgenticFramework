# Agentic MVP

Lean starting point for the agentic AI platform: login/signup, registries for
agents/skills/tools/plugins/hooks/prompts, a streaming chat interface
(multi-agent compare, file attachments, markdown/code/artifact rendering,
citations, message branching), a lifecycle hook engine that actually executes
around every chat turn (guardrails, redaction, telemetry, halting), and a
BaseSkill contract for framework-blind, unit-tested agent business logic.

## Stack

- **Frontend**: React + Vite + TypeScript, plain CSS (no build-heavy UI kit)
- **Backend**: FastAPI + SQLAlchemy 2.0 + Alembic, JWT auth (bcrypt + python-jose),
  Server-Sent Events for chat streaming (no WebSockets)
- **Database**: PostgreSQL 16
- All three run in Docker via `docker-compose.yml`. Schema is managed by Alembic
  migrations, run automatically by the backend container on startup; the SQL
  file in `db/init/` only sets up database-level prerequisites (extensions).

## Run it

```bash
cp .env.example .env        # adjust secrets/ports if needed
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend docs (Swagger): http://localhost:8000/docs
- Postgres: localhost:5432 (user/pass/db from `.env`, default `agentic`/`agentic`/`agentic`)

First run: sign up a user at http://localhost:3000/#/signup, then create a
skill/tool/plugin/hook, create an agent that references them, and open Chat to
talk to it. Type `@` in the chat box to pick which agent(s) respond (pick more
than one to compare side by side), `/` to insert a saved prompt template.

> This sandbox environment has no Docker, so `docker compose up` itself was not
> run here — it needs to happen on your machine. Everything it builds on was
> verified directly: Python app imports with all routes registered, all 14
> SQLAlchemy tables compile to valid Postgres DDL, the SSE token-streaming
> generator and multi-agent fan-out/merge logic were smoke-tested standalone,
> the hook engine was exercised end-to-end with real asyncio (halt path, fault
> isolation including the on_error-re-raise fix, PII redaction, contextvar
> isolation across concurrent tasks), the skill contract has a real green
> pytest suite (19 tests), and the frontend passes `tsc` + a production
> `vite build`.

## Project layout

```
backend/
  app/
    core/       # settings, DB engine/session, JWT + password hashing
    models/     # SQLAlchemy models — see "Chat data model" below for Message/Conversation
    schemas/    # Pydantic request/response models
    api/routes/ # auth, agents, skills, tools, plugins, hooks, prompts, files, models, chat
    services/
      agent_runner.py  # swappable, streaming (async generator of SSE-shaped events), hook- and skill-aware
      thread.py        # message-tree traversal (active thread, siblings, branch switching)
      hooks.py         # lifecycle hook engine — HookManager, built-in handlers, scoping, contextvars
    skills/
      base.py          # BaseSkill contract — validation, str serialization, zero-crash containment
      catalog.py        # built-in skills (word_count, calculator, json_formatter) + SKILL_REGISTRY
      adapters.py        # framework adapters (OpenAI/Anthropic tool-calling JSON schema)
  alembic/      # migrations: 0001 initial schema, 0002 chat streaming, 0003 hooks, 0004 skill execution
  tests/        # pytest — framework-blind unit tests for the skill contract, run with `pytest`
frontend/
  src/
    api/        # fetch client + per-resource API wrappers; chat.ts has the SSE client
    context/    # AuthContext (JWT stored in localStorage)
    pages/      # Login, Signup, AgentsPage, SkillsPage, RegistryPage, HooksPage, PromptsPage, ChatPage
    components/
      chat/     # ChatComposer, MessageBubble, MarkdownRenderer, CodeBlock, CitationBadge/Drawer, BranchNav
db/init/        # one-time Postgres init script (extensions only)
docker-compose.yml
```

## Chat streaming architecture

React talks to FastAPI two ways, per the design spec this was built from:
config/auth/history/files over plain REST, and live chat tokens over **SSE
only** (no WebSockets, per explicit scope).

- `POST /api/v1/chat/conversations/{id}/messages/stream` opens a
  `text/event-stream` response and emits `status`, `stream_start`, `token`,
  `tool_call`, `stream_end`, `stream_complete` events — matching the event
  names the frontend listens for in `api/chat.ts`.
- The frontend uses `@microsoft/fetch-event-source` instead of the native
  `EventSource` API, because `EventSource` can't send an `Authorization`
  header and this app is JWT-bearer-authenticated.
- Multiple agents can respond to one message concurrently (split-screen
  compare): the backend runs one async generator per agent, merges their
  events through an `asyncio.Queue`, and tags every event with `agent_id` so
  the frontend routes tokens to the right column.

### Chat data model (branching / message tree)

`Message.parent_message_id` makes the conversation a tree, not a flat list.
Editing a user message or regenerating a response creates a **sibling**
(same `parent_message_id` + `agent_id`), not a child; exactly one sibling in
that group has `is_active_branch=True` at a time. Multi-agent responses to the
same user message are *not* alternatives — they're siblings with different
`agent_id`, rendered side by side. Full rationale is in
`backend/app/services/thread.py` and `backend/app/models/chat.py`.

The rendered "active thread" is a BFS walk that only follows
`is_active_branch=True` messages. Switching branches
(`PATCH /chat/messages/{id}/select-branch`) just flips that flag — old
branches stay in the database.

**Simplification**: the next user message after a multi-agent turn always
attaches under the *primary* agent's reply (the conversation's `agent_id`,
not `secondary_agent_ids`), so the thread has one deterministic backbone even
when several columns are visible. Secondary-agent replies are always leaves.

### Citations & tool calls

`agent_runner.py`'s stub fabricates citations only when the message has
attached files (referencing the uploaded filename), and fires a demo
`tool_call` event when the responding agent has at least one tool attached —
enough to exercise the citation badge/drawer and the tool-call UI without a
real retrieval pipeline wired in yet.

### Markdown/code rendering — one deviation from the spec

The spec called for `dompurify` sanitizing raw HTML from the model. Instead,
`rehype-raw` (which would let raw HTML into the render tree) is **not**
enabled, so `react-markdown` treats any HTML-looking text as inert plain
text — inherently XSS-safe with no extra library. `rehype-sanitize` is kept
as a defensive second layer in case raw-HTML support gets added later. This
is the current recommended pattern for this exact library combo; see the
comment in `frontend/src/components/chat/MarkdownRenderer.tsx`.

Artifact (`html`/`svg` code block) previews render in an `<iframe
sandbox="allow-scripts">` — scripts run, but the artifact can't reach the
parent app's cookies, localStorage, or DOM.

## Lifecycle hook engine

`backend/app/services/hooks.py` implements the full 10-stage lifecycle
taxonomy: `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
`PostToolUse.Success`, `PostToolUse.Failure`, `PreCompact`, `SubagentStart`,
`SubagentStop`, `Stop`, `Notification`. It's wired into the SSE endpoint in
`api/routes/chat.py` and the demo tool/skill calls in `agent_runner.py`, not
just defined and left unused — see `GET /api/v1/hooks/lifecycle-events` for
which stages have a real trigger point today (`wired: true/false`).

**Where each stage actually fires** — this is a lean, mostly-stub agent
runner, not a full coding-agent harness, so not every stage has a natural
trigger yet:

| Stage | Fires |
|---|---|
| `SessionStart` | once per new conversation, one pass per attached agent (`chat.py::create_conversation`) |
| `UserPromptSubmit` | per turn, on the raw incoming message — halting here cancels the whole turn |
| `PreToolUse` | per turn, before the demo tool call and before the skill invocation — halting here skips just that one action |
| `PostToolUse.Success` / `.Failure` | right after each tool/skill call (failure = a skill result starting with `SKILL_EXECUTION_ERROR`), and again on the assembled final message |
| `Stop` | once per turn, after the message is persisted — final audit/summary pass |
| `Notification` | the fault-isolation channel (any hook failure anywhere), plus fired explicitly whenever `UserPromptSubmit`/`PreToolUse` denies something |
| `SubagentStart` / `SubagentStop` | around each *secondary* agent's execution in a multi-agent split-screen turn — the closest thing this app has to subagents today |
| `PreCompact` | **not wired** — there's no context-window compaction in this stub runner. Hooks can still be registered against it (it's a valid `lifecycle_event`), they just never fire. Reserved for when a real, context-limited model is wired in. |

**Two handler families, deliberately different trust levels** (a `Hook` DB
row picks one via `handler_type`):

- **`python`** (the default, safe path) — `handler_key` picks a vetted,
  code-reviewed function from `BUILTIN_HOOKS` (`GET /api/v1/hooks/handlers`).
  No code is stored or `eval()`'d; `lifecycle_event` is derived from the
  catalog and validated to match. Shipped handlers: `guardrail_interceptor`
  (UserPromptSubmit, blocks banned phrases and halts), `pii_redactor` /
  `telemetry_observer` (PostToolUse.Success, redact/measure the outgoing
  message), `tool_allowlist_guard` (PreToolUse, blocks unlisted tool/skill
  names), `usage_logger` (Stop, structured summary log), `session_logger`
  (SessionStart), `subagent_metrics_logger` (SubagentStop),
  `error_alert_logger` (Notification).
- **`http` / `command` / `mcp_tool`** (real execution, opt-in) — `http` POSTs
  `{stage, data, context}` to a configured webhook; `command` runs a
  configured local script with that same payload on stdin; `mcp_tool` POSTs
  to a configured URL as a simplified MCP adapter (a plain HTTP call, **not**
  a spec-compliant MCP JSON-RPC/stdio client — building a full MCP transport
  was out of scope). **These three genuinely execute code or make network
  calls on this host, on behalf of whoever can create a Hook record — there
  is no sandbox, only a timeout and a `fallback_strategy`.** Treat write
  access to Hooks with `handler_type != "python"` as equivalent to shell
  access on this backend. See `backend/app/services/hook_handlers.py`'s
  module docstring for the full trust-boundary writeup.

**Return directives.** Every hook — python or custom — settles on one of five
outcomes: `Allow` (proceed), `Deny` (raises `HookHaltException`, caught either
at UserPromptSubmit — cancels the turn — or at PreToolUse — skips one action),
`Modify` (replaces the payload), `InjectContext` (merges data into
`HookContext.metadata`), `SilentLog` (logs, no behavior change). Python
handlers express this directly in code (return a value, or raise
`HookHaltException`); custom handlers return it as JSON
(`{"directive": ..., "data": ..., "context_updates": ..., "reason": ...}`),
uniformly interpreted by `_interpret_outcome()`.

**Static gate before any custom handler runs.** `execution_policy.blocked_keywords`
/ `.allowed_tools` are checked against the payload *before* an http/command/
mcp_tool handler is ever invoked (`hook_handlers.py::static_gate`) — this is
what lets a Hook block `rm -rf` without a network call or process spawn for
the common case, matching the YAML sample's `blocked_keywords` +
`return_directives.on_match` pattern.

**Three scopes, unchanged from the original design**:
- **Global** (`Hook.scope="global"`) — applies to every agent automatically,
  no attachment needed.
- **Agent** (`Hook.scope="agent"`) — only applies to agents it's attached to
  via the existing agent↔hook relationship.
- **Task** (`SendMessageRequest.hook_ids`) — extra hooks for one request only,
  never persisted.

**Thread safety**: each per-agent asyncio task in the SSE fan-out sets its own
`contextvars.ContextVar` (`current_hook_context`) — `asyncio.create_task`
snapshots the current context, so concurrent split-screen agent streams never
see each other's trace id/metadata, with no manual locking.

**Bugs fixed versus the reference design this was originally built from**
(kept from the earlier 4-stage version, still load-bearing): (1) a hook that
wants to genuinely halt raises `HookHaltException` rather than returning a
replacement value, so it actually skips generation instead of just feeding a
different string into it. (2) `HookManager.trigger_pipeline`'s fault-isolation
path dispatches to `Notification` from inside its own try/except that only
logs, so a broken Notification hook (or a Notification hook at all, by
design) can never crash the pipeline that triggered it. Verified with tests
that deliberately break a `Notification` hook and confirm the outer pipeline
still returns normally (`backend/tests/test_hooks.py`).

## Registry UI: side panels, not popups

Agents, Hooks, Skills, Tools, and Plugins all share one layout
(`.registry-layout` in `styles/index.css`): a list on the left, a persistent
detail panel on the right. Clicking a row loads it into the panel; "New"
opens a blank one. Create/Update/Delete all happen inline in that panel — no
modal dialogs for these five screens. Each panel has a Form/YAML toggle; YAML
mirrors the record's real shape (id, name, lifecycle_event/handler, metadata,
execution_policy, etc., matching the per-entry YAML template style) and is
generated client-side (`utils/yaml.ts`, via `js-yaml`) — the wire format to
the backend is still plain JSON, YAML is purely an editing/inspection view.
Skills' Skill Packages tab and the transient "Try it" skill tester keep
their own modal, since those are one-off actions rather than CRUD on a
registry record.

## Skill contract (BaseSkill)

`backend/app/skills/base.py` implements the Autonomous Skill System spec this
was built from: skills are orchestration-framework-blind units of business
logic, callable the same way whether the caller is this app's stub agent, a
future real LLM with function-calling, or a completely different framework.

**Contract**: every skill is a `BaseSkill` subclass declaring `name`,
`description`, and `input_schema` (a Pydantic model) — the mandatory metadata
triad — and implementing `_run(self, validated_args) -> Any`. Callers never
call `_run` directly; they call `execute(raw_args: dict) -> str`, which:
validates `raw_args` against `input_schema` before running anything (halts
immediately on failure), never lets an exception from `_run` escape (caught
and turned into a descriptive `SKILL_EXECUTION_ERROR ...` string an LLM could
parse and self-correct from), and always returns `str` — non-string results
get `json.dumps`'d before leaving the skill boundary.

**Same handler-key indirection as Hooks, same reason.** A DB `Skill` record
doesn't store or `eval()` code — it binds to a `handler_key` from a small,
code-reviewed catalog (`GET /api/v1/skills/handlers`), same pattern as
`Hook.handler_key`. Shipped skills: `word_count`, `calculator` (a hand-rolled
`ast`-based safe expression evaluator — not `eval()`, no code-execution
surface even though the input is untrusted chat text), and `json_formatter`.
Try one from the Skills screen's "Try it" button, which calls
`POST /skills/{id}/execute` — the same entrypoint an orchestration layer uses.

**Framework adapters** (`app/skills/adapters.py`): `to_openai_tool_schema()`
converts a skill's four public properties into an OpenAI/Anthropic
function-calling tool definition — the one concrete adapter shipped, since
it's what this project could actually use once `agent_runner.py` talks to a
real model. A CrewAI/AutoGen/LangGraph adapter would read the same four
properties into that framework's Tool class; not built here since this repo
doesn't depend on those packages and an untested adapter is dead code.

**Real unit tests, not just an import check**: `backend/tests/test_skills.py`
has 19 deterministic tests — success/validation-error/runtime-error paths for
each skill, a code-injection attempt against the calculator's safe evaluator,
a generic "never raises on garbage input" sweep across the whole registry,
the OpenAI adapter shape, and an AST-based check that the skill layer never
imports an agent framework package. Run them with:

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

**Logging, not print()**: skills log through `logging.getLogger("agentic_mvp.skills")`,
never `print()`. `app/main.py` explicitly configures the root logger to
stream to stderr on startup so this holds even before any request comes in.

## Skill import/export (config-only bundles)

`GET /skills/export`, `GET /skills/{id}/export`, `POST /skills/import` move a
`SkillBundle` JSON document — `schema_version`, `kind`, `exported_at`, and a
list of `{name, description, handler_key, config, is_active}` entries. No
code, ever. Import only succeeds per-entry if the *importing* system already
has that `handler_key` in its own built-in catalog (`SKILL_REGISTRY`) —
otherwise that entry is skipped with a reason (`SkillImportResult.skipped`),
not silently dropped or half-applied. This is how two installs that both
ship `word_count` share a tuned config for it; it cannot introduce a handler
that didn't already exist. UI: Skills page → Export / Export All / Import
buttons.

For sharing an actual new skill implementation (not just config for an
existing one), see Skill Packages below.

## Skill Packages (agentskills.io directory format)

A second way to package/share a skill, alongside config-only bundles above —
this one matches the open [Agent Skills
spec](https://agentskills.io/specification) exactly, so a skill built for
this app (or downloaded from anywhere following that spec) is a portable
directory:

```
skill-name/
├── SKILL.md          # required: YAML frontmatter + Markdown instructions
├── scripts/           # optional: executable code
├── references/        # optional: documentation
├── assets/             # optional: templates, resources
└── ...                  # any additional files or directories
```

**Upload is a zip of that directory** (`POST /skill-packages/upload`,
Skills page → Skill Packages tab). `app/skills/package_extract.py` extracts
it safely — rejecting zip-slip path traversal, zip bombs (checked against
`MAX_SKILL_PACKAGE_EXTRACTED_BYTES` before a single byte is written), archive
bombs by file count, and anything that isn't exactly one top-level directory
containing `SKILL.md`. `app/skills/package_spec.py` then parses and validates
the frontmatter against the spec's exact rules — `name` (≤64 chars, lowercase
letters/digits/hyphens, no leading/trailing/consecutive hyphens, must match
the directory name), `description` (1-1024 chars), optional `license`,
`compatibility` (≤500 chars), `metadata` (string map), `allowed-tools`.
Validation collects every violation at once rather than stopping at the
first, and unrecognized frontmatter fields warn instead of failing (forward
compatibility with future spec additions).

**Nothing here executes anything — deliberately.** Per the spec itself,
`scripts/` are meant to be run *by an agent that decides to*, during its own
tool use — not automatically by whatever system loaded the skill. This app's
`agent_runner.py` is still a stub with no real tool-calling loop (see its
module docstring), so there's genuinely no execution engine to build yet;
packages are storable, browsable (SKILL.md rendered, every file in
`references`/`assets`/`scripts` viewable), downloadable, and attachable to
Agents. This is the one skill-sharing path in this app that doesn't need a
trust-boundary writeup, because it doesn't cross one.

**Progressive disclosure, approximated.** The spec's three loading tiers —
metadata (~100 tokens, always resident), full SKILL.md body (loaded on
activation), and files (loaded on demand) — show up in `agent_runner.py`'s
stub reply: every attached skill package's name+description is always listed
in the capability note, and the first one's SKILL.md body is "activated" and
quoted, standing in for what a real tool-calling agent would do on its own
once one exists.

**Sharing**: `GET /skill-packages/{id}/download` re-zips the stored directory
byte-for-byte re-uploadable — distribution is "hand someone a file," same as
the config-only bundle model above, just directory-shaped and spec-compliant.

## Enterprise platform layer: Tenancy, Personas, Datasources, Projects

Six pillars sit on top of the registries above, turning this from a
single-tenant demo into the shape described in the project's original admin/
user-flow brief. All are real (DB models, migration 0008, CRUD routes,
frontend pages) except where explicitly called out as scaffolded below.

1. **User & Persona Management.** `Tenant` + `User.tenant_id`/`role`
   (`admin`/`member`) are the RBAC foundation — signup creates a brand-new
   tenant and makes the signing-up user its first admin; further users are
   admin-created via `POST /admin/users`, always inside that admin's own
   tenant (`app/api/routes/admin_users.py`). `Persona` (`app/models/persona.py`)
   stores the full 9-vector trait document (Core Objectives, Target
   Audience, Capabilities & Tools, Knowledge Domain, Guardrails &
   Boundaries, Tone & Voice, Personality Quirks, Interaction Style, Safety
   & Compliance) as JSONB, validated through `app/schemas/persona.py`'s
   `PersonaTraits` pydantic model; `UserPersonaMapping` binds a user to a
   persona, optionally scoped to one Project. Frontend: `PersonasPage.tsx`.
2. **Datasource & Data Lifecycle Management.** `Datasource`
   (`app/models/datasource.py`) covers all ten connector types from the
   brief (SharePoint, Confluence, REST, GraphQL, SQL, NoSQL, GitHub,
   GitLab, web crawl, file upload) with security classification tiers and
   chunking/embedding policy fields. **Scaffolded, not real:** `POST
   /datasources/{id}/connect` and `.../sync` are synchronous stub state
   transitions — no live OAuth2 handshake, no VPC tunnel, no crawler.
   Frontend: `DatasourcesPage.tsx`.
3. **Project Management.** `Project` (`app/models/project.py`) is the
   deployment wrapper: metadata, connected Datasources (`project_datasources`),
   mapped Users (`project_users`). Frontend: `ProjectsPage.tsx`'s Overview/
   Users/Datasources tabs.
4. **The Intelligence Layer.** Agents/Tools/Plugins/Hooks/Skills/
   SkillPackages all gained `tenant_id` (nullable — `NULL` = platform-shared
   catalog item, non-`NULL` = tenant-private) + `version` + `status` via
   `TenantScopedMixin` (`app/models/mixins.py`); writes are admin-only,
   reads are open to any tenant member (`registry_factory.py`, `hooks.py`,
   `skills.py`, `skill_packages.py`, `agents.py` all filter/gate the same
   way). `Tool` gained real `tool_type="mcp"` metadata columns
   (`mcp_transport`/`mcp_endpoint`/`mcp_command`/`mcp_tool_name`) — **the
   MCP client itself is scaffolded**: `app/services/mcp_client.py` validates
   config shape but never opens a real SSE/stdio connection (no MCP host to
   test against here; see that module's docstring for the real-client
   upgrade path). Hooks gained a `dlp_scrubber` builtin (UserPromptSubmit
   stage) as the "Pre-LLM DLP hook" the brief calls out specifically.
5. **Intelligence-to-Project Association.** `ProjectIntelligenceBinding`
   (`app/models/project_intelligence_binding.py`) is the matrix row: one
   `(project, component_type, component_id)` binding per attached Agent/
   Tool/Hook/Skill/Plugin/SkillPackage, with an optional pinned version.
   Frontend: `ProjectsPage.tsx`'s Intelligence tab (chip-toggle matrix per
   component type).
6. **Project Runtime & Freeze Preview.** `Project.execution_mode`
   (`event_driven`/`real_time_chat`/`scheduled`) + `schedule_cron` +
   `webhook_slug` describe the operational mode. `POST /projects/{id}/freeze`
   resolves the live topology (mapped users+personas, datasources,
   intelligence composition) via `_resolve_topology()` and stores it
   verbatim into `frozen_snapshot` (immutable from then on, even if the
   underlying registry items change later); `POST .../deploy` requires
   `frozen` status. **Scaffolded, not real:** deploying provisions nothing —
   no event listener actually starts, no cron scheduler runs, the webhook
   receiver (`POST /projects/{id}/webhook/{slug}`) just accepts and
   acknowledges a payload. Frontend: `ProjectsPage.tsx`'s Runtime & Freeze
   tab renders the exact "Freeze Screen" layout from the brief.

Real-time chat is wired to Project scope: `Conversation.project_id`
(nullable) plus `GET /projects/{id}/available-agents` restrict the chat
composer's agent picker to agents actually bound to that project once one
is selected (`ChatPage.tsx`'s project dropdown); omitting a project keeps
the original unscoped behavior.

## Notes on the chat / agent execution

`app/services/agent_runner.py` still returns a deterministic stub reply (not
a real model) so the full flow — login → pick agent(s) → stream a reply,
attach a file, branch, compare — works end-to-end without an LLM API key.
Swap the body of `stream_agent_response()` for a real provider's streaming
API when ready; the route layer doesn't need to change since it already
consumes an async generator of the same event shapes.

## What's intentionally simple (v1 scope)

- Tenant/Persona/Datasource/Project/RBAC now exist (see "Enterprise platform
  layer" above) but real external integrations are scaffolded: no live
  OAuth2 to SharePoint/Confluence/GitHub/GitLab, no real SQL/NoSQL tunnel or
  web crawler, no real MCP SSE/stdio client, no real cron scheduler or
  webhook listener behind a deployed Project.
- RBAC is two-tier (`admin`/`member`) and tenant-scoped — no finer-grained
  per-resource permissions (e.g. "can edit Hooks but not Agents") yet.
- No password reset, email verification, or refresh tokens — access tokens
  are long-lived (24h) bearer JWTs.
- Tool/Plugin `config` is a free-form JSON blob edited as raw text in the UI
  — no schema-driven config forms yet (Skills and Hooks moved off this
  pattern onto handler_key + a vetted implementation catalog).
- File uploads land on local disk (a Docker volume), not object storage —
  fine for one backend replica, won't survive a multi-instance deployment.
- No WebSockets — per explicit scope for this pass, only SSE. If a future
  feature genuinely needs bidirectional push (e.g. live voice), that's a
  separate connection, not a replacement for the chat stream.
- Sibling/branch metadata is fetched per user message with one request each
  (`GET /chat/messages/{id}/siblings`) — fine for short demo threads, worth
  batching into a single endpoint if thread lengths grow.
- Hooks can only bind to the built-in handler catalog, not arbitrary
  user-supplied code — deliberate (no `eval`, no RCE surface), not a
  temporary limitation. Adding a new hook behavior means adding a Python
  function to `hooks.py`, not a UI-only change.
- Task-specific hooks (`SendMessageRequest.hook_ids`) are wired through the
  API but have no picker in the chat composer UI yet.
- Skills can only bind to the built-in catalog too, same rationale as Hooks
  — 3 real skills ship (word_count, calculator, json_formatter); adding one
  means a Python class in `app/skills/catalog.py`, not a UI-only change.
- The stub agent only ever invokes the *first* skill attached to an agent
  (with that skill's own `example_args`, not real extracted arguments) —
  enough to prove the contract runs inside the chat flow, not real
  LLM-driven tool selection. Real argument extraction needs a real model.
- `Skill.config` (JSON, editable in the UI) is stored but not currently
  passed into `execute()` — the spec's contract is `execute(raw_args)` only,
  with no per-instance configuration concept. It's inherited structurally
  from the same `RegistryBase` Tools/Plugins use; harmless, just currently a
  no-op. Wire it through as a third `execute(args, config)` parameter (same
  shape as Hook's `ConfiguredHookFn`) if a skill ever needs instance-level
  settings (e.g. a per-record API key or default).
