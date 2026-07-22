"""Tenant slug generation — shared by /auth/signup (a customer signing
themselves up, which implicitly creates a tenant) and
POST /platform/tenants (a Super Admin creating one directly). Previously
lived only in app/api/routes/auth.py; extracted here once a second caller
needed it rather than duplicating it.
"""
import re
import uuid

from sqlalchemy.orm import Session

from app.models.tenant import Tenant

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-") or "workspace"


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    slug = base
    # Collision-safe without a retry loop: append a short random suffix if
    # the base slug is already taken. Good enough at this scale — a proper
    # multi-tenant SaaS would reserve/lock the slug transactionally instead.
    if db.query(Tenant).filter(Tenant.slug == slug).first() is not None:
        slug = f"{base}-{uuid.uuid4().hex[:6]}"
    return slug
