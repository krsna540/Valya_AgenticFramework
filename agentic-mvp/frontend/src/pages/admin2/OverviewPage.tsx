import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { adminOverviewApi, type AdminOverview } from "../../api/adminOverview";
import { runsApi } from "../../api/runs";

// Matches admin-app.html's "Overview" screen — real aggregation from
// backend/app/api/routes/admin_overview.py. Approve/decline call the real
// runs.decide() endpoint, same one the User app's approval card uses.
export default function OverviewPage() {
  const [ov, setOv] = useState<AdminOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      setOv(await adminOverviewApi.get());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load overview");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function resolve(id: string, approved: boolean) {
    setBusyId(id);
    try {
      await runsApi.decide(id, approved);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not resolve that approval");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <p className="mds-muted">Loading…</p>;

  return (
    <div className="mds-col" style={{ maxWidth: 1000, gap: 40 }}>
      <div>
        <h1 style={{ fontSize: 36, marginBottom: 8 }}>Overview</h1>
        <p className="mds-lead" style={{ maxWidth: 600 }}>
          What is running across your workspaces, and what is waiting on someone.
        </p>
      </div>

      {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

      {ov && (
        <div className="mds-stats">
          <div><div className="v">{ov.workspaces_active_7d}</div><div className="l">Workspaces active this week</div></div>
          <div><div className="v">{ov.work_finished_7d}</div><div className="l">Pieces of work finished</div></div>
          <div>
            <div className="v" style={ov.waiting_on_person > 0 ? { color: "var(--mds-a700)" } : undefined}>{ov.waiting_on_person}</div>
            <div className="l">Waiting on a person</div>
          </div>
          <div><div className="v">{ov.sources_connected}</div><div className="l">Sources connected</div></div>
        </div>
      )}

      <div>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 14 }}>
          <h2 style={{ fontSize: 21 }}>Waiting on a person</h2>
          <span className="mds-muted" style={{ fontSize: 13 }}>Nothing moves until someone decides</span>
        </div>
        {!ov || ov.approvals.length === 0 ? (
          <div style={{ padding: "28px 12px", fontSize: 14, color: "var(--mds-n700)", borderBottom: "1px solid var(--mds-n300)" }}>
            Nothing is waiting. Everything running has what it needs.
          </div>
        ) : (
          ov.approvals.map((a) => (
            <div key={a.id} style={{ display: "flex", gap: 24, alignItems: "flex-start", padding: "18px 12px", borderBottom: "1px solid var(--mds-n300)" }}>
              <div className="mds-grow">
                <div className="mds-rname" style={{ marginBottom: 4 }}>{a.title}</div>
                <div style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--mds-n800)" }}>{a.detail}</div>
                <div className="mds-muted" style={{ fontSize: 12.5, marginTop: 6 }}>
                  {a.project_name ?? "—"} {a.created_at ? `· ${new Date(a.created_at).toLocaleString()}` : ""}
                </div>
              </div>
              <div className="mds-fix" style={{ display: "flex", gap: 8, paddingTop: 2 }}>
                <button className="mds-btn mds-btn-primary mds-btn-sm" disabled={busyId === a.id} onClick={() => resolve(a.id, true)}>
                  Approve
                </button>
                <button className="mds-btn mds-btn-sm" disabled={busyId === a.id} onClick={() => resolve(a.id, false)}>
                  Decline
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      <div>
        <h2 style={{ fontSize: 21, marginBottom: 14 }}>Recent work</h2>
        {!ov || ov.recent.length === 0 ? (
          <p className="mds-muted">Nothing recorded yet.</p>
        ) : (
          ov.recent.map((r) => (
            <div className="mds-row" key={r.id} style={{ padding: "14px 12px" }}>
              <div className="mds-fix mds-muted" style={{ width: 140, fontSize: 13 }}>{r.time ? new Date(r.time).toLocaleString() : "—"}</div>
              <div className="mds-grow">
                <div style={{ fontSize: 14.5, lineHeight: 1.5 }}>{r.summary}</div>
                <div className="mds-muted" style={{ fontSize: 12.5, marginTop: 2 }}>{r.context}</div>
              </div>
              <span className={`mds-tag mds-fix ${r.status === "succeeded" ? "mds-tag-accent" : r.status === "failed" ? "mds-tag-outline" : "mds-tag-neutral"}`}>
                {r.status}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
