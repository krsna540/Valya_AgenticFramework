import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import authorize, get_current_user
from app.core.database import get_db
from app.core.tenant_scope import apply_shared_or_own_tenant, is_visible
from app.models.hook import Hook
from app.models.user import User
from app.schemas.registry import HookCreate, HookHandlerInfo, HookRead, HookUpdate, LifecycleEventInfo
from app.services.hooks import BUILTIN_HOOKS, STAGES, WIRED_STAGES, list_builtin_handlers


def _visible_or_404(db: Session, current_user: User, hook_id: uuid.UUID) -> Hook:
    hook = db.get(Hook, hook_id)
    if hook is None or not is_visible(hook.tenant_id, current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hook not found")
    return hook

router = APIRouter(prefix="/hooks", tags=["hooks"])

_CUSTOM_HANDLER_TYPES = {"http", "command", "mcp_tool"}


def _validate_hook_fields(handler_type: str, handler_key: str | None, lifecycle_event: str, handler_config: dict) -> None:
    if lifecycle_event not in STAGES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown lifecycle_event '{lifecycle_event}'. See GET /hooks/lifecycle-events.",
        )

    if handler_type == "python":
        if not handler_key or handler_key not in BUILTIN_HOOKS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown handler_key '{handler_key}'. See GET /hooks/handlers for valid options.",
            )
        expected_stage = BUILTIN_HOOKS[handler_key]["stage"]
        if lifecycle_event != expected_stage:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"handler_key '{handler_key}' is registered under lifecycle_event "
                f"'{expected_stage}', not '{lifecycle_event}'.",
            )
        return

    if handler_type not in _CUSTOM_HANDLER_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown handler_type '{handler_type}'")

    if handler_type == "http" and not handler_config.get("endpoint"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="handler_config.endpoint is required for handler_type=http")
    if handler_type == "command" and not handler_config.get("script_path"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="handler_config.script_path is required for handler_type=command")
    if handler_type == "mcp_tool" and not (handler_config.get("mcp_server_url") and handler_config.get("tool_name")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="handler_config.mcp_server_url and .tool_name are required for handler_type=mcp_tool",
        )


@router.get("/handlers", response_model=list[HookHandlerInfo])
def get_hook_handlers(_: User = Depends(get_current_user)) -> list[HookHandlerInfo]:
    """Catalog of vetted, code-reviewed hook implementations a Hook record can
    bind to via handler_key when handler_type="python" — hooks never store
    or eval arbitrary code on this path."""
    return [HookHandlerInfo(**h) for h in list_builtin_handlers()]


@router.get("/lifecycle-events", response_model=list[LifecycleEventInfo])
def get_lifecycle_events(_: User = Depends(get_current_user)) -> list[LifecycleEventInfo]:
    """The full 10-stage lifecycle taxonomy, flagged with whether this app
    currently fires it for real (see app/services/hooks.py's module
    docstring — PreCompact is schema-only today, no compaction exists yet)."""
    return [LifecycleEventInfo(key=stage, wired=stage in WIRED_STAGES) for stage in STAGES]


@router.get("", response_model=list[HookRead])
def list_hooks(db: Session = Depends(get_db), current_user: User = Depends(authorize("hook", "list"))) -> list[Hook]:
    return (
        apply_shared_or_own_tenant(db.query(Hook), Hook.tenant_id, current_user)
        .order_by(Hook.created_at.desc())
        .all()
    )


@router.post("", response_model=HookRead, status_code=status.HTTP_201_CREATED)
def create_hook(payload: HookCreate, db: Session = Depends(get_db), current_admin: User = Depends(authorize("hook", "create"))) -> Hook:
    _validate_hook_fields(payload.handler_type, payload.handler_key, payload.lifecycle_event, payload.handler_config)
    hook = Hook(**payload.model_dump(), tenant_id=current_admin.tenant_id)
    db.add(hook)
    db.commit()
    db.refresh(hook)
    return hook


@router.get("/{hook_id}", response_model=HookRead)
def get_hook(hook_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("hook", "read"))) -> Hook:
    return _visible_or_404(db, current_user, hook_id)


@router.put("/{hook_id}", response_model=HookRead)
def update_hook(
    hook_id: uuid.UUID,
    payload: HookUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("hook", "update")),
) -> Hook:
    hook = _visible_or_404(db, current_admin, hook_id)
    if hook.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be edited")
    data = payload.model_dump(exclude_unset=True)

    if {"handler_type", "handler_key", "lifecycle_event", "handler_config"} & data.keys():
        _validate_hook_fields(
            data.get("handler_type", hook.handler_type),
            data.get("handler_key", hook.handler_key),
            data.get("lifecycle_event", hook.lifecycle_event),
            data.get("handler_config", hook.handler_config),
        )

    for field, value in data.items():
        setattr(hook, field, value)
    db.commit()
    db.refresh(hook)
    return hook


@router.delete("/{hook_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_hook(hook_id: uuid.UUID, db: Session = Depends(get_db), current_admin: User = Depends(authorize("hook", "delete"))) -> None:
    hook = _visible_or_404(db, current_admin, hook_id)
    if hook.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be deleted")
    db.delete(hook)
    db.commit()
    return None
