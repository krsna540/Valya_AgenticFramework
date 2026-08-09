"""Shared helpers for the one thing OPA deliberately does NOT decide:
which specific rows a query should return. OPA's `authorize()` (see
app/api/deps.py) answers "is this role even allowed to attempt this kind
of action" — coarse, resource-*type*-level. These helpers answer "which
actual rows", the same job the tenant_id filters in every route already
did before OPA existed.

The one thing that changed: super_admin has no tenant_id of its own
(tenant_id is None — see docs/AUTHORIZATION.md), so it needs to see every
tenant's rows rather than being filtered down to nothing. Every route that
lists or fetches a tenant-scoped resource should route its tenant check
through here rather than repeating `role == "super_admin"` ad hoc.
"""
from sqlalchemy import ColumnElement, or_, true
from sqlalchemy.orm import Query

from app.models.user import User


def shared_or_own_tenant_filter(tenant_id_column: ColumnElement, current_user: User) -> ColumnElement:
    """For registries where a NULL tenant_id means "platform-shared,
    visible to everyone" (Skill/Hook/Plugin/Tool/Prompt/Agent — see
    TenantScopedMixin's docstring): super_admin sees every row in every
    tenant plus the platform-shared ones; everyone else sees platform-
    shared rows plus their own tenant's."""
    if current_user.role == "super_admin":
        return true()
    return or_(tenant_id_column.is_(None), tenant_id_column == current_user.tenant_id)


def own_tenant_filter(tenant_id_column: ColumnElement, current_user: User) -> ColumnElement:
    """For registries with no platform-shared concept at all (Persona,
    Datasource, User — every row belongs to exactly one tenant):
    super_admin sees every tenant's rows; everyone else only their own."""
    if current_user.role == "super_admin":
        return true()
    return tenant_id_column == current_user.tenant_id


def is_visible(row_tenant_id, current_user: User, *, shared_ok: bool = True) -> bool:
    """The single-row equivalent of the two filters above, for
    `_get_..._or_404`-style helpers that fetch by id first and then check
    visibility in Python rather than in the SQL WHERE clause."""
    if current_user.role == "super_admin":
        return True
    if shared_ok and row_tenant_id is None:
        return True
    return row_tenant_id == current_user.tenant_id


def apply_shared_or_own_tenant(query: Query, tenant_id_column: ColumnElement, current_user: User) -> Query:
    return query.filter(shared_or_own_tenant_filter(tenant_id_column, current_user))


def apply_registry_visibility(query: Query, model, current_user: User) -> Query:
    """Adds the migration-0016 `visibility` axis on top of
    `shared_or_own_tenant_filter`: a `custom` row whose owner marked it
    `visibility="public"` is now also visible to OTHER tenants, which the
    plain tenant filter above never allowed (every pre-existing route kept
    using that coarser filter deliberately — see its docstring — so this is
    additive, opt-in per route, not a behavior change to skills.py/tools.py/
    hooks.py/plugins.py/prompts.py).

    default rows are unaffected (always visible, per `shared_or_own_tenant_
    filter`); `protected`/`private` custom rows fall back to the existing
    own-tenant-only behavior. `private` narrowing to a specific bound
    project (PLATFORM_ARCHITECTURE.md §7.2's third tier) is not enforced
    here — no route in this build needs it yet (see the gap map).
    """
    if current_user.role == "super_admin":
        return query
    return query.filter(
        or_(
            model.tenant_id.is_(None),
            model.tenant_id == current_user.tenant_id,
            model.visibility == "public",
        )
    )


def apply_own_tenant(query: Query, tenant_id_column: ColumnElement, current_user: User) -> Query:
    return query.filter(own_tenant_filter(tenant_id_column, current_user))
