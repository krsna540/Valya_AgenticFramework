# Authorization policy for the three role-based flows in this app:
#
#   super_admin — unrestricted. Only role that can manage Tenants themselves
#                 and create/promote/demote Admin (or other Super Admin)
#                 accounts. See docs/AUTHORIZATION.md.
#   admin       — full CRUD on everything *within their own tenant*: users
#                 (but only "user"-role accounts — not admins/super admins),
#                 projects (including freeze/unfreeze/deploy), agents,
#                 skills, hooks, plugins, prompts, personas, datasources,
#                 tools.
#   user        — read-only on the handful of resource types the chat
#                 application itself needs (agents to talk to, projects
#                 they're mapped to, prompt templates), plus full access to
#                 their own chat conversations. Nothing else.
#
# This is the single source of truth for those three flows — the FastAPI
# backend (app/core/opa.py, app/api/deps.py::authorize) has no independent
# copy of this logic; it POSTs an `input` document here and does exactly
# what `allow` says. Per-row tenant scoping (e.g. "is this specific Project
# actually in my tenant") still happens in SQL at the route layer, same as
# before OPA existed — this policy answers the coarser "is this role even
# allowed to attempt this kind of action" question that `require_admin`
# used to answer ad hoc, scattered across a dozen route files.
#
# Input shape (see app/core/opa.py::authorize for the Python side that
# builds this):
#
#   {
#     "subject":  {"id": "<uuid>", "role": "super_admin|admin|user", "tenant_id": "<uuid>|null"},
#     "action":   "create|read|update|delete|list|freeze|unfreeze|deploy",
#     "resource": {
#       "type": "tenant|user|project|agent|skill|hook|plugin|prompt|persona|datasource|tool|chat",
#       "tenant_id": "<uuid>|null",
#       "target_role": "admin|user|super_admin"   # only present for resource.type == "user" writes
#     }
#   }
package agentic.authz

import rego.v1

default allow := false

# ---------------------------------------------------------------------------
# Super Admin: unrestricted, in every tenant, including Tenant management
# itself.
# ---------------------------------------------------------------------------

allow if {
	input.subject.role == "super_admin"
}

# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

# Tenant rows themselves are Super Admin-only for lifecycle management
# (create, delete, list every tenant) — an Admin manages their own
# tenant's *contents*, not the Tenant record's lifecycle or any other
# tenant's. The one exception is directly below: an Admin may still
# read/rename their own tenant's profile (GET/PUT /tenants/me — existing
# self-service that predates this policy).
_tenant_resource_types := {"tenant"}

allow if {
	input.subject.role == "admin"
	input.resource.type == "tenant"
	input.action in {"read", "update"}
	input.resource.tenant_id == input.subject.tenant_id
}

# Creating, updating, or deleting a User whose role is (or would become)
# admin/super_admin is Super Admin-only — "assigning admins to tenants" is
# explicitly a Super Admin action per the product's role design. An Admin
# may still *read* those rows (e.g. see that a co-admin exists in their
# tenant's user list) — this guard only fires for writes.
_privileged_user_write if {
	input.resource.type == "user"
	input.action in {"create", "update", "delete"}
	input.resource.target_role in {"admin", "super_admin"}
}


# Reads (and list) may also see platform-shared rows (tenant_id == null) —
# same "visible to every tenant, editable by nobody but its owner" rule the
# app already applies at the SQL layer for Skills/Hooks/Plugins/Tools/etc.
allow if {
	input.subject.role == "admin"
	not input.resource.type in _tenant_resource_types
	input.action in {"read", "list"}
	input.resource.tenant_id in {input.subject.tenant_id, null}
}

# Writes are always scoped to the admin's own tenant — never a platform-
# shared row (tenant_id == null) and never another tenant's.
allow if {
	input.subject.role == "admin"
	not input.resource.type in _tenant_resource_types
	not _privileged_user_write
	input.action in {"create", "update", "delete", "freeze", "unfreeze", "deploy"}
	input.resource.tenant_id == input.subject.tenant_id
}

# ---------------------------------------------------------------------------
# User: agents + chat only.
# ---------------------------------------------------------------------------

# Read-only visibility into the resource types the chat application itself
# needs to render: which agents exist, which projects this user is mapped
# to (project membership itself is still enforced in SQL — see
# app/api/routes/projects.py::_get_project), prompt templates for the
# "/" quick-insert picker, and — added for user-app.html's "Sources"
# screen ("What the assistant is allowed to read") — datasource metadata.
# Read-only and tenant-scoped, same as the rest of this set: a user sees
# what sources exist and their status, never connection secrets (those
# aren't in the DatasourceRead response body to begin with).
_user_readable_types := {"agent", "project", "prompt", "run", "datasource"}

allow if {
	input.subject.role == "user"
	input.resource.type in _user_readable_types
	input.action in {"read", "list"}
	input.resource.tenant_id == input.subject.tenant_id
}

# Full access to their own chat conversations/messages.
allow if {
	input.subject.role == "user"
	input.resource.type == "chat"
	input.resource.tenant_id == input.subject.tenant_id
}

# A user may resolve (start a session against) their own tenant's manifest
# — this is the capability-document handoff PLATFORM_ARCHITECTURE.md §6
# describes, gated the same way starting a chat conversation already is.
allow if {
	input.subject.role == "user"
	input.resource.type == "manifest"
	input.action in {"read", "create"}
	input.resource.tenant_id == input.subject.tenant_id
}

# Resolving an ESCALATE/awaiting-human run (PLATFORM_ARCHITECTURE.md §9.6's
# HUMAN_RESOLVED touchpoint) — approve/decline is a "decide" action, not a
# generic "update", so it does not fall under the admin-only write rule
# above. Any user in the tenant may decide, same as any workspace member
# can see the approval card in user-app.html's plan panel — a real
# deployment would likely narrow this to workspace owners (see the
# admin-app.html "Who can approve: Owners only" setting, which is UI-level
# in this build, not yet enforced here — yet another documented, not
# silently dropped, gap).
allow if {
	input.subject.role in {"user", "admin"}
	input.resource.type == "run"
	input.action == "decide"
	input.resource.tenant_id == input.subject.tenant_id
}
