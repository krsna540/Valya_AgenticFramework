import uuid
from datetime import datetime, timezone
from typing import TypedDict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import authorize, get_current_user
from app.core.database import get_db
from app.core.tenant_scope import apply_own_tenant, is_visible
from app.models.datasource import Datasource
from app.models.user import User
from app.schemas.datasource import DatasourceCreate, DatasourceRead, DatasourceUpdate
from app.services import audit

router = APIRouter(prefix="/datasources", tags=["datasources"])


class ConnectorField(TypedDict, total=False):
    key: str
    label: str
    # "string" | "number" | "boolean" | "select"
    type: str
    required: bool
    # UI-masking hint only (password-style input) — this app never stores
    # real secrets (see Datasource's class docstring); matches Airbyte's
    # `airbyte_secret` spec.json annotation, which is the same kind of
    # display-only masking, not encryption-at-rest.
    secret: bool
    options: list[str]
    help_text: str


def _field(key: str, label: str, type_: str = "string", *, required: bool = True, secret: bool = False, options: list[str] | None = None, help_text: str | None = None) -> ConnectorField:
    f: ConnectorField = {"key": key, "label": label, "type": type_, "required": required, "secret": secret}
    if options is not None:
        f["options"] = options
    if help_text is not None:
        f["help_text"] = help_text
    return f


# Per-connector-type field specs for the frontend's dynamic connection_config
# form — adopted from Airbyte's spec.json convention (JSON-schema-per-source,
# `airbyte_secret` marking sensitive fields). Not enforced server-side
# (connection_config stays a free JSON dict, validated only for shape at the
# DB level), same scaffold boundary as the rest of this model — see
# app/models/datasource.py's class docstring.
CONNECTOR_FIELD_SPECS: dict[str, list[ConnectorField]] = {
    "sharepoint": [
        _field("site_url", "Site URL", help_text="https://<tenant>.sharepoint.com/sites/<site>"),
        _field("tenant_id", "Tenant ID"),
        _field("client_id", "Client (application) ID"),
        _field("client_secret", "Client secret", secret=True),
    ],
    "confluence": [
        _field("base_url", "Base URL", help_text="https://<org>.atlassian.net/wiki"),
        _field("space_key", "Space key"),
        _field("email", "Account email"),
        _field("api_token", "API token", secret=True),
    ],
    "rest_api": [
        _field("base_url", "Base URL"),
        _field("auth_header_name", "Auth header name", required=False, help_text="e.g. Authorization"),
        _field("api_key", "API key", secret=True, required=False),
    ],
    "graphql": [
        _field("endpoint", "GraphQL endpoint"),
        _field("api_key", "API key", secret=True, required=False),
    ],
    "sql_database": [
        _field("host", "Host"),
        _field("port", "Port", "number"),
        _field("database", "Database name"),
        _field("username", "Username"),
        _field("password", "Password", secret=True),
        _field("ssl_mode", "SSL mode", "select", required=False, options=["disable", "require", "verify-full"]),
        _field("use_vpc_tunnel", "Use VPC tunnel", "boolean", required=False),
    ],
    "nosql_database": [
        _field("connection_uri", "Connection URI", secret=True, help_text="e.g. mongodb+srv://..."),
        _field("database", "Database name"),
        _field("use_vpc_tunnel", "Use VPC tunnel", "boolean", required=False),
    ],
    "github": [
        _field("org_or_group", "Organization"),
        _field("repo", "Repository"),
        _field("ref", "Branch / ref", required=False),
        _field("access_token", "Access token", secret=True),
    ],
    "gitlab": [
        _field("org_or_group", "Group"),
        _field("repo", "Project"),
        _field("ref", "Branch / ref", required=False),
        _field("access_token", "Access token", secret=True),
    ],
    "web_crawl": [
        _field("seed_urls", "Seed URLs", help_text="comma-separated list of starting URLs"),
        _field("max_depth", "Max crawl depth", "number", required=False),
        _field("exclusion_regex", "Exclusion regex", required=False),
    ],
    "file_upload": [],
}

# Default auth_type per connector type (see AUTH_TYPES) — the create form
# pre-selects this but the field stays editable (e.g. rest_api can
# legitimately be api_key or basic).
CONNECTOR_DEFAULT_AUTH_TYPE: dict[str, str] = {
    "sharepoint": "oauth2",
    "confluence": "oauth2",
    "rest_api": "api_key",
    "graphql": "api_key",
    "sql_database": "basic",
    "nosql_database": "basic",
    "github": "api_key",
    "gitlab": "api_key",
    "web_crawl": "none",
    "file_upload": "none",
}


