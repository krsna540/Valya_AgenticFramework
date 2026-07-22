import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type {
  AdminUser,
  Binding,
  ComponentType,
  Datasource,
  ExecutionMode,
  Hook,
  Project,
  ProjectTopology,
  RegistryItem,
} from "../types";
import { projectsApi } from "../api/projects";
import { adminUsersApi } from "../api/admin";
import { datasourcesApi } from "../api/datasources";
import { agentsApi, hooksApi, pluginsApi } from "../api/registry";
import { toolsApi } from "../api/tools";
import { skillsApi } from "../api/skills";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";

type Tab = "overview" | "users" | "datasources" | "intelligence" | "runtime";

const COMPONENT_GROUPS: { type: ComponentType; label: string }[] = [
  { type: "agent", label: "Agents" },
  { type: "tool", label: "Tools" },
  { type: "hook", label: "Hooks" },
  { type: "skill", label: "Skills" },
  { type: "plugin", label: "Plugins" },
];

function fmtDate(s: string | null): string {
  if (!s) return "—";
  return new Date(s).toLocaleString();
}

export default function ProjectsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isAdmin = user?.role === "admin";

  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");

  // create-project mini form
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function loadProjects() {
    setLoading(true);
    setError(null);
    try {
      setProjects(await projectsApi.list());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadProjects();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreateError(null);
    setCreating(true);
    try {
      const project = await projectsApi.create({ name: newName, description: newDescription || null });
      setNewName("");
      setNewDescription("");
      setShowCreate(false);
      await loadProjects();
      setSelectedId(project.id);
      setTab("overview");
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Create failed");
    } finally {
      setCreating(false);
    }
  }

  async function handleDeleteProject(id: string) {
    if (!confirm("Delete this project? This cannot be undone.")) return;
    try {
      await projectsApi.remove(id);
      if (selectedId === id) setSelectedId(null);
      await loadProjects();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  const selected = projects.find((p) => p.id === selectedId) ?? null;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Projects</h1>
          <p>
            The deployment wrapper: connect datasources, map users (+ personas), compose the Intelligence Layer, then
            freeze and deploy the runtime.
          </p>
        </div>
        {isAdmin && (
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            New Project
          </button>
        )}
      </div>

      {error && <p className="error-text">{error}</p>}

      {showCreate && (
        <div className="blueprint card" style={{ marginBottom: 16 }}>
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          <form onSubmit={handleCreate}>
            <div className="field-row">
              <div className="field">
                <label>Name</label>
                <input className="input" required value={newName} onChange={(e) => setNewName(e.target.value)} />
              </div>
              <div className="field">
                <label>Description</label>
                <input className="input" value={newDescription} onChange={(e) => setNewDescription(e.target.value)} />
              </div>
            </div>
            {createError && <p className="error-text">{createError}</p>}
            <div className="panel-actions-right">
              <button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={creating}>
                {creating ? "Creating..." : "Create"}
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="registry-layout">
        <div className="blueprint registry-list-col">
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          {loading ? (
            <p className="empty-state">Loading...</p>
          ) : projects.length === 0 ? (
            <p className="empty-state">No projects yet.</p>
          ) : (
            projects.map((p) => (
              <div
                key={p.id}
                className={`rowbtn ${selectedId === p.id ? "selected" : ""}`}
                onClick={() => {
                  setSelectedId(p.id);
                  setTab("overview");
                }}
              >
                <span className="rowbtn-title">{p.name}</span>
                <div className="rowbtn-tags">
                  <span className={`status-pill ${p.status}`}>{p.status}</span>
                  <span className="text-muted" style={{ fontSize: 11.5 }}>{p.execution_mode.replace("_", " ")}</span>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="blueprint registry-panel" style={{ minWidth: 560 }}>
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          {!selected ? (
            <p className="registry-panel-placeholder">Select a project to view details.</p>
          ) : (
            <>
              <div className="detail-header" style={{ marginBottom: 8 }}>
                <div>
                  <h6 className="detail-kicker">Project</h6>
                  <h2>{selected.name}</h2>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className={`status-pill ${selected.status}`}>{selected.status}</span>
                  {isAdmin && (
                    <button
                      className="btn btn-danger"
                      onClick={() => handleDeleteProject(selected.id)}
                    >
                      Delete
                    </button>
                  )}
                </div>
              </div>
              <div className="project-tabs">
                {(["overview", "users", "datasources", "intelligence", "runtime"] as Tab[]).map((t) => (
                  <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
                    {t === "runtime" ? "Runtime & Freeze" : t.charAt(0).toUpperCase() + t.slice(1)}
                  </button>
                ))}
              </div>

              {tab === "overview" && (
                <OverviewTab project={selected} isAdmin={isAdmin} onSaved={loadProjects} onOpenChat={() => navigate(`/app/chat?project=${selected.id}`)} />
              )}
              {tab === "users" && <UsersTab project={selected} isAdmin={isAdmin} />}
              {tab === "datasources" && <DatasourcesTab project={selected} isAdmin={isAdmin} />}
              {tab === "intelligence" && <IntelligenceTab project={selected} isAdmin={isAdmin} />}
              {tab === "runtime" && <RuntimeTab project={selected} isAdmin={isAdmin} onChanged={loadProjects} />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// --- Overview -----------------------------------------------------------

function OverviewTab({
  project,
  isAdmin,
  onSaved,
  onOpenChat,
}: {
  project: Project;
  isAdmin: boolean;
  onSaved: () => void;
  onOpenChat: () => void;
}) {
  const editable = isAdmin && project.status === "draft";
  const [description, setDescription] = useState(project.description ?? "");
  const [costCenter, setCostCenter] = useState(project.cost_center ?? "");
  const [executionMode, setExecutionMode] = useState<ExecutionMode>(project.execution_mode);
  const [scheduleCron, setScheduleCron] = useState(project.schedule_cron ?? "");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    setDescription(project.description ?? "");
    setCostCenter(project.cost_center ?? "");
    setExecutionMode(project.execution_mode);
    setScheduleCron(project.schedule_cron ?? "");
  }, [project]);

  async function handleSave() {
    setFormError(null);
    setSaving(true);
    try {
      await projectsApi.update(project.id, {
        description: description || null,
        cost_center: costCenter || null,
        execution_mode: executionMode,
        schedule_cron: executionMode === "scheduled" ? scheduleCron || null : null,
      });
      await onSaved();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <div className="field">
        <label>Description</label>
        <textarea className="input" rows={2} disabled={!editable} value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>
      <div className="field">
        <label>Cost center / billing tag</label>
        <input className="input" disabled={!editable} value={costCenter} onChange={(e) => setCostCenter(e.target.value)} />
      </div>
      <h3 className="section-heading">Operational Mode</h3>
      <div className="field">
        <label>Execution mode</label>
        <select className="input" disabled={!editable} value={executionMode} onChange={(e) => setExecutionMode(e.target.value as ExecutionMode)}>
          <option value="real_time_chat">Real-Time Chat — multi-turn conversational interface</option>
          <option value="event_driven">Event-Driven — triggered by an external webhook</option>
          <option value="scheduled">Scheduled Execution — cron-based polling</option>
        </select>
      </div>
      {executionMode === "scheduled" && (
        <div className="field">
          <label>Cron schedule</label>
          <input className="input" disabled={!editable} placeholder="0 17 * * FRI" value={scheduleCron} onChange={(e) => setScheduleCron(e.target.value)} />
        </div>
      )}
      {executionMode === "event_driven" && project.webhook_slug && (
        <p className="composer-overlay-desc">
          Webhook receiver (stub): POST /api/v1/projects/{project.id}/webhook/{project.webhook_slug}
        </p>
      )}
      {!editable && project.status !== "draft" && (
        <p className="composer-overlay-desc">Unfreeze this project (Runtime &amp; Freeze tab) to edit its composition.</p>
      )}
      {formError && <p className="error-text">{formError}</p>}
      <div className="panel-actions-right" style={{ marginTop: 12 }}>
        <button className="btn btn-secondary" onClick={onOpenChat}>
          Open in Chat
        </button>
        {editable && (
          <button className="btn btn-primary" disabled={saving} onClick={handleSave}>
            {saving ? "Saving..." : "Save"}
          </button>
        )}
      </div>
    </div>
  );
}

// --- Users ----------------------------------------------------------------

function UsersTab({ project, isAdmin }: { project: Project; isAdmin: boolean }) {
  const [allUsers, setAllUsers] = useState<AdminUser[]>([]);
  const [mappedIds, setMappedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const editable = isAdmin && project.status === "draft";

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const mapped = await projectsApi.listUsers(project.id);
      setMappedIds(mapped);
      if (isAdmin) setAllUsers(await adminUsersApi.list());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id]);

  async function toggleUser(userId: string, mapped: boolean) {
    setBusyId(userId);
    try {
      if (mapped) {
        await projectsApi.removeUser(project.id, userId);
      } else {
        await projectsApi.addUser(project.id, userId);
      }
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <p className="empty-state">Loading...</p>;
  if (!isAdmin) {
    return <p className="composer-overlay-desc">{mappedIds.length} user(s) mapped to this project.</p>;
  }

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {allUsers.length === 0 ? (
        <p className="empty-state">No users in this tenant yet. Add them from Admin &gt; Users.</p>
      ) : (
        <table className="registry-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {allUsers.map((u) => {
              const mapped = mappedIds.includes(u.id);
              return (
                <tr key={u.id}>
                  <td>{u.full_name}</td>
                  <td>{u.email}</td>
                  <td>
                    <span className={`tag ${u.role === "admin" ? "tag-accent" : "tag-neutral"}`}>{u.role}</span>
                  </td>
                  <td>
                    <button
                      className={mapped ? "btn btn-danger" : "btn btn-secondary"}
                      disabled={!editable || busyId === u.id}
                      onClick={() => toggleUser(u.id, mapped)}
                    >
                      {mapped ? "Remove" : "Add"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

// --- Datasources ------------------------------------------------------------

function DatasourcesTab({ project, isAdmin }: { project: Project; isAdmin: boolean }) {
  const [allDatasources, setAllDatasources] = useState<Datasource[]>([]);
  const [connectedIds, setConnectedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const editable = isAdmin && project.status === "draft";

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [ds, topo] = await Promise.all([datasourcesApi.list(), projectsApi.topology(project.id)]);
      setAllDatasources(ds);
      setConnectedIds(topo.datasources.map((d) => d.datasource_id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id]);

  async function toggleDatasource(id: string, connected: boolean) {
    setBusyId(id);
    try {
      if (connected) {
        await projectsApi.removeDatasource(project.id, id);
      } else {
        await projectsApi.addDatasource(project.id, id);
      }
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <p className="empty-state">Loading...</p>;

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {allDatasources.length === 0 ? (
        <p className="empty-state">No datasources onboarded yet.</p>
      ) : (
        <div className="chip-select">
          {allDatasources.map((d) => {
            const connected = connectedIds.includes(d.id);
            return (
              <div
                key={d.id}
                className={`chip ${connected ? "selected" : ""}`}
                onClick={() => (editable ? toggleDatasource(d.id, connected) : undefined)}
                style={{ opacity: editable || connected ? 1 : 0.6, cursor: editable ? "pointer" : "default" }}
              >
                {d.name} <span style={{ opacity: 0.6 }}>({d.security_classification})</span>
                {busyId === d.id && "…"}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// --- Intelligence-to-Project association matrix --------------------------

function IntelligenceTab({ project, isAdmin }: { project: Project; isAdmin: boolean }) {
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [agents, setAgents] = useState<{ id: string; name: string; version: string }[]>([]);
  const [tools, setTools] = useState<RegistryItem[]>([]);
  const [hooks, setHooks] = useState<Hook[]>([]);
  const [skills, setSkills] = useState<{ id: string; name: string; version: string }[]>([]);
  const [plugins, setPlugins] = useState<RegistryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const editable = isAdmin && project.status === "draft";

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [b, a, t, h, s, p] = await Promise.all([
        projectsApi.listBindings(project.id),
        agentsApi.list(),
        toolsApi.list(),
        hooksApi.list(),
        skillsApi.list(),
        pluginsApi.list(),
      ]);
      setBindings(b);
      setAgents(a.map((x) => ({ id: x.id, name: x.name, version: x.version })));
      setTools(t);
      setHooks(h);
      setSkills(s.map((x) => ({ id: x.id, name: x.name, version: x.version })));
      setPlugins(p);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id]);

  function listFor(type: ComponentType): { id: string; name: string; version: string }[] {
    switch (type) {
      case "agent":
        return agents;
      case "tool":
        return tools.map((x) => ({ id: x.id, name: x.name, version: x.version }));
      case "hook":
        return hooks.map((x) => ({ id: x.id, name: x.name, version: x.version }));
      case "skill":
        return skills;
      case "plugin":
        return plugins.map((x) => ({ id: x.id, name: x.name, version: x.version }));
    }
  }

  function bindingFor(type: ComponentType, componentId: string): Binding | undefined {
    return bindings.find((b) => b.component_type === type && b.component_id === componentId);
  }

  async function toggle(type: ComponentType, componentId: string, version: string) {
    const key = `${type}:${componentId}`;
    setBusyKey(key);
    try {
      const existing = bindingFor(type, componentId);
      if (existing) {
        await projectsApi.removeBinding(project.id, existing.id);
      } else {
        await projectsApi.createBinding(project.id, type, componentId, version);
      }
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    } finally {
      setBusyKey(null);
    }
  }

  if (loading) return <p className="empty-state">Loading...</p>;

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      <p className="composer-overlay-desc" style={{ marginBottom: 12 }}>
        "For this Project, attach Agent v1.2, grant it the Jira MCP Tool, apply the PII-Scrubber Hook, and activate
        the Excel Generation Skill." Bindings pin the component's current version at bind time.
      </p>
      {COMPONENT_GROUPS.map(({ type, label }) => {
        const items = listFor(type);
        return (
          <div className="matrix-group" key={type}>
            <h4>{label}</h4>
            {items.length === 0 ? (
              <p className="empty-state" style={{ padding: "4px 0", textAlign: "left" }}>None created yet.</p>
            ) : (
              <div className="chip-select">
                {items.map((item) => {
                  const bound = bindingFor(type, item.id);
                  const key = `${type}:${item.id}`;
                  return (
                    <div
                      key={item.id}
                      className={`chip ${bound ? "selected" : ""}`}
                      style={{ opacity: editable ? 1 : bound ? 1 : 0.6, cursor: editable ? "pointer" : "default" }}
                      onClick={() => (editable ? toggle(type, item.id, item.version) : undefined)}
                    >
                      {item.name} <span style={{ opacity: 0.6 }}>v{bound?.version_pinned ?? item.version}</span>
                      {busyKey === key && "…"}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// --- Runtime & Freeze -------------------------------------------------------

function RuntimeTab({ project, isAdmin, onChanged }: { project: Project; isAdmin: boolean; onChanged: () => void }) {
  const [topology, setTopology] = useState<ProjectTopology | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setTopology(await projectsApi.topology(project.id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, project.status]);

  async function handleFreeze() {
    setBusy(true);
    setError(null);
    try {
      await projectsApi.freeze(project.id);
      await onChanged();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Freeze failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleUnfreeze() {
    setBusy(true);
    setError(null);
    try {
      await projectsApi.unfreeze(project.id);
      await onChanged();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unfreeze failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeploy() {
    if (!confirm("Confirm & Deploy? The configuration matrix will be locked.")) return;
    setBusy(true);
    setError(null);
    try {
      await projectsApi.deploy(project.id);
      await onChanged();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Deploy failed");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <p className="empty-state">Loading...</p>;
  if (!topology) return null;

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      <div className="freeze-screen">
        <div className="freeze-screen-header">
          <strong>{topology.project_name}</strong>
          <span className={`status-pill ${topology.status}`}>{topology.status}</span>
        </div>
        <div className="freeze-section">
          <h4>Runtime Engine</h4>
          <div className="freeze-row">
            <span>Mode</span>
            <span>
              {topology.execution_mode === "scheduled"
                ? `Scheduled Execution: ${topology.schedule_cron || "(no cron set)"}`
                : topology.execution_mode === "event_driven"
                ? `Event-Driven: webhook ${topology.webhook_slug ?? "(unassigned)"}`
                : "Real-Time Chat"}
            </span>
          </div>
        </div>
        <div className="freeze-section">
          <h4>Mapped Users &amp; Personas</h4>
          {topology.mapped_users.length === 0 ? (
            <p className="empty-state" style={{ padding: "4px 0", textAlign: "left" }}>No users mapped yet.</p>
          ) : (
            topology.mapped_users.map((u) => (
              <div className="freeze-row" key={u.user_id}>
                <span>{u.full_name}</span>
                <span>{u.persona_name ? `Persona: ${u.persona_name}` : "No persona assigned"}</span>
              </div>
            ))
          )}
        </div>
        <div className="freeze-section">
          <h4>Datasources Connected</h4>
          {topology.datasources.length === 0 ? (
            <p className="empty-state" style={{ padding: "4px 0", textAlign: "left" }}>None connected yet.</p>
          ) : (
            topology.datasources.map((d) => (
              <div className="freeze-row" key={d.datasource_id}>
                <span>{d.name} ({d.connector_type})</span>
                <span>{d.security_classification} tier</span>
              </div>
            ))
          )}
        </div>
        <div className="freeze-section">
          <h4>Intelligence Composition</h4>
          {topology.intelligence.length === 0 ? (
            <p className="empty-state" style={{ padding: "4px 0", textAlign: "left" }}>Nothing bound yet.</p>
          ) : (
            COMPONENT_GROUPS.map(({ type, label }) => {
              const items = topology.intelligence.filter((c) => c.component_type === type);
              if (items.length === 0) return null;
              return (
                <div className="freeze-row" key={type}>
                  <span>{label}</span>
                  <span>{items.map((c) => `${c.name} (v${c.version})`).join(", ")}</span>
                </div>
              );
            })
          )}
        </div>
      </div>

      <p className="composer-overlay-desc" style={{ marginTop: 8 }}>
        Resolved {fmtDate(topology.resolved_at)}. {project.status === "deployed" && "This project's runtime is live — no real event listeners/schedulers are actually provisioned in this MVP."}
      </p>

      {isAdmin && (
        <div className="panel-actions-right" style={{ marginTop: 12 }}>
          {project.status === "draft" && (
            <button className="btn btn-primary" disabled={busy} onClick={handleFreeze}>
              {busy ? "Freezing..." : "Freeze"}
            </button>
          )}
          {project.status === "frozen" && (
            <>
              <button className="btn btn-secondary" disabled={busy} onClick={handleUnfreeze}>
                Modify Components
              </button>
              <button className="btn btn-primary" disabled={busy} onClick={handleDeploy}>
                {busy ? "Deploying..." : "Confirm & Deploy"}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
