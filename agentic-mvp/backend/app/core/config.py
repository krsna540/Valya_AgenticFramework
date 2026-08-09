from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    project_name: str = "Knowledge Nexus"
    api_v1_prefix: str = "/api/v1"
    environment: str = "development"

    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_user: str = "agentic"
    postgres_password: str = "agentic"
    postgres_db: str = "agentic"

    # RS256 (asymmetric) as of 2026-08-08 — see PLATFORM_ARCHITECTURE.md
    # §14's identity layer and the gap-map entry that flagged HS256 as a
    # hard blocker: a shared HS256 secret lets every verifier also MINT
    # tokens, which is fine for one process and wrong the moment a second
    # service (the split Stream Service, app/stream.py) only needs to
    # verify. RS256 keeps the private key on the API service alone; every
    # other service holds only jwt_public_key.
    #
    # Keys are PEM strings (not file paths) so they pass through as plain
    # env vars in docker-compose with no volume mount — generate a pair
    # with `python scripts/generate_jwt_keypair.py` and put both blocks in
    # your untracked .env (see .env.example). jwt_secret/HS256 remain as
    # a fallback so a bare `docker compose up` with no .env still boots
    # (decode_access_token tries RS256 first, then falls back — see
    # security.py) — never rely on the fallback outside local dev.
    jwt_algorithm: str = "RS256"
    jwt_private_key: str = ""
    jwt_public_key: str = ""
    jwt_secret: str = "change-me-in-prod"  # HS256 dev fallback only
    access_token_expire_minutes: int = 60 * 24

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    upload_dir: str = "data/uploads"
    max_upload_bytes: int = 25 * 1024 * 1024  # 25 MB

    # Agent Skills (agentskills.io) directory-format packages — SKILL.md +
    # optional scripts/references/assets, uploaded as a zip. See
    # app/skills/package_spec.py and app/api/routes/skills.py.
    skill_packages_dir: str = "data/skill_packages"
    max_skill_package_zip_bytes: int = 10 * 1024 * 1024  # 10 MB compressed upload
    max_skill_package_extracted_bytes: int = 40 * 1024 * 1024  # 40 MB total after extraction (zip-bomb guard)
    max_skill_package_files: int = 500

    # Open Policy Agent — the authorization decision point for the three
    # role-based flows (super_admin/admin/user). See app/core/opa.py and
    # backend/policies/authz.rego. Always fails closed (denies) when OPA
    # can't be reached — there is no "allow if OPA is down" mode, by design
    # (see docs/AUTHORIZATION.md).
    opa_url: str = "http://opa:8181"
    opa_timeout_s: float = 2.0

    # Redis 8 (AGPLv3) — PLATFORM_ARCHITECTURE.md §3.7. See app/core/redis_client.py.
    redis_url: str = "redis://redis:6379/0"

    # MinIO — PLATFORM_ARCHITECTURE.md §3.8. See app/core/minio_client.py.
    # Content-addressed skill blobs live in minio_skills_bucket; nothing
    # else is migrated off local disk this session (uploaded documents,
    # persona files stay where they were — see the module docstring on
    # minio_client.py for exactly what's wired vs deferred).
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "valya"
    minio_secret_key: str = "valya-dev-secret"
    minio_secure: bool = False
    minio_skills_bucket: str = "skills"

    # Super Admin platform-overview KPIs (app/api/routes/platform.py) —
    # configured targets, not computed from anything: the "budget $X" and
    # "SLO Yms" figures a real deployment would set in an ops runbook.
    platform_llm_budget_usd: float = 12_000.0
    platform_gateway_slo_ms: int = 2_000

    # --- Agent runtime (app/agents/) ---------------------------------------
    # The Planner -> Executor -> Critic graph. These are *deployment*
    # settings; per-run budgets (revisions, timeouts, tool execution) are
    # per-Agent and live in Agent.runtime_config -> AgentRuntimeConfig.

    # "stub"    -> deterministic offline provider (app/agents/llm.py). The
    #              default so a fresh checkout runs with no credentials, and
    #              so the graph/loop/persistence can be regression-tested
    #              without a network.
    # "gateway" -> MLflow AI Gateway, OpenAI-compatible REST over httpx. No
    #              anthropic/openai SDK by design — generation goes through
    #              the gateway built into the existing `mlflow` service.
    agent_llm_provider: str = "stub"
    agent_llm_gateway_url: str = ""
    agent_llm_api_key: str = ""
    agent_llm_timeout_s: float = 60.0

    # Role-split gateway routes (PLATFORM_ARCHITECTURE.md provider-split
    # decision: Planner and Critic are the strong-reasoning roles and route
    # to Claude via the gateway's "claude-strong" route; Executor is the
    # high-volume, latency-sensitive role and routes to OpenAI's
    # "openai-fast" route instead — see mlflow-gateway/config.yaml, which
    # defines both route names against ANTHROPIC_API_KEY / OPENAI_API_KEY.
    # Only takes effect when an Agent's own model_name is left as "default"
    # — an agent with an explicit model_name keeps using that one model for
    # every role (see app/agents/state.py::resolve_model_route). Values are
    # gateway route names when agent_llm_provider="gateway"; with the
    # "stub" provider they're just labels threaded through for logging.
    agent_llm_route_planner: str = "claude-strong"
    agent_llm_route_executor: str = "openai-fast"
    agent_llm_route_critic: str = "claude-strong"

    # "direct" provider (app/agents/llm.py::DirectLLMProvider) — httpx
    # straight to Anthropic/OpenAI, no gateway in the loop. See that class's
    # docstring for why this exists alongside "gateway": MLflow's AI Gateway
    # (>=3.0) turned out to require manual UI setup with no documented
    # provisioning API, which is incompatible with "docker compose up and
    # it just works" for a real LLM call. This is the provider actually
    # used when AGENT_LLM_PROVIDER=direct; "gateway" remains available for
    # anyone who completes the mlflow-gateway UI setup themselves.
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    # claude-sonnet-5: current strong-reasoning Claude model as of this
    # build (2026-08-08) — Planner/Critic's route. gpt-4o-mini is OpenAI's
    # fast/cheap tier for Executor's route; check platform.openai.com for
    # whatever is current when you deploy, since this one isn't pinned from
    # as authoritative a source as the Anthropic model string is.
    anthropic_model: str = "claude-sonnet-5"
    openai_model: str = "gpt-4o-mini"

    # "memory"   -> per-process LangGraph checkpoints, lost on restart.
    # "postgres" -> AsyncPostgresSaver; runs become resumable and HITL
    #               interrupts survive a restart. Requires the psycopg[binary]
    #               extra. Degrades to memory with a warning if unavailable —
    #               see app/agents/checkpointer.py for why it never hard-fails.
    agent_checkpointer: str = "memory"

    # Temporal durable envelope (app/agents/durable/). Off => runs execute
    # in-process via LocalRunner, which is correct for development and for
    # short interactive chat turns. On => each turn is a durable workflow
    # that survives a backend restart mid-run.
    temporal_enabled: bool = False
    temporal_host: str = "temporal:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "valya-agents"
    # Ceiling for one whole agent run as a workflow. Must exceed
    # AgentRuntimeConfig.run_timeout_s or the envelope kills runs the graph
    # still considers healthy.
    temporal_workflow_timeout_s: float = 1_800.0

    # MLflow Tracing (app/agents/tracing.py) — OpenTelemetry-based spans over
    # every agent execution: one root trace per run, an AGENT span per
    # Planner/Executor/Critic node, and an LLM span per model call, all
    # logged to the same `mlflow` service already in docker-compose (no
    # separate OTel collector — see [[project_check_builtin_before_new_service]]
    # reasoning: this stack already has a trace store, standing up a second
    # one would just be two places traces can end up). `mlflow` is already a
    # requirements.txt dependency (mlflow[genai]) from the gateway work;
    # tracing reuses that same package as a client against the tracking
    # server's REST API — nothing new to install.
    #
    # Best-effort by contract, same isolation rule as EventSink.emit: a
    # tracing failure (package import error, tracking server unreachable,
    # span export error) is logged and swallowed, never allowed to fail or
    # slow down the agent run it is observing. Disable entirely with
    # MLFLOW_TRACING_ENABLED=false if the mlflow service isn't running.
    mlflow_tracing_enabled: bool = True
    mlflow_tracking_uri: str = "http://mlflow:5000"
    mlflow_experiment_name: str = "agentic-mvp-agent-runs"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
