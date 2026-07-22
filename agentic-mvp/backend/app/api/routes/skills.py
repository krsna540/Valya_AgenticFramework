"""Skills: upload a zip of the canonical folder format —

    my-custom-skill/
    ├── SKILL.md          # Required
    ├── skill.json        # Optional: triggers & hooks manifest
    ├── references/       # Optional
    ├── scripts/          # Optional: executable code
    └── assets/           # Optional

— browse/download it, optionally attach it to Agents.

Nothing in this router executes any file it stores. Per the agentskills.io
spec, `scripts/` files are meant to be run *by an agent that decides to*,
not by whatever system loaded the skill — this app's agent_runner.py is
still a deterministic stub with no real tool-calling loop (see its module
docstring), so for now these are purely storable, browsable, downloadable,
and attachable content. This used to be two systems — a handler_key-bound
`Skill` DB row calling into a vetted Python `BaseSkill` catalog, and this
folder-based format as a separate "SkillPackage" — until the handler_key
system was retired in favor of making this folder format the only one,
per the user's explicit request. See docs/SKILL_STANDARD.md for the full
history and the no-stored-code rationale (this is intentionally the "safe"
end of this app's skill-sharing spectrum — same posture as before, just one
format instead of two).
"""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import authorize, get_current_user, get_current_user_flexible
from app.core import opa
from app.core.config import settings
from app.core.database import get_db
from app.core.tenant_scope import apply_shared_or_own_tenant, is_visible
from app.models.skill import Skill
from app.models.user import User
from app.schemas.skill import SkillRead, SkillUpdate
from app.skills.package_extract import SkillPackageExtractError, extract_skill_zip, zip_package
from app.skills.package_spec import (
    SkillPackageValidationError,
    parse_and_validate_skill_json,
    parse_and_validate_skill_md,
)

router = APIRouter(prefix="/skills", tags=["skills"])


def _skill_dir(skill_id: uuid.UUID) -> Path:
    return Path(settings.skill_packages_dir) / str(skill_id)


def _get_or_404(db: Session, skill_id: uuid.UUID) -> Skill:
    skill = db.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    return skill


def _visible_or_404(db: Session, current_user: User, skill_id: uuid.UUID) -> Skill:
    skill = _get_or_404(db, skill_id)
    if not is_visible(skill.tenant_id, current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    return skill


def _resolve_manifest_path(skill: Skill, file_path: str) -> Path:
    if file_path not in skill.file_manifest:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found in this skill")
    resolved = (Path(skill.dir_path) / file_path).resolve()
    root = Path(skill.dir_path).resolve()
    if not str(resolved).startswith(str(root)) or not resolved.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found in this skill")
    return resolved


@router.get("", response_model=list[SkillRead])
def list_skills(db: Session = Depends(get_db), current_user: User = Depends(authorize("skill", "list"))) -> list[Skill]:
    return (
        apply_shared_or_own_tenant(db.query(Skill), Skill.tenant_id, current_user)
        .order_by(Skill.created_at.desc())
        .all()
    )


@router.post("/upload", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
async def upload_skill(
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(authorize("skill", "create")),
) -> Skill:
    raw = await file.read()
    if len(raw) > settings.max_skill_package_zip_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Zip exceeds {settings.max_skill_package_zip_bytes // (1024 * 1024)} MB limit",
        )

    skill_id = uuid.uuid4()
    dest_dir = _skill_dir(skill_id)
    try:
        extracted = extract_skill_zip(
            raw,
            dest_dir,
            max_extracted_bytes=settings.max_skill_package_extracted_bytes,
            max_files=settings.max_skill_package_files,
        )
    except SkillPackageExtractError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    skill_md_path = extracted.extracted_path / "SKILL.md"
    skill_md_raw = skill_md_path.read_text(encoding="utf-8")

    try:
        parsed = parse_and_validate_skill_md(skill_md_raw, dir_name=extracted.root_dir_name)
    except SkillPackageValidationError as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"errors": e.errors})

    # skill.json is optional — only parse/validate it if the zip included one.
    skill_json_raw: str | None = None
    triggers: dict = {"keywords": [], "intents": [], "lifecycle_events": []}
    hooks: list[str] = []
    skill_json_path = extracted.extracted_path / "skill.json"
    if skill_json_path.is_file():
        skill_json_raw = skill_json_path.read_text(encoding="utf-8")
        try:
            parsed_json = parse_and_validate_skill_json(skill_json_raw, skill_md_name=parsed.name)
        except SkillPackageValidationError as e:
            shutil.rmtree(dest_dir, ignore_errors=True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"errors": e.errors})
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
        uploaded_by=current_user.id,
        tenant_id=current_user.tenant_id,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def _require_flexible_read(current_user: User) -> None:
    """The two routes below accept a query-param token (get_current_user_flexible)
    instead of only a bearer header, so plain <a href>/<img src> tags can
    load them — that dependency alone can't also express an OPA resource
    type/action the way `authorize()` does (it doesn't take a `User` as
    input, it *produces* one). Same OPA check, just invoked manually."""
    if not opa.authorize(current_user, "skill", "read", tenant_id=current_user.tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")


@router.get("/{skill_id}", response_model=SkillRead)
def get_skill(skill_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("skill", "read"))) -> Skill:
    return _visible_or_404(db, current_user, skill_id)


