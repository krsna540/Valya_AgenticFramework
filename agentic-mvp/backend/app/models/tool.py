from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import RegistryMixin, TenantScopedMixin


class Tool(RegistryMixin, TenantScopedMixin, Base):
    __tablename__ = "tools"

    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    # "function" -> a plain REST/config-described tool (the original model)
    # "mcp"      -> discovered/described via the Model Context Protocol; the
    #               remaining mcp_* fields describe how to reach it. This app
    #               stores MCP tool *metadata* (what the Tools Registry
    #               needs to display/associate an MCP tool with a Project);
    #               it does not run a live SSE/stdio client to actually call
    #               out to an MCP host — see app/services/mcp_client.py's
    #               module docstring for the scaffold/real-client boundary.
    tool_type: Mapped[str] = mapped_column(String(20), nullable=False, default="function")
    # "sse" | "stdio" — only meaningful when tool_type == "mcp"
    mcp_transport: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # SSE server URL, e.g. "https://mcp.example.com/sse" — sse transport only
    mcp_endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Launch command for a local MCP server, e.g. "npx -y @modelcontextprotocol/server-github"
    # — stdio transport only
    mcp_command: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # The specific tool name exposed by the MCP server this registry entry
    # represents (an MCP host can expose many tools; one Tool row = one of them)
    mcp_tool_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- manifest metadata (adopted from NexusClaw's skill manifest.json
    # shape — see docs/SKILL_STANDARD.md). Most useful for tool_type=
    # "function": describes the call contract the same way a Skill's
    # handler already does via input_schema.model_json_schema(), so a
    # function-type Tool row can be handed to an LLM's tool-calling API
    # without a separate lookup. For tool_type="mcp" this is typically left
    # empty since the MCP host is the source of truth for its own schema.
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    permissions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    rate_limit_per_min: Mapped[int] = mapped_column(default=60, nullable=False)
    timeout_s: Mapped[int] = mapped_column(default=15, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # MCP tool annotation hints (Model Context Protocol spec 2025-06-18):
    # client-facing display/behavior hints, purely advisory — never a
    # security boundary (a client must still treat them as untrusted unless
    # the server itself is explicitly trusted). Shape:
    #   {title: str|None, readOnlyHint: bool, destructiveHint: bool,
    #    idempotentHint: bool, openWorldHint: bool}
    annotations: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: {
            "title": None,
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
        nullable=False,
    )
