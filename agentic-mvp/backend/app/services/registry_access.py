"""Enforcement helpers for the two access-modifier axes added in migration
0016 (PLATFORM_ARCHITECTURE.md §7.2): access_class (default/custom) and
visibility (public/protected/private). Every registry route (skills,
prompts, tools, hooks, plugins, agents) should route mutations through
these functions rather than re-deriving the rules inline — that is the
whole point of centralizing them (see app/core/opa.py's docstring for the
same "one place to read" argument applied to authorization).

Two things live here:
  1. assign_access_class() — keeps `access_class` in lockstep with the
     existing `tenant_id IS NULL` convention at write time, so every older
     query in the app that already filters on tenant_id keeps working
     unchanged while the new column is also correct.
  2. fork_row() — the §7.5 "fork, don't edit" operation: default/public
     entities are immutable to everyone but super_admin, so changing one
     means copying it into a new `custom` row with `forked_from_id` set.

Neither of these touches OPA. Rego (backend/policies/authz.rego) still
answers "may this actor call this route at all" (coarse role check); these
functions answer the finer-grained "which access_class/visibility may this
particular row end up with" — the same two-layer split PLATFORM_ARCHITECTURE
describes for tools (OPA says *may you*, the manifest says *does it exist
for you*).
"""
from __future__ import annotations

import uuid
from typing import TypeVar

from app.models.mixins import ACCESS_CLASSES, VISIBILITIES

ModelT = TypeVar("ModelT")


class AccessDeniedError(Exception):
    """Raised when a write would violate the access matrix in
    PLATFORM_ARCHITECTURE.md §7.3. Routes should catch this and translate to
    HTTP 403 — see app/api/deps.py for the existing 403-shaping convention.
    """


def assign_access_class(*, tenant_id: uuid.UUID | None, requested: str | None, actor_role: str) -> str:
    """Resolve the access_class a new/updated row should carry.

    tenant_id IS NULL rows are ALWAYS "default" — that pairing is the
    platform-shared convention every pre-existing query already relies on,
    so it cannot be overridden by the request body. A non-NULL tenant_id row
    is always "custom" for the same reason, in reverse: a tenant-owned row
    claiming to be "default" would be invisible to the access matrix's
    super-admin-only write rule while still being editable by that tenant's
    own admins, which is exactly the privilege escalation §7.3 exists to
    prevent.
    """
    if tenant_id is None:
        return "default"
    return "custom"


def assert_can_write(*, actor_role: str, actor_tenant_id: uuid.UUID | None, row_access_class: str, row_tenant_id: uuid.UUID | None) -> None:
    """The mutation half of the §7.3 matrix. Read/use/fork visibility is
    enforced separately (see `visible_to` below) because it is a query
    filter, not a single boolean gate.
    """
    if actor_role == "super_admin":
        return
    if row_access_class == "default":
        raise AccessDeniedError("Platform defaults can only be changed by a super_admin. Fork it instead.")
    if actor_role != "admin":
        raise AccessDeniedError("Only a tenant admin or super_admin may modify a custom registry entry.")
    if row_tenant_id is None or row_tenant_id != actor_tenant_id:
        raise AccessDeniedError("You may only modify custom entries owned by your own tenant.")


def fork_row(source: ModelT, *, new_tenant_id: uuid.UUID, owner_user_id: uuid.UUID, model_cls: type) -> ModelT:
    """Copy `source` into a brand-new `custom`/`protected` row owned by
    `new_tenant_id`, recording provenance. Does not persist — the caller
    adds it to the session, same convention as every other route in this
    app (see e.g. app/api/routes/skills.py's upload handler).

    Only copies columns that exist on both the mixin and the concrete
    model; anything model-specific (skill_md_raw, mcp_endpoint, etc.) is
    carried over via getattr/setattr against the row's own __table__
    columns, so this one function forks any of the five registry kinds
    without a kind-specific branch.
    """
    if source.access_class not in ACCESS_CLASSES:
        raise ValueError(f"Unknown access_class {source.access_class!r} on fork source")

    forked = model_cls()
    skip = {"id", "created_at", "updated_at", "tenant_id", "access_class", "visibility", "forked_from_id", "forked_from_version", "owner_user_id", "reviewed_by_user_id"}
    for column in source.__table__.columns:  # type: ignore[attr-defined]
        col_name = column.name
        if col_name in skip:
            continue
        if hasattr(forked, col_name):
            setattr(forked, col_name, getattr(source, col_name))

    forked.id = uuid.uuid4()
    forked.tenant_id = new_tenant_id
    forked.access_class = "custom"
    forked.visibility = "protected"
    forked.forked_from_id = source.id
    forked.forked_from_version = getattr(source, "version", None)
    forked.owner_user_id = owner_user_id
    forked.reviewed_by_user_id = None
    if hasattr(forked, "name"):
        forked.name = f"{source.name} (fork)"
    return forked


def validate_visibility(value: str) -> str:
    if value not in VISIBILITIES:
        raise ValueError(f"visibility must be one of {VISIBILITIES}")
    return value
