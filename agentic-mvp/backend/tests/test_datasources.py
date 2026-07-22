"""Tests for the Airbyte-inspired per-connector-type field specs (see
docs/SKILL_STANDARD.md's Datasources section) and the new auth_type/
sync_mode schema fields. Pure unit tests — no DB.
"""
from app.api.routes.datasources import CONNECTOR_DEFAULT_AUTH_TYPE, CONNECTOR_FIELD_SPECS
from app.models.datasource import AUTH_TYPES, CONNECTOR_TYPES, SYNC_MODES
from app.schemas.datasource import DatasourceCreate


def test_every_connector_type_has_a_field_spec_and_default_auth_type():
    for connector in CONNECTOR_TYPES:
        assert connector in CONNECTOR_FIELD_SPECS
        assert connector in CONNECTOR_DEFAULT_AUTH_TYPE
        assert CONNECTOR_DEFAULT_AUTH_TYPE[connector] in AUTH_TYPES


def test_secret_fields_are_flagged():
    sql_fields = {f["key"]: f for f in CONNECTOR_FIELD_SPECS["sql_database"]}
    assert sql_fields["password"]["secret"] is True
    assert sql_fields["host"]["secret"] is False


def test_field_types_are_valid():
    valid_types = {"string", "number", "boolean", "select"}
    for fields in CONNECTOR_FIELD_SPECS.values():
        for f in fields:
            assert f["type"] in valid_types
            if f["type"] == "select":
                assert "options" in f and len(f["options"]) > 0


def test_file_upload_has_no_fields():
    assert CONNECTOR_FIELD_SPECS["file_upload"] == []


def test_datasource_create_defaults_auth_type_and_sync_mode():
    ds = DatasourceCreate(name="my_source", connector_type="rest_api")
    assert ds.auth_type == "none"
    assert ds.sync_mode == "full_refresh"
    assert ds.sync_schedule_cron is None


def test_datasource_create_accepts_all_sync_modes():
    for mode in SYNC_MODES:
        ds = DatasourceCreate(name="s", connector_type="file_upload", sync_mode=mode)
        assert ds.sync_mode == mode


def test_datasource_create_rejects_invalid_auth_type():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DatasourceCreate(name="s", connector_type="file_upload", auth_type="carrier_pigeon")
