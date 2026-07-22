"""Schema-level tests for Prompt's market-standard structure (messages +
variables + model_params), adopted from Langfuse/LangSmith Hub conventions
— see docs/SKILL_STANDARD.md. Pure pydantic, no DB, same style as the rest
of this project's tests.
"""
import pytest
from pydantic import ValidationError

from app.schemas.prompt import PromptCreate, PromptUpdate


def test_prompt_create_accepts_declared_variable():
    prompt = PromptCreate(
        name="greeting",
        messages=[{"role": "user", "content": "Hello {{name}}, welcome to {{product}}."}],
        variables=[
            {"name": "name", "required": True},
            {"name": "product", "required": True},
        ],
    )
    assert len(prompt.messages) == 1
    assert {v.name for v in prompt.variables} == {"name", "product"}


def test_prompt_create_rejects_undeclared_variable():
    with pytest.raises(ValidationError, match="not declared"):
        PromptCreate(
            name="greeting",
            messages=[{"role": "user", "content": "Hello {{name}}."}],
            variables=[],
        )


def test_prompt_create_requires_at_least_one_message():
    with pytest.raises(ValidationError):
        PromptCreate(name="empty", messages=[])


def test_prompt_create_rejects_invalid_role():
    with pytest.raises(ValidationError):
        PromptCreate(name="bad_role", messages=[{"role": "tool", "content": "hi"}])


def test_prompt_create_defaults():
    prompt = PromptCreate(name="basic", messages=[{"role": "user", "content": "hi"}])
    assert prompt.label == "latest"
    assert prompt.status == "Active"
    assert prompt.version == "1.0.0"
    assert prompt.model_params.model is None
    assert prompt.model_params.stop == []


def test_prompt_model_params_validates_ranges():
    with pytest.raises(ValidationError):
        PromptCreate(
            name="bad_temp",
            messages=[{"role": "user", "content": "hi"}],
            model_params={"temperature": 5.0},
        )


def test_prompt_update_allows_unrelated_field_without_messages():
    update = PromptUpdate(name="renamed")
    assert update.messages is None


def test_prompt_update_requires_messages_and_variables_together():
    with pytest.raises(ValidationError, match="together"):
        PromptUpdate(messages=[{"role": "user", "content": "hi"}])


def test_prompt_update_accepts_messages_and_variables_together():
    update = PromptUpdate(
        messages=[{"role": "user", "content": "Hi {{x}}"}],
        variables=[{"name": "x", "required": True}],
    )
    assert update.messages is not None
