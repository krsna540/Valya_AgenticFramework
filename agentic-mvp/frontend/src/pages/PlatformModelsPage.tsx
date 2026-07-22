import { FormEvent, useEffect, useState } from "react";
import type { ModelKind, ModelRoute, ModelStatus } from "../types";
import { modelRoutesApi } from "../api/modelRoutes";
import { ApiError } from "../api/client";

const EMPTY_CREATE = {
  name: "",
  provider: "",
  route: "",
  kind: "chat" as ModelKind,
  input_cost_per_1m: 0,
  output_cost_per_1m: null as number | null,
};

export default function PlatformModelsPage() {
  const [models, setModels] = useState<ModelRoute[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState(EMPTY_CREATE);
  const [createError, setCreateError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [selected, setSelected] = useState<ModelRoute | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setModels(await modelRoutesApi.list());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load models");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setCreateError(null);
    setSubmitting(true);
    try {
      await modelRoutesApi.create(createForm);
      setCreateForm(EMPTY_CREATE);
      setShowCreate(false);
      await load();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Create failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleGate(m: ModelRoute, field: "gateway_configured" | "cost_meter_registered" | "eval_security_redteam_passed") {
    try {
      const updated = await modelRoutesApi.update(m.id, { [field]: !m[field] });
      setModels((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
      if (selected?.id === updated.id) setSelected(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  }

  async function setStatus(m: ModelRoute, status: ModelStatus) {
    try {
      const updated = await modelRoutesApi.update(m.id, { status });
      setModels((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
      if (selected?.id === updated.id) setSelected(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  }

  async function handleDelete(m: ModelRoute) {
    if (!confirm(`Remove model route "${m.name}" (${m.route})?`)) return;
    try {
      await modelRoutesApi.remove(m.id);
      if (selected?.id === m.id) setSelected(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Model catalog</h1>
          <p>MLflow AI Gateway routes available to tenants — pricing, provider, and onboarding gates.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
          + Onboard model
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {showCreate && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 style={{ marginBottom: 12 }}>Onboard a model route</h2>
          <form onSubmit={handleCreate}>
            <div className="field-row">
              <div className="field">
                <label>Model name</label>
                <input className="input" required value={createForm.name} onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })} />
              </div>
              <div className="field">
                <label>Provider</label>
                <input className="input" required value={createForm.provider} onChange={(e) => setCreateForm({ ...createForm, provider: e.target.value })} />
              </div>
            </div>
            <div className="field-row">
              <div className="field">
                <label>Gateway route</label>
                <input className="input" required placeholder="chat/primary" value={createForm.route} onChange={(e) => setCreateForm({ ...createForm, route: e.target.value })} />
              </div>
              <div className="field">
                <label>Kind</label>
                <select className="input" value={createForm.kind} onChange={(e) => setCreateForm({ ...createForm, kind: e.target.value as ModelKind })}>
                  <option value="chat">Chat</option>
                  <option value="embed">Embed</option>
                </select>
              </div>
            </div>
            <div className="field-row">
              <div className="field">
                <label>Input $/1M tokens</label>
                <input
                  className="input"
                  type="number"
                  step="0.01"
                  value={createForm.input_cost_per_1m}
                  onChange={(e) => setCreateForm({ ...createForm, input_cost_per_1m: Number(e.target.value) })}
                />
              </div>
              <div className="field">
                <label>Output $/1M tokens (optional)</label>
                <input
                  className="input"
                  type="number"
                  step="0.01"
                  value={createForm.output_cost_per_1m ?? ""}
                  onChange={(e) => setCreateForm({ ...createForm, output_cost_per_1m: e.target.value === "" ? null : Number(e.target.value) })}
                />
              </div>
            </div>
            {createError && <p className="error-text">{createError}</p>}
            <div className="panel-actions-right">
              <button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={submitting}>
                {submitting ? "Saving..." : "Onboard"}
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="models-row">
        <div className="card" style={{ overflow: "hidden" }}>
          {loading ? (
            <p className="empty-state">Loading...</p>
          ) : models.length === 0 ? (
            <p className="empty-state">No models onboarded yet.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Provider</th>
                  <th>Route</th>
                  <th>$/1M tok</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {models.map((m) => (
                  <tr key={m.id} className="row-selectable" onClick={() => setSelected(m)}>
                    <td className="td-main">{m.name}</td>
                    <td className="td-dim">{m.provider}</td>
                    <td className="mono">{m.route}</td>
                    <td className="mono">
                      {m.input_cost_per_1m.toFixed(2)}
                      {m.output_cost_per_1m != null ? ` / ${m.output_cost_per_1m.toFixed(2)}` : ""}
                    </td>
                    <td>
                      <span className={`state ${m.status === "live" ? "ok" : m.status === "eval" ? "warn" : ""}`}>{m.status}</span>
                    </td>
                    <td className="td-menu">
                      <button className="btn btn-danger btn-sm" onClick={(e) => { e.stopPropagation(); handleDelete(m); }}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card card-pad">
          {!selected ? (
            <p className="empty-state">Select a model to view onboarding gates.</p>
          ) : (
            <>
              <div className="onb-title">{selected.name}</div>
              <div className="onb-sub">
                {selected.route} · {selected.provider}
              </div>
              <ul className="check-list">
                <li>
                  <span className={`check-circle ${selected.gates.gateway_configured ? "done" : "todo"}`}>{selected.gates.gateway_configured ? "✓" : ""}</span>
                  <button className="btn-ghost" style={{ padding: 0 }} onClick={() => toggleGate(selected, "gateway_configured")}>
                    Gateway route configured
                  </button>
                </li>
                <li>
                  <span className={`check-circle ${selected.gates.cost_meter_registered ? "done" : "todo"}`}>{selected.gates.cost_meter_registered ? "✓" : ""}</span>
                  <button className="btn-ghost" style={{ padding: 0 }} onClick={() => toggleGate(selected, "cost_meter_registered")}>
                    Cost meter registered
                  </button>
                </li>
                <li>
                  <span className={`check-circle ${selected.gates.faithfulness_passed ? "done" : "now"}`}>{selected.gates.faithfulness_passed ? "✓" : ""}</span>
                  <span>
                    Faithfulness ≥ {selected.eval_faithfulness_threshold}{" "}
                    <span className="check-metric">{selected.eval_faithfulness ?? "—"}</span>
                  </span>
                </li>
                <li>
                  <span className={`check-circle ${selected.gates.task_completion_passed ? "done" : "todo"}`}>{selected.gates.task_completion_passed ? "✓" : ""}</span>
                  <span>
                    Task completion ≥ {selected.eval_task_completion_threshold}{" "}
                    <span className="check-metric">{selected.eval_task_completion ?? "—"}</span>
                  </span>
                </li>
                <li>
                  <span className={`check-circle ${selected.gates.security_redteam_passed ? "done" : "todo"}`}>{selected.gates.security_redteam_passed ? "✓" : ""}</span>
                  <button className="btn-ghost" style={{ padding: 0 }} onClick={() => toggleGate(selected, "eval_security_redteam_passed")}>
                    Security red-team pass
                  </button>
                </li>
              </ul>
              <div className="field" style={{ marginTop: 16 }}>
                <label>Status</label>
                <select className="input" value={selected.status} onChange={(e) => setStatus(selected, e.target.value as ModelStatus)}>
                  <option value="eval">Eval</option>
                  <option value="live">Live</option>
                  <option value="disabled">Disabled</option>
                </select>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
