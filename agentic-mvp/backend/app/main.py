import asyncio
import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin_overview,
    admin_users,
    agents,
    auth,
    chat,
    datasources,
    files,
    hooks,
    manifests,
    models,
    personas,
    platform,
    platform_catalog,
    platform_rules,
    playbooks,
    plugins,
    policies,
    projects,
    prompts,
    runs,
    skills,
    tenants,
    tools,
)
from app.core.config import settings

# NFR-2 (skills spec): app loggers (agentic_mvp.*) must never rely on print()
# or fall through to stdout un-configured — explicitly target stderr so
# operational traces stay out of anything parsing stdout downstream.
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

app = FastAPI(title=settings.project_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.api_v1_prefix)
app.include_router(platform.router, prefix=settings.api_v1_prefix)
app.include_router(tenants.router, prefix=settings.api_v1_prefix)
app.include_router(admin_users.router, prefix=settings.api_v1_prefix)
app.include_router(personas.router, prefix=settings.api_v1_prefix)
app.include_router(policies.router, prefix=settings.api_v1_prefix)
app.include_router(datasources.router, prefix=settings.api_v1_prefix)
app.include_router(projects.router, prefix=settings.api_v1_prefix)
app.include_router(agents.router, prefix=settings.api_v1_prefix)
app.include_router(skills.router, prefix=settings.api_v1_prefix)
app.include_router(tools.router, prefix=settings.api_v1_prefix)
app.include_router(plugins.router, prefix=settings.api_v1_prefix)
app.include_router(hooks.router, prefix=settings.api_v1_prefix)
app.include_router(prompts.router, prefix=settings.api_v1_prefix)
app.include_router(files.router, prefix=settings.api_v1_prefix)
app.include_router(models.router, prefix=settings.api_v1_prefix)
app.include_router(chat.router, prefix=settings.api_v1_prefix)
app.include_router(playbooks.router, prefix=settings.api_v1_prefix)
app.include_router(runs.router, prefix=settings.api_v1_prefix)
app.include_router(manifests.router, prefix=settings.api_v1_prefix)
app.include_router(admin_overview.router, prefix=settings.api_v1_prefix)
app.include_router(platform_catalog.router, prefix=settings.api_v1_prefix)
app.include_router(platform_rules.router, prefix=settings.api_v1_prefix)


@app.on_event("startup")
async def _ensure_minio_buckets() -> None:
    """Idempotent bucket creation for the skill blob mirror (see
    app/core/minio_client.py). A `minio-init` one-shot container in
    docker-compose does this too, before backend ever starts — this is a
    second, harmless call so `ensure_bucket`'s own docstring ("safe to call
    repeatedly") is actually exercised, and so the app is self-healing if
    ever run outside that compose file. Non-fatal if MinIO isn't reachable
    yet: ensure_bucket already logs and swallows (see its own try/except).
    """
    from app.core.minio_client import ensure_bucket

    await asyncio.to_thread(ensure_bucket, settings.minio_skills_bucket)


@app.on_event("startup")
async def _init_agent_tracing() -> None:
    """Point MLflow tracing at the tracking server so agent execution (every
    Planner/Executor/Critic run started through the chat SSE path or the
    /runs API, in-process here or replayed via a Temporal activity — see the
    matching call in durable/worker.py) is logged as a trace. See
    app/agents/tracing.py for the fault-isolation contract; this call itself
    can never fail the app's startup.
    """
    from app.agents.tracing import init_tracing

    await asyncio.to_thread(init_tracing)


@app.on_event("shutdown")
async def _release_agent_runtime_resources() -> None:
    """Release the long-lived connections the agent runtime holds.

    Both are process-wide singletons created lazily on first use — the
    LangGraph Postgres checkpointer owns a psycopg connection pool, and the
    Temporal client owns a gRPC channel. Neither is tied to a request, so
    without an explicit shutdown they are only reclaimed when the process
    dies, which leaks connections across a reload in development and delays
    a clean container stop in production.

    Best-effort and independently guarded: a failure releasing one must not
    prevent the other from being released, and neither should turn a normal
    shutdown into a non-zero exit.
    """
    from app.agents.checkpointer import close_checkpointer
    from app.agents.durable.client import close_client
    from app.core.redis_client import close_redis

    for name, closer in (
        ("checkpointer", close_checkpointer),
        ("temporal client", close_client),
        ("redis client", close_redis),
    ):
        try:
            await closer()
        except Exception:  # noqa: BLE001 — shutdown must not fail
            logging.getLogger("agentic_mvp").exception("Error releasing the agent %s", name)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
