import { FormEvent, useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { projectsApi } from "../../api/projects";
import type { Project } from "../../types";

// Matches admin-app.html's "Workspaces" screen — real Project rows.
// Per-project people/sources/abilities counts aren't aggregated by a single
// list endpoint today (they're each their own sub-resource — see
// projectsApi.listUsers/listBindings), so this table shows what the list
// endpoint actually returns (name, status, execution mode) rather than
// fabricating the mockup's People/Sources/Abilities columns; open a
// workspace's own detail view for those.
export default function WorkspacesPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setProjects(await projectsApi.list());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load workspaces");
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
      await projectsApi.create({ name, description: description || null });
      setName("");
      setDescription("");
      setShowCreate(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Create failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mds-col" style={{ maxWidth: 1040, gap: 32 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 24 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: 36, marginBottom: 8 }}>Workspaces</h1>
          <p className="mds-lead" style={{ maxWidth: 600 }}>
            Each workspace has its own people, sources and abilities. Someone in one cannot see into another.
          </p>
        </div>
        <button className="mds-btn mds-btn-primary" onClick={() => setShowCreate(true)}>New workspace</button>
      </div>

      {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

      {showCreate && (
        <form onSubmit={handleCreate} className="mds-card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div>
            <label className="mds-kicker" style={{ display: "block", marginBottom: 6 }}>Name</label>
            <input required value={name} onChange={(e) => setName(e.target.value)} style={{ width: "100%" }} />
          </div>
          <div>
            <label className="mds-kicker" style={{ display: "block", marginBottom: 6 }}>Description</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)} style={{ width: "100%" }} />
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button type="button" className="mds-btn" onClick={() => setShowCreate(false)}>Cancel</button>
            <button type="submit" className="mds-btn mds-btn-primary" disabled={submitting}>{submitting ? "Creating…" : "Create"}</button>
          </div>
        </form>
      )}

      <div>
        <div className="mds-table-head">
          <div className="mds-grow">Workspace</div>
          <div className="mds-fix" style={{ width: 120 }}>Execution</div>
          <div className="mds-fix" style={{ width: 110 }}>Status</div>
        </div>
        {loading ? (
          <p className="mds-muted" style={{ padding: "20px 12px" }}>Loading…</p>
        ) : projects.length === 0 ? (
          <p className="mds-muted" style={{ padding: "20px 12px" }}>No workspaces yet.</p>
        ) : (
          projects.map((p) => (
            <div className="mds-row" key={p.id} style={{ padding: "18px 12px" }}>
              <div className="mds-grow">
                <div className="mds-rname" style={{ fontSize: 17 }}>{p.name}</div>
                <div className="mds-rsub">{p.description ?? "—"}</div>
              </div>
              <div className="mds-fix" style={{ width: 120, fontSize: 14, textTransform: "capitalize" }}>{p.execution_mode}</div>
              <div className="mds-fix" style={{ width: 110 }}>
                <span className={`mds-tag ${p.status === "deployed" ? "mds-tag-accent" : p.status === "frozen" ? "mds-tag-outline" : "mds-tag-neutral"}`}>
                  {p.status}
                </span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
