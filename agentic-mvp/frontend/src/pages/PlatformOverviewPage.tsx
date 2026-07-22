import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../api/client";
import { platformApi } from "../api/platform";
import { modelRoutesApi } from "../api/modelRoutes";
import type { CostByTenant, ModelRoute, PlatformOverview, TenantSummary, UsageDailyPoint } from "../types";

function fmtUsd(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: n < 10 ? 3 : 0 })}`;
}

export default function PlatformOverviewPage() {
  const [overview, setOverview] = useState<PlatformOverview | null>(null);
  const [daily, setDaily] = useState<UsageDailyPoint[]>([]);
  const [cost, setCost] = useState<CostByTenant | null>(null);
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  const [models, setModels] = useState<ModelRoute[]>([]);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [ov, d, c, t, m] = await Promise.all([
          platformApi.overview(),
          platformApi.usageDaily(14),
          platformApi.costByTenant(),
          platformApi.listTenants(),
          modelRoutesApi.list(),
        ]);
        setOverview(ov);
        setDaily(d);
        setCost(c);
        setTenants(t);
        setModels(m);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to load overview");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const maxDailyTotal = Math.max(1, ...daily.map((d) => d.chat_turns + d.tool_and_skill_calls));
  const filteredTenants = tenants.filter((t) => t.name.toLowerCase().includes(filter.toLowerCase()) || t.slug.includes(filter.toLowerCase()));
  const onboardingModel = models.find((m) => !m.gates.all_passed) ?? models.find((m) => m.status === "eval");

  if (loading) return <p className="empty-state">Loading platform overview…</p>;

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Platform overview</h1>
          <p>All tenants · last 30 days</p>
        </div>
        <div className="head-actions">
          <Link className="btn btn-ghost" to="/app/platform/admins">+ Create admin</Link>
          <Link className="btn btn-primary" to="/app/platform/tenants">+ Create tenant</Link>
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}

      {overview && (
        <div className="kpi-grid">
          <div className="kpi">
            <div className="kpi-label">Active tenants</div>
            <div className="kpi-value">{overview.active_tenants}</div>
            <div className="kpi-note ok">+{overview.new_tenants_this_month} this month</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Monthly active users</div>
            <div className="kpi-value">{overview.monthly_active_users.toLocaleString()}</div>
            <div className="kpi-note">last 30 days</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">LLM spend (MTD)</div>
            <div className="kpi-value">{fmtUsd(overview.llm_spend_mtd_usd)}</div>
            <div className="kpi-note">budget {fmtUsd(overview.llm_budget_usd)}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Gateway p95 latency</div>
            <div className="kpi-value">{overview.gateway_p95_latency_ms != null ? `${(overview.gateway_p95_latency_ms / 1000).toFixed(1)}s` : "—"}</div>
            <div className={`kpi-note ${overview.gateway_p95_latency_ms != null && overview.gateway_p95_latency_ms > overview.gateway_slo_ms ? "warn" : ""}`}>
              SLO {(overview.gateway_slo_ms / 1000).toFixed(1)}s
            </div>
          </div>
        </div>
      )}

      <div className="charts-row">
        <div className="card card-pad">
          <div className="card-head" style={{ margin: 0, padding: 0, border: "none" }}>
            <span className="card-title">Requests per day</span>
            <div className="chart-legend">
              <span className="legend-item"><span className="legend-sq knw" />chat turns</span>
              <span className="legend-item"><span className="legend-sq exp" />tool &amp; skill calls</span>
            </div>
          </div>
          {daily.length === 0 ? (
            <p className="empty-state">No usage recorded yet.</p>
          ) : (
            <>
              <div className="bars">
                {daily.map((d) => (
                  <div className="bar-col" key={d.date}>
                    <div className="bar-seg exp" style={{ height: `${(d.tool_and_skill_calls / maxDailyTotal) * 100}%` }} />
                    <div className="bar-seg knw" style={{ height: `${(d.chat_turns / maxDailyTotal) * 100}%` }} />
                  </div>
                ))}
              </div>
              <div className="bars-axis">
                <span>{daily[0]?.date}</span>
                <span>{daily[Math.floor(daily.length / 2)]?.date}</span>
                <span>{daily[daily.length - 1]?.date}</span>
              </div>
            </>
          )}
        </div>

        <div className="card card-pad">
          <span className="card-title">Cost by tenant (MTD)</span>
          {!cost || cost.by_tenant.every((r) => r.cost_usd === 0) ? (
            <p className="empty-state">No spend recorded this month.</p>
          ) : (
            <>
              <ul className="cost-list">
                {cost.by_tenant.slice(0, 5).map((r) => {
                  const max = Math.max(...cost.by_tenant.map((x) => x.cost_usd), 1);
                  return (
                    <li key={r.tenant_slug}>
                      <div className="cost-row">
                        <span>{r.tenant_slug}</span>
                        <span className="amount">{fmtUsd(r.cost_usd)}</span>
                      </div>
                      <div className="cost-track">
                        <div className="cost-fill" style={{ width: `${(r.cost_usd / max) * 100}%` }} />
                      </div>
                    </li>
                  );
                })}
              </ul>
              <div className="cost-foot">
                <span className="label">Per-request avg</span>
                <span className="val">{fmtUsd(cost.avg_cost_per_request_usd)}</span>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 24, overflow: "hidden" }}>
        <div className="card-head">
          <span className="card-title">Tenants</span>
          <input className="filter-input" placeholder="Filter tenants…" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        {filteredTenants.length === 0 ? (
          <p className="empty-state">No tenants yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Tenant</th>
                <th>Admins</th>
                <th>Users</th>
                <th>Workspaces</th>
                <th>Layer setup</th>
                <th>MTD cost</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {filteredTenants.map((t) => (
                <tr key={t.id}>
                  <td>
                    <div className="td-main">{t.name}</div>
                    <div className="slug">{t.slug}</div>
                  </td>
                  <td className="mono">{t.admin_count}</td>
                  <td className="mono">{t.user_count}</td>
                  <td className="mono">{t.workspace_count}</td>
                  <td>
                    <span className="layer-dots">
                      <span className={`ldot ${t.layer_knowledge ? "knw" : "empty"}`} title="Knowledge" />
                      <span className={`ldot ${t.layer_expertise ? "exp" : "empty"}`} title="Expertise" />
                      <span className={`ldot ${t.layer_norms ? "nrm" : "empty"}`} title="Norms" />
                    </span>
                  </td>
                  <td className="mono">{fmtUsd(t.mtd_cost_usd)}</td>
                  <td>
                    <span className={`state ${t.status_label === "Active" ? "ok" : "warn"}`}>{t.status_label}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="models-row">
        <div className="card">
          <div className="card-head">
            <span className="card-title">
              Model catalog <span className="light">(MLflow Gateway routes)</span>
            </span>
            <Link className="btn btn-primary btn-sm" to="/app/platform/models">+ Onboard model</Link>
          </div>
          {models.length === 0 ? (
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
                </tr>
              </thead>
              <tbody>
                {models.map((m) => (
                  <tr key={m.id}>
                    <td className="td-main">{m.name}</td>
                    <td className="td-dim">{m.provider}</td>
                    <td className="mono">{m.route}</td>
                    <td className="mono">
                      {m.input_cost_per_1m.toFixed(2)}
                      {m.output_cost_per_1m != null ? ` / ${m.output_cost_per_1m.toFixed(2)}` : ""}
                    </td>
                    <td>
                      <span className={`state ${m.status === "live" ? "ok" : m.status === "eval" ? "warn" : ""}`}>
                        {m.status === "live" ? "Live" : m.status === "eval" ? `Eval · ${Object.values(m.gates).filter(Boolean).length - 1}/5 gates` : "Disabled"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {onboardingModel && (
          <div className="card card-pad">
            <div className="onb-title">Onboarding: {onboardingModel.name}</div>
            <div className="onb-sub">Gates must pass before tenants can route to it.</div>
            <ul className="check-list">
              <li>
                <span className={`check-circle ${onboardingModel.gates.gateway_configured ? "done" : "todo"}`}>{onboardingModel.gates.gateway_configured ? "✓" : ""}</span>
                Gateway route configured
              </li>
              <li>
                <span className={`check-circle ${onboardingModel.gates.cost_meter_registered ? "done" : "todo"}`}>{onboardingModel.gates.cost_meter_registered ? "✓" : ""}</span>
                Cost meter registered
              </li>
              <li>
                <span className={`check-circle ${onboardingModel.gates.faithfulness_passed ? "done" : "now"}`}>{onboardingModel.gates.faithfulness_passed ? "✓" : ""}</span>
                <span>
                  Faithfulness ≥ {onboardingModel.eval_faithfulness_threshold}{" "}
                  <span className="check-metric">{onboardingModel.eval_faithfulness ?? "—"}</span>
                </span>
              </li>
              <li>
                <span className={`check-circle ${onboardingModel.gates.task_completion_passed ? "done" : "todo"}`}>{onboardingModel.gates.task_completion_passed ? "✓" : ""}</span>
                Task completion ≥ {onboardingModel.eval_task_completion_threshold}
              </li>
              <li>
                <span className={`check-circle ${onboardingModel.gates.security_redteam_passed ? "done" : "todo"}`}>{onboardingModel.gates.security_redteam_passed ? "✓" : ""}</span>
                Security red-team pass
              </li>
            </ul>
            <Link to="/app/platform/models" className="onb-btn" style={{ display: "block", textAlign: "center" }}>
              View eval details
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
