"""HTTP client for Open Policy Agent (OPA) — the authorization decision
point for this app's three role-based flows (super_admin/admin/user). The
Rego policy at backend/policies/authz.rego is the single source of truth
for who can do what; this module's only job is asking it the question and
relaying the answer. See docs/AUTHORIZATION.md for the full design and
deployment story (OPA runs as its own container — docker-compose.yml —
loading that policy bundle; there is no embedded/in-process Rego
evaluator, since none exists for Python).

Fails closed, always: if OPA is unreachable, times out, or returns
something unparseable, `authorize()` returns False (deny) rather than
raising past the caller or defaulting to allow. A misconfigured or down
policy engine must never silently grant access.
"""
import logging
import uuid
from typing import TYPE_CHECKING

import httpx

from app.core.config import settings

if TYPE_CHECKING:
    from app.models.user import User

logger = logging.getLogger("agentic_mvp.opa")

_ALLOW_PATH = "/v1/data/agentic/authz/allow"


class OpaUnavailableError(Exception):
    """Raised internally when OPA can't be reached or returns something
    that isn't a well-formed decision document. Never escapes
    `authorize()` — callers always get a plain bool (fail-closed)."""


def check_allow(input_doc: dict) -> bool:
    """POSTs `input_doc` to OPA's `agentic/authz/allow` rule over HTTP and
    returns the boolean decision. Raises OpaUnavailableError on any
    network/parse failure — this is the one function in this module that
    does NOT fail closed on its own; `authorize()` below is what applies
    the fail-closed policy, so this stays easy to unit test in isolation
    (mock the transport, assert on the raised error or the returned bool,
    no need to also reason about logging/fallback behavior here)."""
    try:
        resp = httpx.post(
            f"{settings.opa_url}{_ALLOW_PATH}",
            json={"input": input_doc},
            timeout=settings.opa_timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise OpaUnavailableError(str(e)) from e

    if not isinstance(data, dict) or "result" not in data:
        # OPA omits "result" entirely when the queried path is undefined
        # (e.g. the bundle failed to load) — that is a deny, not an error;
        # `default allow := false` in the policy would normally prevent
        # this, but an unloaded bundle bypasses the policy's own default.
        return False
    return bool(data["result"])


def _subject_doc(user: "User") -> dict:
    return {
        "id": str(user.id),
        "role": user.role,
        "tenant_id": str(user.tenant_id) if user.tenant_id is not None else None,
    }


def authorize(
    user: "User",
    resource_type: str,
    action: str,
    *,
    tenant_id: uuid.UUID | None = None,
    target_role: str | None = None,
) -> bool:
    """The one function every authorization check in this app should call.
    Builds the OPA input document from `user` + the resource/action being
    attempted and returns OPA's decision, fail-closed on any error.

    `tenant_id` is the tenant the RESOURCE belongs to (not necessarily the
    caller's) — for the common case (an admin/user acting within their own
    tenant) this is just `user.tenant_id`; callers that need to check a
    specific existing row's tenant (or a super_admin's cross-tenant
    action) pass it explicitly. `target_role` is only meaningful for
    resource_type == "user" writes — see authz.rego's
    _privileged_user_write.
    """
    resource: dict = {
        "type": resource_type,
        "tenant_id": str(tenant_id) if tenant_id is not None else None,
    }
    if target_role is not None:
        resource["target_role"] = target_role

    input_doc = {"subject": _subject_doc(user), "action": action, "resource": resource}
    try:
        return check_allow(input_doc)
    except OpaUnavailableError as e:
        logger.error("OPA unreachable or returned a bad response (denying): %s", e)
        return False
