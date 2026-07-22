# Example skills

Three ready-to-upload skills in this app's canonical folder format. (There's
a fourth skill in this format, `text-case-converter` — it's not here because
it's not manual-upload-only: it's bundled inside the backend at
`backend/app/skills/defaults/text-case-converter/` and auto-seeded onto
every new tenant at signup, via `app/skills/default_seed.py`, so a fresh
workspace's Skills page isn't empty on day one. Same folder format, just a
different source of truth since it has to be reliably present at runtime.)

```
skill-name/
├── SKILL.md          # Required: YAML frontmatter + Markdown instructions
├── skill.json        # Optional: config/manifest for triggers & hooks
├── references/       # Optional: static context, templates, styles
├── scripts/          # Optional: executable code (Python, Bash, JS)
└── assets/           # Optional: images, schemas, raw data assets
```

These were previously the three platform-executed handler_key skills in
`app/skills/catalog.py` (`word_count`, `calculator`, `json_formatter`)
before that system was retired — kept here as real, working examples of the
new format rather than lost. Each `scripts/*.py` is a genuine, runnable CLI
tool; none of it is executed automatically by this app. See
`docs/SKILL_STANDARD.md` for the full convention and rationale.

## Uploading one

Zip a skill's folder (the folder itself must be the zip's single top-level
entry) and upload it via the Skills page, or `POST /api/v1/skills/upload`:

```
cd example_skills/word-count && zip -r ../word-count.zip . -x '*.DS_Store'
```

## Skills

- **word-count** — counts words/characters in a block of text.
- **calculator** — evaluates a restricted arithmetic expression safely (no
  `eval()`; a hand-written AST walker permitting only numbers and
  `+ - * / % **`).
- **json-formatter** — pretty-prints/sorts a raw JSON string.
