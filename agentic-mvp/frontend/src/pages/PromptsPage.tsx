import { FormEvent, useEffect, useState } from "react";
import type { Prompt, PromptMessage, PromptVariable } from "../types";
import { promptsApi } from "../api/prompts";
import { ApiError } from "../api/client";
import { useAuth } from "../context/AuthContext";
import TagInput from "../components/TagInput";

interface FormState {
  name: string;
  description: string;
  is_active: boolean;
  version: string;
  status: "Active" | "Experimental" | "Deprecated";
  label: string;
  tags: string[];
  messages: PromptMessage[];
  variables: PromptVariable[];
  model: string;
  temperature: string;
  max_tokens: string;
  top_p: string;
  stop: string[];
}

function emptyForm(): FormState {
  return {
    name: "",
    description: "",
    is_active: true,
    version: "1.0.0",
    status: "Active",
    label: "latest",
    tags: [],
    messages: [{ role: "user", content: "" }],
    variables: [],
    model: "",
    temperature: "",
    max_tokens: "",
    top_p: "",
    stop: [],
  };
}

const VARIABLE_PATTERN = /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g;

function referencedVariables(messages: PromptMessage[]): string[] {
  const found = new Set<string>();
  for (const m of messages) {
    for (const match of m.content.matchAll(VARIABLE_PATTERN)) found.add(match[1]);
  }
  return [...found];
}

