import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { platformApi } from "../../api/platform";
import type { AuditLogEntry } from "../../types";

// Matches superadmin-app.html's "Audit log" screen — real, append-only
// audit_logs rows (app/models/audit_log.py), filterable by action text.
export default function AuditPage() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      setEntries(await platformApi.audit({ limit: 200 }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load the audit log");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const filtered = entries.filter((e) => {
    const needle = q.trim().toLowerCase();
    if (!needle) return true;
    return (
      e.action.toLowerCase().includes(needle) ||
      e.resource_type.toLowerCase().includes(needle) ||
      (e.actor_email ?? "").toLowerCase().includes(needle)
    );
  });

  return (
    <div className="mds-col" style={{ maxWidth: 1000, gap: 28 }}>
      <div>
        <h1 style={{ fontSize: 36, marginBottom: 8 }}>Audit log</h1>
        <p className="mds-lead" style={{ maxWidth: 640 }}>
          Every change anyone made, in order, permanently. Entries are added and never edited.
        </p>
      </div>

      {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

      <input placeholder="Search the log" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: "100%", fontSize: 13.5, padding: "7px 12px" }} />

      {loading ? (
        <p className="mds-muted">Loading…</p>
      ) : filtered.length === 0 ? (
        <div style={{ padding: "28px 12px", fontSize: 14, color: "var(--mds-n700)" }}>Nothing matches that.</div>
      ) : (
        filtered.map((e) => (
          <div className="mds-row" key={e.id} style={{ padding: "13px 12px", alignItems: "baseline" }}>
            <div className="mds-fix mds-muted" style={{ width: 170, fontSize: 12.5 }}>{new Date(e.created_at).toLocaleString()}</div>
            <div className="mds-fix" style={{ width: 160, fontSize: 13.5 }}>{e.actor_email ?? "System"}</div>
            <div className="mds-grow" style={{ fontSize: 14, lineHeight: 1.5 }}>{e.action}</div>
            <div className="mds-fix mds-muted" style={{ width: 170, fontSize: 13, textAlign: "right", fontFamily: "monospace" }}>
              {e.resource_type}
              {e.resource_id ? ` · ${e.resource_id.slice(0, 8)}` : ""}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
