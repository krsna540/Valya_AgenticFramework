"""Tests for the session-level tool/skill/playbook cache
(app/services/registry_cache.py).

Uses plain namespace fakes rather than real ORM rows — this module only
reads a handful of attributes off `agent`/`agent.tools`/`agent.skills`/
`agent.playbooks`, so a fake that has exactly those attributes exercises the
same code path as a real `Agent` without a database.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services import registry_cache


def _tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description="d",
        tool_type="function",
        input_schema=None,
        config={},
        timeout_s=15,
        annotations={},
    )


def _agent(*, tools: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tools=tools or [],
        skills=[],
        playbooks=[],
    )


def setup_function() -> None:
    registry_cache.clear()


def test_get_capabilities_flattens_orm_relationships_into_plain_dicts():
    agent = _agent(tools=[_tool("sql_query")])
    caps = registry_cache.get_capabilities(agent)
    assert caps["tools"] == [
        {
            "name": "sql_query",
            "description": "d",
            "tool_type": "function",
            "input_schema": None,
            "config": {},
            "timeout_s": 15,
            "annotations": {},
        }
    ]
    assert caps["skills"] == []
    assert caps["playbooks"] == []


def test_a_second_call_within_the_ttl_is_served_from_cache_not_reflattened():
    agent = _agent(tools=[_tool("sql_query")])
    first = registry_cache.get_capabilities(agent)

    # Mutate the ORM-side list after the first call; a cache hit must not
    # notice, because it never touches `agent.tools` again.
    agent.tools.append(_tool("second_tool"))
    second = registry_cache.get_capabilities(agent)

    assert second == first
    assert len(second["tools"]) == 1


def test_invalidate_forces_the_next_call_to_reflatten():
    agent = _agent(tools=[_tool("sql_query")])
    registry_cache.get_capabilities(agent)

    agent.tools.append(_tool("second_tool"))
    registry_cache.invalidate(agent.id)
    refreshed = registry_cache.get_capabilities(agent)

    assert len(refreshed["tools"]) == 2


def test_different_agents_are_cached_independently():
    agent_one = _agent(tools=[_tool("a")])
    agent_two = _agent(tools=[_tool("b")])

    assert registry_cache.get_capabilities(agent_one)["tools"][0]["name"] == "a"
    assert registry_cache.get_capabilities(agent_two)["tools"][0]["name"] == "b"
