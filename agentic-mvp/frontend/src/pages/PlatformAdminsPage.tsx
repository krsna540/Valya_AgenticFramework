import { useEffect, useState } from "react";
import type { AdminUser, Role } from "../types";
import { platformApi } from "../api/platform";
import { ApiError } from "../api/client";

// Cross-tenant roster of every Admin account — GET /platform/users?role=admin.
// Role changes here reuse the same Super-Admin-only PUT /platform/users/{id}/role
// as the Tenants page's expanded user table.
export default function PlatformAdminsPage() {
  const [admins, setAdmins] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setAdmins(await platformApi.listUsers({ role: "admin" }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load admins");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function changeRole(u: AdminUser, role: Role) {
    try {
      await platformApi.updateUserRole(u.id, { role, tenant_id: u.tenant_id });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Role change failed");
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Admins</h1>
          <p>Every Admin account across every tenant. Assign new ones from the Tenants page.</p>
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}

      <div className="card" style={{ overflow: "hidden" }}>
        {loading ? (
          <p className="empty-state">Loading...</p>
        ) : admins.length === 0 ? (
          <p className="empty-state">No admins yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Email</th>
                <th>Tenant ID</th>
                <th>Status</th>
                <th>Role</th>
              </tr>
            </thead>
            <tbody>
              {admins.map((u) => (
                <tr key={u.id}>
                  <td className="td-main">{u.full_name}</td>
                  <td className="td-dim">{u.email}</td>
                  <td className="mono">{u.tenant_id}</td>
                  <td>
                    <span className={`state ${u.is_active ? "ok" : "warn"}`}>{u.is_active ? "Active" : "Inactive"}</span>
                  </td>
                  <td>
                    <select className="input" value={u.role} onChange={(e) => changeRole(u, e.target.value as Role)}>
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
    </div>
  );
}