@router.get("/{skill_id}/skill-md", response_class=PlainTextResponse)
def get_skill_md(skill_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("skill", "read"))) -> str:
    """The exact original SKILL.md text (frontmatter + body), byte-identical
    to what was uploaded."""
    return _visible_or_404(db, current_user, skill_id).skill_md_raw


@router.get("/{skill_id}/skill-json", response_class=PlainTextResponse)
def get_skill_json(skill_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("skill", "read"))) -> str:
    """The exact original skill.json text, or an empty string if this skill
    didn't include one (it's optional)."""
    return _visible_or_404(db, current_user, skill_id).skill_json_raw or ""


@router.get("/{skill_id}/files", response_model=list[str])
def list_skill_files(skill_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("skill", "read"))) -> list[str]:
    return _visible_or_404(db, current_user, skill_id).file_manifest


@router.get("/{skill_id}/files/{file_path:path}", response_class=PlainTextResponse)
def get_skill_file(
    skill_id: uuid.UUID,
    file_path: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_flexible),
) -> str:
    """Read-only view of one file inside the skill (a script, reference
    doc, or asset) — never executed, just returned as text for inspection.
    Binary files will render as best-effort decoded text; use /download to
    get exact bytes."""
    _require_flexible_read(current_user)
    skill = _visible_or_404(db, current_user, skill_id)
    path = _resolve_manifest_path(skill, file_path)
    return path.read_text(encoding="utf-8", errors="replace")


@router.get("/{skill_id}/download")
def download_skill(skill_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_flexible)) -> Response:
    """Re-zips the stored directory — the "share it with others" path:
    someone else downloads this and uploads it to their own instance,
    going through the same parse-and-validate flow there."""
    _require_flexible_read(current_user)
    skill = _visible_or_404(db, current_user, skill_id)
    data = zip_package(Path(skill.dir_path), skill.name)
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{skill.name}.zip"'},
    )


@router.put("/{skill_id}", response_model=SkillRead)
def update_skill(
    skill_id: uuid.UUID,
    payload: SkillUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("skill", "update")),
) -> Skill:
    skill = _visible_or_404(db, current_admin, skill_id)
    if skill.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be edited")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(skill, field, value)
    db.commit()
    db.refresh(skill)
    return skill


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_skill(skill_id: uuid.UUID, db: Session = Depends(get_db), current_admin: User = Depends(authorize("skill", "delete"))) -> None:
    skill = _visible_or_404(db, current_admin, skill_id)
    if skill.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be deleted")
    shutil.rmtree(skill.dir_path, ignore_errors=True)
    db.delete(skill)
    db.commit()
    return None
