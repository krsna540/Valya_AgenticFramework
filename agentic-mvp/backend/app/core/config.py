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
