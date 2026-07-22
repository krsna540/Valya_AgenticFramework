"""Parsing and validation for this app's canonical Skill folder format:

    my-custom-skill/
    ├── SKILL.md          # Required: YAML frontmatter + Markdown instructions
    ├── skill.json        # Optional: config/manifest for triggers & hooks
    ├── references/       # Optional: static context, templates, styles
    ├── scripts/          # Optional: executable code (Python, Bash, JS)
    └── assets/           # Optional: images, schemas, raw data assets

SKILL.md's frontmatter rules match https://agentskills.io/specification
exactly (this format started as a straight implementation of that spec —
see [[project_agentic_mvp_skill_packages]] in project memory):
  - name: 1-64 chars, lowercase unicode alphanumerics and hyphens only,
    no leading/trailing hyphen, no consecutive hyphens
  - description: 1-1024 chars, non-empty
  - compatibility: 1-500 chars if present
  - license: free text if present
  - metadata: map of string -> string
  - allowed-tools: a space-separated string (kept as-is, not parsed further
    — the spec marks this experimental and implementation-defined)

skill.json is this app's own addition on top of that spec — a machine-
readable sidecar for *triggers* (when a router/agent might want to surface
this skill) and *hooks* (which of this app's existing vetted Hook handlers
should be considered alongside it). Both are advisory metadata: this module
only parses and validates, it never executes anything, and neither
skill.json nor SKILL.md's own scripts/ directory crosses this app's no-
stored-code trust boundary. Per the spec, `scripts/` files are meant to be
run *by an agent that decides to*, not by the platform loading the skill;
this app has no real tool-calling agent loop yet (see
app/services/agent_runner.py's module docstring), so skills are, for now,
purely storable/browsable/attachable content. See
app/api/routes/skills.py's module docstring for the full rationale, and
docs/SKILL_STANDARD.md for the complete convention writeup.
"""
import re
from dataclasses import dataclass, field

import yaml

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_MAX_LEN = 64
DESCRIPTION_MAX_LEN = 1024
COMPATIBILITY_MAX_LEN = 500

FRONTMATTER_DELIMITER = "---"


