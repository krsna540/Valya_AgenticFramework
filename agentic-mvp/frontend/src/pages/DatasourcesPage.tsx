import { FormEvent, useEffect, useState } from "react";
import type { AuthType, ConnectorType, ConnectorTypeInfo, Datasource, SecurityTier, SyncMode } from "../types";
import { datasourcesApi } from "../api/datasources";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";
import { toYamlText } from "../utils/yaml";

interface FormState {
  name: string;
  description: string;
  connector_type: ConnectorType;
  connection_config: Record<string, string>;
  auth_type: AuthType;
  security_classification: SecurityTier;
  chunking_strategy: "token" | "semantic" | "layout_aware";
  chunk_size: string;
  overlap: string;
  embedding_model: string;
  sync_mode: SyncMode;
  sync_schedule_cron: string;
  is_active: boolean;
}

const CONNECTOR_LABELS: Record<ConnectorType, string> = {
  sharepoint: "SharePoint (OAuth2 / tenant scopes)",
  confluence: "Confluence (OAuth2 / space scopes)",
  rest_api: "REST API (API key / bearer proxy)",
  graphql: "GraphQL API",
  sql_database: "SQL Database (read-only, VPC tunnel optional)",
  nosql_database: "NoSQL Database (read-only, VPC tunnel optional)",
  github: "GitHub (App install token / SSH)",
  gitlab: "GitLab (App install token / SSH)",
  web_crawl: "Web crawl (seed URLs, depth, exclusions)",
  file_upload: "Direct file upload",
};

const AUTH_TYPE_LABELS: Record<AuthType, string> = {
  oauth2: "OAuth2",
  api_key: "API key",
  basic: "Basic (username/password)",
  service_account: "Service account",
  none: "None",
};

function emptyForm(connectorTypes: ConnectorTypeInfo[]): FormState {
  const first = connectorTypes[0];
  return {
    name: "",
    description: "",
    connector_type: first?.key ?? "file_upload",
    connection_config: {},
    auth_type: first?.default_auth_type ?? "none",
    security_classification: "Internal",
    chunking_strategy: "token",
    chunk_size: "800",
    overlap: "100",
    embedding_model: "text-embedding-3-small",
    sync_mode: "full_refresh",
    sync_schedule_cron: "",
    is_active: true,
  };
}

