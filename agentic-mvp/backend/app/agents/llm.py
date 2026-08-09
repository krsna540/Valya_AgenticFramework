"""LLM provider port, plus the two adapters this app ships.

The three agents never import httpx and never know what a model route is.
They call `LLMProvider.complete()` / `.complete_json()` / `.stream()`. That
boundary is what makes the whole runtime testable without a network, and it
is why the stub provider below is a first-class implementation rather than a
mock in the test folder.

**GatewayLLMProvider** talks to the MLflow AI Gateway's OpenAI-compatible
`/chat/completions` endpoint. Deliberately *not* the anthropic/openai SDK:
this stack already decided generation goes through the gateway built into
the existing `mlflow` service, so the only dependency needed is httpx, which
is already present. `model` is the gateway *route* name, matched against
`ModelRoute.route` — the Agent row's `model_name` is resolved to one by the
runtime, not here.

**StubLLMProvider** is deterministic and offline. It exists so that the state
machine, the revision loop, the hook pipeline, the persistence layer and the
SSE contract can all be exercised end-to-end with no credentials — which is
the difference between a runtime you can regression-test and one you can only
smoke-test in staging. It is chosen automatically when no gateway is
configured, so a fresh checkout runs.

**JSON coercion.** `complete_json` is where "LLMs return almost-JSON" is
handled once, rather than in each of the three agents. Fenced blocks, leading
prose, and trailing commentary are all stripped before parsing; a genuinely
unparseable body raises ProviderError, which is retryable, so the caller's
repair loop gets a turn.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.agents.errors import ProviderConfigurationError, ProviderError
from app.agents.tracing import set_span_attributes, set_span_outputs, traced_span
from app.core.config import settings

logger = logging.getLogger("agentic_mvp.agents.llm")


# --- Wire types -------------------------------------------------------------


class LLMMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str  # system | user | assistant
    content: str


class LLMRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    messages: list[LLMMessage]
    model: str
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, gt=0)
    #: Free-form label (planner/executor/critic) used for logging and for the
    #: stub's response selection. Never sent upstream.
    purpose: str = "generic"
    stop: list[str] | None = None

    def with_messages(self, messages: list[LLMMessage]) -> LLMRequest:
        return self.model_copy(update={"messages": messages})


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


# --- Port -------------------------------------------------------------------


class LLMProvider(ABC):
    """The generation boundary. Two required operations; the other two are
    provided as templates on top of them so an adapter only implements what
    is genuinely provider-specific."""

    #: Human-readable identifier, surfaced in run records.
    name: str = "abstract"

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """One non-streaming completion."""

    @abstractmethod
    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """Return an async iterator of text deltas.

        Awaitable-returning-an-iterator rather than an async generator, so an
        adapter can do its connection setup (and raise a connection error)
        eagerly at `await provider.stream(...)` instead of on the first
        `__anext__` — a caller that has already started emitting SSE frames
        cannot cleanly turn a late failure into an error response.

        Adapters that can't stream natively chunk a `complete()` result: the
        caller must never have to ask whether streaming is real.
        """

    async def complete_json(
        self,
        request: LLMRequest,
        *,
        schema_hint: str | None = None,
    ) -> dict[str, Any]:
        """Complete, then coerce the body to a JSON object.

        `schema_hint` is appended as a system message rather than passed as a
        provider-native response_format, because gateway routes front several
        providers with inconsistent structured-output support and a prompt
        instruction is the one thing all of them honour.
        """
        messages = list(request.messages)
        if schema_hint:
            messages.append(
                LLMMessage(
                    role="system",
                    content=(
                        "Respond with a single JSON object and nothing else — no prose, "
                        f"no markdown fences. Required shape:\n{schema_hint}"
                    ),
                )
            )
        response = await self.complete(request.with_messages(messages))
        return coerce_json_object(response.text, purpose=request.purpose)

    async def healthcheck(self) -> bool:
        """Cheap liveness probe. Default: assume healthy — an adapter with a
        real endpoint should override."""
        return True


async def _traced_complete(
    provider_name: str,
    request: LLMRequest,
    impl: Any,
) -> LLMResponse:
    """Wrap one adapter's actual completion call in an MLflow LLM span.

    Shared by all three adapters below rather than duplicated per class —
    this is the one place "what does an LLM call look like in a trace"
    gets decided, matching this codebase's rule of one definition per
    cross-cutting concern (see lifecycle.py's `instrumented` docstring for
    the same reasoning applied to node timing/retry/tracing). `impl` is a
    zero-arg async callable so this helper never needs to know an adapter's
    own dispatch logic (route -> provider, streaming-vs-not, etc).
    """
    last_user = next(
        (m.content for m in reversed(request.messages) if m.role == "user"), ""
    )
    with traced_span(
        f"llm.{provider_name}.complete",
        span_type="LLM",
        inputs={
            "purpose": request.purpose,
            "route": request.model,
            "message_count": len(request.messages),
            "last_user_message": last_user,
        },
        attributes={
            "llm.provider": provider_name,
            "llm.route": request.model,
            "llm.purpose": request.purpose,
            "llm.temperature": request.temperature,
            "llm.max_tokens": request.max_tokens,
        },
    ) as span:
        response: LLMResponse = await impl()
        set_span_outputs(
            span, {"text": response.text, "finish_reason": response.finish_reason or ""}
        )
        set_span_attributes(
            span,
            {
                "llm.model": response.model,
                "llm.input_tokens": response.input_tokens,
                "llm.output_tokens": response.output_tokens,
            },
        )
        return response


# --- JSON coercion ----------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def coerce_json_object(text: str, *, purpose: str = "generic") -> dict[str, Any]:
    """Extract the first JSON object from a model response.

    Three strategies, cheapest first: parse as-is, unwrap a fenced block,
    then brace-match the first balanced `{...}` (which survives both leading
    prose and trailing commentary). Anything else raises ProviderError —
    retryable, so the caller re-prompts with the parse failure as feedback.
    """
    candidate = (text or "").strip()
    if not candidate:
        raise ProviderError("Model returned an empty body", purpose=purpose)

    attempts: list[str] = [candidate]

    fenced = _FENCE_RE.search(candidate)
    if fenced:
        attempts.append(fenced.group(1).strip())

    start = candidate.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(candidate)):
            char = candidate[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    attempts.append(candidate[start : idx + 1])
                    break

    for attempt in attempts:
        try:
            parsed = json.loads(attempt)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            # Some models answer a "give me steps" prompt with a bare array.
            # Accepting it under a conventional key is strictly better than
            # burning a retry on a response that is semantically correct.
            return {"items": parsed}

    raise ProviderError(
        "Model response was not parseable as JSON",
        purpose=purpose,
        preview=candidate[:300],
    )


# --- Gateway adapter --------------------------------------------------------


class GatewayLLMProvider(LLMProvider):
    """MLflow AI Gateway adapter (OpenAI-compatible REST).

    One `httpx.AsyncClient` is held for the provider's lifetime so connections
    are pooled across a run — creating a client per call is the standard way
    to turn a 200ms turn into a 2s one under load.
    """

    name = "mlflow-gateway"

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 60.0,
        api_key: str | None = None,
    ) -> None:
        if not base_url:
            raise ProviderConfigurationError("No LLM gateway URL configured")
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_s,
            headers=headers,
        )

    def _payload(self, request: LLMRequest, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [m.model_dump() for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
        }
        if request.stop:
            payload["stop"] = request.stop
        return payload

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return await _traced_complete(self.name, request, lambda: self._complete_impl(request))

    async def _complete_impl(self, request: LLMRequest) -> LLMResponse:
        try:
            response = await self._client.post(
                "/v1/chat/completions", json=self._payload(request, stream=False)
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"LLM gateway request failed: {exc}", model=request.model, purpose=request.purpose
            ) from exc

        if response.status_code >= 400:
            # 4xx other than 408/429 is a request problem — retrying an
            # unknown model or a malformed body just wastes the budget.
            hard = 400 <= response.status_code < 500 and response.status_code not in (408, 429)
            error: ProviderError = (
                ProviderConfigurationError if hard else ProviderError
            )(
                f"LLM gateway returned {response.status_code}",
                model=request.model,
                purpose=request.purpose,
                body=response.text[:500],
            )
            raise error

        try:
            body = response.json()
            choice = body["choices"][0]
            text = choice["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"Unexpected LLM gateway response shape: {exc}",
                model=request.model,
                body=response.text[:500],
            ) from exc

        usage = body.get("usage") or {}
        return LLMResponse(
            text=text,
            model=body.get("model", request.model),
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            finish_reason=choice.get("finish_reason"),
            raw=body,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        async def _iter() -> AsyncIterator[str]:
            try:
                async with self._client.stream(
                    "POST", "/v1/chat/completions", json=self._payload(request, stream=True)
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise ProviderError(
                            f"LLM gateway returned {response.status_code} on stream",
                            model=request.model,
                            body=response.text[:500],
                        )
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if data == "[DONE]":
                            return
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0].get("delta", {}).get("content")
                        except (ValueError, KeyError, IndexError, TypeError):
                            # A single malformed SSE frame is not worth
                            # failing a turn that is otherwise streaming fine.
                            continue
                        if delta:
                            yield delta
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"LLM gateway stream failed: {exc}", model=request.model
                ) from exc

        return _iter()

    async def healthcheck(self) -> bool:
        try:
            response = await self._client.get("/health", timeout=5.0)
            return response.status_code < 400
        except httpx.HTTPError:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()


# --- Direct provider adapter (bypasses the gateway) -------------------------


class DirectLLMProvider(LLMProvider):
    """Calls Anthropic and OpenAI directly over httpx — no gateway, no SDK.

    Why this exists alongside GatewayLLMProvider: MLflow's AI Gateway
    (>=3.0, built into `mlflow server`) turned out to be UI/REST-managed —
    LLM Connections and Endpoints are created by clicking through
    `/#/settings` and `/#/gateway`, with no documented way to provision them
    from a docker-compose init container (verified against MLflow's own
    docs during this build; there is no `config.yaml` + `mlflow gateway
    start` route-list anymore — that was the older, since-superseded
    "Experimental" gateway). That makes the gateway unsuitable as the ONLY
    path to a real LLM call in a `docker compose up` that has to work with
    no manual clicking, which is what this session's "real LLM calls, split
    by role" decision actually requires.

    This adapter is the practical path for that: httpx straight to each
    provider's native REST API, still no SDK dependency (same reasoning as
    GatewayLLMProvider's docstring — httpx is already present). The mlflow
    service stays in docker-compose for tracking/observability and as the
    on-ramp to the gateway once someone completes its one-time UI setup
    (see docker-compose.yml's mlflow-gateway comment) — this class is just
    what actually answers chat/plan/critique calls in the meantime.

    Role -> provider is resolved from the *route name* on the request
    (`request.model`, set per-role by app.agents.state.resolve_model_route):
    whichever of settings.agent_llm_route_planner/_executor/_critic equals
    the incoming route name decides Anthropic vs OpenAI. An agent with an
    explicit, non-route model_name (see default_model_routes()) is matched
    by a simple substring heuristic ("claude"/"gpt"/"openai" in the name) —
    good enough for the common case; an unrecognized name falls back to
    whichever provider has a key configured, preferring Anthropic.
    """

    name = "direct"

    def __init__(
        self,
        *,
        anthropic_api_key: str = "",
        openai_api_key: str = "",
        anthropic_model: str = "claude-sonnet-5",
        openai_model: str = "gpt-4o-mini",
        timeout_s: float = 60.0,
    ) -> None:
        if not anthropic_api_key and not openai_api_key:
            raise ProviderConfigurationError(
                "AGENT_LLM_PROVIDER=direct requires at least one of "
                "ANTHROPIC_API_KEY / OPENAI_API_KEY to be set"
            )
        self._anthropic_key = anthropic_api_key
        self._openai_key = openai_api_key
        self._anthropic_model = anthropic_model
        self._openai_model = openai_model
        self._client = httpx.AsyncClient(timeout=timeout_s)

    def _provider_for_route(self, route: str) -> str:
        if route == settings.agent_llm_route_executor:
            return "openai"
        if route in (settings.agent_llm_route_planner, settings.agent_llm_route_critic):
            return "anthropic"
        lowered = route.lower()
        if "claude" in lowered or "anthropic" in lowered:
            return "anthropic"
        if "gpt" in lowered or "openai" in lowered:
            return "openai"
        return "anthropic" if self._anthropic_key else "openai"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return await _traced_complete(self.name, request, lambda: self._complete_impl(request))

    async def _complete_impl(self, request: LLMRequest) -> LLMResponse:
        provider = self._provider_for_route(request.model)
        if provider == "anthropic" and self._anthropic_key:
            return await self._complete_anthropic(request)
        if provider == "openai" and self._openai_key:
            return await self._complete_openai(request)
        # Configured for one provider only and the route resolved to the
        # other — fall back to whichever key is actually present rather
        # than hard-failing a run over a routing preference.
        if self._anthropic_key:
            return await self._complete_anthropic(request)
        return await self._complete_openai(request)

    async def _complete_anthropic(self, request: LLMRequest) -> LLMResponse:
        system_parts = [m.content for m in request.messages if m.role == "system"]
        turns = [
            {"role": m.role, "content": m.content}
            for m in request.messages
            if m.role in ("user", "assistant")
        ]
        payload: dict[str, Any] = {
            "model": self._anthropic_model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": turns or [{"role": "user", "content": ""}],
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if request.stop:
            payload["stop_sequences"] = request.stop
        try:
            response = await self._client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._anthropic_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"Anthropic request failed: {exc}", model=self._anthropic_model, purpose=request.purpose) from exc

        if response.status_code >= 400:
            hard = 400 <= response.status_code < 500 and response.status_code not in (408, 429)
            error_cls = ProviderConfigurationError if hard else ProviderError
            raise error_cls(
                f"Anthropic returned {response.status_code}", model=self._anthropic_model, purpose=request.purpose, body=response.text[:500]
            )

        try:
            body = response.json()
            blocks = body.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            usage = body.get("usage") or {}
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError(f"Unexpected Anthropic response shape: {exc}", model=self._anthropic_model, body=response.text[:500]) from exc

        return LLMResponse(
            text=text,
            model=body.get("model", self._anthropic_model),
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            finish_reason=body.get("stop_reason"),
            raw=body,
        )

    async def _complete_openai(self, request: LLMRequest) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._openai_model,
            "messages": [m.model_dump() for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.stop:
            payload["stop"] = request.stop
        try:
            response = await self._client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._openai_key}", "Content-Type": "application/json"},
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenAI request failed: {exc}", model=self._openai_model, purpose=request.purpose) from exc

        if response.status_code >= 400:
            hard = 400 <= response.status_code < 500 and response.status_code not in (408, 429)
            error_cls = ProviderConfigurationError if hard else ProviderError
            raise error_cls(
                f"OpenAI returned {response.status_code}", model=self._openai_model, purpose=request.purpose, body=response.text[:500]
            )

        try:
            body = response.json()
            choice = body["choices"][0]
            text = choice["message"]["content"] or ""
            usage = body.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"Unexpected OpenAI response shape: {exc}", model=self._openai_model, body=response.text[:500]) from exc

        return LLMResponse(
            text=text,
            model=body.get("model", self._openai_model),
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            finish_reason=choice.get("finish_reason"),
            raw=body,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        # Chunked-complete rather than a native SSE parse for either
        # upstream — see LLMProvider.stream's docstring: "adapters that
        # can't stream natively chunk a complete() result", which is a
        # deliberate scope cut here (both providers' native SSE shapes
        # differ from GatewayLLMProvider's OpenAI-compatible one and from
        # each other, and chat's token-by-token UX degrades gracefully to
        # word-by-word rather than needing two more SSE parsers).
        response = await self.complete(request)

        async def _iter() -> AsyncIterator[str]:
            for word in response.text.split(" "):
                yield word + " "

        return _iter()

    async def healthcheck(self) -> bool:
        return bool(self._anthropic_key or self._openai_key)

    async def aclose(self) -> None:
        await self._client.aclose()


# --- Deterministic stub adapter ---------------------------------------------


class StubLLMProvider(LLMProvider):
    """Offline, deterministic provider.

    Not a mock: it produces structurally valid planner/executor/critic
    payloads, so the full graph — including the revision loop and the
    critic's routing — runs identically to the gateway path. Determinism
    comes from hashing the prompt, which means the same objective always
    yields the same plan and tests can assert on it.

    The critic deliberately does *not* always accept: a run whose objective
    hashes into the rejection band exercises one revision, so the loop is
    covered by any end-to-end test rather than only by a targeted one.
    """

    name = "stub"

    def __init__(self, *, latency_s: float = 0.0) -> None:
        self._latency_s = latency_s

    @staticmethod
    def _seed(request: LLMRequest) -> int:
        joined = "\n".join(m.content for m in request.messages)
        return int(hashlib.sha256(joined.encode("utf-8")).hexdigest()[:8], 16)

    @staticmethod
    def _objective(request: LLMRequest) -> str:
        for message in reversed(request.messages):
            if message.role == "user":
                return message.content.strip().splitlines()[0][:400]
        return "the requested task"

    @staticmethod
    def _capabilities(request: LLMRequest) -> tuple[list[str], list[str]]:
        """Recover the tool and skill names the planner prompt offered.

        Parsing them back out of the prompt is a little indirect, but it is
        exactly what a real model does with the same text, and it is the only
        channel available — `LLMRequest` carries messages, not structured
        capabilities, and widening it just for the stub would leak a test
        concern into the production interface.

        Without this the stub never selects a tool or a skill, so the whole
        activation path (tool_call / skill_call events, the PreToolUse hook
        gate, ToolInvoker) is dead code for anyone running the default
        offline provider — which is the default, and therefore most people.
        """
        tools: list[str] = []
        skills: list[str] = []
        target: list[str] | None = None
        for message in request.messages:
            for line in message.content.splitlines():
                stripped = line.strip()
                if stripped.startswith("Tools available"):
                    target = tools
                elif stripped.startswith("Skills available"):
                    target = skills
                elif stripped.startswith("- ") and target is not None:
                    # Lines are rendered by prompts.py as "- name[ flags]: description".
                    name = stripped[2:].split(":", 1)[0].split(" [")[0].strip()
                    if name:
                        target.append(name)
                elif not stripped:
                    target = None
        return tools, skills

    def _plan(self, request: LLMRequest) -> dict[str, Any]:
        objective = self._objective(request)
        seed = self._seed(request)
        tools, skills = self._capabilities(request)
        step_count = 2 + (seed % 2)
        titles = [
            "Gather the relevant context",
            "Analyse the gathered material",
            "Compose the answer",
        ]
        steps = [
            {
                "id": f"step_{i + 1}",
                "title": titles[i % len(titles)],
                "instruction": f"{titles[i % len(titles)]} for: {objective}",
                # First step uses a tool if one is offered; last step loads a
                # skill. Enough to exercise both activation paths on every
                # run without pretending to be real tool selection.
                "tool_name": tools[0] if (i == 0 and tools) else None,
                "skill_name": skills[0] if (i == step_count - 1 and skills) else None,
                "depends_on": [f"step_{i}"] if i else [],
            }
            for i in range(step_count)
        ]
        return {
            "objective": objective,
            "steps": steps,
            "complexity": 1 + (seed % 5),
            "rationale": "Deterministic stub plan (no LLM gateway configured).",
        }

    def _critique(self, request: LLMRequest) -> dict[str, Any]:
        seed = self._seed(request)
        # ~1 in 4 first passes is sent back once, so the revision loop is
        # exercised by ordinary runs and not only by contrived tests.
        already_revised = any("Revision" in m.content for m in request.messages)
        reject = (seed % 4 == 0) and not already_revised
        if reject:
            return {
                "verdict": "revise",
                "score": 0.55,
                "feedback": (
                    "The draft addresses the objective but is thin on specifics. "
                    "Tie each claim back to a concrete step result."
                ),
                "issues": ["Insufficient grounding in step results"],
                "target_step_ids": [],
            }
        return {
            "verdict": "accept",
            "score": 0.86,
            "feedback": "Addresses the objective and is consistent with the step results.",
            "issues": [],
            "target_step_ids": [],
        }

    def _text(self, request: LLMRequest) -> str:
        if request.purpose == "planner":
            return json.dumps(self._plan(request))
        if request.purpose == "critic":
            return json.dumps(self._critique(request))
        objective = self._objective(request)
        return (
            f"[stub:{request.model}] Working on: {objective}\n\n"
            "This response is generated by the deterministic stub provider because no "
            "LLM gateway is configured. Set AGENT_LLM_PROVIDER=gateway and "
            "AGENT_LLM_GATEWAY_URL to route generation through the MLflow AI Gateway."
        )

    async def complete(self, request: LLMRequest) -> LLMResponse:
        return await _traced_complete(self.name, request, lambda: self._complete_impl(request))

    async def _complete_impl(self, request: LLMRequest) -> LLMResponse:
        if self._latency_s:
            await asyncio.sleep(self._latency_s)
        text = self._text(request)
        return LLMResponse(
            text=text,
            model=f"stub/{request.model}",
            input_tokens=sum(len(m.content.split()) for m in request.messages),
            output_tokens=len(text.split()),
            finish_reason="stop",
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        response = await self.complete(request)

        async def _iter() -> AsyncIterator[str]:
            for word in response.text.split(" "):
                if self._latency_s:
                    await asyncio.sleep(min(self._latency_s / 20, 0.02))
                yield word + " "

        return _iter()


def default_model_routes(explicit_model_name: str | None) -> dict[str, str]:
    """The `scratchpad["model_routes"]` dict `AgentRunRequest.to_state()`
    seeds every run with (app/agents/runtime.py, read back by
    `app.agents.state.resolve_model_route`).

    An agent with an explicit model_name (anything other than the "default"
    sentinel `AgentRunRequest.model_name` falls back to) keeps that single
    model for every role — unchanged from before role-split routing existed.
    An agent left on "default" gets the per-role routes from settings
    instead, so Planner/Critic go to the strong-reasoning route and Executor
    goes to the fast one without every agent needing to be reconfigured.
    """
    if explicit_model_name and explicit_model_name != "default":
        return {
            "planner": explicit_model_name,
            "executor": explicit_model_name,
            "critic": explicit_model_name,
        }
    return {
        "planner": settings.agent_llm_route_planner,
        "executor": settings.agent_llm_route_executor,
        "critic": settings.agent_llm_route_critic,
    }


# --- Factory ----------------------------------------------------------------


def build_provider(kind: str | None = None) -> LLMProvider:
    """Construct the configured provider.

    Falls back to the stub — loudly — when `gateway` is asked for but not
    reachable-by-configuration. A missing gateway URL in development should
    produce a working app with a warning, not a 500 on every chat turn; a
    production deployment catches the same mistake via the logged warning
    and the `provider` field recorded on every run.
    """
    kind = (kind or settings.agent_llm_provider or "stub").lower()
    if kind == "gateway":
        if not settings.agent_llm_gateway_url:
            logger.warning(
                "AGENT_LLM_PROVIDER=gateway but AGENT_LLM_GATEWAY_URL is unset; "
                "falling back to the deterministic stub provider"
            )
            return StubLLMProvider()
        return GatewayLLMProvider(
            settings.agent_llm_gateway_url,
            timeout_s=settings.agent_llm_timeout_s,
            api_key=settings.agent_llm_api_key or None,
        )
    if kind == "direct":
        if not (settings.anthropic_api_key or settings.openai_api_key):
            logger.warning(
                "AGENT_LLM_PROVIDER=direct but neither ANTHROPIC_API_KEY nor "
                "OPENAI_API_KEY is set; falling back to the deterministic stub provider"
            )
            return StubLLMProvider()
        return DirectLLMProvider(
            anthropic_api_key=settings.anthropic_api_key,
            openai_api_key=settings.openai_api_key,
            anthropic_model=settings.anthropic_model,
            openai_model=settings.openai_model,
            timeout_s=settings.agent_llm_timeout_s,
        )
    if kind == "stub":
        return StubLLMProvider()
    raise ProviderConfigurationError(f"Unknown LLM provider kind: {kind!r}")


@lru_cache(maxsize=4)
def get_llm_provider(kind: str | None = None) -> LLMProvider:
    """Process-wide provider singleton, keyed by kind.

    Cached because GatewayLLMProvider owns an httpx connection pool that
    should outlive a single request. Tests that need a fresh instance call
    `get_llm_provider.cache_clear()`.
    """
    return build_provider(kind)
