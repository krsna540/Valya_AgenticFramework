import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { platformRulesApi, type PolicyRevision } from "../../api/platformRules";

// Matches superadmin-app.html's "Platform rules" screen — real, seeded
// PolicyRevision rows (backend/app/services/platform_rules.py::DEFAULT_RULES
// mirrors the mockup's POLICIES array verbatim). Rollback re-points
// `is_current` at an older revision; publish appends a new one. Both are
// wired to the real endpoints, not simulated.
export default function RulesPage() {
  const [current, setCurrent] = useState<PolicyRevision | null>(null);
  const [revisions, setRevisions] = useState<PolicyRevision[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const [c, revs] = await Promise.all([platformRulesApi.current(), platformRulesApi.revisions()]);
      setCurrent(c);
      setRevisions(revs);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load platform rules");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleRollback(revisionId: string) {
    if (!confirm("Roll back to this revision? It becomes the currently-live one; nothing after it is deleted.")) return;
    setBusy(true);
    try {
      await platformRulesApi.rollback(revisionId);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Rollback failed");
    } finally {
      setBusy(false);
    }
  }

  async function handlePublish() {
    if (!current) return;
    setBusy(true);
    try {
      await platformRulesApi.publish(current.summary, current.rules);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Publish failed");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="mds-muted">Loading…</p>;

  return (
    <div className="mds-col" style={{ maxWidth: 920, gap: 32 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 24 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: 36, marginBottom: 8 }}>Platform rules</h1>
          <p className="mds-lead" style={{ maxWidth: 640 }}>
            The limits no organisation can loosen. Each change is tested, then published as a numbered revision that can be
            rolled back whole.
          </p>
        </div>
        <button className="mds-btn mds-btn-primary" onClick={handlePublish} disabled={busy || !current}>
          Publish revision
        </button>
      </div>

      {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

      {current && (
        <div style={{ border: "1px solid var(--mds-a700)", padding: "20px 24px", display: "flex", gap: 28, alignItems: "center" }}>
          <div style={{ flex: 1 }}>
            <div className="mds-kicker" style={{ color: "var(--mds-a700)", marginBottom: 5 }}>Currently live</div>
            <div style={{ fontFamily: "var(--mds-font-head)", fontSize: 22, fontWeight: 600 }}>Revision {current.revision_number}</div>
            <div className="mds-muted" style={{ fontSize: 13.5, marginTop: 3 }}>
              Published {new Date(current.created_at).toLocaleDateString()} by {current.published_by_name ?? "—"} ·{" "}
              {current.tests_passed} tests passed
            </div>
          </div>
        </div>
      )}

      <div>
        <h2 style={{ fontSize: 21, marginBottom: 14 }}>What it enforces</h2>
        {(current?.rules ?? []).map((p) => (
          <div key={p.name} style={{ display: "flex", gap: 24, alignItems: "flex-start", padding: "16px 0", borderBottom: "1px solid var(--mds-n300)" }}>
            <div className="mds-grow">
              <div style={{ fontSize: 15.5, fontWeight: 600, marginBottom: 3 }}>{p.name}</div>
              <div className="mds-muted" style={{ fontSize: 13.5, lineHeight: 1.55 }}>{p.detail}</div>
            </div>
            <div className="mds-fix" style={{ width: 150, textAlign: "right", fontSize: 13.5, color: "var(--mds-a700)" }}>{p.bound}</div>
          </div>
        ))}
      </div>

      <div>
        <h2 style={{ fontSize: 21, marginBottom: 14 }}>Revision history</h2>
        {revisions.map((r) => (
          <div className="mds-row" key={r.id} style={{ padding: "13px 12px" }}>
            <div className="mds-fix" style={{ width: 110, fontFamily: "var(--mds-font-head)", fontSize: 15, fontWeight: 600 }}>
              rev {r.revision_number}
            </div>
            <div className="mds-grow" style={{ fontSize: 14, lineHeight: 1.5 }}>{r.summary}</div>
            <div className="mds-fix mds-muted" style={{ width: 150, fontSize: 13 }}>{r.published_by_name ?? "—"}</div>
            <div className="mds-fix" style={{ width: 100 }}>
              {r.is_current ? (
                <span className="mds-tag mds-tag-accent">Live</span>
              ) : (
                <button className="mds-btn mds-btn-sm" disabled={busy} onClick={() => handleRollback(r.id)}>
                  Roll back
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
