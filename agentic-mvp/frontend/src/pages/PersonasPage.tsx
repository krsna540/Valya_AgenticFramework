import { FormEvent, useEffect, useState } from "react";
import type { Persona, PersonaTraits, RegistryItem } from "../types";
import { emptyPersonaTraits } from "../types";
import { personasApi } from "../api/personas";
import { toolsApi } from "../api/tools";
import { datasourcesApi } from "../api/datasources";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";
import { toYamlText } from "../utils/yaml";

interface FormState {
  name: string;
  description: string;
  archetype: string;
  base_model: string;
  is_active: boolean;
  traits: PersonaTraits;
}

function emptyForm(): FormState {
  return { name: "", description: "", archetype: "", base_model: "", is_active: true, traits: emptyPersonaTraits() };
}

function csvToList(text: string): string[] {
  return text.split(",").map((s) => s.trim()).filter(Boolean);
}

function toggleId(list: string[], id: string): string[] {
  return list.includes(id) ? list.filter((x) => x !== id) : [...list, id];
}

export default function PersonasPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [items, setItems] = useState<Persona[]>([]);
  const [tools, setTools] = useState<RegistryItem[]>([]);
  const [datasources, setDatasources] = useState<{ id: string; name: string }[]>([]);
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
      const [personas, toolList, dsList] = await Promise.all([
        personasApi.list(),
        toolsApi.list(),
        datasourcesApi.list(),
      ]);
      setItems(personas);
      setTools(toolList);
      setDatasources(dsList);
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

  function openEdit(item: Persona) {
    setEditingId(item.id);
    setForm({
      name: item.name,
      description: item.description ?? "",
      archetype: item.archetype ?? "",
      base_model: item.base_model ?? "",
      is_active: item.is_active,
      traits: item.traits,
    });
    setFormError(null);
    setPanelMode(isAdmin ? "edit" : "closed");
    setShowYaml(false);
  }

  function closePanel() {
    setPanelMode("closed");
    setEditingId(null);
  }

  function setTraits<K extends keyof PersonaTraits>(key: K, value: PersonaTraits[K]) {
    setForm({ ...form, traits: { ...form.traits, [key]: value } });
  }

  function yamlPreview(): string {
    return toYamlText({
      id: editingId ?? "(generated on save)",
      name: form.name,
      archetype: form.archetype || null,
      base_model: form.base_model || null,
      description: form.description || null,
      traits: form.traits,
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
        archetype: form.archetype || null,
        base_model: form.base_model || null,
        is_active: form.is_active,
        traits: form.traits,
      };
      if (editingId) {
        await personasApi.update(editingId, payload);
      } else {
        await personasApi.create(payload);
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
    if (!confirm("Delete this persona?")) return;
    try {
      await personasApi.remove(id);
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
          <h1>Personas</h1>
          <p>
            Behavioral templates users adopt inside a Project — identity, objectives, audience, tools, knowledge
            scope, guardrails, tone, quirks, interaction style, and safety/compliance in one trait document.
          </p>
        </div>
        {isAdmin && (
          <button className="btn" onClick={openCreate}>
            New Persona
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
            <p className="empty-state">No personas yet.</p>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className={`rowbtn ${editingId === item.id ? "selected" : ""}`}
                onClick={() => openEdit(item)}
              >
                <span className="rowbtn-title">{item.name}</span>
                <span className="text-muted" style={{ fontSize: 12 }}>{item.archetype || "—"}</span>
                <span className="tag tag-outline" style={{ width: "fit-content" }}>DLP · {item.safety_compliance_tier}</span>
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
            <p className="registry-panel-placeholder">
              {isAdmin ? "Select a persona to view details, or create a new one." : "Select a persona to view details."}
            </p>
          ) : (
            <>
              <div className="detail-header">
                <div>
                  <h6 className="detail-kicker">Persona</h6>
                  <h2>{panelMode === "create" ? "New Persona" : form.name || "Edit Persona"}</h2>
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
                  <h3 className="section-heading">Identity &amp; Archetype</h3>
                  <div className="field-row">
                    <div className="field">
                      <label>Persona name</label>
                      <input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                    </div>
                    <div className="field">
                      <label>Archetype / internal role</label>
                      <input
                        className="input"
                        placeholder="Senior Financial Auditor"
                        value={form.archetype}
                        onChange={(e) => setForm({ ...form, archetype: e.target.value })}
                      />
                    </div>
                  </div>
                  <div className="field">
                    <label>Base model alignment</label>
                    <input
                      className="input"
                      placeholder="claude-sonnet-5"
                      value={form.base_model}
                      onChange={(e) => setForm({ ...form, base_model: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label>Description</label>
                    <textarea className="input" rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                  </div>

                  <h3 className="section-heading">Core Objectives</h3>
                  <div className="field">
                    <label>Mission statement</label>
                    <textarea
                      className="input"
                      rows={2}
                      value={form.traits.core_objectives.mission_statement}
                      onChange={(e) => setTraits("core_objectives", { ...form.traits.core_objectives, mission_statement: e.target.value })}
                    />
                  </div>
                  <div className="field-row">
                    <div className="field">
                      <label>Primary KPIs (comma-separated)</label>
                      <input
                        className="input"
                        value={form.traits.core_objectives.primary_kpis.join(", ")}
                        onChange={(e) =>
                          setTraits("core_objectives", { ...form.traits.core_objectives, primary_kpis: csvToList(e.target.value) })
                        }
                      />
                    </div>
                    <div className="field">
                      <label>What "success" looks like</label>
                      <input
                        className="input"
                        value={form.traits.core_objectives.success_criteria}
                        onChange={(e) => setTraits("core_objectives", { ...form.traits.core_objectives, success_criteria: e.target.value })}
                      />
                    </div>
                  </div>

                  <h3 className="section-heading">Target Audience</h3>
                  <div className="field-row">
                    <div className="field">
                      <label>Primary audience</label>
                      <input
                        className="input"
                        placeholder="C-suite executives"
                        value={form.traits.target_audience.primary_audience}
                        onChange={(e) => setTraits("target_audience", { ...form.traits.target_audience, primary_audience: e.target.value })}
                      />
                    </div>
                    <div className="field">
                      <label>Technical depth</label>
                      <select
                        className="input"
                        value={form.traits.target_audience.technical_depth}
                        onChange={(e) =>
                          setTraits("target_audience", {
                            ...form.traits.target_audience,
                            technical_depth: e.target.value as PersonaTraits["target_audience"]["technical_depth"],
                          })
                        }
                      >
                        <option value="basic">Basic</option>
                        <option value="balanced">Balanced</option>
                        <option value="expert">Expert</option>
                      </select>
                    </div>
                  </div>

                  <h3 className="section-heading">Capabilities &amp; Tools</h3>
                  <div className="field">
                    <label>Permitted tools</label>
                    {tools.length === 0 ? (
                      <p className="empty-state" style={{ padding: "4px 0", textAlign: "left" }}>None created yet.</p>
                    ) : (
                      <div className="chip-select">
                        {tools.map((t) => (
                          <div
                            key={t.id}
                            className={`chip ${form.traits.capabilities_tools.allowed_tool_ids.includes(t.id) ? "selected" : ""}`}
                            onClick={() =>
                              setTraits("capabilities_tools", {
                                ...form.traits.capabilities_tools,
                                allowed_tool_ids: toggleId(form.traits.capabilities_tools.allowed_tool_ids, t.id),
                              })
                            }
                          >
                            {t.name}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="field">
                    <label>Permitted MCP server names (comma-separated)</label>
                    <input
                      className="input"
                      value={form.traits.capabilities_tools.allowed_mcp_server_names.join(", ")}
                      onChange={(e) =>
                        setTraits("capabilities_tools", { ...form.traits.capabilities_tools, allowed_mcp_server_names: csvToList(e.target.value) })
                      }
                    />
                  </div>

                  <h3 className="section-heading">Knowledge Domain</h3>
                  <div className="field">
                    <label>Scope description</label>
                    <input
                      className="input"
                      placeholder="Limited to Q3 Marketing Docs"
                      value={form.traits.knowledge_domain.scope_description}
                      onChange={(e) => setTraits("knowledge_domain", { ...form.traits.knowledge_domain, scope_description: e.target.value })}
                    />
                  </div>
                  <div className="field">
                    <label>Allowed datasources</label>
                    {datasources.length === 0 ? (
                      <p className="empty-state" style={{ padding: "4px 0", textAlign: "left" }}>None connected yet.</p>
                    ) : (
                      <div className="chip-select">
                        {datasources.map((d) => (
                          <div
                            key={d.id}
                            className={`chip ${form.traits.knowledge_domain.allowed_datasource_ids.includes(d.id) ? "selected" : ""}`}
                            onClick={() =>
                              setTraits("knowledge_domain", {
                                ...form.traits.knowledge_domain,
                                allowed_datasource_ids: toggleId(form.traits.knowledge_domain.allowed_datasource_ids, d.id),
                              })
                            }
                          >
                            {d.name}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <h3 className="section-heading">Guardrails &amp; Boundaries</h3>
                  <div className="field">
                    <label>Rules (comma-separated)</label>
                    <input
                      className="input"
                      placeholder="Never discuss competitor pricing, Do not write code outside of Python"
                      value={form.traits.guardrails_boundaries.rules.join(", ")}
                      onChange={(e) => setTraits("guardrails_boundaries", { rules: csvToList(e.target.value) })}
                    />
                  </div>

                  <h3 className="section-heading">Tone &amp; Voice</h3>
                  <div className="field-row">
                    <div className="field">
                      <label>Formality: Casual ({form.traits.tone_voice.formality}) Formal</label>
                      <input
                        type="range"
                        min={0}
                        max={100}
                        value={form.traits.tone_voice.formality}
                        onChange={(e) => setTraits("tone_voice", { ...form.traits.tone_voice, formality: Number(e.target.value) })}
                      />
                    </div>
                    <div className="field">
                      <label>Verbosity: Concise ({form.traits.tone_voice.verbosity}) Verbose</label>
                      <input
                        type="range"
                        min={0}
                        max={100}
                        value={form.traits.tone_voice.verbosity}
                        onChange={(e) => setTraits("tone_voice", { ...form.traits.tone_voice, verbosity: Number(e.target.value) })}
                      />
                    </div>
                  </div>

                  <h3 className="section-heading">Personality Quirks</h3>
                  <div className="field">
                    <label>Quirks (comma-separated)</label>
                    <input
                      className="input"
                      placeholder="Uses analogies frequently, Always lists references at the end"
                      value={form.traits.personality_quirks.quirks.join(", ")}
                      onChange={(e) => setTraits("personality_quirks", { quirks: csvToList(e.target.value) })}
                    />
                  </div>

                  <h3 className="section-heading">Interaction Style</h3>
                  <div className="field-row">
                    <div className="field">
                      <label>Timing</label>
                      <select
                        className="input"
                        value={form.traits.interaction_style.timing}
                        onChange={(e) =>
                          setTraits("interaction_style", { ...form.traits.interaction_style, timing: e.target.value as "synchronous" | "asynchronous" })
                        }
                      >
                        <option value="synchronous">Synchronous</option>
                        <option value="asynchronous">Asynchronous</option>
                      </select>
                    </div>
                    <div className="field">
                      <label>Turn style</label>
                      <select
                        className="input"
                        value={form.traits.interaction_style.turn_style}
                        onChange={(e) =>
                          setTraits("interaction_style", { ...form.traits.interaction_style, turn_style: e.target.value as "multi_turn" | "single_shot" })
                        }
                      >
                        <option value="multi_turn">Multi-turn conversational</option>
                        <option value="single_shot">Single-shot command execution</option>
                      </select>
                    </div>
                  </div>

                  <h3 className="section-heading">Safety &amp; Compliance</h3>
                  <div className="field-row">
                    <div className="field" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input
                        type="checkbox"
                        id="pii_masking"
                        checked={form.traits.safety_compliance.pii_masking}
                        onChange={(e) => setTraits("safety_compliance", { ...form.traits.safety_compliance, pii_masking: e.target.checked })}
                      />
                      <label htmlFor="pii_masking" style={{ margin: 0 }}>PII masking</label>
                    </div>
                    <div className="field" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input
                        type="checkbox"
                        id="mandatory_auditing"
                        checked={form.traits.safety_compliance.mandatory_auditing}
                        onChange={(e) => setTraits("safety_compliance", { ...form.traits.safety_compliance, mandatory_auditing: e.target.checked })}
                      />
                      <label htmlFor="mandatory_auditing" style={{ margin: 0 }}>Mandatory auditing</label>
                    </div>
                  </div>
                  <div className="field">
                    <label>DLP tier</label>
                    <select
                      className="input"
                      value={form.traits.safety_compliance.dlp_tier}
                      onChange={(e) =>
                        setTraits("safety_compliance", { ...form.traits.safety_compliance, dlp_tier: e.target.value as PersonaTraits["safety_compliance"]["dlp_tier"] })
                      }
                    >
                      <option value="Relaxed">Relaxed</option>
                      <option value="Standard">Standard</option>
                      <option value="Strict">Strict</option>
                    </select>
                  </div>

                  <div className="field" style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16 }}>
                    <input
                      type="checkbox"
                      id="is_active"
                      checked={form.is_active}
                      onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                    />
                    <label htmlFor="is_active" style={{ margin: 0 }}>Active</label>
                  </div>
                </form>
              )}

              {formError && <p className="error-text">{formError}</p>}
              {isAdmin && (
                <div className="panel-actions">
                  <div>
                    {editingId && (
                      <button type="button" className="btn-danger btn" onClick={() => handleDelete(editingId)}>
                        Delete
                      </button>
                    )}
                  </div>
                  <div className="panel-actions-right">
                    <button type="button" className="btn-secondary btn" onClick={closePanel}>
                      Close
                    </button>
                    <button type="button" className="btn" disabled={submitting} onClick={() => handleSubmit()}>
                      {submitting ? "Saving..." : "Save"}
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
