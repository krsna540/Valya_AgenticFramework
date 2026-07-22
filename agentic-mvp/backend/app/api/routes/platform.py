"""Super Admin-exclusive endpoints: Tenant lifecycle management, assigning
Admins to tenants, and the platform dashboard (overview KPIs, usage/cost,
model catalog + onboarding gates, platform health, audit log) — everything
under the Super Admin flow's sidebar (Overview / Tenants / Admins / Models
/ Cost & billing / Platform health / Audit) that has no Admin-facing
equivalent (see docs/AUTHORIZATION.md and backend/policies/authz.rego).
"""
import statistics
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import authorize_tenant, require_super_admin
from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password
from app.core.slug import unique_slug
from app.models.agent import Agent
from app.models.audit_log import AuditLog
from app.models.datasource import Datasource
from app.models.model_route import ModelRoute
from app.models.policy import Policy
from app.models.project import Project
from app.models.tenant import Tenant
from app.models.usage_event import UsageEvent
from app.models.user import User
from app.schemas.audit_log import AuditLogRead
from app.schemas.model_route import ModelGates, ModelRouteCreate, ModelRouteRead, ModelRouteUpdate
from app.schemas.tenant import TenantCreate, TenantRead, TenantSummary, TenantUpdate
from app.schemas.user import PlatformAdminCreate, PlatformUserRoleUpdate, UserRead
from app.services import audit

router = APIRouter(prefix="/platform", tags=["platform"])


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(pct * (len(ordered) - 1))))
    return ordered[idx]


# --- Tenant lifecycle (Tenant rows themselves — not their contents) --------


@router.get("/tenants", response_model=list[TenantSummary])
def list_tenants(db: Session = Depends(get_db), _: User = Depends(authorize_tenant("list"))) -> list[TenantSummary]:
    """The Super Admin Tenants table: real per-tenant counts + a computed
    tri-layer "layer setup" readout (has this tenant connected any
    Knowledge, published any Expertise, configured any Norms policy?) —
    every field here is a live query, not stored on Tenant itself."""
    tenants = db.query(Tenant).order_by(Tenant.created_at.desc()).all()
    now = datetime.now(timezone.utc)
    month_start = _month_start(now)
    results: list[TenantSummary] = []
    for t in tenants:
        admin_count = db.query(User).filter(User.tenant_id == t.id, User.role == "admin").count()
        user_count = db.query(User).filter(User.tenant_id == t.id, User.role == "user").count()
        workspace_count = db.query(Project).filter(Project.tenant_id == t.id).count()
        mtd_cost = (
            db.query(func.coalesce(func.sum(UsageEvent.cost_usd), 0.0))
            .filter(UsageEvent.tenant_id == t.id, UsageEvent.created_at >= month_start)
            .scalar()
            or 0.0
        )
        has_knowledge = (
            db.query(Datasource).filter(Datasource.tenant_id == t.id, Datasource.is_active == True).first()  # noqa: E712
            is not None
        )
        has_expertise = (
            db.query(Agent).filter(Agent.tenant_id == t.id, Agent.status == "Active").first() is not None
        )
        has_norms = (
            db.query(Policy).filter(Policy.tenant_id == t.id, Policy.is_active == True).first() is not None  # noqa: E712
        )
        results.append(
            TenantSummary(
                id=t.id,
                name=t.name,
                slug=t.slug,
                is_active=t.is_active,
                settings=t.settings,
                created_at=t.created_at,
                admin_count=admin_count,
                user_count=user_count,
                workspace_count=workspace_count,
                mtd_cost_usd=round(float(mtd_cost), 2),
                layer_knowledge=has_knowledge,
                layer_expertise=has_expertise,
                layer_norms=has_norms,
                status_label="Active" if (has_knowledge or has_expertise) else "Onboarding",
            )
        )
    return results


