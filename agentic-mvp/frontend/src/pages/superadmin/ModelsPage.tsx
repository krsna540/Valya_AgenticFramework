import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { modelRoutesApi } from "../../api/modelRoutes";
import type { ModelRoute } from "../../types";

// Matches superadmin-app.html's "Models" screen — real MLflow-gateway-route
// catalog (app/models/model_route.py). "Spend today" isn't tracked per-route
// per-day in this build, so that column is omitted rather than fabricated;
// see PlatformOverviewPage's cost-by-tenant chart for real spend figures.
export default function ModelsPage() {
  const [models, setModels] = useState<ModelRoute[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setModels(await modelRoutesApi.list());
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to load models");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="mds-col" style={{ maxWidth: 960, gap: 32 }}>
      <div>
        <h1 style={{ fontSize: 36, marginBottom: 8 }}>Models</h1>
        <p className="mds-lead" style={{ maxWidth: 640 }}>
          Every request goes through one door, so swapping a model is a setting here rather than a change in a hundred places.
        </p>
      </div>

      {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

      <div>
        <div className="mds-table-head">
          <div className="mds-grow">Model</div>
          <div className="mds-fix" style={{ width: 140 }}>Provider</div>
          <div className="mds-fix" style={{ width: 160 }}>Route</div>
          <div className="mds-fix" style={{ width: 130 }}>$ / 1M tok</div>
          <div className="mds-fix" style={{ width: 120 }}>Status</div>
        </div>
        {loading ? (
          <p className="mds-muted" style={{ padding: "20px 12px" }}>Loading…</p>
        ) : models.length === 0 ? (
          <p className="mds-muted" style={{ padding: "20px 12px" }}>No models onboarded yet.</p>
        ) : (
          models.map((m) => (
            <div className="mds-row" key={m.id}>
              <div className="mds-grow">
                <div className="mds-rname">{m.name}</div>
                <div className="mds-rsub">{m.kind === "chat" ? "Chat / generation" : "Embedding"}</div>
              </div>
              <div className="mds-fix" style={{ width: 140, fontSize: 13.5 }}>{m.provider}</div>
              <div className="mds-fix mds-muted" style={{ width: 160, fontSize: 13.5, fontFamily: "monospace" }}>{m.route}</div>
              <div className="mds-fix" style={{ width: 130, fontSize: 13.5 }}>
                {m.input_cost_per_1m.toFixed(2)}
                {m.output_cost_per_1m != null ? ` / ${m.output_cost_per_1m.toFixed(2)}` : ""}
              </div>
              <div className="mds-fix" style={{ width: 120 }}>
                <span className={`mds-tag ${m.status === "live" ? "mds-tag-accent" : m.status === "eval" ? "mds-tag-outline" : "mds-tag-neutral"}`}>
                  {m.status === "live" ? "Live" : m.status === "eval" ? "In eval" : "Disabled"}
                </span>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="mds-card" style={{ fontSize: 13.5, lineHeight: 1.6, color: "var(--mds-n800)", maxWidth: 640 }}>
        A model change takes effect for work started afterwards. Anything already running finishes on the model it started
        with, so results stay consistent within a single piece of work.
      </div>
    </div>
  );
}
