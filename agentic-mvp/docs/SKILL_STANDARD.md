# agentic-mvp Skill / Plugin / Tool / Prompt / Datasource Manifest Standard

This document describes the manifest conventions this app's Skills, Plugins,
and Tools registries use for metadata (name, description, input schema,
permissions, rate limits, tags, exports). The shape is adopted from the
sibling `KnowledgeNexusClaw` project's `skills/SKILL_STANDARD.md` and
`plugins/<name>/manifest.yaml` format, so the two codebases describe
capabilities the same way and manifests are easy to eyeball side by side.

**One thing was deliberately NOT adopted: NexusClaw's `logic.py`-as-
executable-code and dynamically-imported hook modules.** Read
"What's different from NexusClaw" below before extending this — it explains
a real decision this project already made and reversed.

## 1. Skills — the canonical folder format

**As of the skill-system unification (2026-07-21), there is exactly one way
to define a Skill: a folder, uploaded as a zip.** The earlier two-system
design (a `handler_key`-bound `Skill`/`BaseSkill` catalog, plus a separate
"Skill Package" folder format) has been retired — see "What's different
from NexusClaw" below for why that's notable. `app/models/skill.py` is now
the only `Skill` model, and it is the same
[agentskills.io](https://agentskills.io/specification) directory shape
NexusClaw's `.skill` zips use:

```
my-custom-skill/
├── SKILL.md             # Required — YAML frontmatter + Markdown instructions
├── skill.json           # Optional — this app's own sidecar: triggers & hooks
├── references/          # Optional — static context, templates, styles
├── scripts/              # Optional — executable code (Python, Bash, JS)
└── assets/               # Optional — images, schemas, raw data
```

`SKILL.md` frontmatter (`name`, `description`, `license`, `compatibility`,
`metadata`, `allowed-tools`) is parsed and validated by
`app/skills/package_spec.py::parse_and_validate_skill_md`. The Markdown body
becomes `Skill.body_markdown` — the actual instructions an agent reads.

`skill.json` is optional and, when present, is validated by
`parse_and_validate_skill_json`:

```json
{
  "name": "word-count",
  "version": "1.0.0",
  "triggers": {
    "keywords": ["word count", "character count"],
    "intents": ["text_analysis"],
    "lifecycle_events": ["UserPromptSubmit"]
  },
  "hooks": ["dlp_scrubber"]
}
```

`name` must match `SKILL.md`'s name if both are present. `triggers.
lifecycle_events` is validated against `app.services.hooks.STAGES` (the same
10-stage taxonomy Hooks use) and `hooks` against
`app.services.hooks.BUILTIN_HOOKS` — the same no-stored-code invariant as
`Plugin.exports_hooks` below. Unknown top-level fields in `skill.json`
produce a warning, not a rejection (forward-compatible).

**`scripts/` are stored and browsable only — never executed by the
platform.** `GET /skills/{id}/files/{path}` lets a caller (or, eventually, an
agent with a real tool-calling loop) read a script's contents and choose to
run it; nothing in this app imports, `exec`s, or shells out to anything
inside an uploaded skill folder automatically. This was an explicit
decision, not an oversight — see "What's different from NexusClaw" below.

Adding one of the built-in example skills (`word-count`, `calculator`,
`json-formatter` — see `agentic-mvp/example_skills/`) means zipping that
folder and uploading it through `POST /skills/upload`, same as any other
skill; they carry no special-cased platform code anymore.

## 1b. The one auto-seeded skill

Every new tenant gets exactly one Skill for free: `text-case-converter`,
seeded at `POST /auth/signup` by `app/skills/default_seed.py`
(`seed_default_skill`). This is the one place in the app where a Skill row
gets created outside the normal upload endpoint — but it still goes through
the *same* `extract_skill_zip`/`parse_and_validate_skill_md`/
`parse_and_validate_skill_json` pipeline, by actually zipping the bundled
folder at `backend/app/skills/defaults/text-case-converter/` first. That
folder lives inside the backend package (not the top-level
`example_skills/`) specifically so it's guaranteed present at runtime
regardless of deployment layout. Seeding is idempotent (checks for an
existing `text-case-converter` Skill on the tenant first) and non-fatal
(extraction/validation failures are logged, never raised — seeding a
starter skill must never be able to break signup).

There is no other seed/bootstrap script in this app — signup is the only
"fresh install" moment, since tenant creation is a repeatable, per-customer
event, not a one-time global thing (see `app/api/routes/auth.py::signup`).

## 2. Plugins

A Plugin row (`app/models/plugin.py`) bundles references to already-vetted
Hooks/Tools plus advisory Skill names, mirroring NexusClaw's
`plugins/<name>/manifest.yaml`:

```json
{
  "name": "security_baseline",
  "version": "1.0.0",
  "description": "Common deny-first security primitives.",
  "exports_skills": [],
  "exports_hooks": ["guardrail_interceptor", "dlp_scrubber"],
  "exports_tools": [],
  "exports_commands": [],
  "requires_permissions": [],
  "requires_env": []
}
```

`exports_hooks` is validated at create/update time (`app/schemas/plugin.py`)
against the live `BUILTIN_HOOKS` catalog — declaring a hook export that
doesn't resolve to a real handler is a 422, the same "any malformed
component aborts the install" invariant NexusClaw's
`PluginRegistry.install()` enforces transactionally. `exports_skills` is
**advisory-only** now (like `exports_tools`/`exports_commands`/
`requires_*`) — there is no longer a `SKILL_REGISTRY` catalog to validate
skill names against, since Skills are folder-based, freeform names rather
than a fixed handler_key set.

## 3. Tools

A Tool row (`app/models/tool.py`) carries manifest.json-shaped metadata:
`input_schema`, `permissions`, `rate_limit_per_min`, `timeout_s`, `tags`.
For `tool_type="function"` this makes a Tool row self-describing enough to
hand to an LLM's tool-calling API directly, without a separate schema
lookup. For `tool_type="mcp"`, these are typically left empty since the MCP
host is the schema's source of truth (see `app/services/mcp_client.py`).

## 3b. Tools — MCP annotations

Tool (`app/models/tool.py`) also carries `annotations`, the Model Context
Protocol's tool-annotation hints (spec 2025-06-18):
`{title, readOnlyHint, destructiveHint, idempotentHint, openWorldHint}`.
These are client display/behavior hints only — never a security boundary,
never enforced server-side — matching the MCP spec's own guidance that a
client must treat them as untrusted unless the server itself is trusted.

## 3c. Plugins/Tools UI

`PluginsPage`/`ToolsPage` (frontend) are dedicated pages, not the generic
`RegistryPage` — the generic form (name/description/raw-JSON-config) can't
express exports/requires or tool_type/MCP fields/annotations. Any registry
entity with structured fields beyond name/description/config needs its own
page and its own `*Create`/`*Update`/`*Read` schemas (Tool and Hook already
did this before Plugin followed suit).

## 3d. Prompts

Prompt (`app/models/prompt.py`) is chat-style `messages` (role: system/user/
assistant + content with `{{variable}}` placeholders), a declared
`variables` contract (name/description/default/required), `model_params`
(model/temperature/max_tokens/top_p/stop) versioned together with the
prompt text, `tags`, and a `label` (production/staging/latest — Langfuse
"labels" / MLflow "aliases" convention). It's also now tenant-scoped via
TenantScopedMixin, closing a real gap: it previously had no `tenant_id` at
all, so any authenticated user in any tenant could edit any prompt.
`messages`/`variables` are cross-validated — every `{{var}}` referenced in
`messages` must be declared in `variables` (`app/schemas/prompt.py`).

## 3e. Datasources — Airbyte-style connector specs

`GET /datasources/connector-types` (`app/api/routes/datasources.py`) now
returns a real per-field spec per connector type — adopted from Airbyte's
`spec.json` convention: `{key, label, type, required, secret, options,
help_text}`, with `secret` matching Airbyte's `airbyte_secret` masking hint
(UI-only; this app never stores real secrets — see Datasource's class
docstring). Datasource also gained `auth_type` (oauth2/api_key/basic/
service_account/none) and `sync_mode`/`sync_schedule_cron`
(full_refresh/incremental, Airbyte's sync-mode vocabulary). The frontend
renders real typed inputs (text/number/checkbox/select/password) per
connector type instead of one raw JSON textarea.

## 4. What's different from NexusClaw, and why

NexusClaw's skills are filesystem folders (`skills/<name>/{SKILL.md,
manifest.json, logic.py}`) where `logic.py` is Python that gets imported and
executed (`async def run(args, ctx)`), and its plugins dynamically
`importlib`-import hook `*.py` modules from disk at install time. Both are
real, freshly-executed code paths outside code review.

This app built exactly that kind of feature once — **Community Skills**
(2026-07-14): upload a `.py` file, AST-scan it, then an explicit "enable"
step that actually executed it via `importlib.util.spec_from_file_location`
+ `exec_module`, registered separately from the (then-existing) Skill
handler catalog. Two sessions later, the user asked to remove it completely
(2026-07-16) — no reason given, but the lesson generalizes: a
previously-approved risky-execution feature was later fully reverted.

That lesson directly shaped the later skill-system unification
(2026-07-21): when asked to make Skills "structured exactly like
NexusClaw's folder format," the user was asked (and confirmed) two things
explicitly rather than by assumption — (1) retire the old `handler_key`-
bound `Skill`/`BaseSkill` catalog entirely, folder format becomes the only
Skill definition, and (2) `scripts/` inside an uploaded skill folder are
stored and exposed for an agent to read and run *if it chooses to*, never
executed by the platform itself. So today: **Skills are pure data** (parsed
`SKILL.md` + optional `skill.json`, no code path at all) — there is no
handler_key or catalog to route through, and adding a skill never touches
backend Python. **Hooks still resolve through `handler_key` into
`BUILTIN_HOOKS`**, and Plugin's `exports_hooks` still validates against
that same catalog — that invariant is unchanged. If a future request asks
to make Plugins/Hooks "more like NexusClaw," that specifically means
reintroducing `logic.py`-style dynamic code execution for those — worth
re-confirming with the user explicitly rather than assuming the trade-off
is wanted, same as before.
