import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { datasourcesApi } from "../../api/datasources";
import type { Datasource } from "../../types";

const STATUS_TAG: Record<Datasource["auth_status"], string> = {
  connected: "mds-tag-accent",
  not_connected: "mds-tag-outline",
  expired: "mds-tag-neutral",
  error: "mds-tag-outline",
};

// Matches admin-app.html's "Sources" screen — real Datasource rows.
export default function SourcesPage() {
  const [sources, setSources] = useState<Datasource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      setSources(await datasourcesApi.list());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load sources");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleSync(id: string) {
    setSyncing(id);
    try {
      await datasourcesApi.sync(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sync failed");
    } finally {
      setSyncing(null);
    }
  }

  return (
    <div className="mds-col" style={{ maxWidth: 1000, gap: 32 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 24 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: 36, marginBottom: 8 }}>Sources</h1>
          <p className="mds-lead" style={{ maxWidth: 620 }}>
            Where knowledge comes from. Connect a system once, say which teams its content belongs to, and it stays in step
            on its own.
          </p>
        </div>
      </div>

      {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {loading ? (
          <p className="mds-muted">Loading…</p>
        ) : sources.length === 0 ? (
          <p className="mds-muted">No sources connected yet.</p>
        ) : (
          sources.map((s) => (
            <div className="mds-card" key={s.id} style={{ display: "flex", gap: 28, alignItems: "flex-start" }}>
              <div className="mds-grow">
                <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 5 }}>
                  <span style={{ fontFamily: "var(--mds-font-head)", fontSize: 19, fontWeight: 600 }}>{s.name}</span>
                  <span className={`mds-tag ${STATUS_TAG[s.auth_status]}`}>{s.auth_status.replace("_", " ")}</span>
                </div>
                <div style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--mds-n800)", marginBottom: 14 }}>
                  {s.description ?? "No description."}
                </div>
                <div style={{ display: "flex", gap: 32, flexWrap: "wrap" }}>
                  <div>
                    <div style={{ fontSize: 11.5, letterSpacing: ".05em", textTransform: "uppercase", color: "var(--mds-n700)", marginBottom: 3 }}>Connector</div>
                    <div style={{ fontSize: 14 }}>{s.connector_type}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11.5, letterSpacing: ".05em", textTransform: "uppercase", color: "var(--mds-n700)", marginBottom: 3 }}>Refreshes</div>
                    <div style={{ fontSize: 14 }}>{s.sync_mode}{s.sync_schedule_cron ? ` · ${s.sync_schedule_cron}` : ""}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11.5, letterSpacing: ".05em", textTransform: "uppercase", color: "var(--mds-n700)", marginBottom: 3 }}>Classification</div>
                    <div style={{ fontSize: 14 }}>{s.security_classification}</div>
                  </div>
                </div>
              </div>
              <div className="mds-fix" style={{ width: 190 }}>
                <div className="mds-muted" style={{ fontSize: 12.5, marginBottom: 6 }}>
                  {s.last_synced_at ? `Synced ${new Date(s.last_synced_at).toLocaleString()}` : "Never synced"}
                </div>
                <button className="mds-btn mds-btn-block mds-btn-sm" disabled={syncing === s.id} onClick={() => handleSync(s.id)}>
                  {syncing === s.id ? "Syncing…" : "Sync now"}
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
