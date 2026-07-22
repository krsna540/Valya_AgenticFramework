import { Fragment, FormEvent, useEffect, useState } from "react";
import type { AdminUser, Role, TenantSummary } from "../types";
import { platformApi } from "../api/platform";
import { ApiError } from "../api/client";

const EMPTY_TENANT_CREATE = { name: "" };
const EMPTY_ADMIN_CREATE = { email: "", full_name: "", password: "" };

function fmtUsd(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: n < 10 ? 3 : 0 })}`;
}

// Super-Admin-only screen: tenant lifecycle + assigning each tenant its
// Admin(s), plus cross-tenant role management. Everyday tenant work (users,
// projects, catalogs) happens inside each tenant via /admin/*, not here —
// see docs/AUTHORIZATION.md.
export default function PlatformTenantsPage() {
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState(EMPTY_TENANT_CREATE);
  const [createError, setCreateError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [expandedTenantId, setExpandedTenantId] = useState<string | null>(null);
  const [tenantUsers, setTenantUsers] = useState<AdminUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(false);

  const [showAddAdminFor, setShowAddAdminFor] = useState<string | null>(null);
  const [adminForm, setAdminForm] = useState(EMPTY_ADMIN_CREATE);
  const [adminError, setAdminError] = useState<string | null>(null);
  const [addingAdmin, setAddingAdmin] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setTenants(await platformApi.listTenants());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load tenants");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCreateTenant(e: FormEvent) {
    e.preventDefault();
    setCreateError(null);
    setSubmitting(true);
    try {
      await platformApi.createTenant(createForm);
      setCreateForm(EMPTY_TENANT_CREATE);
      setShowCreate(false);
      await load();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Create failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleTenantActive(t: TenantSummary) {
    try {
      await platformApi.updateTenant(t.id, { is_active: !t.is_active });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  }

  async function handleDeleteTenant(t: TenantSummary) {
    if (!confirm(`Delete tenant "${t.name}"? This cannot be undone.`)) return;
    try {
      await platformApi.deleteTenant(t.id);
      if (expandedTenantId === t.id) setExpandedTenantId(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  async function toggleExpanded(t: TenantSummary) {
    if (expandedTenantId === t.id) {
      setExpandedTenantId(null);
      return;
    }
    setExpandedTenantId(t.id);
    setUsersLoading(true);
    try {
      setTenantUsers(await platformApi.listUsers({ tenantId: t.id }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load users");
    } finally {
      setUsersLoading(false);
    }
  }

  async function handleAddAdmin(e: FormEvent, tenantId: string) {
    e.preventDefault();
    setAdminError(null);
    setAddingAdmin(true);
    try {
      await platformApi.createTenantAdmin(tenantId, adminForm);
      setAdminForm(EMPTY_ADMIN_CREATE);
      setShowAddAdminFor(null);
      await load();
      if (expandedTenantId === tenantId) {
        setTenantUsers(await platformApi.listUsers({ tenantId }));
      }
    } catch (err) {
      setAdminError(err instanceof ApiError ? err.message : "Add admin failed");
    } finally {
      setAddingAdmin(false);
    }
  }

  async function changeUserRole(u: AdminUser, role: Role) {
    try {
      const updated = await platformApi.updateUserRole(u.id, { role, tenant_id: u.tenant_id });
      setTenantUsers((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Role change failed");
    }
  }

  const filtered = tenants.filter(
    (t) => t.name.toLowerCase().includes(filter.toLowerCase()) || t.slug.includes(filter.toLowerCase())
  );

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Tenants</h1>
          <p>Create tenants, assign their Admins, and manage roles across the platform.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          + Create tenant
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {showCreate && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h6 style={{ marginBottom: 4 }}>New</h6>
          <h2 style={{ marginBottom: 12 }}>Tenant</h2>
          <form onSubmit={handleCreateTenant}>
            <div className="field">
              <label>Name</label>
              <input className="input" required value={createForm.name} onChange={(e) => setCreateForm({ name: e.target.value })} />
            </div>
            {createError && <p className="error-text">{createError}</p>}
            <div className="panel-actions-right">
              <button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={submitting}>
                {submitting ? "Creating..." : "Create"}
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        <div className="card-head">
          <span className="card-title">All tenants</span>
          <input className="filter-input" placeholder="Filter tenants…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        {loading ? (
          <p className="empty-state">Loading...</p>
        ) : filtered.length === 0 ? (
          <p className="empty-state">No tenants yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Tenant</th>
                <th>Admins</th>
                <th>Users</th>
                <th>Workspaces</th>
                <th>Layer setup</th>
                <th>MTD cost</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <Fragment key={t.id}>
                  <tr>
                    <td>
                      <button
                        onClick={() => toggleExpanded(t)}
                        style={{ background: "none", border: "none", padding: 0, cursor: "pointer", font: "inherit", color: "inherit", textAlign: "left" }}
                      >
                        <div className="td-main" style={{ textDecoration: "underline" }}>{t.name}</div>
                        <div className="slug">{t.slug}</div>
                      </button>
                    </td>
                    <td className="mono">{t.admin_count}</td>
                    <td className="mono">{t.user_count}</td>
                    <td className="mono">{t.workspace_count}</td>
                    <td>
                      <span className="layer-dots">
                        <span className={`ldot ${t.layer_knowledge ? "knw" : "empty"}`} title="Knowledge" />
                        <span className={`ldot ${t.layer_expertise ? "exp" : "empty"}`} title="Expertise" />
                        <span className={`ldot ${t.layer_norms ? "nrm" : "empty"}`} title="Norms" />
                      </span>
                    </td>
                    <td className="mono">{fmtUsd(t.mtd_cost_usd)}</td>
                    <td>
                      <span className={`state ${t.status_label === "Active" ? "ok" : "warn"}`}>{t.status_label}</span>
                    </td>
                    <td className="td-menu">
                      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                        <button className="btn btn-secondary btn-sm" onClick={() => setShowAddAdminFor(t.id)}>
                          + Admin
                        </button>
                        <button className="btn btn-secondary btn-sm" onClick={() => toggleTenantActive(t)}>
                          {t.is_active ? "Deactivate" : "Activate"}
                        </button>
                        <button className="btn btn-danger btn-sm" onClick={() => handleDeleteTenant(t)}>
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>

                  {showAddAdminFor === t.id && (
                    <tr>
                      <td colSpan={8}>
                        <form onSubmit={(e) => handleAddAdmin(e, t.id)} style={{ padding: "8px 0" }}>
                          <div className="field-row">
                            <div className="field">
                              <label>Full name</label>
                              <input
                                className="input"
                                required
                                value={adminForm.full_name}
                                onChange={(e) => setAdminForm({ ...adminForm, full_name: e.target.value })}
                              />
                            </div>
                            <div className="field">
                              <label>Email</label>
                              <input
                                className="input"
                                type="email"
                                required
                                value={adminForm.email}
                                onChange={(e) => setAdminForm({ ...adminForm, email: e.target.value })}
                              />
                            </div>
                            <div className="field">
                              <label>Initial password</label>
                              <input
                                className="input"
                                type="password"
                                required
                                minLength={8}
                                value={adminForm.password}
                                onChange={(e) => setAdminForm({ ...adminForm, password: e.target.value })}
                              />
                            </div>
                          </div>
                          {adminError && <p className="error-text">{adminError}</p>}
                          <div className="panel-actions-right">
                            <button
                              type="button"
                              className="btn btn-secondary"
                              onClick={() => {
                                setShowAddAdminFor(null);
                                setAdminError(null);
                              }}
                            >
                              Cancel
                            </button>
                            <button type="submit" className="btn btn-primary" disabled={addingAdmin}>
                              {addingAdmin ? "Adding..." : "Add Admin"}
                            </button>
                          </div>
                        </form>
                      </td>
                    </tr>
                  )}

                  {expandedTenantId === t.id && (
                    <tr>
                      <td colSpan={8}>
                        <div style={{ padding: "8px 0" }}>
                          <h6 style={{ marginBottom: 8 }}>Users in {t.name}</h6>
                          {usersLoading ? (
                            <p className="empty-state">Loading...</p>
                          ) : tenantUsers.length === 0 ? (
                            <p className="empty-state">No users in this tenant yet.</p>
                          ) : (
                            <table className="table">
                              <thead>
                                <tr>
                                  <th>Name</th>
                                  <th>Email</th>
                                  <th>Role</th>
                                </tr>
                              </thead>
                              <tbody>
                                {tenantUsers.map((u) => (
                                  <tr key={u.id}>
                                    <td>{u.full_name}</td>
                                    <td>{u.email}</td>
                                    <td>
                                      <select className="input" value={u.role} onChange={(e) => changeUserRole(u, e.target.value as Role)}>
                                        <option value="user">User</option>
                                        <option value="admin">Admin</option>
                                        <option value="super_admin">Super Admin</option>
                                      </select>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
