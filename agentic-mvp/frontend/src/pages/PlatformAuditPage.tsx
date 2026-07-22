import { useEffect, useState } from "react";
import type { AuditLogEntry } from "../types";
import { platformApi } from "../api/platform";
import { ApiError } from "../api/client";

export default function PlatformAuditPage() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [actionFilter, setActionFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load(action?: string) {
    setLoading(true);
    setError(null);
    try {
      setEntries(await platformApi.audit({ action: action || undefined, limit: 200 }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load audit log");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Audit</h1>
          <p>Tenant/admin lifecycle, role changes, datasource and policy edits, model-route changes, project freeze/deploy.</p>
        </div>
        <input
          className="filter-input"
          placeholder="Filter by action…"
          value={actionFilter}
          onChange={(e) => setActionFilter(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && load(actionFilter)}
        />
      </div>

      {error && <p className="error-text">{error}</p>}

      <div className="card" style={{ overflow: "hidden" }}>
        {loading ? (
          <p className="empty-state">Loading...</p>
        ) : entries.length === 0 ? (
          <p className="empty-state">No audit entries yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>When</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Resource</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td className="mono td-dim">{new Date(e.created_at).toLocaleString()}</td>
                  <td className="td-dim">{e.actor_email ?? "—"}</td>
                  <td className="td-main">{e.action}</td>
                  <td className="mono">
                    {e.resource_type}
                    {e.resource_id ? ` · ${e.resource_id.slice(0, 8)}` : ""}
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
