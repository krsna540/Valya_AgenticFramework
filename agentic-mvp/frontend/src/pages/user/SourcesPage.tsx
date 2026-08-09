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

// Matches user-app.html's "Sources" screen — real, read-only Datasource
// visibility (see the authz.rego change adding "datasource" to
// _user_readable_types for this screen). No "Add a source" button: that's
// an Admin action (admin2/SourcesPage.tsx), not a user one.
export default function SourcesPage() {
  const [sources, setSources] = useState<Datasource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    datasourcesApi
      .list()
      .then(setSources)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load sources"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <section className="mds-screen center" style={{ display: "flex", justifyContent: "center", padding: "56px 32px", flex: 1, minHeight: 0, overflow: "auto" }}>
      <div className="mds-col" style={{ maxWidth: 900, gap: 32, width: "100%" }}>
        <div>
          <h1 style={{ fontSize: 34, marginBottom: 8 }}>Sources</h1>
          <p className="mds-lead" style={{ maxWidth: 560 }}>
            What the assistant is allowed to read. You only ever see results from sources you already have access to.
          </p>
        </div>

        {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

        <div>
          <div className="mds-table-head">
            <div className="mds-grow">Source</div>
            <div className="mds-fix" style={{ width: 130 }}>Connector</div>
            <div className="mds-fix" style={{ width: 150 }}>Last updated</div>
            <div className="mds-fix" style={{ width: 100 }}>Status</div>
          </div>
          {loading ? (
            <p className="mds-muted" style={{ padding: "20px 12px" }}>Loading…</p>
          ) : sources.length === 0 ? (
            <p className="mds-muted" style={{ padding: "20px 12px" }}>No sources visible to you yet.</p>
          ) : (
            sources.map((s) => (
              <div className="mds-row" key={s.id} style={{ cursor: "default" }}>
                <div className="mds-grow">
                  <div style={{ fontFamily: "var(--mds-font-head)", fontSize: 16, fontWeight: 600 }}>{s.name}</div>
                  <div className="mds-muted" style={{ fontSize: 13, marginTop: 2 }}>{s.description ?? "—"}</div>
                </div>
                <div className="mds-fix" style={{ width: 130, fontSize: 13.5 }}>{s.connector_type}</div>
                <div className="mds-fix mds-muted" style={{ width: 150, fontSize: 13.5 }}>
                  {s.last_synced_at ? new Date(s.last_synced_at).toLocaleString() : "Never"}
                </div>
                <div className="mds-fix" style={{ width: 100 }}>
                  <span className={`mds-tag ${STATUS_TAG[s.auth_status]}`}>{s.auth_status.replace("_", " ")}</span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