@router.post("/tenants", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def create_tenant(payload: TenantCreate, db: Session = Depends(get_db), current: User = Depends(authorize_tenant("create"))) -> TenantRead:
    tenant = Tenant(name=payload.name, slug=unique_slug(db, payload.name))
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    audit.record(db, actor=current, action="tenant.create", resource_type="tenant", resource_id=tenant.id, tenant_id=tenant.id, extra={"name": tenant.name})
    return TenantRead.model_validate(tenant)


def _get_tenant_or_404(db: Session, tenant_id: uuid.UUID) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return tenant


@router.get("/tenants/{tenant_id}", response_model=TenantRead)
def get_tenant(tenant_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(authorize_tenant("read"))) -> TenantRead:
    return TenantRead.model_validate(_get_tenant_or_404(db, tenant_id))


@router.put("/tenants/{tenant_id}", response_model=TenantRead)
def update_tenant(
    tenant_id: uuid.UUID,
    payload: TenantUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(authorize_tenant("update")),
) -> TenantRead:
    tenant = _get_tenant_or_404(db, tenant_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)
    db.commit()
    db.refresh(tenant)
    audit.record(db, actor=current, action="tenant.update", resource_type="tenant", resource_id=tenant.id, tenant_id=tenant.id)
    return TenantRead.model_validate(tenant)


@router.delete("/tenants/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(tenant_id: uuid.UUID, db: Session = Depends(get_db), current: User = Depends(authorize_tenant("delete"))) -> None:
    tenant = _get_tenant_or_404(db, tenant_id)
    name = tenant.name
    db.delete(tenant)  # cascades to every tenant-scoped row via ondelete="CASCADE"
    db.commit()
    audit.record(db, actor=current, action="tenant.delete", resource_type="tenant", resource_id=tenant_id, tenant_id=None, extra={"name": name})
    return None


# --- Assigning admins to tenants --------------------------------------------


@router.post("/tenants/{tenant_id}/admins", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_tenant_admin(
    tenant_id: uuid.UUID,
    payload: PlatformAdminCreate,
    db: Session = Depends(get_db),
    current: User = Depends(require_super_admin),
) -> UserRead:
    """"Assigning admins to tenants" — creates a new Admin account directly
    inside `tenant_id`."""
    _get_tenant_or_404(db, tenant_id)
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        tenant_id=tenant_id,
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    audit.record(db, actor=current, action="admin.create", resource_type="user", resource_id=user.id, tenant_id=tenant_id, extra={"email": user.email})
    return UserRead.model_validate(user)


@router.put("/users/{user_id}/role", response_model=UserRead)
def update_user_role(
    user_id: uuid.UUID,
    payload: PlatformUserRoleUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_super_admin),
) -> UserRead:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.role == "super_admin":
        user.tenant_id = None
    else:
        target_tenant_id = payload.tenant_id or user.tenant_id
        if target_tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tenant_id is required when assigning a tenant-scoped role to a user with no tenant",
            )
        _get_tenant_or_404(db, target_tenant_id)
        user.tenant_id = target_tenant_id

    user.role = payload.role
    db.commit()
    db.refresh(user)
    audit.record(db, actor=current, action="user.role_change", resource_type="user", resource_id=user.id, tenant_id=user.tenant_id, extra={"new_role": payload.role})
    return UserRead.model_validate(user)


@router.get("/users", response_model=list[UserRead])
def list_all_users(
    tenant_id: uuid.UUID | None = None,
    role: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> list[UserRead]:
    """Read-only cross-tenant roster. Optionally narrowed to one tenant
    and/or role — the Super Admin's "Admins" nav item is just this endpoint
    called with role=admin."""
    query = db.query(User)
    if tenant_id is not None:
        query = query.filter(User.tenant_id == tenant_id)
    if role is not None:
        query = query.filter(User.role == role)
    users = query.order_by(User.created_at.desc()).all()
    return [UserRead.model_validate(u) for u in users]


# --- Platform dashboard: overview KPIs ---------------------------------------


@router.get("/overview")
def platform_overview(db: Session = Depends(get_db), _: User = Depends(require_super_admin)) -> dict:
    now = datetime.now(timezone.utc)
    month_start = _month_start(now)
    thirty_days_ago = now - timedelta(days=30)

    active_tenants = db.query(Tenant).filter(Tenant.is_active == True).count()  # noqa: E712
    new_tenants_this_month = db.query(Tenant).filter(Tenant.created_at >= month_start).count()

    mau = (
        db.query(func.count(func.distinct(UsageEvent.user_id)))
        .filter(UsageEvent.created_at >= thirty_days_ago, UsageEvent.user_id.isnot(None))
        .scalar()
        or 0
    )

    llm_spend_mtd = (
        db.query(func.coalesce(func.sum(UsageEvent.cost_usd), 0.0)).filter(UsageEvent.created_at >= month_start).scalar()
        or 0.0
    )

    latencies = [
        row[0]
        for row in db.query(UsageEvent.latency_ms)
        .filter(UsageEvent.created_at >= thirty_days_ago, UsageEvent.latency_ms.isnot(None))
        .all()
    ]

    return {
        "active_tenants": active_tenants,
        "new_tenants_this_month": new_tenants_this_month,
        "monthly_active_users": mau,
        "llm_spend_mtd_usd": round(float(llm_spend_mtd), 2),
        "llm_budget_usd": settings.platform_llm_budget_usd,
        "gateway_p95_latency_ms": _percentile(latencies, 0.95),
        "gateway_slo_ms": settings.platform_gateway_slo_ms,
    }


@router.get("/usage/daily")
def usage_daily(days: int = 14, db: Session = Depends(get_db), _: User = Depends(require_super_admin)) -> list[dict]:
    """Backs the "Requests per day" chart — real daily counts of chat turns
    vs. tool/skill activations from UsageEvent, not fabricated bar heights."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = (
        db.query(
            func.date(UsageEvent.created_at).label("day"),
            UsageEvent.event_type,
            func.count().label("n"),
        )
        .filter(UsageEvent.created_at >= since)
        .group_by("day", UsageEvent.event_type)
        .all()
    )
    by_day: dict[str, dict[str, int]] = {}
    for day, event_type, n in rows:
        key = day.isoformat() if hasattr(day, "isoformat") else str(day)
        bucket = by_day.setdefault(key, {"chat_turns": 0, "tool_and_skill_calls": 0})
        if event_type == "chat_turn":
            bucket["chat_turns"] += n
        else:
            bucket["tool_and_skill_calls"] += n
    return [{"date": d, **counts} for d, counts in sorted(by_day.items())]


@router.get("/cost-by-tenant")
def cost_by_tenant(db: Session = Depends(get_db), _: User = Depends(require_super_admin)) -> dict:
    now = datetime.now(timezone.utc)
    month_start = _month_start(now)
    rows = (
        db.query(Tenant.name, Tenant.slug, func.coalesce(func.sum(UsageEvent.cost_usd), 0.0).label("cost"))
        .outerjoin(
            UsageEvent,
            (UsageEvent.tenant_id == Tenant.id) & (UsageEvent.created_at >= month_start),
        )
        .group_by(Tenant.id, Tenant.name, Tenant.slug)
        .order_by(func.coalesce(func.sum(UsageEvent.cost_usd), 0.0).desc())
        .all()
    )
    total_requests = db.query(UsageEvent).filter(UsageEvent.created_at >= month_start).count()
    total_cost = sum(float(r.cost) for r in rows)
    return {
        "by_tenant": [{"tenant_name": r.name, "tenant_slug": r.slug, "cost_usd": round(float(r.cost), 2)} for r in rows],
        "avg_cost_per_request_usd": round(total_cost / total_requests, 4) if total_requests else 0.0,
    }


@router.get("/health")
def platform_health(db: Session = Depends(get_db), _: User = Depends(require_super_admin)) -> dict:
    """Real signals derived from stored data — not a live infra probe (this
    MVP has no deployed gateway/vector store to poll). Error rate comes from
    UsageEvent.status (set from whether a turn was blocked/failed — see
    app/api/routes/chat.py), latency from UsageEvent.latency_ms, and
    ingestion health from Datasource.sync_status."""
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    total_events = db.query(UsageEvent).filter(UsageEvent.created_at >= thirty_days_ago).count()
    errored_events = db.query(UsageEvent).filter(UsageEvent.created_at >= thirty_days_ago, UsageEvent.status == "error").count()
    latencies = [
        row[0]
        for row in db.query(UsageEvent.latency_ms)
        .filter(UsageEvent.created_at >= thirty_days_ago, UsageEvent.latency_ms.isnot(None))
        .all()
    ]
    last_event_at = db.query(func.max(UsageEvent.created_at)).scalar()

    failing_datasources = db.query(Datasource).filter(Datasource.sync_status == "error").count()
    syncing_datasources = db.query(Datasource).filter(Datasource.sync_status == "syncing").count()

    return {
        "gateway_p95_latency_ms": _percentile(latencies, 0.95),
        "gateway_slo_ms": settings.platform_gateway_slo_ms,
        "error_rate_30d": round(errored_events / total_events, 4) if total_events else 0.0,
        "total_requests_30d": total_events,
        "last_request_at": last_event_at,
        "datasources_failing": failing_datasources,
        "datasources_syncing": syncing_datasources,
    }


@router.get("/audit", response_model=list[AuditLogRead])
def list_audit(
    tenant_id: uuid.UUID | None = None,
    action: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_super_admin),
) -> list[AuditLogRead]:
    query = db.query(AuditLog)
    if tenant_id is not None:
        query = query.filter(AuditLog.tenant_id == tenant_id)
    if action is not None:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    rows = query.order_by(AuditLog.created_at.desc()).limit(min(limit, 500)).all()
    return [AuditLogRead.model_validate(r) for r in rows]


# --- Model catalog (Super Admin-managed) -------------------------------------


def _to_model_route_read(r: ModelRoute) -> ModelRouteRead:
    return ModelRouteRead(
        id=r.id,
        name=r.name,
        provider=r.provider,
        route=r.route,
        kind=r.kind,
        input_cost_per_1m=r.input_cost_per_1m,
        output_cost_per_1m=r.output_cost_per_1m,
        status=r.status,
        gateway_configured=r.gateway_configured,
        cost_meter_registered=r.cost_meter_registered,
        eval_faithfulness=r.eval_faithfulness,
        eval_faithfulness_threshold=r.eval_faithfulness_threshold,
        eval_task_completion=r.eval_task_completion,
        eval_task_completion_threshold=r.eval_task_completion_threshold,
        eval_security_redteam_passed=r.eval_security_redteam_passed,
        is_active=r.is_active,
        created_at=r.created_at,
        updated_at=r.updated_at,
        gates=ModelGates(**r.gates()),
    )


@router.get("/model-routes", response_model=list[ModelRouteRead])
def list_model_routes(db: Session = Depends(get_db), _: User = Depends(require_super_admin)) -> list[ModelRouteRead]:
    routes = db.query(ModelRoute).order_by(ModelRoute.created_at.desc()).all()
    return [_to_model_route_read(r) for r in routes]


@router.get("/model-routes/available")
def list_available_model_routes(db: Session = Depends(get_db), _: User = Depends(require_super_admin)) -> list[ModelRouteRead]:
    """Read-only, any authenticated admin can call — powers the Admin
    Expertise tab's Planner/Executor/Critic model-routing selects. Only
    'live' routes are offered there (canary/eval routes are Super
    Admin-visible only, in the main catalog above)."""
    routes = db.query(ModelRoute).filter(ModelRoute.status == "live", ModelRoute.is_active == True).order_by(ModelRoute.name).all()  # noqa: E712
    return [_to_model_route_read(r) for r in routes]


@router.post("/model-routes", response_model=ModelRouteRead, status_code=status.HTTP_201_CREATED)
def create_model_route(
    payload: ModelRouteCreate, db: Session = Depends(get_db), current: User = Depends(require_super_admin)
) -> ModelRouteRead:
    existing = db.query(ModelRoute).filter(ModelRoute.route == payload.route).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A model route with this route name already exists")
    route = ModelRoute(**payload.model_dump())
    db.add(route)
    db.commit()
    db.refresh(route)
    audit.record(db, actor=current, action="model_route.create", resource_type="model_route", resource_id=route.id, tenant_id=None, extra={"name": route.name, "route": route.route})
    return _to_model_route_read(route)


@router.put("/model-routes/{route_id}", response_model=ModelRouteRead)
def update_model_route(
    route_id: uuid.UUID,
    payload: ModelRouteUpdate,
    db: Session = Depends(get_db),
    current: User = Depends(require_super_admin),
) -> ModelRouteRead:
    route = db.get(ModelRoute, route_id)
    if route is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model route not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(route, field, value)
    db.commit()
    db.refresh(route)
    audit.record(db, actor=current, action="model_route.update", resource_type="model_route", resource_id=route.id, tenant_id=None)
    return _to_model_route_read(route)


@router.delete("/model-routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model_route(route_id: uuid.UUID, db: Session = Depends(get_db), current: User = Depends(require_super_admin)) -> None:
    route = db.get(ModelRoute, route_id)
    if route is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model route not found")
    db.delete(route)
    db.commit()
    audit.record(db, actor=current, action="model_route.delete", resource_type="model_route", resource_id=route_id, tenant_id=None)
    return None
