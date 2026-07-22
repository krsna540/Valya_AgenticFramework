import { FormEvent, useEffect, useState } from "react";
import type { Policy, PolicyMode, TenantSettings } from "../types";
import { policiesApi } from "../api/policies";
import { tenantApi } from "../api/admin";
import { ApiError } from "../api/client";
import PersonasPage from "./PersonasPage";
import UserAssignmentsPanel from "./UserAssignmentsPanel";

const EMPTY_POLICY = { name: "", rule_expression: "", mode: "dry_run" as PolicyMode };

type SubTab = "policies" | "personas" | "users";

const SUB_TABS: { key: SubTab; label: string }[] = [
  { key: "policies", label: "Policies & guardrails" },
  { key: "personas", label: "Personas" },
  { key: "users", label: "Users & assignments" },
];

// The Admin Norms tab: named access policies (tenant-scoped, see
// app/models/policy.py), rate limits + guardrail toggles (Tenant.settings
// JSONB, see app/models/tenant.py), the Personas registry, and a
// "Users & assignments" sub-tab combining full user CRUD (AdminUsersPage)
// with a persona/policy assignment matrix (UserAssignmentsPanel) — split
// into sub-tabs via the same pattern as AdminExpertisePage.
export default function AdminNormsPage() {
  const [tab, setTab] = useState<SubTab>("policies");
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [settings, setSettings] = useState<TenantSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState(EMPTY_POLICY);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [p, t] = await Promise.all([policiesApi.list(), tenantApi.me()]);
      setPolicies(p);
      setSettings(t.settings);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load norms");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      await policiesApi.create(form);
      setForm(EMPTY_POLICY);
      setShowCreate(false);
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Create failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleMode(p: Policy) {
    try {
      await policiesApi.update(p.id, { mode: p.mode === "enforced" ? "dry_run" : "enforced" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed");
    }
  }

  async function removePolicy(p: Policy) {
    if (!confirm(`Delete policy "${p.name}"?`)) return;
    try {
      await policiesApi.remove(p.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Delete failed");
    }
  }

  async function saveSettings(next: TenantSettings) {
    setSettings(next);
    try {
      await tenantApi.update({ settings: next });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Settings update failed");
    }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Security, policies &amp; guardrails</h1>
          <p>Control who can do what: access policies, rate limits, personas, users, and output guardrails for this tenant.</p>
        </div>
        {tab === "policies" && (
          <button className="btn btn-nrm" onClick={() => setShowCreate(true)}>
            + New policy
          </button>
        )}
      </div>

      <div className="tab-switch" style={{ marginBottom: 20, display: "inline-flex" }}>
        {SUB_TABS.map((t) => (
          <button key={t.key} type="button" className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "personas" && <PersonasPage />}
      {tab === "users" && <UserAssignmentsPanel />}

      {tab === "policies" && (
        <>
      {error && <p className="error-text">{error}</p>}

      {showCreate && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h2 style={{ marginBottom: 12 }}>New policy</h2>
          <form onSubmit={handleCreate}>
            <div className="field">
              <label>Name</label>
              <input className="input" required placeholder="deny-export-legal-docs" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            </div>
            <div className="field">
              <label>Rule</label>
              <input
                className="input"
                required
                placeholder='resource.class == "legal" -> deny(export)'
                value={form.rule_expression}
                onChange={(e) => setForm({ ...form, rule_expression: e.target.value })}
              />
            </div>
            <div className="field">
              <label>Mode</label>
              <select className="input" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value as PolicyMode })}>
                <option value="dry_run">Dry-run</option>
                <option value="enforced">Enforced</option>
              </select>
            </div>
            {formError && <p className="error-text">{formError}</p>}
            <div className="panel-actions-right">
              <button type="button" className="btn btn-secondary" onClick={() => setShowCreate(false)}>
                Cancel
              </button>
              <button type="submit" className="btn btn-nrm" disabled={submitting}>
                {submitting ? "Saving..." : "Create"}
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="nrm-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
        <div className="card" style={{ overflow: "hidden" }}>
          <div className="card-head">
            <span className="card-title">
              Access policies <span className="light">(tenant-scoped)</span>
            </span>
          </div>
          {loading ? (
            <p className="empty-state">Loading...</p>
          ) : policies.length === 0 ? (
            <p className="empty-state">No policies yet.</p>
          ) : (
            <ul style={{ listStyle: "none", padding: 0 }}>
              {policies.map((p) => (
                <li key={p.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 20px", borderBottom: "1px solid var(--line)" }}>
                  <div>
                    <div style={{ fontWeight: 500 }}>{p.name}</div>
                    <div className="mono text-muted">{p.rule_expression}</div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <button className={`state ${p.mode === "enforced" ? "ok" : "warn"}`} style={{ background: "none", border: "none", cursor: "pointer" }} onClick={() => toggleMode(p)}>
                      {p.mode === "enforced" ? "enforced" : "dry-run"}
                    </button>
                    <button className="btn btn-danger btn-sm" onClick={() => removePolicy(p)}>
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="card card-pad">
            <div className="section-heading" style={{ marginTop: 0, paddingTop: 0, borderTop: "none" }}>Rate limits</div>
            {settings && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, textAlign: "center" }}>
                {(
                  [
                    ["per_user_rpm", "req/min · user"],
                    ["per_tenant_rpm", "req/min · tenant"],
                    ["tokens_per_day", "tok/day · user"],
                  ] as const
                ).map(([key, label]) => (
                  <div key={key} style={{ background: "var(--paper)", borderRadius: "var(--r-md)", padding: "12px 0" }}>
                    <input
                      className="input"
                      style={{ textAlign: "center", fontFamily: "var(--font-disp)", fontWeight: 700, fontSize: 16, background: "transparent", border: "none" }}
                      type="number"
                      value={settings.rate_limits[key]}
                      onChange={(e) => saveSettings({ ...settings, rate_limits: { ...settings.rate_limits, [key]: Number(e.target.value) } })}
                    />
                    <div style={{ fontSize: 11, color: "var(--muted)" }}>{label}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="card card-pad">
            <div className="section-heading" style={{ marginTop: 0, paddingTop: 0, borderTop: "none" }}>Guardrails</div>
            {settings && (
              <ul style={{ listStyle: "none", padding: 0 }}>
                {(
                  [
                    ["pii_redaction", "PII redaction (in + out)"],
                    ["prompt_injection_screening", "Prompt-injection screening"],
                    ["groundedness_check", "Groundedness check (critic gate)"],
                    ["topic_blocklist", "Topic blocklist"],
                  ] as const
                ).map(([key, label]) => (
                  <li key={key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 13, marginBottom: 12 }}>
                    <span>{label}</span>
                    <button
                      className={`toggle ${settings.guardrails[key] ? "on" : "off"}`}
                      onClick={() => saveSettings({ ...settings, guardrails: { ...settings.guardrails, [key]: !settings.guardrails[key] } })}
                    />
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
        </>
      )}
    </div>
  );
}
