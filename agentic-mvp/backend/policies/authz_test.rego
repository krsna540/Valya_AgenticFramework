# Unit tests for authz.rego — run with `opa test policies/` (Krishna's
# machine / CI; this repo's own sandbox has no OPA binary available, see
# docs/AUTHORIZATION.md). One test per meaningful branch of the policy,
# named so a failure immediately tells you which rule broke.
package agentic.authz_test

import data.agentic.authz.allow
import rego.v1

tenant_a := "11111111-1111-1111-1111-111111111111"

tenant_b := "22222222-2222-2222-2222-222222222222"

# ---------------------------------------------------------------------------
# Super Admin: unrestricted, including tenant management and cross-tenant.
# ---------------------------------------------------------------------------

test_super_admin_allowed_tenant_create if {
	allow with input as {
		"subject": {"id": "u1", "role": "super_admin", "tenant_id": null},
		"action": "create",
		"resource": {"type": "tenant", "tenant_id": null},
	}
}

test_super_admin_allowed_any_tenant_write if {
	allow with input as {
		"subject": {"id": "u1", "role": "super_admin", "tenant_id": null},
		"action": "update",
		"resource": {"type": "project", "tenant_id": tenant_b},
	}
}

test_super_admin_allowed_promote_to_admin if {
	allow with input as {
		"subject": {"id": "u1", "role": "super_admin", "tenant_id": null},
		"action": "create",
		"resource": {"type": "user", "tenant_id": tenant_a, "target_role": "admin"},
	}
}

# ---------------------------------------------------------------------------
# Admin: full CRUD within their own tenant.
# ---------------------------------------------------------------------------

test_admin_allowed_create_project_own_tenant if {
	allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "create",
		"resource": {"type": "project", "tenant_id": tenant_a},
	}
}

test_admin_allowed_freeze_own_project if {
	allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "freeze",
		"resource": {"type": "project", "tenant_id": tenant_a},
	}
}

test_admin_allowed_create_plain_user if {
	allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "create",
		"resource": {"type": "user", "tenant_id": tenant_a, "target_role": "user"},
	}
}

test_admin_denied_create_admin_user if {
	not allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "create",
		"resource": {"type": "user", "tenant_id": tenant_a, "target_role": "admin"},
	}
}

test_admin_denied_promote_existing_user_to_admin if {
	not allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "update",
		"resource": {"type": "user", "tenant_id": tenant_a, "target_role": "admin"},
	}
}

test_admin_denied_delete_admin_user if {
	not allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "delete",
		"resource": {"type": "user", "tenant_id": tenant_a, "target_role": "admin"},
	}
}

test_admin_allowed_read_admin_user if {
	# Reading (not writing) another admin's row in the same tenant is fine —
	# the privileged-write guard only fires on create/update/delete.
	allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "read",
		"resource": {"type": "user", "tenant_id": tenant_a, "target_role": "admin"},
	}
}

test_admin_denied_cross_tenant_write if {
	not allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "update",
		"resource": {"type": "project", "tenant_id": tenant_b},
	}
}

test_admin_denied_cross_tenant_read if {
	not allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "read",
		"resource": {"type": "project", "tenant_id": tenant_b},
	}
}

test_admin_allowed_read_platform_shared if {
	allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "read",
		"resource": {"type": "skill", "tenant_id": null},
	}
}

test_admin_denied_write_platform_shared if {
	not allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "update",
		"resource": {"type": "skill", "tenant_id": null},
	}
}

test_admin_allowed_read_own_tenant_profile if {
	allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "read",
		"resource": {"type": "tenant", "tenant_id": tenant_a},
	}
}

test_admin_allowed_update_own_tenant_profile if {
	allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "update",
		"resource": {"type": "tenant", "tenant_id": tenant_a},
	}
}

test_admin_denied_read_other_tenant_profile if {
	not allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "read",
		"resource": {"type": "tenant", "tenant_id": tenant_b},
	}
}