export default function PromptsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<Prompt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [panelMode, setPanelMode] = useState<"closed" | "create" | "edit">("closed");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setItems(await promptsApi.list());
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
  }

  function openEdit(item: Prompt) {
    setEditingId(item.id);
    setForm({
      name: item.name,
      description: item.description ?? "",
      is_active: item.is_active,
      version: item.version,
      status: item.status,
      label: item.label,
      tags: item.tags ?? [],
      messages: item.messages.length > 0 ? item.messages : [{ role: "user", content: "" }],
      variables: item.variables ?? [],
      model: item.model_params?.model ?? "",
      temperature: item.model_params?.temperature != null ? String(item.model_params.temperature) : "",
      max_tokens: item.model_params?.max_tokens != null ? String(item.model_params.max_tokens) : "",
      top_p: item.model_params?.top_p != null ? String(item.model_params.top_p) : "",
      stop: item.model_params?.stop ?? [],
    });
    setFormError(null);
    setPanelMode(isAdmin ? "edit" : "closed");
  }

  function closePanel() {
    setPanelMode("closed");
    setEditingId(null);
  }

  function addMessage() {
    setForm({ ...form, messages: [...form.messages, { role: "user", content: "" }] });
  }

  function removeMessage(index: number) {
    setForm({ ...form, messages: form.messages.filter((_, i) => i !== index) });
  }

  function updateMessage(index: number, patch: Partial<PromptMessage>) {
    setForm({
      ...form,
      messages: form.messages.map((m, i) => (i === index ? { ...m, ...patch } : m)),
    });
  }

  function addVariable(name?: string) {
    setForm({
      ...form,
      variables: [...form.variables, { name: name ?? "", description: null, default: null, required: true }],
    });
  }

  function removeVariable(index: number) {
    setForm({ ...form, variables: form.variables.filter((_, i) => i !== index) });
  }

  function updateVariable(index: number, patch: Partial<PromptVariable>) {
    setForm({
      ...form,
      variables: form.variables.map((v, i) => (i === index ? { ...v, ...patch } : v)),
    });
  }

  const declaredNames = new Set(form.variables.map((v) => v.name));
  const undeclared = referencedVariables(form.messages).filter((n) => !declaredNames.has(n));

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    setFormError(null);

    if (form.messages.some((m) => !m.content.trim())) {
      setFormError("Every message needs content (or remove the empty one)");
      return;
    }
    if (undeclared.length > 0) {
      setFormError(`Messages reference undeclared variable(s): ${undeclared.join(", ")}. Add them below or remove the {{placeholder}}.`);
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        name: form.name,
        description: form.description || null,
        is_active: form.is_active,
        version: form.version,
        status: form.status,
        label: form.label,
        tags: form.tags,
        messages: form.messages,
        variables: form.variables,
        model_params: {
          model: form.model || null,
          temperature: form.temperature ? Number(form.temperature) : null,
          max_tokens: form.max_tokens ? Number(form.max_tokens) : null,
          top_p: form.top_p ? Number(form.top_p) : null,
          stop: form.stop,
        },
      };
      if (editingId) {
        await promptsApi.update(editingId, payload);
      } else {
        await promptsApi.create(payload);
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
    if (!confirm("Delete this prompt template?")) return;
    try {
      await promptsApi.remove(id);
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
          <h1>Prompts</h1>
          <p>
            Chat-style templates with {"{{variables}}"} and versioned model parameters — surfaced in chat via the
            "/" command. Structure follows common prompt-registry conventions (Langfuse/LangSmith-style).
          </p>
        </div>
        {isAdmin && (
          <button className="btn btn-primary" onClick={openCreate}>
            New Prompt
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
            <p className="empty-state">No prompt templates yet.</p>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className={`rowbtn ${editingId === item.id ? "selected" : ""}`}
                onClick={() => openEdit(item)}
              >
                <span className="rowbtn-title">{item.name}</span>
                <div className="rowbtn-tags">
                  <span className={`tag ${item.is_active ? "tag-accent" : "tag-neutral"}`}>{item.is_active ? "active" : "inactive"}</span>
                  <span className="tag tag-neutral">{item.label}</span>
                  <span className="text-muted" style={{ fontSize: 11.5 }}>v{item.version}</span>
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
            <p className="registry-panel-placeholder">
              {isAdmin ? "Select a prompt to view details, or create a new one." : "Select a prompt to view details."}
            </p>
          ) : (
            <>
              <div className="detail-header">
                <div>
                  <h6 className="detail-kicker">Prompt</h6>
                  <h2>{panelMode === "create" ? "New Prompt" : form.name || "Edit Prompt"}</h2>
                </div>
              </div>

              <form onSubmit={handleSubmit}>
                <div className="field-row">
                  <div className="field">
                    <label>Name</label>
                    <input className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                  </div>
                  <div className="field">
                    <label>Label</label>
                    <input
                      className="input"
                      list="prompt-label-suggestions"
                      value={form.label}
                      onChange={(e) => setForm({ ...form, label: e.target.value })}
                    />
                    <datalist id="prompt-label-suggestions">
                      <option value="production" />
                      <option value="staging" />
                      <option value="latest" />
                    </datalist>
                  </div>
                </div>
                <div className="field">
                  <label>Description</label>
                  <textarea className="input" rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
                </div>
                <TagInput label="Tags" values={form.tags} onChange={(tags) => setForm({ ...form, tags })} placeholder="support, onboarding, ..." />

                <h3 className="section-heading">Messages</h3>
                {form.messages.map((m, i) => (
                  <div key={i} className="sectioncard" style={{ marginBottom: 10 }}>
                    <div className="field-row" style={{ alignItems: "flex-start" }}>
                      <div className="field" style={{ flex: "0 0 140px" }}>
                        <label>Role</label>
                        <select className="input" value={m.role} onChange={(e) => updateMessage(i, { role: e.target.value as PromptMessage["role"] })}>
                          <option value="system">system</option>
                          <option value="user">user</option>
                          <option value="assistant">assistant</option>
                        </select>
                      </div>
                      <div className="field" style={{ flex: 1 }}>
                        <label>Content</label>
                        <textarea
                          className="input"
                          rows={3}
                          style={{ fontFamily: "monospace", fontSize: 13 }}
                          placeholder="Use {{variable_name}} for placeholders"
                          value={m.content}
                          onChange={(e) => updateMessage(i, { content: e.target.value })}
                        />
                      </div>
                    </div>
                    {form.messages.length > 1 && (
                      <button type="button" className="btn-secondary btn" onClick={() => removeMessage(i)}>
                        Remove message
                      </button>
                    )}
                  </div>
                ))}
                <button type="button" className="btn-secondary btn" onClick={addMessage} style={{ marginBottom: 16 }}>
                  + Add message
                </button>

                <h3 className="section-heading">Variables</h3>
                {undeclared.length > 0 && (
                  <p className="error-text">
                    Referenced but not declared: {undeclared.join(", ")}.{" "}
                    <button type="button" className="btn-secondary btn" style={{ padding: "2px 8px", fontSize: 12 }} onClick={() => undeclared.forEach((n) => addVariable(n))}>
                      Add all
                    </button>
                  </p>
                )}
                {form.variables.map((v, i) => (
                  <div key={i} className="field-row" style={{ alignItems: "flex-end", marginBottom: 8 }}>
                    <div className="field" style={{ flex: "0 0 160px", marginBottom: 0 }}>
                      <label>Name</label>
                      <input className="input" value={v.name} onChange={(e) => updateVariable(i, { name: e.target.value })} />
                    </div>
                    <div className="field" style={{ flex: 1, marginBottom: 0 }}>
                      <label>Description</label>
                      <input className="input" value={v.description ?? ""} onChange={(e) => updateVariable(i, { description: e.target.value || null })} />
                    </div>
                    <div className="field" style={{ flex: "0 0 140px", marginBottom: 0 }}>
                      <label>Default</label>
                      <input className="input" value={v.default ?? ""} onChange={(e) => updateVariable(i, { default: e.target.value || null })} />
                    </div>
                    <div className="field" style={{ flex: "0 0 90px", display: "flex", alignItems: "center", gap: 6, marginBottom: 0 }}>
                      <input type="checkbox" id={`var-req-${i}`} checked={v.required} onChange={(e) => updateVariable(i, { required: e.target.checked })} />
                      <label htmlFor={`var-req-${i}`} style={{ margin: 0 }}>required</label>
                    </div>
                    <button type="button" className="btn-secondary btn" onClick={() => removeVariable(i)}>
                      &times;
                    </button>
                  </div>
                ))}
                <button type="button" className="btn-secondary btn" onClick={() => addVariable()} style={{ marginBottom: 16 }}>
                  + Add variable
                </button>

                <h3 className="section-heading">Model parameters (versioned with this prompt)</h3>
                <div className="field-row">
                  <div className="field">
                    <label>Model</label>
                    <input className="input" placeholder="e.g. claude-sonnet-5" value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} />
                  </div>
                  <div className="field">
                    <label>Temperature</label>
                    <input className="input" type="number" min={0} max={2} step={0.1} value={form.temperature} onChange={(e) => setForm({ ...form, temperature: e.target.value })} />
                  </div>
                </div>
                <div className="field-row">
                  <div className="field">
                    <label>Max tokens</label>
                    <input className="input" type="number" min={1} value={form.max_tokens} onChange={(e) => setForm({ ...form, max_tokens: e.target.value })} />
                  </div>
                  <div className="field">
                    <label>Top P</label>
                    <input className="input" type="number" min={0} max={1} step={0.05} value={form.top_p} onChange={(e) => setForm({ ...form, top_p: e.target.value })} />
                  </div>
                </div>
                <TagInput label="Stop sequences" values={form.stop} onChange={(stop) => setForm({ ...form, stop })} placeholder="\\n\\nHuman:, ..." />

                <div className="field-row" style={{ marginTop: 14 }}>
                  <div className="field">
                    <label>Version</label>
                    <input className="input" value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} />
                  </div>
                  <div className="field">
                    <label>Status</label>
                    <select className="input" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as FormState["status"] })}>
                      <option value="Active">Active</option>
                      <option value="Experimental">Experimental</option>
                      <option value="Deprecated">Deprecated</option>
                    </select>
                  </div>
                </div>

                <div className="field" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <input type="checkbox" id="is_active" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
                  <label htmlFor="is_active" style={{ margin: 0 }}>Active</label>
                </div>
              </form>

              {formError && <p className="error-text">{formError}</p>}
              {isAdmin && (
                <div className="panel-actions">
                  <div>
                    {editingId && (
                      <button type="button" className="btn btn-danger" onClick={() => handleDelete(editingId)}>
                        Delete
                      </button>
                    )}
                  </div>
                  <div className="panel-actions-right">
                    <button type="button" className="btn btn-secondary" onClick={closePanel}>
                      Close
                    </button>
                    <button type="button" className="btn btn-primary" disabled={submitting} onClick={() => handleSubmit()}>
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
