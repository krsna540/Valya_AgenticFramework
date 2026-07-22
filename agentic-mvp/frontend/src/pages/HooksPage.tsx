import { FormEvent, useEffect, useState } from "react";
import type { HandlerType, Hook, HookHandlerInfo, LifecycleEvent, LifecycleEventInfo } from "../types";
import { hooksApi } from "../api/registry";
import { ApiError } from "../api/client";
import { toYamlText } from "../utils/yaml";
import { useAuth } from "../context/AuthContext";

interface FormState {
  name: string;
  description: string;
  scope: "global" | "agent";
  lifecycle_event: LifecycleEvent | "";
  handler_type: HandlerType;
  handler_key: string;
  // handler_type="http"
  http_endpoint: string;
  http_method: string;
  http_headers_text: string; // JSON object text
  // handler_type="command"
  command_runtime: string;
  command_script_path: string;
  command_args_text: string; // comma-separated
  // handler_type="mcp_tool"
  mcp_server_url: string;
  mcp_tool_name: string;
  mcp_parameters_text: string; // JSON object text
  // execution_policy (custom handler types only)
  timeout_ms: string;
  fallback_strategy: "Block" | "Allow";
  allowed_tools_text: string; // comma-separated
  blocked_keywords_text: string; // comma-separated
  // python handler config
  configText: string;
  version: string;
  status: "Active" | "Experimental" | "Deprecated";
  tags_text: string; // comma-separated
  author: string;
  is_active: boolean;
}

function emptyForm(lifecycleEvents: LifecycleEventInfo[], handlers: HookHandlerInfo[]): FormState {
  const firstHandler = handlers[0];
  return {
    name: "",
    description: "",
    scope: "agent",
    lifecycle_event: firstHandler ? (firstHandler.stage as LifecycleEvent) : lifecycleEvents[0]?.key ?? "",
    handler_type: "python",
    handler_key: firstHandler?.key ?? "",
    http_endpoint: "",
    http_method: "POST",
    http_headers_text: "{}",
    command_runtime: "python3",
    command_script_path: "",
    command_args_text: "",
    mcp_server_url: "",
    mcp_tool_name: "",
    mcp_parameters_text: "{}",
    timeout_ms: "3500",
    fallback_strategy: "Block",
    allowed_tools_text: "",
    blocked_keywords_text: "",
    configText: "{}",
    version: "1.0.0",
    status: "Active",
    tags_text: "",
    author: "",
    is_active: true,
  };
}

