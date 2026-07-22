"""Pure schema/logic unit tests (no DB/HTTP — this repo's sandbox has no
live Postgres, see tests/test_skill_packages.py's module docstring for the
same constraint) for the six-pillar enterprise layer: Persona trait schema,
Datasource/Project wire schemas, and the MCP config validator backing the
Tools registry's tool_type="mcp" support.
"""
import uuid

import pytest
from pydantic import ValidationError

from app.schemas.datasource import DatasourceCreate
from app.schemas.persona import PersonaTraits, SafetyCompliance
from app.schemas.project import BindingCreate, ProjectCreate
from app.schemas.tool import ToolCreate
from app.services.mcp_client import validate_mcp_config

# --- mcp_client.validate_mcp_config -----------------------------------------


def test_function_tool_type_never_errors():
    assert validate_mcp_config("function", None, None, None) == []


def test_mcp_sse_requires_endpoint():
    errors = validate_mcp_config("mcp", "sse", None, None)
    assert any("mcp_endpoint" in e for e in errors)


def test_mcp_sse_with_endpoint_is_valid():
    assert validate_mcp_config("mcp", "sse", "https://mcp.example.com/sse", None) == []


def test_mcp_stdio_requires_command():
    errors = validate_mcp_config("mcp", "stdio", None, None)
    assert any("mcp_command" in e for e in errors)


def test_mcp_stdio_with_command_is_valid():
    assert validate_mcp_config("mcp", "stdio", None, "npx -y @modelcontextprotocol/server-github") == []


def test_mcp_requires_valid_transport():
    errors = validate_mcp_config("mcp", None, None, None)
    assert any("mcp_transport" in e for e in errors)


# --- ToolCreate wraps the validator as a pydantic model_validator ----------


def test_tool_create_rejects_mcp_without_transport():
    with pytest.raises(ValidationError):
        ToolCreate(name="Jira MCP", tool_type="mcp")


def test_tool_create_accepts_valid_mcp_sse():
    tool = ToolCreate(name="Jira MCP", tool_type="mcp", mcp_transport="sse", mcp_endpoint="https://mcp.jira.example/sse")
    assert tool.mcp_transport == "sse"


def test_tool_create_defaults_to_function_type():
    tool = ToolCreate(name="Plain REST tool")
    assert tool.tool_type == "function"


# --- PersonaTraits (the 9-vector JSONB document) -----------------------------


def test_persona_traits_all_defaults_construct():
    traits = PersonaTraits()
    assert traits.tone_voice.formality == 50
    assert traits.safety_compliance.dlp_tier == "Standard"
    assert traits.interaction_style.turn_style == "multi_turn"


def test_persona_traits_rejects_invalid_dlp_tier():
    with pytest.raises(ValidationError):
        SafetyCompliance(dlp_tier="Nonsense")


def test_persona_traits_round_trips_tool_ids():
    tool_id = uuid.uuid4()
    traits = PersonaTraits(capabilities_tools={"allowed_tool_ids": [tool_id], "allowed_mcp_server_names": ["jira"]})
    assert traits.capabilities_tools.allowed_tool_ids == [tool_id]
    dumped = traits.model_dump(mode="json")
    assert dumped["capabilities_tools"]["allowed_tool_ids"] == [str(tool_id)]


# --- Datasource / Project wire schemas --------------------------------------


def test_datasource_create_rejects_unknown_connector_type():
    with pytest.raises(ValidationError):
        DatasourceCreate(name="Mystery source", connector_type="ftp")


def test_datasource_create_accepts_sharepoint():
    ds = DatasourceCreate(name="Finance SharePoint", connector_type="sharepoint", connection_config={"site_url": "https://x.sharepoint.com"})
    assert ds.security_classification == "Internal"
    assert ds.chunking_policy["strategy"] == "token"


def test_project_create_rejects_unknown_execution_mode():
    with pytest.raises(ValidationError):
        ProjectCreate(name="Audit Bot", execution_mode="on_click")


def test_project_create_accepts_scheduled_with_cron():
    project = ProjectCreate(name="Weekly Rollup", execution_mode="scheduled", schedule_cron="0 17 * * FRI")
    assert project.schedule_cron == "0 17 * * FRI"


def test_binding_create_rejects_unknown_component_type():
    with pytest.raises(ValidationError):
        BindingCreate(component_type="widget", component_id=uuid.uuid4())


def test_binding_create_accepts_all_five_component_types():
    # "skill_package" used to be a sixth, separate component_type before the
    # handler_key Skill system was retired — see
    # app/models/project_intelligence_binding.py's COMPONENT_TYPES comment.
    for component_type in ("agent", "tool", "hook", "skill", "plugin"):
        binding = BindingCreate(component_type=component_type, component_id=uuid.uuid4())
        assert binding.component_type == component_type
