import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin_users,
    agents,
    auth,
    chat,
    datasources,
    files,
    hooks,
    models,
    personas,
    platform,
    plugins,
    policies,
    projects,
    prompts,
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