function csvToList(text: string): string[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function buildHandlerConfig(form: FormState): Record<string, unknown> {
  if (form.handler_type === "http") {
    let headers: Record<string, unknown> = {};
    try {
      headers = form.http_headers_text.trim() ? JSON.parse(form.http_headers_text) : {};
    } catch {
      // surfaced as a form error by caller before this is used
    }
    return { endpoint: form.http_endpoint, method: form.http_method || "POST", headers };
  }
  if (form.handler_type === "command") {
    return {
      runtime: form.command_runtime || "python3",
      script_path: form.command_script_path,
      args: csvToList(form.command_args_text),
    };
  }
  if (form.handler_type === "mcp_tool") {
    let parameters: Record<string, unknown> = {};
    try {
      parameters = form.mcp_parameters_text.trim() ? JSON.parse(form.mcp_parameters_text) : {};
    } catch {
      // surfaced as a form error by caller before this is used
    }
    return { mcp_server_url: form.mcp_server_url, tool_name: form.mcp_tool_name, parameters };
  }
  return {};
}

function buildExecutionPolicy(form: FormState): Record<string, unknown> {
  const policy: Record<string, unknown> = {
    timeout_ms: Number(form.timeout_ms) || 3500,
    fallback_strategy: form.fallback_strategy,
  };
  const allowed = csvToList(form.allowed_tools_text);
  const blocked = csvToList(form.blocked_keywords_text);
  if (allowed.length) policy.allowed_tools = allowed;
  if (blocked.length) policy.blocked_keywords = blocked;
  return policy;
}

export default function HooksPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [items, setItems] = useState<Hook[]>([]);
  const [handlers, setHandlers] = useState<HookHandlerInfo[]>([]);
  const [lifecycleEvents, setLifecycleEvents] = useState<LifecycleEventInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [panelMode, setPanelMode] = useState<"closed" | "create" | "edit">("closed");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm([], []));
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showYaml, setShowYaml] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [hookList, handlerList, lifecycleList] = await Promise.all([
        hooksApi.list(),
        hooksApi.listHandlers(),
        hooksApi.listLifecycleEvents(),
      ]);
      setItems(hookList);
      setHandlers(handlerList);
      setLifecycleEvents(lifecycleList);
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
    setForm(emptyForm(lifecycleEvents, handlers));
    setFormError(null);
    setPanelMode("create");
    setShowYaml(false);
  }

  function openEdit(item: Hook) {
    setEditingId(item.id);
    const cfg = item.handler_config || {};
    setForm({
      name: item.name,
      description: item.description ?? "",
      scope: item.scope,
      lifecycle_event: item.lifecycle_event,
      handler_type: item.handler_type,
      handler_key: item.handler_key ?? "",
      http_endpoint: (cfg.endpoint as string) ?? "",
      http_method: (cfg.method as string) ?? "POST",
      http_headers_text: JSON.stringify(cfg.headers ?? {}, null, 2),
      command_runtime: (cfg.runtime as string) ?? "python3",
      command_script_path: (cfg.script_path as string) ?? "",
      command_args_text: Array.isArray(cfg.args) ? (cfg.args as string[]).join(", ") : "",
      mcp_server_url: (cfg.mcp_server_url as string) ?? "",
      mcp_tool_name: (cfg.tool_name as string) ?? "",
      mcp_parameters_text: JSON.stringify(cfg.parameters ?? {}, null, 2),
      timeout_ms: String((item.execution_policy?.timeout_ms as number) ?? 3500),
      fallback_strategy: ((item.execution_policy?.fallback_strategy as string) ?? "Block") as "Block" | "Allow",
      allowed_tools_text: Array.isArray(item.execution_policy?.allowed_tools)
        ? (item.execution_policy!.allowed_tools as string[]).join(", ")
        : "",
      blocked_keywords_text: Array.isArray(item.execution_policy?.blocked_keywords)
        ? (item.execution_policy!.blocked_keywords as string[]).join(", ")
        : "",
      configText: JSON.stringify(item.config ?? {}, null, 2),
      version: item.version,
      status: item.status,
      tags_text: (item.tags || []).join(", "),
      author: item.author ?? "",
      is_active: item.is_active,
    });
    setFormError(null);
    setPanelMode("edit");
    setShowYaml(false);
  }

  function closePanel() {
    setPanelMode("closed");
    setEditingId(null);
  }

  function selectHandlerKey(key: string) {
    const handler = handlers.find((h) => h.key === key);
    setForm({ ...form, handler_key: key, lifecycle_event: handler ? (handler.stage as LifecycleEvent) : form.lifecycle_event });
  }

  function yamlPreview(): string {
    return toYamlText({
      id: editingId ?? "(generated on save)",
      name: form.name,
      lifecycle_event: form.lifecycle_event,
      version: form.version,
      status: form.status,
      metadata: { author: form.author || null, description: form.description || null, tags: csvToList(form.tags_text) },
      handler:
        form.handler_type === "python"
          ? { type: "python", handler_key: form.handler_key, config: safeParse(form.configText) }
          : { type: form.handler_type, ...buildHandlerConfig(form) },
      execution_policy: form.handler_type === "python" ? undefined : buildExecutionPolicy(form),
      scope: form.scope,
      is_active: form.is_active,
    });
  }

  function safeParse(text: string): unknown {
    try {
      return text.trim() ? JSON.parse(text) : {};
    } catch {
      return {};
    }
  }

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    setFormError(null);

    if (!form.lifecycle_event) {
      setFormError("Pick a lifecycle event");
      return;
    }

    let config: Record<string, unknown> = {};
    if (form.handler_type === "python") {
      if (!form.handler_key) {
        setFormError("Pick a handler");
        return;
      }
      try {
        config = form.configText.trim() ? JSON.parse(form.configText) : {};
      } catch {
        setFormError("Config must be valid JSON");
        return;
      }
    } else {
      try {
        if (form.handler_type === "http" && form.http_headers_text.trim()) JSON.parse(form.http_headers_text);
        if (form.handler_type === "mcp_tool" && form.mcp_parameters_text.trim()) JSON.parse(form.mcp_parameters_text);
      } catch {
        setFormError("Handler headers/parameters must be valid JSON");
        return;
      }
      if (form.handler_type === "http" && !form.http_endpoint.trim()) {
        setFormError("HTTP handler requires an endpoint");
        return;
      }
      if (form.handler_type === "command" && !form.command_script_path.trim()) {
        setFormError("Command handler requires a script_path");
        return;
      }
      if (form.handler_type === "mcp_tool" && (!form.mcp_server_url.trim() || !form.mcp_tool_name.trim())) {
        setFormError("MCP tool handler requires an mcp_server_url and tool_name");
        return;
      }
    }

    setSubmitting(true);
    try {
      const payload = {
        name: form.name,
        description: form.description || null,
        scope: form.scope,
        lifecycle_event: form.lifecycle_event as LifecycleEvent,
        handler_type: form.handler_type,
        handler_key: form.handler_type === "python" ? form.handler_key : null,
        handler_config: form.handler_type === "python" ? {} : buildHandlerConfig(form),
        execution_policy: form.handler_type === "python" ? {} : buildExecutionPolicy(form),
        config,
        version: form.version,
        status: form.status,
        tags: csvToList(form.tags_text),
        author: form.author || null,
        is_active: form.is_active,
      };
      if (editingId) {
        await hooksApi.update(editingId, payload);
      } else {
        await hooksApi.create(payload);
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
    if (!confirm("Delete this hook?")) return;
    try {
      await hooksApi.remove(id);
      if (editingId === id) closePanel();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  const wiredByKey = (key: string) => lifecycleEvents.find((l) => l.key === key)?.wired ?? true;
  const handlersForPythonType = handlers; // all — lifecycle_event is derived from the chosen handler

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Hooks</h1>
          <p>
            The full 10-stage lifecycle registry — SessionStart, UserPromptSubmit, PreToolUse,
            PostToolUse.Success/.Failure, PreCompact, SubagentStart/Stop, Stop, Notification. Bind to a vetted
            built-in handler (safe) or a real HTTP/Command/MCP_Tool handler (executes code — see README).
          </p>
        </div>
        {isAdmin && (
          <button className="btn" onClick={openCreate}>
            New Hook
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
                <div className="rowbtn-tags">
                  <span className="tag tag-neutral">{item.scope}</span>
                  <span className="tag tag-outline">{item.lifecycle_event}</span>
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
            <p className="registry-panel-placeholder">Select a hook to view details, or create a new one.</p>
          ) : (
            <>
              <div className="detail-header">
                <div>
                  <h6 className="detail-kicker">Hook</h6>
                  <h2>{panelMode === "create" ? "New Hook" : form.name || "Edit Hook"}</h2>
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

                  <div className="field-row">
                    <div className="field">
                      <label>Scope</label>
                      <select
                        className="input"
                        value={form.scope}
                        onChange={(e) => setForm({ ...form, scope: e.target.value as "global" | "agent" })}
                      >
                        <option value="agent">Agent — only where attached</option>
                        <option value="global">Global — runs for every agent</option>
                      </select>
                    </div>
                    <div className="field">
                      <label>Status</label>
                      <select
                        className="input"
                        value={form.status}
                        onChange={(e) => setForm({ ...form, status: e.target.value as FormState["status"] })}
                      >
                        <option value="Active">Active</option>
                        <option value="Experimental">Experimental</option>
                        <option value="Deprecated">Deprecated</option>
                      </select>
                    </div>
                  </div>

                  <div className="field">
                    <label>Handler type</label>
                    <select
                      className="input"
                      value={form.handler_type}
                      onChange={(e) => setForm({ ...form, handler_type: e.target.value as HandlerType })}
                    >
                      <option value="python">python — vetted built-in (safe, no code stored)</option>
                      <option value="http">http — outbound webhook (executes remotely)</option>
                      <option value="command">command — local script (executes on this host)</option>
                      <option value="mcp_tool">mcp_tool — MCP server call</option>
                    </select>
                    {form.handler_type !== "python" && (
                      <p className="composer-overlay-desc" style={{ marginTop: 6, color: "var(--danger)" }}>
                        This handler type runs real code/network calls configured below. See README's "Hook handler
                        types" section.
                      </p>
                    )}
                  </div>

                  {form.handler_type === "python" ? (
                    <>
                      <div className="field">
                        <label>Handler</label>
                        <select className="input" value={form.handler_key} onChange={(e) => selectHandlerKey(e.target.value)}>
                          <option value="">— pick a handler —</option>
                          {handlersForPythonType.map((h) => (
                            <option key={h.key} value={h.key}>
                              {h.key} ({h.stage})
                            </option>
                          ))}
                        </select>
                        {form.handler_key && (
                          <p className="composer-overlay-desc" style={{ marginTop: 6 }}>
                            {handlers.find((h) => h.key === form.handler_key)?.description}
                          </p>
                        )}
                      </div>
                      <div className="field">
                        <label>Lifecycle event (derived from handler)</label>
                        <input className="input" disabled value={form.lifecycle_event} />
                      </div>
                      <div className="field">
                        <label>Config (JSON, passed to the handler)</label>
                        <textarea
                          className="input"
                          rows={4}
                          style={{ fontFamily: "monospace" }}
                          value={form.configText}
                          onChange={(e) => setForm({ ...form, configText: e.target.value })}
                        />
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="field">
                        <label>Lifecycle event</label>
                        <select
                          className="input"
                          value={form.lifecycle_event}
                          onChange={(e) => setForm({ ...form, lifecycle_event: e.target.value as LifecycleEvent })}
                        >
                          {lifecycleEvents.map((l) => (
                            <option key={l.key} value={l.key}>
                              {l.key} {l.wired ? "" : "(not yet wired — schema only)"}
                            </option>
                          ))}
                        </select>
                      </div>

                      {form.handler_type === "http" && (
                        <>
                          <div className="field-row">
                            <div className="field">
                              <label>Endpoint</label>
                              <input
                                className="input"
                                placeholder="https://internal.net/hook"
                                value={form.http_endpoint}
                                onChange={(e) => setForm({ ...form, http_endpoint: e.target.value })}
                              />
                            </div>
                            <div className="field" style={{ maxWidth: 120 }}>
                              <label>Method</label>
                              <select
                                className="input"
                                value={form.http_method}
                                onChange={(e) => setForm({ ...form, http_method: e.target.value })}
                              >
                                <option value="POST">POST</option>
                                <option value="PUT">PUT</option>
                              </select>
                            </div>
                          </div>
                          <div className="field">
                            <label>Headers (JSON)</label>
                            <textarea
                              className="input"
                              rows={3}
                              style={{ fontFamily: "monospace" }}
                              value={form.http_headers_text}
                              onChange={(e) => setForm({ ...form, http_headers_text: e.target.value })}
                            />
                          </div>
                        </>
                      )}

                      {form.handler_type === "command" && (
                        <>
                          <div className="field-row">
                            <div className="field" style={{ maxWidth: 140 }}>
                              <label>Runtime</label>
                              <input
                                className="input"
                                value={form.command_runtime}
                                onChange={(e) => setForm({ ...form, command_runtime: e.target.value })}
                              />
                            </div>
                            <div className="field">
                              <label>Script path</label>
                              <input
                                className="input"
                                placeholder="/opt/agent/hooks/scripts/run.py"
                                value={form.command_script_path}
                                onChange={(e) => setForm({ ...form, command_script_path: e.target.value })}
                              />
                            </div>
                          </div>
                          <div className="field">
                            <label>Args (comma-separated)</label>
                            <input
                              className="input"
                              value={form.command_args_text}
                              onChange={(e) => setForm({ ...form, command_args_text: e.target.value })}
                            />
                          </div>
                        </>
                      )}

                      {form.handler_type === "mcp_tool" && (
                        <>
                          <div className="field">
                            <label>MCP server URL</label>
                            <input
                              className="input"
                              placeholder="https://mcp.internal/tools"
                              value={form.mcp_server_url}
                              onChange={(e) => setForm({ ...form, mcp_server_url: e.target.value })}
                            />
                          </div>
                          <div className="field">
                            <label>Tool name</label>
                            <input
                              className="input"
                              value={form.mcp_tool_name}
                              onChange={(e) => setForm({ ...form, mcp_tool_name: e.target.value })}
                            />
                          </div>
                          <div className="field">
                            <label>Parameters (JSON)</label>
                            <textarea
                              className="input"
                              rows={3}
                              style={{ fontFamily: "monospace" }}
                              value={form.mcp_parameters_text}
                              onChange={(e) => setForm({ ...form, mcp_parameters_text: e.target.value })}
                            />
                          </div>
                        </>
                      )}

                      <div className="field-row">
                        <div className="field">
                          <label>Timeout (ms)</label>
                          <input
                            className="input"
                            type="number"
                            value={form.timeout_ms}
                            onChange={(e) => setForm({ ...form, timeout_ms: e.target.value })}
                          />
                        </div>
                        <div className="field">
                          <label>Fallback strategy</label>
                          <select
                            className="input"
                            value={form.fallback_strategy}
                            onChange={(e) => setForm({ ...form, fallback_strategy: e.target.value as "Block" | "Allow" })}
                          >
                            <option value="Block">Block (fail closed)</option>
                            <option value="Allow">Allow (fail open)</option>
                          </select>
                        </div>
                      </div>
                      <div className="field">
                        <label>Allowed tools (comma-separated, optional — empty = allow all)</label>
                        <input
                          className="input"
                          placeholder="git, npm run build, pytest"
                          value={form.allowed_tools_text}
                          onChange={(e) => setForm({ ...form, allowed_tools_text: e.target.value })}
                        />
                      </div>
                      <div className="field">
                        <label>Blocked keywords (comma-separated, optional)</label>
                        <input
                          className="input"
                          placeholder="rm -rf, chmod 777"
                          value={form.blocked_keywords_text}
                          onChange={(e) => setForm({ ...form, blocked_keywords_text: e.target.value })}
                        />
                      </div>
                    </>
                  )}

                  <div className="field">
                    <label>Description</label>
                    <textarea
                      className="input"
                      rows={2}
                      value={form.description}
                      onChange={(e) => setForm({ ...form, description: e.target.value })}
                    />
                  </div>

                  <div className="field-row">
                    <div className="field">
                      <label>Version</label>
                      <input
                        className="input"
                        value={form.version}
                        onChange={(e) => setForm({ ...form, version: e.target.value })}
                      />
                    </div>
                    <div className="field">
                      <label>Author</label>
                      <input
                        className="input"
                        value={form.author}
                        onChange={(e) => setForm({ ...form, author: e.target.value })}
                      />
                    </div>
                  </div>
                  <div className="field">
                    <label>Tags (comma-separated)</label>
                    <input
                      className="input"
                      value={form.tags_text}
                      onChange={(e) => setForm({ ...form, tags_text: e.target.value })}
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