test_admin_denied_delete_own_tenant if {
	not allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "delete",
		"resource": {"type": "tenant", "tenant_id": tenant_a},
	}
}

test_admin_denied_list_all_tenants if {
	not allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "list",
		"resource": {"type": "tenant", "tenant_id": tenant_a},
	}
}

test_admin_denied_tenant_create if {
	not allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "create",
		"resource": {"type": "tenant", "tenant_id": null},
	}
}

test_admin_denied_tenant_read if {
	not allow with input as {
		"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
		"action": "read",
		"resource": {"type": "tenant", "tenant_id": null},
	}
}

test_admin_allowed_manage_skills_hooks_plugins_prompts_personas_datasources if {
	every rtype in ["skill", "hook", "plugin", "prompt", "persona", "datasource", "tool", "agent"] {
		allow with input as {
			"subject": {"id": "u2", "role": "admin", "tenant_id": tenant_a},
			"action": "create",
			"resource": {"type": rtype, "tenant_id": tenant_a},
		}
	}
}

# ---------------------------------------------------------------------------
# User: agents + chat only.
# ---------------------------------------------------------------------------

test_user_allowed_read_agent if {
	allow with input as {
		"subject": {"id": "u3", "role": "user", "tenant_id": tenant_a},
		"action": "read",
		"resource": {"type": "agent", "tenant_id": tenant_a},
	}
}

test_user_allowed_list_projects if {
	allow with input as {
		"subject": {"id": "u3", "role": "user", "tenant_id": tenant_a},
		"action": "list",
		"resource": {"type": "project", "tenant_id": tenant_a},
	}
}

test_user_allowed_read_prompts if {
	allow with input as {
		"subject": {"id": "u3", "role": "user", "tenant_id": tenant_a},
		"action": "list",
		"resource": {"type": "prompt", "tenant_id": tenant_a},
	}
}

test_user_allowed_full_chat_access if {
	every act in ["create", "read", "update", "delete", "list"] {
		allow with input as {
			"subject": {"id": "u3", "role": "user", "tenant_id": tenant_a},
			"action": act,
			"resource": {"type": "chat", "tenant_id": tenant_a},
		}
	}
}

test_user_denied_write_agent if {
	not allow with input as {
		"subject": {"id": "u3", "role": "user", "tenant_id": tenant_a},
		"action": "update",
		"resource": {"type": "agent", "tenant_id": tenant_a},
	}
}

test_user_denied_write_project if {
	not allow with input as {
		"subject": {"id": "u3", "role": "user", "tenant_id": tenant_a},
		"action": "create",
		"resource": {"type": "project", "tenant_id": tenant_a},
	}
}

test_user_denied_skills_hooks_plugins_datasources_personas if {
	every rtype in ["skill", "hook", "plugin", "datasource", "persona", "tool", "user", "tenant"] {
		not allow with input as {
			"subject": {"id": "u3", "role": "user", "tenant_id": tenant_a},
			"action": "read",
			"resource": {"type": rtype, "tenant_id": tenant_a},
		}
	}
}

test_user_denied_cross_tenant_agent_read if {
	not allow with input as {
		"subject": {"id": "u3", "role": "user", "tenant_id": tenant_a},
		"action": "read",
		"resource": {"type": "agent", "tenant_id": tenant_b},
	}
}

test_user_denied_cross_tenant_chat if {
	not allow with input as {
		"subject": {"id": "u3", "role": "user", "tenant_id": tenant_a},
		"action": "read",
		"resource": {"type": "chat", "tenant_id": tenant_b},
	}
}

# ---------------------------------------------------------------------------
# Default deny: an unrecognized role gets nothing, ever.
# ---------------------------------------------------------------------------

test_unknown_role_denied if {
	not allow with input as {
		"subject": {"id": "u4", "role": "guest", "tenant_id": tenant_a},
		"action": "read",
		"resource": {"type": "chat", "tenant_id": tenant_a},
	}
}
