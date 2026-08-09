import uuid

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import RegistryAccessMixin, RegistryMixin


class Hook(RegistryMixin, RegistryAccessMixin, Base):
    __tablename__ = "hooks"

    # NULL = platform-shared (visible/attachable by every tenant), same
    # nullable-tenant convention as TenantScopedMixin — Hook predates that
    # mixin (already had its own version/status columns) so tenant_id is
    # added directly here instead of retrofitting the mixin. access_class/
    # visibility/forked_from_*/owner_user_id come from RegistryAccessMixin
    # directly (migration 0016) since Hook can't pick them up via
    # TenantScopedMixin without duplicate version/status columns.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True)

    # "global"  -> auto-applied to every agent's pipeline, no attachment needed
    # "agent"   -> only applies to agents it's attached to via agent_hooks
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="agent")

    # One of the 10 lifecycle events in app.services.hooks.STAGES
    # (SessionStart, UserPromptSubmit, PreToolUse, PostToolUse.Success,
    # PostToolUse.Failure, PreCompact, SubagentStart, SubagentStop, Stop,
    # Notification). For handler_type="python" this must match the stage
    # the chosen handler_key is registered under (validated at write time);
    # for custom handler types it's the only source of truth for where the
    # hook fires.
    lifecycle_event: Mapped[str] = mapped_column(String(50), nullable=False, default="UserPromptSubmit")

    # "python"    -> handler_key must reference a vetted class in
    #                app.services.hooks.BUILTIN_HOOKS (no code stored/eval'd)
    # "http"      -> handler_config describes an outbound webhook call
    # "command"   -> handler_config describes a local script to execute
    # "mcp_tool"  -> handler_config describes a call to a configured MCP tool
    # The last three are real code/network execution paths, deliberately
    # separate from the safe python path — see README's "Hook handler types"
    # section for the trust-boundary discussion.
    handler_type: Mapped[str] = mapped_column(String(20), nullable=False, default="python")
    handler_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Shape depends on handler_type — see app/services/hook_handlers.py:
    #   http:      {endpoint, method, headers}
    #   command:   {runtime, script_path, args}
    #   mcp_tool:  {mcp_server_url, tool_name, parameters}
    handler_config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # {timeout_ms, fallback_strategy: "Block"|"Allow", allowed_tools: [...],
    #  blocked_keywords: [...], return_directives: {on_match, on_clean}}
    # blocked_keywords/allowed_tools are checked before any handler actually
    # runs (a static gate), independent of handler_type — see
    # app/services/hook_handlers.py::static_gate.
    execution_policy: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # Config passed to python built-in handlers (e.g. banned_phrases) — kept
    # separate from handler_config, which is about *how to reach* a custom
    # handler, not what to tell it to do.
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    version: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0.0")
    # Active | Experimental | Deprecated — purely descriptive; use is_active
    # (RegistryMixin) to actually enable/disable a hook in the pipeline.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Active")
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
