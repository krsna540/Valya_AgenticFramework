import { FormEvent, useEffect, useState } from "react";
import type { Tool } from "../types";
import { emptyToolAnnotations } from "../types";
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
  tool_type: "function" | "mcp";
  mcp_transport: "sse" | "stdio";
  mcp_endpoint: string;
  mcp_command: string;
  mcp_tool_name: string;
  input_schema_text: string;
  permissions: string[];
  rate_limit_per_min: string;
  timeout_s: string;
  tags: string[];
  annotations: ReturnType<typeof emptyToolAnnotations>;
}

function emptyForm(): FormState {
  return {
    name: "",
    description: "",
    is_active: true,
    version: "1.0.0",
    status: "Active",
    tool_type: "function",
    mcp_transport: "sse",
    mcp_endpoint: "",
    mcp_command: "",
    mcp_tool_name: "",
    input_schema_text: '{\n  "type": "object",\n  "properties": {}\n}',
    permissions: [],
    rate_limit_per_min: "60",
    timeout_s: "15",
    tags: [],
    annotations: emptyToolAnnotations(),
  };
}

export default function ToolsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<Tool[]>([]);
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
      setItems(await toolsApi.list());
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

  function openEdit(item: Tool) {
    setEditingId(item.id);
    setForm({
      name: item.name,
      description: item.description ?? "",
      is_active: item.is_active,
      version: item.version,
      status: item.status,
      tool_type: item.tool_type,
      mcp_transport: item.mcp_transport ?? "sse",
      mcp_endpoint: item.mcp_endpoint ?? "",
      mcp_command: item.mcp_command ?? "",
      mcp_tool_name: item.mcp_tool_name ?? "",
      input_schema_text: JSON.stringify(item.input_schema ?? { type: "object", properties: {} }, null, 2),
      permissions: item.permissions ?? [],
      rate_limit_per_min: String(item.rate_limit_per_min ?? 60),
      timeout_s: String(item.timeout_s ?? 15),
      tags: item.tags ?? [],
      annotations: item.annotations ?? emptyToolAnnotations(),
    });
    setFormError(null);
    setPanelMode("edit");
    setShowYaml(false);
  }

  function closePanel() {
    setPanelMode("closed");
    setEditingId(null);
  }

  function parsedSchema(): Record<string, unknown> | null {
    try {
      return form.input_schema_text.trim() ? JSON.parse(form.input_schema_text) : null;
    } catch {
      return null;
    }
  }

  function yamlPreview(): string {
    return toYamlText({
      id: editingId ?? "(generated on save)",
      name: form.name,
      description: form.description || null,
      tool_type: form.tool_type,
      ...(form.tool_type === "mcp"
        ? {
            mcp_transport: form.mcp_transport,
            mcp_endpoint: form.mcp_transport === "sse" ? form.mcp_endpoint : null,
            mcp_command: form.mcp_transport === "stdio" ? form.mcp_command : null,
            mcp_tool_name: form.mcp_tool_name,
          }
        : { input_schema: parsedSchema() }),
      permissions: form.permissions,
      rate_limit_per_min: Number(form.rate_limit_per_min) || 60,
      timeout_s: Number(form.timeout_s) || 15,
      tags: form.tags,
      annotations: form.annotations,
      version: form.version,
      status: form.status,
      is_active: form.is_active,
    });
  }

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    setFormError(null);

    let input_schema: Record<string, unknown> | null = null;
    if (form.tool_type === "function") {
      input_schema = parsedSchema();
      if (form.input_schema_text.trim() && input_schema === null) {
        setFormError("Input schema must be valid JSON");
        return;
      }
    }

    setSubmitting(true);
    try {
      const payload = {
        name: form.name,
        description: form.description || null,
        is_active: form.is_active,
        version: form.version,
        status: form.status,
        tool_type: form.tool_type,
        mcp_transport: form.tool_type === "mcp" ? form.mcp_transport : null,
        mcp_endpoint: form.tool_type === "mcp" && form.mcp_transport === "sse" ? form.mcp_endpoint || null : null,
        mcp_command: form.tool_type === "mcp" && form.mcp_transport === "stdio" ? form.mcp_command || null : null,
        mcp_tool_name: form.tool_type === "mcp" ? form.mcp_tool_name || null : null,
        input_schema: form.tool_type === "function" ? input_schema : null,
        permissions: form.permissions,
        rate_limit_per_min: Number(form.rate_limit_per_min) || 60,
        timeout_s: Number(form.timeout_s) || 15,
        tags: form.tags,
        annotations: form.annotations,
      };
      if (editingId) {
        await toolsApi.update(editingId, payload);
      } else {
        await toolsApi.create(payload);
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
    if (!confirm("Delete this tool?")) return;
    try {
      await toolsApi.remove(id);
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
          <h1>Tools</h1>
          <p>
            External functions/APIs agents can call — a plain function contract (JSON-schema args) or a reference
            to an MCP server's tool. Annotation hints follow the Model Context Protocol spec.
          </p>
        </div>
        {isAdmin && (
          <button className="btn" onClick={openCreate}>
            New Tool
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
            <p className="empty-state">No tools yet.</p>
          ) : (
            items.map((item) => (
              <div
                key={item.id}
                className={`rowbtn ${editingId === item.id ? "selected" : ""}`}
                onClick={() => openEdit(item)}
              >
                <span className="rowbtn-title">{item.name}</span>
                <div className="rowbtn-tags">
                  <span className="tag tag-neutral">{item.tool_type}</span>
                  <span className={`tag ${item.is_active ? "tag-accent" : "tag-neutral"}`}>
                    {item.is_active ? "active" : "inactive"}
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
            <p className="registry-panel-placeholder">Select a tool to view details, or create a new one.</p>
          ) : (
            <>
              <div className="detail-header">
                <div>
                  <h6 className="detail-kicker">{form.tool_type === "mcp" ? "MCP Tool" : "Function Tool"}</h6>
                  <h2>{panelMode === "create" ? "New Tool" : form.name || "Edit Tool"}</h2>
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

                  <div className="field">
                    <label>Tool type</label>
                    <div className="chip-picker">
                      <button
                        type="button"
                        className={`chip ${form.tool_type === "function" ? "selected" : ""}`}
                        onClick={() => setForm({ ...form, tool_type: "function" })}
                      >
                        Function (JSON-schema args)
                      </button>
                      <button
                        type="button"
                        className={`chip ${form.tool_type === "mcp" ? "selected" : ""}`}
                        onClick={() => setForm({ ...form, tool_type: "mcp" })}
                      >
                        MCP server tool
                      </button>
                    </div>
                  </div>

                  {form.tool_type === "mcp" ? (
                    <>
                      <div className="field">
                        <label>MCP transport</label>
                        <div className="chip-picker">
                          <button
                            type="button"
                            className={`chip ${form.mcp_transport === "sse" ? "selected" : ""}`}
                            onClick={() => setForm({ ...form, mcp_transport: "sse" })}
                          >
                            SSE (remote server URL)
                          </button>
                          <button
                            type="button"
                            className={`chip ${form.mcp_transport === "stdio" ? "selected" : ""}`}
                            onClick={() => setForm({ ...form, mcp_transport: "stdio" })}
                          >
                            stdio (local launch command)
                          </button>
                        </div>
                      </div>
                      {form.mcp_transport === "sse" ? (
                        <div className="field">
                          <label>SSE endpoint</label>
                          <input
                            className="input"
                            placeholder="https://mcp.example.com/sse"
                            value={form.mcp_endpoint}
                            onChange={(e) => setForm({ ...form, mcp_endpoint: e.target.value })}
                          />
                        </div>
                      ) : (
                        <div className="field">
                          <label>Launch command</label>
                          <input
                            className="input"
                            placeholder="npx -y @modelcontextprotocol/server-github"
                            value={form.mcp_command}
                            onChange={(e) => setForm({ ...form, mcp_command: e.target.value })}
                          />
                        </div>
                      )}
                      <div className="field">
                        <label>MCP tool name</label>
                        <input
                          className="input"
                          placeholder="the specific tool this row represents on that server"
                          value={form.mcp_tool_name}
                          onChange={(e) => setForm({ ...form, mcp_tool_name: e.target.value })}
                        />
                      </div>
                    </>
                  ) : (
                    <div className="field">
                      <label>Input schema (JSON Schema Draft-07)</label>
                      <textarea
                        className="input"
                        rows={6}
                        style={{ fontFamily: "monospace" }}
                        value={form.input_schema_text}
                        onChange={(e) => setForm({ ...form, input_schema_text: e.target.value })}
                      />
                    </div>
                  )}

                  <h3 className="section-heading">Manifest metadata</h3>
                  <TagInput
                    label="Tags"
                    values={form.tags}
                    onChange={(tags) => setForm({ ...form, tags })}
                    placeholder="retrieval, rag, ..."
                  />
                  <TagInput
                    label="Permissions"
                    values={form.permissions}
                    onChange={(permissions) => setForm({ ...form, permissions })}
                    placeholder="memory:read, ..."
                    helpText="Advisory today — not yet enforced by execution."
                  />
                  <div className="field-row">
                    <div className="field">
                      <label>Rate limit (calls/min)</label>
                      <input
                        className="input"
                        type="number"
                        min={1}
                        value={form.rate_limit_per_min}
                        onChange={(e) => setForm({ ...form, rate_limit_per_min: e.target.value })}
                      />
                    </div>
                    <div className="field">
                      <label>Timeout (seconds)</label>
                      <input
                        className="input"
                        type="number"
                        min={1}
                        value={form.timeout_s}
                        onChange={(e) => setForm({ ...form, timeout_s: e.target.value })}
                      />
                    </div>
                  </div>

                  <h3 className="section-heading">MCP annotations (display/behavior hints)</h3>
                  <div className="field">
                    <label>Display title</label>
                    <input
                      className="input"
                      value={form.annotations.title ?? ""}
                      onChange={(e) => setForm({ ...form, annotations: { ...form.annotations, title: e.target.value || null } })}
                    />
                  </div>
                  <div className="field-row">
                    {(
                      [
                        ["readOnlyHint", "Read-only", "Doesn't modify state"],
                        ["destructiveHint", "Destructive", "May make irreversible changes"],
                        ["idempotentHint", "Idempotent", "Same args -> same effect"],
                        ["openWorldHint", "Open-world", "Interacts with external systems"],
                      ] as const
                    ).map(([key, label, hint]) => (
                      <div key={key} className="field" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <input
                          type="checkbox"
                          id={key}
                          checked={form.annotations[key]}
                          onChange={(e) => setForm({ ...form, annotations: { ...form.annotations, [key]: e.target.checked } })}
                        />
                        <label htmlFor={key} style={{ margin: 0 }} title={hint}>
                          {label}
                        </label>
                      </div>
                    ))}
                  </div>

                  <div className="field" style={{ display: "flex", alignItems: "center", gap: 8 }}>
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
