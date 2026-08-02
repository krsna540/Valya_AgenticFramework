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

    jwt_secret: str = "change-me-in-prod"
    jwt_algorithm: str = "HS256"
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
