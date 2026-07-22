"""Model Context Protocol (MCP) client — scaffold boundary.

Per the Intelligence Layer spec, the Tools Registry should "natively parse
MCP configurations, allowing the application to dynamically fetch available
tools from a running local or remote MCP host over SSE or stdio transport
layers." Implementing a real MCP client (an SSE event stream reader or a
subprocess-based stdio JSON-RPC client, both speaking the full MCP
handshake/list_tools/call_tool lifecycle) is out of scope for this pass —
this repo has no running MCP host to test against, and a fake client would
be worse than an honest stub.

What *is* real: app/models/tool.py's tool_type/mcp_transport/mcp_endpoint/
mcp_command/mcp_tool_name columns, full CRUD via the Tools registry (a Tool
row with tool_type="mcp" is exactly the metadata a real client would need
to connect), and this module's validate_mcp_config, which enforces the
transport-specific required fields so bad configs are caught at write time
even though nothing connects yet.

To go from scaffold to real: implement `list_remote_tools(tool: Tool) ->
list[str]` here using the `mcp` Python SDK (ClientSession + sse_client/
stdio_client), call it from a new POST /tools/{id}/discover route, and
surface the returned tool names in the Tools panel instead of requiring
mcp_tool_name to be typed in by hand.
"""
from __future__ import annotations


def validate_mcp_config(tool_type: str, mcp_transport: str | None, mcp_endpoint: str | None, mcp_command: str | None) -> list[str]:
    """Static validation only — no network/process calls. Returns a list of
    error strings (empty = valid)."""
    errors: list[str] = []
    if tool_type != "mcp":
        return errors
    if mcp_transport not in ("sse", "stdio"):
        errors.append("mcp_transport must be 'sse' or 'stdio' when tool_type is 'mcp'")
        return errors
    if mcp_transport == "sse" and not mcp_endpoint:
        errors.append("mcp_endpoint is required for sse transport")
    if mcp_transport == "stdio" and not mcp_command:
        errors.append("mcp_command is required for stdio transport")
    return errors
