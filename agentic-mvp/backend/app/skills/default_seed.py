"""Seeds exactly one default Skill for a brand-new tenant, so a fresh
workspace's Skills page isn't empty on day one.

This app has no general seed/bootstrap script (see docs/SKILL_STANDARD.md
and project memory `project_agentic_mvp_skill_unification`) — tenant
creation happens once, per-customer, at `POST /auth/signup`
(`app/api/routes/auth.py`). That's the one natural "fresh install" moment
in this single-deployment, multi-tenant-by-data app, so that's where this
hooks in, rather than introducing a separate global startup-seeding
mechanism.

The seeded skill (`text-case-converter`) is bundled as real files under
`app/skills/defaults/` — shipped with the backend package, not a sibling
`example_skills/` directory — because it must be reliably present at
runtime inside the deployed container, independent of whether the repo's
top-level `example_skills/` folder is mounted/copied there.

Seeding goes through the *exact same* extract-and-parse pipeline as a real
`POST /skills/upload` (`extract_skill_zip` + `parse_and_validate_skill_md` +
`parse_and_validate_skill_json`) by actually zipping the bundled folder
first — this is deliberate: it means the seeded Skill row is constructed
by the same code path as any user-uploaded one, so there's no separate,
possibly-drifting "seed data" shape to keep in sync by hand.

Idempotent: checks for an existing Skill named `text-case-converter` on the
tenant before inserting, so re-running this (or a retried signup) is a
no-op. Failures are swallowed and logged rather than raised — seeding a
starter skill must never be able to break signup itself.
"""
import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.skill import Skill
from app.skills.package_extract import SkillPackageExtractError, extract_skill_zip, zip_package
from app.skills.package_spec import (
    SkillPackageValidationError,
    parse_and_validate_skill_json,
    parse_and_validate_skill_md,
)

logger = logging.getLogger(__name__)

_DEFAULT_SKILL_DIR_NAME = "text-case-converter"
_BUNDLED_SKILL_PATH = Path(__file__).parent / "defaults" / _DEFAULT_SKILL_DIR_NAME


def _skill_dir(skill_id: uuid.UUID) -> Path:
    return Path(settings.skill_packages_dir) / str(skill_id)


def seed_default_skill(db: Session, *, tenant_id: uuid.UUID, uploaded_by: uuid.UUID) -> Skill | None:
    """Creates the `text-case-converter` Skill for `tenant_id` if it doesn't
    already have one. Adds (does not commit) the new Skill row — the caller
    controls the transaction, matching how `signup()` already flushes the
    Tenant before committing everything together. Returns the new Skill, the
    already-existing one, or None if seeding failed (logged, not raised)."""
    existing = (
        db.query(Skill)
        .filter(Skill.tenant_id == tenant_id, Skill.name == _DEFAULT_SKILL_DIR_NAME)
        .first()
    )
    if existing is not None:
        return existing

    if not (_BUNDLED_SKILL_PATH / "SKILL.md").is_file():
        logger.warning("Default skill bundle missing at %s; skipping seed", _BUNDLED_SKILL_PATH)
        return None

    try:
        zip_bytes = zip_package(_BUNDLED_SKILL_PATH, _DEFAULT_SKILL_DIR_NAME)

        skill_id = uuid.uuid4()
        dest_dir = _skill_dir(skill_id)
        extracted = extract_skill_zip(
            zip_bytes,
            dest_dir,
            max_extracted_bytes=settings.max_skill_package_extracted_bytes,
            max_files=settings.max_skill_package_files,
        )

        skill_md_raw = (extracted.extracted_path / "SKILL.md").read_text(encoding="utf-8")
        parsed = parse_and_validate_skill_md(skill_md_raw, dir_name=extracted.root_dir_name)

        skill_json_raw: str | None = None
        triggers: dict = {"keywords": [], "intents": [], "lifecycle_events": []}
        hooks: list[str] = []
        skill_json_path = extracted.extracted_path / "skill.json"
        if skill_json_path.is_file():
            skill_json_raw = skill_json_path.read_text(encoding="utf-8")
            parsed_json = parse_and_validate_skill_json(skill_json_raw, skill_md_name=parsed.name)
            triggers = {
                "keywords": parsed_json.trigger_keywords,
                "intents": parsed_json.trigger_intents,
                "lifecycle_events": parsed_json.trigger_lifecycle_events,
            }
            hooks = parsed_json.hooks

        skill = Skill(
            id=skill_id,
            name=parsed.name,
            description=parsed.description,
            is_active=True,
            license=parsed.license,
            compatibility=parsed.compatibility,
            metadata_fields=parsed.metadata,
            allowed_tools=parsed.allowed_tools,
            skill_md_raw=skill_md_raw,
            body_markdown=parsed.body_markdown,
            skill_json_raw=skill_json_raw,
            triggers=triggers,
            hooks=hooks,
            dir_path=str(extracted.extracted_path),
            file_manifest=extracted.file_manifest,
            uploaded_by=uploaded_by,
            tenant_id=tenant_id,
        )
        db.add(skill)
        return skill
    except (SkillPackageExtractError, SkillPackageValidationError, OSError) as e:
        logger.warning("Failed to seed default skill for tenant %s: %s", tenant_id, e)
        return None
