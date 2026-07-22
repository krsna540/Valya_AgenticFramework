import { FormEvent, useEffect, useState } from "react";
import type { HookHandlerInfo, Plugin, Tool } from "../types";
import { pluginsApi } from "../api/plugins";
import { hooksApi } from "../api/registry";
import { toolsApi } from "../api/tools";
import { ApiError } from "../api/client";
import { toYamlText } from "../utils/yaml";
import { useAuth } from "../context/AuthContext";
import TagInput from "../components/TagInput";

interface FormState {
  name: string;
  description: string;
  is_active: boolean;
  version: string;
  status: "Active" | "Experimental" | "Deprecated";
  exports_skills: string[];
  exports_hooks: string[];
  exports_tools: string[];
  exports_commands: string[];
  requires_permissions: string[];
  requires_env: string[];
}

function emptyForm(): FormState {
  return {
    name: "",
    description: "",
    is_active: true,
    version: "1.0.0",
    status: "Active",
    exports_skills: [],
    exports_hooks: [],
    exports_tools: [],
    exports_commands: [],
    requires_permissions: [],
    requires_env: [],
  };
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export default function PluginsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<Plugin[]>([]);
  const [hookHandlers, setHookHandlers] = useState<HookHandlerInfo[]>([]);
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [panelMode, setPanelMode] = useState<"closed" | "create" | "edit">("closed");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showYaml, setShowYaml] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [plugins, hooks, toolList] = await Promise.all([
        pluginsApi.list(),
        hooksApi.listHandlers(),
        toolsApi.list(),
      ]);
      setItems(plugins);
      setHookHandlers(hooks);
      setTools(toolList);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function openCreate() {
    setEditingId(null);
    setForm(emptyForm());
    setFormError(null);
    setPanelMode("create");
    setShowYaml(false);
  }

  function openEdit(item: Plugin) {
    setEditingId(item.id);
    setForm({
      name: item.name,
      description: item.description ?? "",
      is_active: item.is_active,
      version: item.version,
      status: item.status,
      exports_skills: item.exports_skills ?? [],
      exports_hooks: item.exports_hooks ?? [],
      exports_tools: item.exports_tools ?? [],
      exports_commands: item.exports_commands ?? [],
      requires_permissions: item.requires_permissions ?? [],
      requires_env: item.requires_env ?? [],
    });
    setFormError(null);
    setPanelMode("edit");
    setShowYaml(false);
  }

  function closePanel() {
    setPanelMode("closed");
    setEditingId(null);
  }

  function yamlPreview(): string {
    return toYamlText({
      id: editingId ?? "(generated on save)",
      name: form.name,
      description: form.description || null,
      version: form.version,
      status: form.status,
      exports: {
        skills: form.exports_skills,
        hooks: form.exports_hooks,
        tools: form.exports_tools,
        commands: form.exports_commands,
      },
      requires: {
        permissions: form.requires_permissions,
        env: form.requires_env,
      },
      is_active: form.is_active,
    });
  }

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      const payload = {
        name: form.name,
        description: form.description || null,
        is_active: form.is_active,
        version: form.version,
        status: form.status,
        exports_skills: form.exports_skills,
        exports_hooks: form.exports_hooks,
        exports_tools: form.exports_tools,
        exports_commands: form.exports_commands,
        requires_permissions: form.requires_permissions,
        requires_env: form.requires_env,
      };
      if (editingId) {
        await pluginsApi.update(editingId, payload);
      } else {
        await pluginsApi.create(payload);
      }
      closePanel();
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Save failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this plugin?")) return;
    try {
      await pluginsApi.remove(id);
      if (editingId === id) closePanel();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Plugins</h1>
          <p>
            Bundles of Skills/Hooks/Tools, installed together as one unit. Hooks and Tools exports must resolve to
            a real, code-reviewed handler already registered; Skills exports are advisory names only — skills are
            now folder-based (SKILL.md + optional skill.json) rather than a handler_key catalog, so there's nothing
            to validate against (see docs/SKILL_STANDARD.md).
          </p>
        </div>
        {isAdmin && (
          <button className="btn" onClick={openCreate}>
            New Plugin
          </button>
        )}
      </div>

      {error && <p className="error-text">{error}</p>}

      <div className="registry-layout">
        <div className="blueprint registry-list-col">
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          {loading ? (
            <p className="empty-state">Loading...</p>
          ) : items.length === 0 ? (
            <p className="empty-state">No plugins yet.</p>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className={`rowbtn ${editingId === item.id ? "selected" : ""}`}
                onClick={() => openEdit(item)}
              >
                <span className="rowbtn-title">{item.name}</span>
                <div className="rowbtn-tags">
                  <span className={`tag ${item.is_active ? "tag-accent" : "tag-neutral"}`}>
                    {item.is_active ? "active" : "inactive"}
                  </span>
                  <span className="text-muted" style={{ fontSize: 11.5 }}>
                    {item.exports_skills.length + item.exports_hooks.length + item.exports_tools.length} exports
                  </span>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="blueprint registry-panel">
          <i className="corner tl" />
          <i className="corner tr" />
          <i className="corner bl" />
          <i className="corner br" />
          {panelMode === "closed" ? (
            <p className="registry-panel-placeholder">Select a plugin to view details, or create a new one.</p>
          ) : (
            <>
              <div className="detail-header">
                <div>
                  <h6 className="detail-kicker">Plugin</h6>
                  <h2>{panelMode === "create" ? "New Plugin" : form.name || "Edit Plugin"}</h2>
                </div>
                <div className="tab-switch">
                  <button type="button" className={!showYaml ? "active" : ""} onClick={() => setShowYaml(false)}>
                    Form
                  </button>
                  <button type="button" className={showYaml ? "active" : ""} onClick={() => setShowYaml(true)}>
                    YAML
                  </button>
                </div>
              </div>

              {showYaml ? (
                <pre className="yaml-view">{yamlPreview()}</pre>
              ) : (
                <form onSubmit={handleSubmit}>
                  <div className="field">
                    <label>Name</label>
                    <input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                  </div>
                  <div className="field">
                    <label>Description</label>
                    <textarea className="input" rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                  </div>

                  <h3 className="section-heading">Exports</h3>
                  <TagInput
                    label="Skills (advisory names)"
                    values={form.exports_skills}
                    onChange={(exports_skills) => setForm({ ...form, exports_skills })}
                    placeholder="skill-folder-name, ..."
                  />
                  <div className="field">
                    <label>Hooks ({form.exports_hooks.length} selected)</label>
                    <div className="chip-picker">
                      {hookHandlers.length === 0 && <p className="empty-state">No hook handlers registered.</p>}
                      {hookHandlers.map((h) => (
                        <button
                          key={h.key}
                          type="button"
                          className={`chip ${form.exports_hooks.includes(h.key) ? "selected" : ""}`}
                          title={`${h.stage}: ${h.description}`}
                          onClick={() => setForm({ ...form, exports_hooks: toggle(form.exports_hooks, h.key) })}
                        >
                          {h.key}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="field">
                    <label>Tools ({form.exports_tools.length} selected)</label>
                    <div className="chip-picker">
                      {tools.length === 0 && <p className="empty-state">No tools registered yet.</p>}
                      {tools.map((t) => (
                        <button
                          key={t.id}
                          type="button"
                          className={`chip ${form.exports_tools.includes(t.name) ? "selected" : ""}`}
                          onClick={() => setForm({ ...form, exports_tools: toggle(form.exports_tools, t.name) })}
                        >
                          {t.name}
                        </button>
                      ))}
                    </div>
                  </div>
                  <TagInput
                    label="Commands"
                    values={form.exports_commands}
                    onChange={(exports_commands) => setForm({ ...form, exports_commands })}
                    placeholder="slash-command shortcuts (advisory)"
                  />

                  <h3 className="section-heading">Requires</h3>
                  <TagInput
                    label="Permissions"
                    values={form.requires_permissions}
                    onChange={(requires_permissions) => setForm({ ...form, requires_permissions })}
                    placeholder="memory:read, ..."
                  />
                  <TagInput
                    label="Environment keys"
                    values={form.requires_env}
                    onChange={(requires_env) => setForm({ ...form, requires_env })}
                    placeholder="API_KEY_NAME, ..."
                  />

                  <div className="field" style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 14 }}>
                    <input type="checkbox" id="is_active" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
                    <label htmlFor="is_active" style={{ margin: 0 }}>
                      Active
                    </label>
                  </div>
                </form>
              )}

              {formError && <p className="error-text">{formError}</p>}
              <div className="panel-actions">
                <div>
                  {isAdmin && editingId && (
                    <button type="button" className="btn-danger btn" onClick={() => handleDelete(editingId)}>
                      Delete
                    </button>
                  )}
                </div>
                <div className="panel-actions-right">
                  <button type="button" className="btn-secondary btn" onClick={closePanel}>
                    Close
                  </button>
                  {isAdmin && (
                    <button type="button" className="btn" disabled={submitting} onClick={() => handleSubmit()}>
                      {submitting ? "Saving..." : "Save"}
                    </button>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
