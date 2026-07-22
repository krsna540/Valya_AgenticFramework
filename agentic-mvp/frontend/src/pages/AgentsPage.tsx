import { FormEvent, useEffect, useState } from "react";
import type { Agent, Hook, RegistryItem, Skill } from "../types";
import { agentsApi, hooksApi, pluginsApi } from "../api/registry";
import { toolsApi } from "../api/tools";
import { skillsApi } from "../api/skills";
import { ApiError } from "../api/client";
import { toYamlText } from "../utils/yaml";
import { useAuth } from "../context/AuthContext";

interface FormState {
  name: string;
  description: string;
  system_prompt: string;
  model_name: string;
  is_active: boolean;
  skill_ids: string[];
  tool_ids: string[];
  plugin_ids: string[];
  hook_ids: string[];
}

const EMPTY_FORM: FormState = {
  name: "",
  description: "",
  system_prompt: "",
  model_name: "stub-echo",
  is_active: true,
  skill_ids: [],
  tool_ids: [],
  plugin_ids: [],
  hook_ids: [],
};

function toggle(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

export default function AgentsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [agents, setAgents] = useState<Agent[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [tools, setTools] = useState<RegistryItem[]>([]);
  const [plugins, setPlugins] = useState<RegistryItem[]>([]);
  const [hooks, setHooks] = useState<Hook[]>([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [panelMode, setPanelMode] = useState<"closed" | "create" | "edit">("closed");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showYaml, setShowYaml] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [a, s, t, p, h] = await Promise.all([
        agentsApi.list(),
        skillsApi.list(),
        toolsApi.list(),
        pluginsApi.list(),
        hooksApi.list(),
      ]);
      setAgents(a);
      setSkills(s);
      setTools(t);
      setPlugins(p);
      setHooks(h);
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
    setForm(EMPTY_FORM);
    setFormError(null);
    setPanelMode("create");
    setShowYaml(false);
  }

  function openEdit(agent: Agent) {
    setEditingId(agent.id);
    setForm({
      name: agent.name,
      description: agent.description ?? "",
      system_prompt: agent.system_prompt ?? "",
      model_name: agent.model_name,
      is_active: agent.is_active,
      skill_ids: agent.skill_ids,
      tool_ids: agent.tool_ids,
      plugin_ids: agent.plugin_ids,
      hook_ids: agent.hook_ids,
    });
    setFormError(null);
    setPanelMode("edit");
    setShowYaml(false);
  }

  function closePanel() {
    setPanelMode("closed");
    setEditingId(null);
  }

  function nameFor(list: { id: string; name: string }[], id: string): string {
    return list.find((i) => i.id === id)?.name ?? id;
  }

  function yamlPreview(): string {
    return toYamlText({
      id: editingId ?? "(generated on save)",
      name: form.name,
      description: form.description || null,
      model_name: form.model_name,
      system_prompt: form.system_prompt || null,
      is_active: form.is_active,
      skills: form.skill_ids.map((id) => nameFor(skills, id)),
      tools: form.tool_ids.map((id) => nameFor(tools, id)),
      plugins: form.plugin_ids.map((id) => nameFor(plugins, id)),
      hooks: form.hook_ids.map((id) => nameFor(hooks, id)),
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
        system_prompt: form.system_prompt || null,
        model_name: form.model_name,
        is_active: form.is_active,
        skill_ids: form.skill_ids,
        tool_ids: form.tool_ids,
        plugin_ids: form.plugin_ids,
        hook_ids: form.hook_ids,
      };
      if (editingId) {
        await agentsApi.update(editingId, payload);
      } else {
        await agentsApi.create(payload);
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
    if (!confirm("Delete this agent?")) return;
    try {
      await agentsApi.remove(id);
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
          <h1>Agents</h1>
          <p>Compose agents from skills, tools, plugins, and hooks.</p>
        </div>
        {isAdmin && (
          <button className="btn" onClick={openCreate}>
            New Agent
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
          ) : agents.length === 0 ? (
            <p className="empty-state">No agents yet.</p>
          ) : (
            agents.map((agent) => (
              <div
                key={agent.id}
                className={`rowbtn ${editingId === agent.id ? "selected" : ""}`}
                onClick={() => openEdit(agent)}
              >
                <span className="rowbtn-title">{agent.name}</span>
                <div className="rowbtn-tags">
                  <span className={`tag ${agent.is_active ? "tag-accent" : "tag-neutral"}`}>
                    {agent.is_active ? "active" : "inactive"}
                  </span>
                  <span className="text-muted" style={{ fontSize: 11.5 }}>{agent.model_name}</span>
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
            <p className="registry-panel-placeholder">Select an agent to view details, or create a new one.</p>
          ) : (
            <>
              <div className="detail-header">
                <div>
                  <h6 className="detail-kicker">Agent</h6>
                  <h2>{panelMode === "create" ? "New Agent" : form.name || "Edit Agent"}</h2>
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
                    <input
                      className="input"
                      required
                      value={form.name}
                      onChange={(e) => setForm({ ...form, name: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label>Description</label>
                    <textarea
                      className="input"
                      rows={2}
                      value={form.description}
                      onChange={(e) => setForm({ ...form, description: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label>Model name</label>
                    <input
                      className="input"
                      value={form.model_name}
                      onChange={(e) => setForm({ ...form, model_name: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label>System prompt</label>
                    <textarea
                      className="input"
                      rows={4}
                      value={form.system_prompt}
                      onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
                    />
                  </div>

                  {[
                    { label: "Skills", list: skills, selected: form.skill_ids, key: "skill_ids" as const },
                    { label: "Tools", list: tools, selected: form.tool_ids, key: "tool_ids" as const },
                    { label: "Plugins", list: plugins, selected: form.plugin_ids, key: "plugin_ids" as const },
                    {
                      label: "Hooks",
                      // Global-scope hooks apply to every agent automatically —
                      // only agent-scope hooks need explicit attachment here.
                      list: hooks.filter((h) => h.scope === "agent"),
                      selected: form.hook_ids,
                      key: "hook_ids" as const,
                    },
                  ].map(({ label, list, selected, key }) => (
                    <div className="field" key={key}>
                      <label>{label}</label>
                      {key === "hook_ids" && hooks.some((h) => h.scope === "global") && (
                        <p className="composer-overlay-desc" style={{ marginBottom: 6 }}>
                          {hooks.filter((h) => h.scope === "global" && h.is_active).length} global hook(s) also apply
                          automatically and don't need to be picked here.
                        </p>
                      )}
                      {list.length === 0 ? (
                        <p className="empty-state" style={{ padding: "4px 0", textAlign: "left" }}>
                          None created yet.
                        </p>
                      ) : (
                        <div className="chip-select">
                          {list.map((item) => (
                            <div
                              key={item.id}
                              className={`chip ${selected.includes(item.id) ? "selected" : ""}`}
                              onClick={() => setForm({ ...form, [key]: toggle(selected, item.id) })}
                            >
                              {item.name}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}

                  <div className="field" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <input
                      type="checkbox"
                      id="is_active"
                      checked={form.is_active}
                      onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                    />
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
