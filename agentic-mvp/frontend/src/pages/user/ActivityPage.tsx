import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { runsApi, type RunSummary } from "../../api/runs";

const STATUS_TAG: Record<string, string> = {
  succeeded: "mds-tag-accent",
  running: "mds-tag-outline",
  failed: "mds-tag-outline",
  pending: "mds-tag-neutral",
};

// Matches user-app.html's "Activity" screen — real AgentRun history for
// this tenant, newest first.
export default function ActivityPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    runsApi
      .list({ limit: 100 })
      .then(setRuns)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load activity"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <section className="mds-screen center" style={{ display: "flex", justifyContent: "center", padding: "56px 32px", flex: 1, minHeight: 0, overflow: "auto" }}>
      <div className="mds-col" style={{ maxWidth: 820, gap: 32, width: "100%" }}>
        <div>
          <h1 style={{ fontSize: 34, marginBottom: 8 }}>Activity</h1>
          <p className="mds-lead">Everything the assistant has done, newest first.</p>
        </div>

        {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

        {loading ? (
          <p className="mds-muted">Loading…</p>
        ) : runs.length === 0 ? (
          <p className="mds-muted">Nothing recorded yet.</p>
        ) : (
          runs.map((r) => (
            <div className="mds-list-row" key={r.id} style={{ padding: "16px 12px" }}>
              <div className="mds-fix mds-muted" style={{ width: 150, fontSize: 13 }}>
                {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}
              </div>
              <div className="mds-grow">
                <div style={{ fontSize: 15, lineHeight: 1.5 }}>{r.objective}</div>
                <div className="mds-muted" style={{ fontSize: 12.5, marginTop: 3 }}>{r.project_name ?? "—"} · {r.agent_name ?? "an agent"}</div>
              </div>
              <span className={`mds-tag ${STATUS_TAG[r.status] ?? "mds-tag-neutral"} mds-fix`}>{r.status}</span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
