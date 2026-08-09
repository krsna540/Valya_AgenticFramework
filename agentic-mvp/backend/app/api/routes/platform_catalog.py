"""Backs superadmin-app.html's "Platform catalog" screen: the
access_class="default" rows every tenant starts with, plus how many times
each has been forked (§7.5) and how many project bindings currently use it.
Read-only aggregation over the five registry tables — the actual
promote-to-default action stays where it already conceptually lives (a
super_admin editing a row's access_class via the existing PUT routes;
see app/services/registry_access.py::assert_can_write, which is what
actually enforces that only a super_admin may ever set access_class=
"default" in the first place).
"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import require_super_admin
from app.core.database import get_db
from app.models.hook import Hook
from app.models.plugin import Plugin
from app.models.project_intelligence_binding import ProjectIntelligenceBinding
from app.models.prompt import Prompt
from app.models.skill import Skill
from app.models.tool import Tool
from app.models.user import User

router = APIRouter(prefix="/platform/catalog", tags=["platform-catalog"])

_KIND_MODELS: dict[str, type] = {"skill": Skill, "prompt": Prompt, "tool": Tool, "hook": Hook, "plugin": Plugin}
_BINDABLE_KINDS = {"skill", "tool", "hook", "plugin"}  # component_types ProjectIntelligenceBinding actually stores


class CatalogItem(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    description: str | None
    version: str
    status: str
    forked_count: int
    projects_in_use: int


@router.get("", response_model=list[CatalogItem])
def list_platform_catalog(db: Session = Depends(get_db), _: User = Depends(require_super_admin)) -> list[CatalogItem]:
    items: list[CatalogItem] = []
    for kind, model in _KIND_MODELS.items():
        rows = db.query(model).filter(model.access_class == "default").order_by(model.name).all()
        for row in rows:
            forked_count = db.query(func.count(model.id)).filter(model.forked_from_id == row.id).scalar() or 0
            projects_in_use = 0
            if kind in _BINDABLE_KINDS:
                projects_in_use = (
                    db.query(func.count(ProjectIntelligenceBinding.id))
                    .filter(
                        ProjectIntelligenceBinding.component_type == kind,
                        ProjectIntelligenceBinding.component_id == row.id,
                        ProjectIntelligenceBinding.is_active == True,  # noqa: E712
                    )
                    .scalar()
                    or 0
                )
            items.append(
                CatalogItem(
                    id=row.id,
                    kind=kind,
                    name=row.name,
                    description=row.description,
                    version=getattr(row, "version", "1.0.0"),
                    status=getattr(row, "status", "Active"),
                    forked_count=forked_count,
                    projects_in_use=projects_in_use,
                )
            )
    return items
