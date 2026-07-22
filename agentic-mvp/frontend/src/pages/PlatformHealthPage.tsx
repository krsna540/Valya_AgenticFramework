import { useEffect, useState } from "react";
import type { PlatformHealth } from "../types";
import { platformApi } from "../api/platform";
import { ApiError } from "../api/client";

export default function PlatformHealthPage() {
  const [health, setHealth] = useState<PlatformHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setHealth(await platformApi.health());
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to load platform health");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Platform health</h1>
          <p>Signals derived from real recorded usage and ingestion state — not a live infra probe.</p>
        </div>
      </div>

      {error && <p className="error-text">{error}</p>}

      {loading ? (
        <p className="empty-state">Loading...</p>
      ) : health ? (
        <div className="kpi-grid">
          <div className="kpi">
            <div className="kpi-label">Gateway p95 latency</div>
            <div className="kpi-value">{health.gateway_p95_latency_ms != null ? `${(health.gateway_p95_latency_ms / 1000).toFixed(1)}s` : "—"}</div>
            <div className={`kpi-note ${health.gateway_p95_latency_ms != null && health.gateway_p95_latency_ms > health.gateway_slo_ms ? "warn" : "ok"}`}>
              SLO {(health.gateway_slo_ms / 1000).toFixed(1)}s
            </div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Error rate (30d)</div>
            <div className="kpi-value">{(health.error_rate_30d * 100).toFixed(1)}%</div>
            <div className="kpi-note">{health.total_requests_30d.toLocaleString()} requests</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Datasources failing</div>
            <div className={`kpi-value ${health.datasources_failing > 0 ? "err" : ""}`}>{health.datasources_failing}</div>
            <div className="kpi-note">{health.datasources_syncing} currently syncing</div>
          </div>
          <div className="kpi">
            <div className="kpi-label">Last request</div>
            <div className="kpi-value" style={{ fontSize: 16 }}>
              {health.last_request_at ? new Date(health.last_request_at).toLocaleString() : "—"}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
