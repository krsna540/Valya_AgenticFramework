"""Skill parsing/extraction utilities for this app's canonical folder format
(SKILL.md + skill.json + references/ + scripts/ + assets/) — see
app/models/skill.py and docs/SKILL_STANDARD.md.

This package used to also hold a handler_key-bound BaseSkill/SKILL_REGISTRY
catalog (app/skills/base.py, app/skills/catalog.py, app/skills/adapters.py)
— a fixed, code-reviewed set of Python implementations a DB-backed Skill row
could bind to and actually execute. That system was retired: the folder
format above is now the only way a skill is defined in this app, and it is
never executed by the platform (see app/api/routes/skills.py's module
docstring for the full rationale).
"""
from app.skills.default_seed import seed_default_skill
from app.skills.package_extract import SkillPackageExtractError, extract_skill_zip, zip_package
from app.skills.package_spec import (
    ParsedSkillJson,
    ParsedSkillMd,
    SkillPackageValidationError,
    parse_and_validate_skill_json,
    parse_and_validate_skill_md,
)

__all__ = [
    "SkillPackageExtractError",
    "extract_skill_zip",
    "zip_package",
    "ParsedSkillJson",
    "ParsedSkillMd",
    "SkillPackageValidationError",
    "parse_and_validate_skill_json",
    "parse_and_validate_skill_md",
    "seed_default_skill",
]
