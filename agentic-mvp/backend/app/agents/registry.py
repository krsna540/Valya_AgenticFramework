"""Agent class registry — the `@register_agent` decorator.

Same shape as this codebase's existing `@builtin_hook` registry
(app/services/hooks.py): a decorator populates a module-level dict at import
time, and the assembly layer reads the dict instead of importing concrete
classes. `graph.py` therefore never mentions `PlannerAgent` by name, which is
what makes "add a fourth role" a matter of writing one class rather than
editing the graph builder.

Validation happens at *decoration* time, not at first use. A duplicate role
or a non-BaseAgent class raises on import, so the failure surfaces when the
module loads rather than on the first chat turn that reaches that node.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from app.agents.base import AgentRole, BaseAgent

logger = logging.getLogger("agentic_mvp.agents.registry")

T = TypeVar("T", bound=type[BaseAgent])

#: role -> concrete agent class.
AGENT_REGISTRY: dict[AgentRole, type[BaseAgent]] = {}


def register_agent(role: AgentRole, *, replace: bool = False) -> Callable[[T], T]:
    """Register a concrete agent class under `role`.

    `replace=True` is the supported way for a deployment to swap in its own
    implementation of a role (a tenant-specific critic, say) without editing
    this package — an unguarded silent overwrite would instead make a stray
    duplicate import a very hard bug to find.
    """

    def decorator(cls: T) -> T:
        if not issubclass(cls, BaseAgent):
            raise TypeError(f"{cls.__name__} must subclass BaseAgent to be registered")
        if cls.role != role:
            raise TypeError(
                f"{cls.__name__}.role is {cls.role!r} but it is being registered as {role!r}"
            )
        existing = AGENT_REGISTRY.get(role)
        if existing is not None and not replace:
            raise ValueError(
                f"Role {role.value!r} is already registered to {existing.__name__}; "
                "pass replace=True to override deliberately"
            )
        if existing is not None:
            logger.info(
                "Replacing agent for role %s: %s -> %s",
                role.value,
                existing.__name__,
                cls.__name__,
            )
        AGENT_REGISTRY[role] = cls
        return cls

    return decorator


def get_agent(role: AgentRole) -> type[BaseAgent]:
    """Look up a registered agent class, importing the built-ins first."""
    _ensure_builtins_imported()
    try:
        return AGENT_REGISTRY[role]
    except KeyError:
        raise LookupError(f"No agent registered for role {role.value!r}") from None


def list_agents() -> dict[AgentRole, type[BaseAgent]]:
    _ensure_builtins_imported()
    return dict(AGENT_REGISTRY)


def _ensure_builtins_imported() -> None:
    """Import the shipped roles so their decorators have run.

    Deferred rather than imported at module top because planner/executor/
    critic import `registry` themselves for the decorator — a top-level
    import here would close that cycle.
    """
    if len(AGENT_REGISTRY) >= len(AgentRole):
        return
    from app.agents import critic, executor, planner  # noqa: F401
