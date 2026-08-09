import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { platformApi } from "../../api/platform";
import { runsApi, type RunSummary } from "../../api/runs";
import type { PlatformHealth } from "../../types";

// Matches superadmin-app.html's "Platform health" screen. The stats grid
// and the "needs attention" list are real (platformApi.health() +
// awaiting-human runs across every tenant). The per-service breakdown
// below it is descriptive reference material, not a live probe — this app
// has no per-component healthcheck aggregator endpoint, so rather than
// fabricate "Healthy/Slow" numbers the way the original mockup's static
// data does, each row is labeled "Not monitored" honestly.
const SERVICES: { name: string; sub: string; ifStops: string }[] = [
  { name: "Sign in", sub: "Verifies who someone is", ifStops: "Nobody new can sign in; people already in keep working" },
  { name: "Admin service", sub: "All the settings and catalogs", ifStops: "No new work can start; running work is unaffected" },
  { name: "Live connection", sub: "Streams answers to people as they are written", ifStops: "Browsers reconnect and catch up automatically" },
  { name: "Work engine", sub: "Runs the steps and the checks (Temporal)", ifStops: "Work pauses and resumes elsewhere; nothing is lost" },
  { name: "Models", sub: "The one door to every model", ifStops: "Requests retry, then stop for a person" },
];

export default function HealthPage() {
  const [health, setHealth] = useState<PlatformHealth | null>(null);
  const [attention, setAttention] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [h, runs] = await Promise.all([platformApi.health(), runsApi.list({ awaitingHuman: true, limit: 20 })]);
        setHealth(h);
        setAttention(runs);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to load platform health");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <p className="mds-muted">Loading…</p>;

  return (
    <div className="mds-col" style={{ maxWidth: 1040, gap: 40 }}>
      <div>
        <h1 style={{ fontSize: 36, marginBottom: 8 }}>Platform health</h1>
        <p className="mds-lead" style={{ maxWidth: 620 }}>
          Everything running, across every organisation. Red here means people are feeling it right now.
        </p>
      </div>

      {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

      {health && (
        <div className="mds-stats">
          <div>
            <div className="v">{health.gateway_p95_latency_ms != null ? `${(health.gateway_p95_latency_ms / 1000).toFixed(1)}s` : "—"}</div>
            <div className="l">Gateway p95 latency (SLO {(health.gateway_slo_ms / 1000).toFixed(1)}s)</div>
          </div>
          <div>
            <div className="v" style={health.error_rate_30d > 0.02 ? { color: "var(--mds-a700)" } : undefined}>
              {(health.error_rate_30d * 100).toFixed(1)}%
            </div>
            <div className="l">Error rate, last 30 days ({health.total_requests_30d.toLocaleString()} requests)</div>
          </div>
          <div>
            <div className="v" style={health.datasources_failing > 0 ? { color: "var(--mds-a700)" } : undefined}>{health.datasources_failing}</div>
            <div className="l">Sources failing ({health.datasources_syncing} syncing now)</div>
          </div>
          <div>
            <div className="v" style={{ fontSize: 22 }}>{health.last_request_at ? new Date(health.last_request_at).toLocaleString() : "—"}</div>
            <div className="l">Last request seen</div>
          </div>
        </div>
      )}

      <div>
        <h2 style={{ fontSize: 21, marginBottom: 14 }}>Services</h2>
        <div className="mds-table-head">
          <div className="mds-grow">Service</div>
          <div className="mds-fix" style={{ width: 260 }}>If it stops</div>
          <div className="mds-fix" style={{ width: 130 }}>Status</div>
        </div>
        {SERVICES.map((s) => (
          <div className="mds-row" key={s.name} style={{ cursor: "default" }}>
            <div className="mds-grow">
              <div className="mds-rname">{s.name}</div>
              <div className="mds-rsub">{s.sub}</div>
            </div>
            <div className="mds-fix mds-muted" style={{ width: 260, fontSize: 13, lineHeight: 1.45 }}>{s.ifStops}</div>
            <div className="mds-fix" style={{ width: 130 }}>
              <span className="mds-tag mds-tag-outline">Not monitored</span>
            </div>
          </div>
        ))}
      </div>

      <div>
        <h2 style={{ fontSize: 21, marginBottom: 14 }}>Needs attention</h2>
        {attention.length === 0 ? (
          <div className="mds-card mds-muted">Nothing is waiting on a person across any organisation.</div>
        ) : (
          attention.map((r) => (
            <div className="mds-alert" key={r.id}>
              <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>{r.objective}</div>
              <div className="mds-muted" style={{ fontSize: 12.5, marginTop: 6 }}>
                {r.project_name ?? "No workspace"} · {r.agent_name ?? "an agent"} · {r.created_at ? new Date(r.created_at).toLocaleString() : ""}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
