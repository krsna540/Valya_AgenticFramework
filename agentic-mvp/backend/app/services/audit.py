"""Audit trail writer for the Super Admin's Audit view. Not every mutation
in this app calls `record()` — the routes that do are the ones with real
platform/tenant-governance significance: tenant lifecycle, admin creation
and role changes, datasource connect/sync, policy and model-route changes,
and project freeze/deploy. See each call site's comment for why that
action was picked.

Deliberately synchronous and best-effort within the caller's existing
session/transaction — a failed audit write should not be allowed to mask
or roll back the real mutation it's describing, so callers should invoke
`record()` after their own `db.commit()`, not before.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

if TYPE_CHECKING:
    from app.models.user import User


def record(
    db: Session,
    *,
    actor: "User | None",
    action: str,
    resource_type: str,
    resource_id: Any = None,
    tenant_id: uuid.UUID | None = None,
    extra: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        tenant_id=tenant_id if tenant_id is not None else (actor.tenant_id if actor else None),
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        extra=extra or {},
    )
    db.add(entry)
    db.commit()
    return entry
