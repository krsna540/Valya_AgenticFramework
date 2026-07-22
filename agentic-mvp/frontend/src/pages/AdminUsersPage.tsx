import { FormEvent, useEffect, useState } from "react";
import type { AdminUser, Tenant } from "../types";
import { adminUsersApi, tenantApi } from "../api/admin";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";

// Admins can only create plain "user" accounts here — role is fixed
// server-side (AdminUserCreate.role is schema-locked to "user"). Promoting
// someone to admin/super_admin happens on the Super Admin's Platform page
// via PUT /platform/users/{id}/role.
const EMPTY_CREATE = { email: "", full_name: "", password: "" };

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [tenantName, setTenantName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState(EMPTY_CREATE);
  const [createError, setCreateError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [u, t] = await Promise.all([adminUsersApi.list(), tenantApi.me()]);
      setUsers(u);
      setTenant(t);
      setTenantName(t.name);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreateError(null);
    setSubmitting(true);
    try {
      await adminUsersApi.create(createForm);
      setCreateForm(EMPTY_CREATE);
      setShowCreate(false);
      await load();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Create failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleActive(u: AdminUser) {
    try {
      await adminUsersApi.update(u.id, { is_active: !u.is_active });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  }

  async function handleDelete(u: AdminUser) {
    if (!confirm(`Remove ${u.full_name} from this tenant?`)) return;
    try {
      await adminUsersApi.remove(u.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  async function handleTenantSave() {
    try {
      const t = await tenantApi.update({ name: tenantName });
      setTenant(t);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Save failed");
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Admin: Tenant &amp; Users</h1>
          <p>Manage your tenant's profile and the users who belong to it.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          New User
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      <div className="blueprint card" style={{ marginBottom: 16 }}>
        <i className="corner tl" />
        <i className="corner tr" />
        <i className="corner bl" />
        <i className="corner br" />
        <h6 className="detail-kicker" style={{ marginBottom: 4 }}>Workspace</h6>
        <h2 style={{ marginBottom: 12 }}>Tenant</h2>
        <div className="field-row">
          <div className="field">
            <label>Name</label>
            <input className="input" value={tenantName} onChange={(e) => setTenantName(e.target.value)} />
          </div>
          <div className="field">
            <label>Slug</label>
            <input className="input" disabled value={tenant?.slug ?? ""} />
          </div>
        </div>
        <div className="panel-actions-right">
          <button className="btn btn-primary" onClick={handleTenantSave}>
            Save
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="blueprint card" style={{ marginBottom: 16 }}>
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          <h6 className="detail-kicker" style={{ marginBottom: 4 }}>New</h6>
          <h2 style={{ marginBottom: 12 }}>User</h2>
          <form onSubmit={handleCreate}>
            <div className="field-row">
              <div className="field">
                <label>Full name</label>
                <input className="input" required value={createForm.full_name} onChange={(e) => setCreateForm({ ...createForm, full_name: e.target.value })} />
              </div>
              <div className="field">
                <label>Email</label>
                <input className="input" type="email" required value={createForm.email} onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })} />
              </div>
            </div>
            <div className="field-row">
              <div className="field">
                <label>Initial password</label>
                <input
                  className="input"
                  type="password"
                  required
                  minLength={8}
                  value={createForm.password}
                  onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
                />
              </div>
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

      <div className="blueprint card">
        <i className="corner tl" />
        <i className="corner tr" />
        <i className="corner bl" />
        <i className="corner br" />
        {loading ? (
          <p className="empty-state">Loading...</p>
        ) : (
          <table className="registry-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.full_name}</td>
                  <td>{u.email}</td>
                  <td>
                    <span className={`tag ${u.role !== "user" ? "tag-accent" : "tag-neutral"}`}>{u.role}</span>
                  </td>
                  <td>
                    <span className={`tag ${u.is_active ? "tag-accent" : "tag-neutral"}`}>{u.is_active ? "active" : "inactive"}</span>
                  </td>
                  <td>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn btn-secondary" disabled={u.id === currentUser?.id} onClick={() => toggleActive(u)}>
                        {u.is_active ? "Deactivate" : "Activate"}
                      </button>
                      <button className="btn btn-danger" disabled={u.id === currentUser?.id} onClick={() => handleDelete(u)}>
                        Remove
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