class SkillPackageValidationError(Exception):
    """Raised with every violation collected (not just the first), so a
    single upload attempt tells the user everything wrong with SKILL.md at
    once instead of a frustrating one-error-at-a-time loop."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class ParsedSkillMd:
    name: str
    description: str
    license: str | None
    compatibility: str | None
    metadata: dict[str, str]
    allowed_tools: str | None
    body_markdown: str
    warnings: list[str] = field(default_factory=list)


_FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(.*?)\n---[ \t]*\n?(.*)$", re.DOTALL)


def _split_frontmatter(raw: str) -> tuple[str, str]:
    """Splits SKILL.md into (frontmatter_yaml, body_markdown). Raises
    SkillPackageValidationError if the file doesn't start with a `---`
    delimited frontmatter block, or that block is never closed."""
    text = raw.lstrip("﻿")  # tolerate a BOM
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        if not text.startswith(FRONTMATTER_DELIMITER):
            raise SkillPackageValidationError(["SKILL.md must start with YAML frontmatter delimited by '---'"])
        raise SkillPackageValidationError(["SKILL.md frontmatter is not closed with a second '---' line"])

    frontmatter_yaml, body = match.group(1), match.group(2)
    return frontmatter_yaml, body.lstrip("\n")


def parse_and_validate_skill_md(raw: str, dir_name: str | None = None) -> ParsedSkillMd:
    """Parses SKILL.md and validates every frontmatter rule from the spec.
    `dir_name`, if given, is checked against `name` (the spec requires the
    two to match) — pass None to skip that check (e.g. validating a
    standalone SKILL.md not yet placed in a directory)."""
    errors: list[str] = []
    warnings: list[str] = []

    frontmatter_yaml, body = _split_frontmatter(raw)

    try:
        frontmatter = yaml.safe_load(frontmatter_yaml) or {}
    except yaml.YAMLError as e:
        raise SkillPackageValidationError([f"SKILL.md frontmatter is not valid YAML: {e}"])

    if not isinstance(frontmatter, dict):
        raise SkillPackageValidationError(["SKILL.md frontmatter must be a YAML mapping (key: value pairs)"])

    # --- name ---------------------------------------------------------
    name = frontmatter.get("name")
    if not isinstance(name, str) or not name:
        errors.append("frontmatter 'name' is required and must be a non-empty string")
        name = ""
    else:
        if len(name) > NAME_MAX_LEN:
            errors.append(f"'name' must be at most {NAME_MAX_LEN} characters (got {len(name)})")
        if not NAME_PATTERN.match(name):
            errors.append(
                "'name' must contain only lowercase letters, numbers, and hyphens, "
                "must not start/end with a hyphen, and must not contain consecutive hyphens"
            )
        if dir_name is not None and name != dir_name:
            errors.append(f"'name' ({name!r}) must match the skill's directory name ({dir_name!r})")

    # --- description ----------------------------------------------------
    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append("frontmatter 'description' is required and must be a non-empty string")
        description = ""
    elif len(description) > DESCRIPTION_MAX_LEN:
        errors.append(f"'description' must be at most {DESCRIPTION_MAX_LEN} characters (got {len(description)})")

    # --- license (optional) ----------------------------------------------
    license_ = frontmatter.get("license")
    if license_ is not None and not isinstance(license_, str):
        errors.append("'license' must be a string if present")
        license_ = None

    # --- compatibility (optional) -----------------------------------------
    compatibility = frontmatter.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str) or not compatibility.strip():
            errors.append("'compatibility' must be a non-empty string if present")
            compatibility = None
        elif len(compatibility) > COMPATIBILITY_MAX_LEN:
            errors.append(f"'compatibility' must be at most {COMPATIBILITY_MAX_LEN} characters (got {len(compatibility)})")

    # --- metadata (optional) -----------------------------------------
    metadata = frontmatter.get("metadata")
    parsed_metadata: dict[str, str] = {}
    if metadata is not None:
        if not isinstance(metadata, dict):
            errors.append("'metadata' must be a mapping of string keys to string values")
        else:
            for k, v in metadata.items():
                parsed_metadata[str(k)] = str(v)

    # --- allowed-tools (optional) -----------------------------------------
    allowed_tools = frontmatter.get("allowed-tools")
    if allowed_tools is not None and not isinstance(allowed_tools, str):
        errors.append("'allowed-tools' must be a space-separated string if present")
        allowed_tools = None

    # --- unknown top-level keys: warn, don't fail (forward-compatible) ------
    known_keys = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    unknown = set(frontmatter.keys()) - known_keys
    if unknown:
        warnings.append(f"Unrecognized frontmatter field(s), ignored: {', '.join(sorted(unknown))}")

    if not body.strip():
        warnings.append("SKILL.md body (the Markdown after frontmatter) is empty")

    if errors:
        raise SkillPackageValidationError(errors)

    return ParsedSkillMd(
        name=name,
        description=description,
        license=license_,
        compatibility=compatibility,
        metadata=parsed_metadata,
        allowed_tools=allowed_tools,
        body_markdown=body,
        warnings=warnings,
    )


# --- skill.json (triggers & hooks manifest) ---------------------------------

# Imported lazily inside parse_and_validate_skill_json (not at module level)
# to avoid a skills -> services -> skills import cycle, same reasoning as
# app/schemas/plugin.py's local imports of SKILL_REGISTRY/BUILTIN_HOOKS.


@dataclass
class ParsedSkillJson:
    name: str | None
    version: str | None
    trigger_keywords: list[str] = field(default_factory=list)
    trigger_intents: list[str] = field(default_factory=list)
    trigger_lifecycle_events: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_and_validate_skill_json(raw: str, *, skill_md_name: str | None = None) -> ParsedSkillJson:
    """Parses and validates the optional skill.json sidecar.

    - `name`, if present, must match the skill's SKILL.md `name` (pass
      `skill_md_name` to check; skip the check by passing None).
    - `triggers.lifecycle_events` must each be one of the 10 lifecycle
      stages this app's Hook engine already defines (app/services/hooks.py
      STAGES) — advisory ("this skill is relevant around this stage"), not
      a real trigger wiring yet.
    - `hooks` must each resolve to a real, vetted handler_key in
      app.services.hooks.BUILTIN_HOOKS — same no-stored-code invariant as
      Plugin.exports_hooks (app/schemas/plugin.py). A skill.json can point
      at existing hooks; it can't ship its own hook code.
    """
    import json

    from app.services.hooks import BUILTIN_HOOKS, STAGES

    errors: list[str] = []
    warnings: list[str] = []

    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        raise SkillPackageValidationError([f"skill.json is not valid JSON: {e}"])

    if not isinstance(data, dict):
        raise SkillPackageValidationError(["skill.json must be a JSON object"])

    name = data.get("name")
    if name is not None:
        if not isinstance(name, str):
            errors.append("skill.json 'name' must be a string if present")
            name = None
        elif skill_md_name is not None and name != skill_md_name:
            errors.append(f"skill.json 'name' ({name!r}) must match SKILL.md 'name' ({skill_md_name!r})")

    version = data.get("version")
    if version is not None and not isinstance(version, str):
        errors.append("skill.json 'version' must be a string if present")
        version = None

    triggers = data.get("triggers") or {}
    if not isinstance(triggers, dict):
        errors.append("skill.json 'triggers' must be an object if present")
        triggers = {}

    def _string_list(value: object, field_name: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            errors.append(f"skill.json '{field_name}' must be a list of strings")
            return []
        return value

    keywords = _string_list(triggers.get("keywords"), "triggers.keywords")
    intents = _string_list(triggers.get("intents"), "triggers.intents")
    lifecycle_events = _string_list(triggers.get("lifecycle_events"), "triggers.lifecycle_events")
    unknown_stages = [s for s in lifecycle_events if s not in STAGES]
    if unknown_stages:
        errors.append(f"skill.json 'triggers.lifecycle_events' has unknown stage(s): {unknown_stages}")

    hooks = _string_list(data.get("hooks"), "hooks")
    unknown_hooks = [h for h in hooks if h not in BUILTIN_HOOKS]
    if unknown_hooks:
        errors.append(f"skill.json 'hooks' references unknown handler_key(s): {unknown_hooks}")

    known_keys = {"name", "version", "triggers", "hooks"}
    unknown_top = set(data.keys()) - known_keys
    if unknown_top:
        warnings.append(f"skill.json: unrecognized field(s), ignored: {', '.join(sorted(unknown_top))}")

    if errors:
        raise SkillPackageValidationError(errors)

    return ParsedSkillJson(
        name=name,
        version=version,
        trigger_keywords=keywords,
        trigger_intents=intents,
        trigger_lifecycle_events=lifecycle_events,
        hooks=hooks,
        warnings=warnings,
    )
