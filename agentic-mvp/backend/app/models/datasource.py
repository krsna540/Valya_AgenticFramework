import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Kept as a plain string column (not a DB enum) validated in
# app/schemas/datasource.py, so adding a connector type later is a
# schema-only change. See ROUTE_TYPE_HINTS in app/api/routes/datasources.py
# for the per-type connection_config field hints the UI renders.
CONNECTOR_TYPES = (
    "sharepoint",
    "confluence",
    "rest_api",
    "graphql",
    "sql_database",
    "nosql_database",
    "github",
    "gitlab",
    "web_crawl",
    "file_upload",
)

SECURITY_TIERS = ("Public", "Internal", "Confidential", "Restricted")

# oauth2 | api_key | basic | service_account | none — advisory, matches the
# connector type (see app/api/routes/datasources.py::CONNECTOR_FIELD_SPECS),
# surfaced so the UI can render the right auth affordance without hardcoding
# per-connector logic in the frontend.
AUTH_TYPES = ("oauth2", "api_key", "basic", "service_account", "none")

# full_refresh | incremental — Airbyte's sync-mode vocabulary
# (docs.airbyte.com/platform/understanding-airbyte/airbyte-protocol):
# full_refresh re-pulls everything each sync, incremental pulls only what
# changed since last_synced_at. Advisory in this MVP — POST .../sync is
# still a synchronous stub (see class docstring) that doesn't actually
# branch on this value yet.
SYNC_MODES = ("full_refresh", "incremental")


class Datasource(Base):
    """One connected/connectable source of ingestible content. Lives at the
    tenant level (not the project level) so the same SharePoint site or
    Postgres replica can be wired into more than one Project via
    project_datasources — see app/models/project.py.

    This is deliberately a *scaffold*: connection_config/auth_config store
    non-secret shape only (base URLs, scopes, seed URLs, chunking/embedding
    policy). There is no real OAuth2 handshake, no live SQL/NoSQL tunnel,
    and no crawler — POST /datasources/{id}/connect and .../sync are
    synchronous stub state transitions (see app/api/routes/datasources.py)
    that a later milestone would replace with real connector workers.
    """

    __tablename__ = "datasources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    connector_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # Non-secret connection shape, per connector_type e.g.:
    #  sharepoint:  {site_url, tenant_id}
    #  confluence:  {base_url, space_key}
    #  rest_api:    {base_url, auth_header_name}
    #  graphql:     {endpoint}
    #  sql_database/nosql_database: {host, port, database, use_vpc_tunnel}
    #  github/gitlab: {org_or_group, repo, ref}
    #  web_crawl:   {seed_urls: [...], max_depth, exclusion_regex}
    #  file_upload: {} (files come in through the existing /files upload route)
    connection_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    # not_connected | connected | expired | error
    auth_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_connected")
    # Non-secret auth metadata only (client_id, scopes, auth_type) — actual
    # secrets are never stored here; this is a scaffold, see class docstring.
    auth_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # oauth2 | api_key | basic | service_account | none — see AUTH_TYPES.
    # Defaulted from the connector type's spec at create time but editable,
    # since e.g. rest_api can legitimately use either api_key or basic.
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False, default="none")

    # Public | Internal | Confidential | Restricted
    security_classification: Mapped[str] = mapped_column(String(20), nullable=False, default="Internal")

    # idle | syncing | success | error
    sync_status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # full_refresh | incremental — see SYNC_MODES.
    sync_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="full_refresh")
    # Optional cron expression for an unattended recurring sync — same
    # free-text-cron convention as Project.schedule_cron
    # (app/models/project.py), advisory only (no scheduler wired up yet).
    sync_schedule_cron: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # {strategy: "token"|"semantic"|"layout_aware", chunk_size, overlap}
    chunking_policy: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    # {model_name, dimensions}
    embedding_policy: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    tenant = relationship("Tenant")
