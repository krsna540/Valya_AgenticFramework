import { useEffect, useState } from "react";
import type { CostByTenant, PlatformOverview } from "../types";
import { platformApi } from "../api/platform";
import { ApiError } from "../api/client";

function fmtUsd(n: number): string {
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: n < 10 ? 4 : 2 })}`;
}

export default function PlatformCostPage() {
  const [cost, setCost] = useState<CostByTenant | null>(null);
  const [overview, setOverview] = useState<PlatformOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [c, o] = await Promise.all([platformApi.costByTenant(), platformApi.overview()]);
        setCost(c);
        setOverview(o);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to load cost data");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const max = Math.max(1, ...(cost?.by_tenant.map((r) => r.cost_usd) ?? [1]));

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Cost &amp; billing</h1>
          <p>Real LLM spend recorded from every chat turn (see UsageEvent ledger), month to date.</p>
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}

      {overview && (
        <div className="kpi-grid">
          <div className="kpi">
            <div className="kpi-label">LLM spend (MTD)</div>
            <div className="kpi-value">{fmtUsd(overview.llm_spend_mtd_usd)}</div>
            <div className="kpi-note">budget {fmtUsd(overview.llm_budget_usd)}</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Budget remaining</div>
            <div className="kpi-value">{fmtUsd(Math.max(0, overview.llm_budget_usd - overview.llm_spend_mtd_usd))}</div>
            <div className={`kpi-note ${overview.llm_spend_mtd_usd > overview.llm_budget_usd ? "warn" : "ok"}`}>
              {((overview.llm_spend_mtd_usd / overview.llm_budget_usd) * 100).toFixed(0)}% used
            </div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Avg cost / request</div>
            <div className="kpi-value">{cost ? fmtUsd(cost.avg_cost_per_request_usd) : "—"}</div>
          </div>
        </div>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        <div className="card-head">
          <span className="card-title">Cost by tenant (MTD)</span>
        </div>
        {loading ? (
          <p className="empty-state">Loading...</p>
        ) : !cost || cost.by_tenant.length === 0 ? (
          <p className="empty-state">No spend recorded this month.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Tenant</th>
                <th>MTD cost</th>
                <th>Share</th>
              </tr>
            </thead>
            <tbody>
              {cost.by_tenant.map((r) => (
                <tr key={r.tenant_slug}>
                  <td>
                    <div className="td-main">{r.tenant_name}</div>
                    <div className="slug">{r.tenant_slug}</div>
                  </td>
                  <td className="mono">{fmtUsd(r.cost_usd)}</td>
                  <td style={{ width: 200 }}>
                    <div className="cost-track">
                      <div className="cost-fill" style={{ width: `${(r.cost_usd / max) * 100}%` }} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
