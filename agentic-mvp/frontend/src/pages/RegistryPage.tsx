import { FormEvent, useEffect, useState } from "react";
import type { RegistryItem } from "../types";
import type { RegistryPayload } from "../api/registry";
import { ApiError } from "../api/client";
import { fromYamlText, toYamlText } from "../utils/yaml";
import { useAuth } from "../context/AuthContext";

interface RegistryApi {
  list: () => Promise<RegistryItem[]>;
  create: (payload: RegistryPayload) => Promise<RegistryItem>;
  update: (id: string, payload: Partial<RegistryPayload>) => Promise<RegistryItem>;
  remove: (id: string) => Promise<void>;
}

interface Props {
  title: string;
  description: string;
  api: RegistryApi;
}

interface FormState {
  name: string;
  description: string;
  is_active: boolean;
  configText: string;
}

const EMPTY_FORM: FormState = { name: "", description: "", is_active: true, configText: "{}" };

type PanelMode = "closed" | "create" | "edit";

export default function RegistryPage({ title, description, api }: Props) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<RegistryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [panelMode, setPanelMode] = useState<PanelMode>("closed");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showYaml, setShowYaml] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setItems(await api.list());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  function openCreate() {
    setEditingId(null);
    setForm(EMPTY_FORM);
    setFormError(null);
    setPanelMode("create");
  }

  function openEdit(item: RegistryItem) {
    setEditingId(item.id);
    setForm({
      name: item.name,
      description: item.description ?? "",
      is_active: item.is_active,
      configText: JSON.stringify(item.config ?? {}, null, 2),
    });
    setFormError(null);
    setPanelMode("edit");
  }

  function closePanel() {
    setPanelMode("closed");
    setEditingId(null);
  }

  function yamlText(): string {
    let config: Record<string, unknown> = {};
    try {
      config = form.configText.trim() ? JSON.parse(form.configText) : {};
    } catch {
      // fall through with empty config — form validation catches this on submit
    }
    return toYamlText({ name: form.name, description: form.description || null, is_active: form.is_active, config });
  }

  function applyYamlText(text: string) {
    try {
      const parsed = fromYamlText(text);
      setForm({
        name: typeof parsed.name === "string" ? parsed.name : form.name,
        description: typeof parsed.description === "string" ? parsed.description : "",
        is_active: typeof parsed.is_active === "boolean" ? parsed.is_active : form.is_active,
        configText: JSON.stringify(parsed.config ?? {}, null, 2),
      });
      setFormError(null);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Invalid YAML");
    }
  }

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    setFormError(null);
    let config: Record<string, unknown> = {};
    try {
      config = form.configText.trim() ? JSON.parse(form.configText) : {};
    } catch {
      setFormError("Config must be valid JSON");
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        name: form.name,
        description: form.description || null,
        is_active: form.is_active,
        config,
      };
      if (editingId) {
        await api.update(editingId, payload);
      } else {
        await api.create(payload);
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
    if (!confirm("Delete this item?")) return;
    try {
      await api.remove(id);
      if (editingId === id) closePanel();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  const singular = title.replace(/s$/, "");

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        {isAdmin && (
          <button className="btn" onClick={openCreate}>
            New {singular}
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
            <p className="empty-state">Nothing here yet.</p>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className={`rowbtn ${editingId === item.id ? "selected" : ""}`}
                onClick={() => openEdit(item)}
              >
                <span className="rowbtn-title">{item.name}</span>
                <span className={`tag ${item.is_active ? "tag-accent" : "tag-neutral"}`} style={{ width: "fit-content" }}>
                  {item.is_active ? "active" : "inactive"}
                </span>
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
            <p className="registry-panel-placeholder">Select a {singular.toLowerCase()} to view details, or create a new one.</p>
          ) : (
            <>
              <div className="detail-header">
                <div>
                  <h6 className="detail-kicker">{singular}</h6>
                  <h2>{panelMode === "create" ? `New ${singular}` : form.name || `Edit ${singular}`}</h2>
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
                <div className="field">
                  <textarea
                    className="input yaml-editable"
                    value={yamlText()}
                    onChange={(e) => applyYamlText(e.target.value)}
                  />
                </div>
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
                    <label>Config (JSON)</label>
                    <textarea
                      className="input"
                      rows={6}
                      style={{ fontFamily: "monospace" }}
                      value={form.configText}
                      onChange={(e) => setForm({ ...form, configText: e.target.value })}
                    />
                  </div>
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
