import { FormEvent, useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { platformApi } from "../../api/platform";
import type { TenantSummary } from "../../types";

// Matches superadmin-app.html's "Organisations" screen.
export default function TenantsPage() {
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setTenants(await platformApi.listTenants());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load organisations");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await platformApi.createTenant({ name });
      setName("");
      setShowCreate(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Create failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mds-col" style={{ maxWidth: 1080, gap: 32 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 24 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: 36, marginBottom: 8 }}>Organisations</h1>
          <p className="mds-lead" style={{ maxWidth: 620 }}>
            Each one is sealed off from the others. Nothing crosses between them — not people, not sources, not work.
          </p>
        </div>
        <button className="mds-btn mds-btn-primary" onClick={() => setShowCreate(true)}>
          Add an organisation
        </button>
      </div>

      {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

      {showCreate && (
        <form onSubmit={handleCreate} className="mds-card" style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
          <div style={{ flex: 1 }}>
            <label className="mds-kicker" style={{ display: "block", marginBottom: 6 }}>Name</label>
            <input required value={name} onChange={(e) => setName(e.target.value)} style={{ width: "100%" }} />
          </div>
          <button type="button" className="mds-btn" onClick={() => setShowCreate(false)}>Cancel</button>
          <button type="submit" className="mds-btn mds-btn-primary" disabled={submitting}>
            {submitting ? "Creating…" : "Create"}
          </button>
        </form>
      )}

      <div>
        <div className="mds-table-head">
          <div className="mds-grow">Organisation</div>
          <div className="mds-fix" style={{ width: 100 }}>People</div>
          <div className="mds-fix" style={{ width: 110 }}>Workspaces</div>
          <div className="mds-fix" style={{ width: 180 }}>Monthly allowance</div>
          <div className="mds-fix" style={{ width: 100 }}>Status</div>
        </div>
        {loading ? (
          <p className="mds-muted" style={{ padding: "20px 12px" }}>Loading…</p>
        ) : tenants.length === 0 ? (
          <p className="mds-muted" style={{ padding: "20px 12px" }}>No organisations yet.</p>
        ) : (
          tenants.map((t) => (
            <div className="mds-row" key={t.id} style={{ padding: "18px 12px" }}>
              <div className="mds-grow">
                <div className="mds-rname" style={{ fontSize: 17 }}>{t.name}</div>
                <div className="mds-rsub">{t.slug}</div>
              </div>
              <div className="mds-fix" style={{ width: 100, fontSize: 14 }}>{t.user_count}</div>
              <div className="mds-fix" style={{ width: 110, fontSize: 14 }}>{t.workspace_count}</div>
              <div className="mds-fix" style={{ width: 180 }}>
                <div className="mds-bar" style={{ marginBottom: 5 }}>
                  <i style={{ width: "0%" }} />
                </div>
                <div className="mds-muted" style={{ fontSize: 12.5 }}>${t.mtd_cost_usd.toFixed(0)} MTD</div>
              </div>
              <div className="mds-fix" style={{ width: 100 }}>
                <span className={`mds-tag ${t.status_label === "Active" ? "mds-tag-accent" : "mds-tag-outline"}`}>{t.status_label}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
