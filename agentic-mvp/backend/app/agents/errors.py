"""Exception taxonomy for the agent runtime.

Two axes matter to callers and neither is expressible with a single base
class, so both are encoded explicitly on every error:

  * `retryable` — is a bare retry plausibly going to help? Drives both the
    in-process `@retryable` decorator (app/agents/lifecycle.py) and
    Temporal's `RetryPolicy.non_retryable_error_types` (app/agents/durable/),
    so the same classification governs a 3-attempt in-node retry and a
    workflow-level activity retry. Get this wrong in the permissive
    direction and a deterministic failure burns the whole retry budget.

  * `terminal` — should the *run* end, or can the graph route around it? A
    PlanValidationError is retryable (ask the planner again) but a
    BudgetExceededError is terminal (asking again costs more money).

Everything here inherits AgentRuntimeError so `app/services/agent_runner.py`
and the Temporal activities can have exactly one `except` clause for
"the runtime failed in a way it understands", distinct from the bare
`except Exception` fault boundary that catches genuine bugs.
"""
from __future__ import annotations

from typing import Any


class AgentRuntimeError(Exception):
    """Base for every failure this runtime raises deliberately."""

    #: Whether re-running the same operation could plausibly succeed.
    retryable: bool = False
    #: Whether this failure should end the run rather than be routed around.
    terminal: bool = False

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe shape used in run/step records and SSE error events."""
        return {
            "error_type": type(self).__name__,
            "message": self.message,
            "retryable": self.retryable,
            "terminal": self.terminal,
            "details": self.details,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}({self.message!r}, {self.details!r})"


class ProviderError(AgentRuntimeError):
    """The LLM provider (MLflow AI Gateway, or whatever is configured) was
    unreachable, timed out, or returned a non-2xx / unparseable body."""

    retryable = True


class ProviderConfigurationError(ProviderError):
    """The provider is misconfigured (no gateway URL, unknown model route).

    Deliberately *not* retryable even though it subclasses ProviderError:
    retrying a config mistake just burns the budget more slowly.
    """

    retryable = False
    terminal = True


class PlanValidationError(AgentRuntimeError):
    """The planner produced something that isn't a usable plan — malformed
    JSON, zero steps, a step referencing a tool the agent doesn't have.

    Retryable because the fix is "ask the planner again, with the validation
    error fed back in as context" — which is exactly what the planner node's
    repair loop does before giving up.
    """

    retryable = True


class ToolExecutionError(AgentRuntimeError):
    """A tool invocation failed. Retryable by default because the common
    causes (network blip, upstream 503) are transient; pass
    `retryable=False` explicitly for a 4xx-shaped failure."""

    retryable = True

    def __init__(self, message: str, *, retryable: bool = True, **details: Any) -> None:
        super().__init__(message, **details)
        self.retryable = retryable


class AgentTimeoutError(AgentRuntimeError):
    """A single agent node exceeded its wall-clock budget."""

    retryable = True


class BudgetExceededError(AgentRuntimeError):
    """The run exhausted a hard budget (revisions, steps, tokens, or
    wall-clock). Terminal: the graph must finalize, not loop again."""

    terminal = True


class RunHaltedError(AgentRuntimeError):
    """A guardrail hook denied the run (HookHaltException surfaced into the
    runtime's own taxonomy). Terminal by construction — the caller renders
    `fallback_message` instead of a model answer."""

    terminal = True

    def __init__(self, fallback_message: str, *, stage: str | None = None) -> None:
        super().__init__(fallback_message, stage=stage)
        self.fallback_message = fallback_message
        self.stage = stage


#: Error class names that Temporal must never retry. Kept as strings because
#: that is the shape `temporalio.common.RetryPolicy` wants, and derived from
#: the classes themselves so the two can't drift.
NON_RETRYABLE_ERROR_TYPES: tuple[str, ...] = tuple(
    cls.__name__
    for cls in (
        ProviderConfigurationError,
        BudgetExceededError,
        RunHaltedError,
    )
)
