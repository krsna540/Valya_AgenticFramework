import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { platformCatalogApi, type CatalogItem } from "../../api/platformCatalog";

// Matches superadmin-app.html's "Platform catalog" screen — real
// access_class="default" rows across skills/prompts/tools/hooks/plugins,
// with fork counts and project-binding counts (see
// backend/app/api/routes/platform_catalog.py).
export default function CatalogPage() {
  const [items, setItems] = useState<CatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setItems(await platformCatalogApi.list());
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Failed to load the platform catalog");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="mds-col" style={{ maxWidth: 1000, gap: 32 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 24 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: 36, marginBottom: 8 }}>Platform catalog</h1>
          <p className="mds-lead" style={{ maxWidth: 640 }}>
            Abilities every organisation starts with. Organisations cannot edit these. They copy one, change the copy, and keep
            a visible link back to what it came from.
          </p>
        </div>
      </div>

      {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

      <div>
        <div className="mds-table-head">
          <div className="mds-grow">Ability</div>
          <div className="mds-fix" style={{ width: 90 }}>Kind</div>
          <div className="mds-fix" style={{ width: 90 }}>Version</div>
          <div className="mds-fix" style={{ width: 120 }}>Copied by</div>
          <div className="mds-fix" style={{ width: 120 }}>In use</div>
          <div className="mds-fix" style={{ width: 100 }}>Status</div>
        </div>
        {loading ? (
          <p className="mds-muted" style={{ padding: "20px 12px" }}>Loading…</p>
        ) : items.length === 0 ? (
          <p className="mds-muted" style={{ padding: "20px 12px" }}>Nothing published to the catalog yet.</p>
        ) : (
          items.map((c) => (
            <div className="mds-row" key={`${c.kind}-${c.id}`}>
              <div className="mds-grow">
                <div className="mds-rname">{c.name}</div>
                <div className="mds-rsub">{c.description ?? "—"}</div>
              </div>
              <div className="mds-fix mds-muted" style={{ width: 90, fontSize: 13.5, textTransform: "capitalize" }}>{c.kind}</div>
              <div className="mds-fix mds-muted" style={{ width: 90, fontSize: 13.5 }}>{c.version}</div>
              <div className="mds-fix" style={{ width: 120, fontSize: 13.5 }}>
                {c.forked_count} organisation{c.forked_count === 1 ? "" : "s"}
              </div>
              <div className="mds-fix" style={{ width: 120, fontSize: 13.5 }}>
                {c.projects_in_use} workspace{c.projects_in_use === 1 ? "" : "s"}
              </div>
              <div className="mds-fix" style={{ width: 100 }}>
                <span className="mds-tag mds-tag-accent">{c.status}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
