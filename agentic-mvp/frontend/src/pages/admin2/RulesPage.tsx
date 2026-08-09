import { FormEvent, useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { policiesApi } from "../../api/policies";
import type { Policy } from "../../types";

// Matches admin-app.html's "Rules" screen — real tenant-scoped Policy rows
// (OPA/Rego-style rule_expression, app/models/policy.py). The mockup's copy
// is narrative ("Actions that change things: Always ask first"); this
// build's actual policies are named rule expressions an admin writes
// themselves, so the table below shows those real rows rather than
// hard-coding the mockup's specific example limits, which aren't backed by
// a per-tenant setting in this build (they're enforced platform-wide — see
// the Super Admin "Platform rules" screen for the floor every tenant
// inherits and cannot loosen).
export default function RulesPage() {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", rule_expression: "" });
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setPolicies(await policiesApi.list());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load rules");
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
      await policiesApi.create(form);
      setForm({ name: "", rule_expression: "" });
      setShowCreate(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Create failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mds-col" style={{ maxWidth: 760, gap: 36 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 24 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: 36, marginBottom: 8 }}>Rules</h1>
          <p className="mds-lead">
            Limits that apply to every workspace here. These cannot be talked around by the assistant or by anyone using it.
          </p>
        </div>
        <button className="mds-btn mds-btn-primary" onClick={() => setShowCreate(true)}>Add a rule</button>
      </div>

      {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

      {showCreate && (
        <form onSubmit={handleCreate} className="mds-card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <label className="mds-kicker" style={{ display: "block", marginBottom: 6 }}>Name</label>
            <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} style={{ width: "100%" }} />
          </div>
          <div>
            <label className="mds-kicker" style={{ display: "block", marginBottom: 6 }}>Rule expression</label>
            <input required value={form.rule_expression} onChange={(e) => setForm({ ...form, rule_expression: e.target.value })} style={{ width: "100%" }} />
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button type="button" className="mds-btn" onClick={() => setShowCreate(false)}>Cancel</button>
            <button type="submit" className="mds-btn mds-btn-primary" disabled={submitting}>{submitting ? "Saving…" : "Save"}</button>
          </div>
        </form>
      )}

      {loading ? (
        <p className="mds-muted">Loading…</p>
      ) : policies.length === 0 ? (
        <div className="mds-card mds-muted">No rules defined for this organisation yet.</div>
      ) : (
        policies.map((p) => (
          <div key={p.id} style={{ display: "flex", gap: 24, alignItems: "center", padding: "18px 0", borderBottom: "1px solid var(--mds-n300)" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 15.5, fontWeight: 600, marginBottom: 3 }}>{p.name}</div>
              <div className="mds-muted" style={{ fontSize: 13.5, lineHeight: 1.5, fontFamily: "monospace" }}>{p.rule_expression}</div>
            </div>
            <div className="mds-fix" style={{ width: 100, textAlign: "right" }}>
              <span className={`mds-tag ${p.is_active ? "mds-tag-accent" : "mds-tag-outline"}`}>{p.mode}</span>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
