import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import authorize, get_current_user
from app.core.database import get_db
from app.core.tenant_scope import apply_shared_or_own_tenant, is_visible
from app.models.plugin import Plugin
from app.models.user import User
from app.schemas.plugin import PluginCreate, PluginRead, PluginUpdate
from app.services.registry_access import fork_row

router = APIRouter(prefix="/plugins", tags=["plugins"])

# Not built on registry_factory's generic router: Plugin carries structured
# exports/requires columns (see app/models/plugin.py) that PluginCreate/
# Update validate against the live SKILL_REGISTRY/BUILTIN_HOOKS catalogs —
# the generic RegistryCreate/Update schemas don't know about those fields or
# that validation, the same reason Tool broke out of the factory earlier.


def _visible_or_404(db: Session, current_user: User, plugin_id: uuid.UUID) -> Plugin:
    plugin = db.get(Plugin, plugin_id)
    if plugin is None or not is_visible(plugin.tenant_id, current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plugin not found")
    return plugin


@router.get("", response_model=list[PluginRead])
def list_plugins(db: Session = Depends(get_db), current_user: User = Depends(authorize("plugin", "list"))) -> list[PluginRead]:
    plugins = (
        apply_shared_or_own_tenant(db.query(Plugin), Plugin.tenant_id, current_user)
        .order_by(Plugin.created_at.desc())
        .all()
    )
    return [PluginRead.model_validate(p) for p in plugins]


@router.post("", response_model=PluginRead, status_code=status.HTTP_201_CREATED)
def create_plugin(payload: PluginCreate, db: Session = Depends(get_db), current_admin: User = Depends(authorize("plugin", "create"))) -> PluginRead:
    plugin = Plugin(**payload.model_dump(), tenant_id=current_admin.tenant_id)
    db.add(plugin)
    db.commit()
    db.refresh(plugin)
    return PluginRead.model_validate(plugin)


@router.get("/{plugin_id}", response_model=PluginRead)
def get_plugin(plugin_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("plugin", "read"))) -> PluginRead:
    return PluginRead.model_validate(_visible_or_404(db, current_user, plugin_id))


@router.put("/{plugin_id}", response_model=PluginRead)
def update_plugin(
    plugin_id: uuid.UUID,
    payload: PluginUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("plugin", "update")),
) -> PluginRead:
    plugin = _visible_or_404(db, current_admin, plugin_id)
    if plugin.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be edited")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(plugin, field, value)

    db.commit()
    db.refresh(plugin)
    return PluginRead.model_validate(plugin)


@router.delete("/{plugin_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plugin(plugin_id: uuid.UUID, db: Session = Depends(get_db), current_admin: User = Depends(authorize("plugin", "delete"))) -> None:
    plugin = _visible_or_404(db, current_admin, plugin_id)
    if plugin.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be deleted")
    db.delete(plugin)
    db.commit()
    return None


@router.post("/{plugin_id}/fork", response_model=PluginRead, status_code=status.HTTP_201_CREATED)
def fork_plugin(plugin_id: uuid.UUID, db: Session = Depends(get_db), current_admin: User = Depends(authorize("plugin", "create"))) -> PluginRead:
    """PLATFORM_ARCHITECTURE.md §7.5 fork-and-override — see prompts.py's
    fork_prompt for the full rationale, identical here."""
    source = _visible_or_404(db, current_admin, plugin_id)
    if current_admin.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Super admin has no tenant of their own to fork into")
    forked = fork_row(source, new_tenant_id=current_admin.tenant_id, owner_user_id=current_admin.id, model_cls=Plugin)
    db.add(forked)
    db.commit()
    db.refresh(forked)
    return PluginRead.model_validate(forked)