export default function DatasourcesPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [items, setItems] = useState<Datasource[]>([]);
  const [connectorTypes, setConnectorTypes] = useState<ConnectorTypeInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [panelMode, setPanelMode] = useState<"closed" | "create" | "edit">("closed");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm([]));
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showYaml, setShowYaml] = useState(false);
  const [actionBusy, setActionBusy] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [ds, ct] = await Promise.all([datasourcesApi.list(), datasourcesApi.listConnectorTypes()]);
      setItems(ds);
      setConnectorTypes(ct);
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
    setForm(emptyForm(connectorTypes));
    setFormError(null);
    setPanelMode("create");
    setShowYaml(false);
  }

  function openEdit(item: Datasource) {
    setEditingId(item.id);
    const stringConfig: Record<string, string> = {};
    for (const [k, v] of Object.entries(item.connection_config ?? {})) stringConfig[k] = String(v);
    setForm({
      name: item.name,
      description: item.description ?? "",
      connector_type: item.connector_type,
      connection_config: stringConfig,
      auth_type: item.auth_type,
      security_classification: item.security_classification,
      chunking_strategy: (item.chunking_policy?.strategy as FormState["chunking_strategy"]) ?? "token",
      chunk_size: String(item.chunking_policy?.chunk_size ?? 800),
      overlap: String(item.chunking_policy?.overlap ?? 100),
      embedding_model: (item.embedding_policy?.model_name as string) ?? "text-embedding-3-small",
      sync_mode: item.sync_mode,
      sync_schedule_cron: item.sync_schedule_cron ?? "",
      is_active: item.is_active,
    });
    setFormError(null);
    setPanelMode(isAdmin ? "edit" : "closed");
    setShowYaml(false);
  }

  function closePanel() {
    setPanelMode("closed");
    setEditingId(null);
  }

  const activeSpec = connectorTypes.find((c) => c.key === form.connector_type);
  const fields = activeSpec?.fields ?? [];

  function buildConnectionConfig(): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    for (const f of fields) {
      const raw = form.connection_config[f.key];
      if (raw === undefined || raw === "") continue;
      if (f.type === "number") out[f.key] = Number(raw);
      else if (f.type === "boolean") out[f.key] = raw === "true";
      else out[f.key] = raw;
    }
    return out;
  }

  function yamlPreview(): string {
    return toYamlText({
      id: editingId ?? "(generated on save)",
      name: form.name,
      connector_type: form.connector_type,
      auth_type: form.auth_type,
      security_classification: form.security_classification,
      connection_config: buildConnectionConfig(),
      chunking_policy: { strategy: form.chunking_strategy, chunk_size: Number(form.chunk_size), overlap: Number(form.overlap) },
      embedding_policy: { model_name: form.embedding_model },
      sync_mode: form.sync_mode,
      sync_schedule_cron: form.sync_schedule_cron || null,
      is_active: form.is_active,
    });
  }

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    setFormError(null);

    const missing = fields.filter((f) => f.required && !form.connection_config[f.key]?.trim());
    if (missing.length > 0) {
      setFormError(`Missing required field(s): ${missing.map((f) => f.label).join(", ")}`);
      return;
    }

    setSubmitting(true);
    try {
      const payload = {
        name: form.name,
        description: form.description || null,
        connector_type: form.connector_type,
        connection_config: buildConnectionConfig(),
        auth_type: form.auth_type,
        security_classification: form.security_classification,
        chunking_policy: { strategy: form.chunking_strategy, chunk_size: Number(form.chunk_size) || 800, overlap: Number(form.overlap) || 0 },
        embedding_policy: { model_name: form.embedding_model, dimensions: 1536 },
        sync_mode: form.sync_mode,
        sync_schedule_cron: form.sync_schedule_cron || null,
        is_active: form.is_active,
      };
      if (editingId) {
        await datasourcesApi.update(editingId, payload);
      } else {
        await datasourcesApi.create(payload);
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
    if (!confirm("Delete this datasource?")) return;
    try {
      await datasourcesApi.remove(id);
      if (editingId === id) closePanel();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  async function handleConnect(id: string) {
    setActionBusy(id);
    try {
      await datasourcesApi.connect(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Connect failed");
    } finally {
      setActionBusy(null);
    }
  }

  async function handleSync(id: string) {
    setActionBusy(id);
    try {
      await datasourcesApi.sync(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sync failed");
    } finally {
      setActionBusy(null);
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Datasources</h1>
          <p>
            Ingestion connectors — SharePoint/Confluence, REST/GraphQL APIs, SQL/NoSQL databases, GitHub/GitLab, web
            crawls, and direct file uploads. Per-connector fields follow Airbyte's spec.json convention (secret
            fields masked). Connect/sync here are stub state transitions in this MVP.
          </p>
        </div>
        {isAdmin && (
          <button className="btn" onClick={openCreate}>
            New Datasource
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
            <p className="empty-state">No datasources yet.</p>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className={`rowbtn ${editingId === item.id ? "selected" : ""}`}
                onClick={() => openEdit(item)}
              >
                <span className="rowbtn-title">{item.name}</span>
                <div className="rowbtn-tags">
                  <span className="tag tag-neutral">{item.connector_type}</span>
                  <span className={`tag ${item.auth_status === "connected" ? "tag-accent" : "tag-neutral"}`}>
                    {item.auth_status}
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
            <p className="registry-panel-placeholder">
              {isAdmin ? "Select a datasource to view details, or create a new one." : "Select a datasource to view details."}
            </p>
          ) : (
            <>
              <div className="detail-header">
                <div>
                  <h6 className="detail-kicker">{form.connector_type || "Datasource"}</h6>
                  <h2>{panelMode === "create" ? "New Datasource" : form.name || "Edit Datasource"}</h2>
                </div>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  {panelMode === "edit" && editingId && isAdmin && (
                    <>
                      {form.connector_type !== "file_upload" && (
                        <button className="btn btn-secondary" disabled={actionBusy === editingId} onClick={() => handleConnect(editingId)}>
                          Connect
                        </button>
                      )}
                      <button className="btn btn-secondary" disabled={actionBusy === editingId} onClick={() => handleSync(editingId)}>
                        Sync
                      </button>
                    </>
                  )}
                  <div className="tab-switch">
                    <button type="button" className={!showYaml ? "active" : ""} onClick={() => setShowYaml(false)}>
                      Form
                    </button>
                    <button type="button" className={showYaml ? "active" : ""} onClick={() => setShowYaml(true)}>
                      YAML
                    </button>
                  </div>
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
                    <label>Connector type</label>
                    <select
                      className="input"
                      value={form.connector_type}
                      onChange={(e) => {
                        const key = e.target.value as ConnectorType;
                        const spec = connectorTypes.find((c) => c.key === key);
                        setForm({ ...form, connector_type: key, connection_config: {}, auth_type: spec?.default_auth_type ?? "none" });
                      }}
                      disabled={panelMode === "edit"}
                    >
                      {connectorTypes.map((c) => (
                        <option key={c.key} value={c.key}>
                          {CONNECTOR_LABELS[c.key] ?? c.key}
                        </option>
                      ))}
                    </select>
                  </div>

                  {fields.length > 0 && (
                    <>
                      <h3 className="section-heading">Connection</h3>
                      {fields.map((f) => (
                        <div className="field" key={f.key}>
                          <label>
                            {f.label}
                            {f.required && " *"}
                          </label>
                          {f.type === "select" ? (
                            <select
                              className="input"
                              value={form.connection_config[f.key] ?? ""}
                              onChange={(e) => setForm({ ...form, connection_config: { ...form.connection_config, [f.key]: e.target.value } })}
                            >
                              <option value="">(select)</option>
                              {(f.options ?? []).map((o) => (
                                <option key={o} value={o}>
                                  {o}
                                </option>
                              ))}
                            </select>
                          ) : f.type === "boolean" ? (
                            <select
                              className="input"
                              value={form.connection_config[f.key] ?? "false"}
                              onChange={(e) => setForm({ ...form, connection_config: { ...form.connection_config, [f.key]: e.target.value } })}
                            >
                              <option value="false">false</option>
                              <option value="true">true</option>
                            </select>
                          ) : (
                            <input
                              className="input"
                              type={f.secret ? "password" : f.type === "number" ? "number" : "text"}
                              autoComplete={f.secret ? "new-password" : "off"}
                              value={form.connection_config[f.key] ?? ""}
                              onChange={(e) => setForm({ ...form, connection_config: { ...form.connection_config, [f.key]: e.target.value } })}
                            />
                          )}
                          {f.help_text && (
                            <p className="composer-overlay-desc" style={{ marginTop: 4 }}>
                              {f.help_text}
                            </p>
                          )}
                        </div>
                      ))}
                    </>
                  )}

                  <div className="field-row">
                    <div className="field">
                      <label>Auth type</label>
                      <select className="input" value={form.auth_type} onChange={(e) => setForm({ ...form, auth_type: e.target.value as AuthType })}>
                        {Object.entries(AUTH_TYPE_LABELS).map(([k, l]) => (
                          <option key={k} value={k}>
                            {l}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="field">
                      <label>Security classification</label>
                      <select
                        className="input"
                        value={form.security_classification}
                        onChange={(e) => setForm({ ...form, security_classification: e.target.value as SecurityTier })}
                      >
                        <option value="Public">Public</option>
                        <option value="Internal">Internal</option>
                        <option value="Confidential">Confidential</option>
                        <option value="Restricted">Restricted (PII)</option>
                      </select>
                    </div>
                  </div>

                  <h3 className="section-heading">Sync</h3>
                  <div className="field-row">
                    <div className="field">
                      <label>Sync mode</label>
                      <select className="input" value={form.sync_mode} onChange={(e) => setForm({ ...form, sync_mode: e.target.value as SyncMode })}>
                        <option value="full_refresh">Full refresh</option>
                        <option value="incremental">Incremental</option>
                      </select>
                    </div>
                    <div className="field">
                      <label>Schedule (cron, optional)</label>
                      <input
                        className="input"
                        placeholder="0 */6 * * *"
                        value={form.sync_schedule_cron}
                        onChange={(e) => setForm({ ...form, sync_schedule_cron: e.target.value })}
                      />
                    </div>
                  </div>

                  <h3 className="section-heading">Extraction Policy</h3>
                  <div className="field-row">
                    <div className="field">
                      <label>Chunking strategy</label>
                      <select
                        className="input"
                        value={form.chunking_strategy}
                        onChange={(e) => setForm({ ...form, chunking_strategy: e.target.value as FormState["chunking_strategy"] })}
                      >
                        <option value="token">Token-based</option>
                        <option value="semantic">Semantic</option>
                        <option value="layout_aware">Layout-aware</option>
                      </select>
                    </div>
                    <div className="field">
                      <label>Chunk size</label>
                      <input className="input" type="number" value={form.chunk_size} onChange={(e) => setForm({ ...form, chunk_size: e.target.value })} />
                    </div>
                    <div className="field">
                      <label>Overlap</label>
                      <input className="input" type="number" value={form.overlap} onChange={(e) => setForm({ ...form, overlap: e.target.value })} />
                    </div>
                  </div>
                  <div className="field">
                    <label>Embedding model</label>
                    <input className="input" value={form.embedding_model} onChange={(e) => setForm({ ...form, embedding_model: e.target.value })} />
                  </div>

                  <div className="field" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <input type="checkbox" id="is_active" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
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