@router.get("/connector-types")
def list_connector_types(_: User = Depends(get_current_user)) -> list[dict]:
    return [
        {
            "key": key,
            "default_auth_type": CONNECTOR_DEFAULT_AUTH_TYPE.get(key, "none"),
            "fields": fields,
        }
        for key, fields in CONNECTOR_FIELD_SPECS.items()
    ]


def _get_tenant_datasource(db: Session, current_user: User, datasource_id: uuid.UUID) -> Datasource:
    ds = db.get(Datasource, datasource_id)
    if ds is None or not is_visible(ds.tenant_id, current_user, shared_ok=False):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Datasource not found")
    return ds


@router.get("", response_model=list[DatasourceRead])
def list_datasources(db: Session = Depends(get_db), current_user: User = Depends(authorize("datasource", "list"))) -> list[DatasourceRead]:
    items = (
        apply_own_tenant(db.query(Datasource), Datasource.tenant_id, current_user)
        .order_by(Datasource.created_at.desc())
        .all()
    )
    return [DatasourceRead.model_validate(d) for d in items]


@router.post("", response_model=DatasourceRead, status_code=status.HTTP_201_CREATED)
def create_datasource(
    payload: DatasourceCreate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("datasource", "create")),
) -> DatasourceRead:
    ds = Datasource(tenant_id=current_admin.tenant_id, created_by=current_admin.id, **payload.model_dump())
    db.add(ds)
    db.commit()
    db.refresh(ds)
    audit.record(db, actor=current_admin, action="datasource.create", resource_type="datasource", resource_id=ds.id, extra={"name": ds.name, "connector_type": ds.connector_type})
    return DatasourceRead.model_validate(ds)


@router.get("/{datasource_id}", response_model=DatasourceRead)
def get_datasource(datasource_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(authorize("datasource", "read"))) -> DatasourceRead:
    return DatasourceRead.model_validate(_get_tenant_datasource(db, current_user, datasource_id))


@router.put("/{datasource_id}", response_model=DatasourceRead)
def update_datasource(
    datasource_id: uuid.UUID,
    payload: DatasourceUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("datasource", "update")),
) -> DatasourceRead:
    ds = _get_tenant_datasource(db, current_admin, datasource_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(ds, field, value)
    db.commit()
    db.refresh(ds)
    return DatasourceRead.model_validate(ds)


@router.delete("/{datasource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_datasource(
    datasource_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("datasource", "delete")),
) -> None:
    ds = _get_tenant_datasource(db, current_admin, datasource_id)
    name = ds.name
    db.delete(ds)
    db.commit()
    audit.record(db, actor=current_admin, action="datasource.delete", resource_type="datasource", resource_id=datasource_id, extra={"name": name})
    return None


@router.post("/{datasource_id}/connect", response_model=DatasourceRead)
def connect_datasource(
    datasource_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("datasource", "update")),
) -> DatasourceRead:
    """Stub auth handshake — see app/models/datasource.py's class docstring.
    Synchronously flips auth_status to 'connected' and stamps auth_config
    with a fake connected_at marker. A real implementation would redirect
    through an OAuth2 authorization-code flow (SharePoint/Confluence/GitHub/
    GitLab) or validate a connection string (SQL/NoSQL) here instead."""
    ds = _get_tenant_datasource(db, current_admin, datasource_id)
    ds.auth_status = "connected"
    ds.auth_config = {**ds.auth_config, "connected_at": datetime.now(timezone.utc).isoformat(), "auth_type": "stub"}
    db.commit()
    db.refresh(ds)
    audit.record(db, actor=current_admin, action="datasource.connect", resource_type="datasource", resource_id=ds.id)
    return DatasourceRead.model_validate(ds)


@router.post("/{datasource_id}/sync", response_model=DatasourceRead)
def sync_datasource(
    datasource_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_admin: User = Depends(authorize("datasource", "update")),
) -> DatasourceRead:
    """Stub ingestion run — no real crawler/extractor/chunker/embedder is
    invoked (that pipeline lives in the sibling milestone-based codebase,
    not here). Synchronously marks the datasource as freshly synced so the
    Project/Freeze UI has something meaningful to show."""
    ds = _get_tenant_datasource(db, current_admin, datasource_id)
    if ds.auth_status != "connected" and ds.connector_type != "file_upload":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Connect the datasource before syncing")
    ds.sync_status = "success"
    ds.last_synced_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ds)
    audit.record(db, actor=current_admin, action="datasource.sync", resource_type="datasource", resource_id=ds.id)
    return DatasourceRead.model_validate(ds)
