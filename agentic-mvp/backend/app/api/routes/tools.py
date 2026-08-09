import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import authorize, get_current_user
from app.core.database import get_db
from app.core.tenant_scope import apply_shared_or_own_tenant, is_visible
from app.models.tool import Tool
from app.models.user import User
from app.schemas.tool import ToolCreate, ToolRead, ToolUpdate
from app.services.registry_access import fork_row

router = APIRouter(prefix="/tools", tags=["tools"])

# Not built on registry_factory's generic router: Tool carries MCP-specific
# columns (tool_type/mcp_transport/mcp_endpoint/mcp_command/mcp_tool_name)
# that the generic RegistryCreate/Update schemas don't know about — see
# app/schemas/tool.py and app/services/mcp_client.py's module docstring for
# the scaffold-vs-real boundary on MCP support.


def _visible_or_404(db: Session, current_user: User, tool_id: uuid.UUID) -> Tool:
    tool = db.get(Tool, tool_id)
    if tool is None or not is_visible(tool.tenant_id, current_user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
    return tool


@router.get("", response_model=list[ToolRead])
def list_tools(db: Session = Depends(get_db), current_user: User = Depends(authorize("tool", "list"))) -> list[ToolRead]:
    tools = (
        apply_shared_or_own_tenant(db.query(Tool), Tool.tenant_id, current_user)
        .order_by(Tool.created_at.desc())
        .all()
    )
    return [ToolRead.model_validate(t) for t in tools]


@router.post("", response_model=ToolRead, status_code=status.HTTP_201_CREATED)
def create_tool(payload: ToolCreate, db: Session = Depends(get_db), current_admin: User = Depends(authorize("tool", "create"))) -> ToolRead:
    tool = Tool(**payload.model_dump(), tenant_id=current_admin.tenant_id)
    db.add(tool)
    db.commit()
    db.refresh(tool)
    return ToolRead.model_validate(tool)


@router.get("/{tool_id}", response_model=ToolRead)
def get_tool(tool_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("tool", "read"))) -> ToolRead:
    return ToolRead.model_validate(_visible_or_404(db, current_user, tool_id))


@router.put("/{tool_id}", response_model=ToolRead)
def update_tool(
    tool_id: uuid.UUID,
    payload: ToolUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("tool", "update")),
) -> ToolRead:
    tool = _visible_or_404(db, current_admin, tool_id)
    if tool.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be edited")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(tool, field, value)

    from app.services.mcp_client import validate_mcp_config

    errors = validate_mcp_config(tool.tool_type, tool.mcp_transport, tool.mcp_endpoint, tool.mcp_command)
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(errors))

    db.commit()
    db.refresh(tool)
    return ToolRead.model_validate(tool)


@router.delete("/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tool(tool_id: uuid.UUID, db: Session = Depends(get_db), current_admin: User = Depends(authorize("tool", "delete"))) -> None:
    tool = _visible_or_404(db, current_admin, tool_id)
    if tool.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Platform-shared items cannot be deleted")
    db.delete(tool)
    db.commit()
    return None


@router.post("/{tool_id}/fork", response_model=ToolRead, status_code=status.HTTP_201_CREATED)
def fork_tool(tool_id: uuid.UUID, db: Session = Depends(get_db), current_admin: User = Depends(authorize("tool", "create"))) -> ToolRead:
    """PLATFORM_ARCHITECTURE.md §7.5 fork-and-override — see prompts.py's
    fork_prompt for the full rationale, identical here."""
    source = _visible_or_404(db, current_admin, tool_id)
    if current_admin.tenant_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Super admin has no tenant of their own to fork into")
    forked = fork_row(source, new_tenant_id=current_admin.tenant_id, owner_user_id=current_admin.id, model_cls=Tool)
    db.add(forked)
    db.commit()
    db.refresh(forked)
    return ToolRead.model_validate(forked)
