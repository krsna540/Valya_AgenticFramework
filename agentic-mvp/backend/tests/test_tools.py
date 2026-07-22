"""Schema-level tests for Tool's manifest.json-shaped metadata fields
(input_schema/permissions/rate_limit_per_min/timeout_s/tags), adopted from
NexusClaw's manifest.json convention — see docs/SKILL_STANDARD.md.
"""
from app.schemas.tool import ToolCreate, ToolRead


def test_tool_create_defaults_match_manifest_convention():
    tool = ToolCreate(name="my_function_tool")
    assert tool.input_schema is None
    assert tool.permissions == []
    assert tool.rate_limit_per_min == 60
    assert tool.timeout_s == 15
    assert tool.tags == []


def test_tool_create_accepts_full_manifest_metadata():
    tool = ToolCreate(
        name="rag_query",
        tool_type="function",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        permissions=["memory:read"],
        rate_limit_per_min=30,
        timeout_s=10,
        tags=["retrieval", "rag"],
    )
    assert tool.input_schema == {"type": "object", "properties": {"query": {"type": "string"}}}
    assert tool.permissions == ["memory:read"]
    assert tool.rate_limit_per_min == 30
    assert tool.timeout_s == 10
    assert tool.tags == ["retrieval", "rag"]


def test_tool_read_requires_manifest_fields():
    # ToolRead is from_attributes — just confirms the field set includes the
    # new columns so a DB row missing them would fail validation loudly.
    fields = ToolRead.model_fields
    for f in ("input_schema", "permissions", "rate_limit_per_min", "timeout_s", "tags", "annotations"):
        assert f in fields


# --- MCP tool annotations (spec 2025-06-18) ----------------------------------


def test_tool_create_default_annotations_match_mcp_open_world_default():
    tool = ToolCreate(name="my_tool")
    assert tool.annotations.title is None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is False
    assert tool.annotations.openWorldHint is True


def test_tool_create_accepts_custom_annotations():
    tool = ToolCreate(
        name="delete_file",
        annotations={"title": "Delete a file", "readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False},
    )
    assert tool.annotations.title == "Delete a file"
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.openWorldHint is False
