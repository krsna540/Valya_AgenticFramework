import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { skillsApi } from "../../api/skills";
import { toolsApi } from "../../api/tools";
import { promptsApi } from "../../api/prompts";
import { hooksApi } from "../../api/registry";
import { playbooksApi, type Playbook } from "../../api/playbooks";
import type { Hook, Prompt, Skill, Tool } from "../../types";

type TabKey = "skills" | "instructions" | "tools" | "guardrails" | "playbooks";
const TABS: { key: TabKey; label: string }[] = [
  { key: "skills", label: "Skills" },
  { key: "instructions", label: "Instructions" },
  { key: "tools", label: "Tools" },
  { key: "guardrails", label: "Guardrails" },
  { key: "playbooks", label: "Playbooks" },
];

interface Row {
  id: string;
  name: string;
  description: string | null;
  version: string;
  status: string;
}

const LIFECYCLE = [
  { n: 1, t: "Draft", d: "Someone writes it, or the system suggests it from work that kept succeeding." },
  { n: 2, t: "Checked", d: "Automatic checks catch the obvious problems before a person spends time on it." },
  { n: 3, t: "Reviewed", d: "A named person who did not write it signs it off." },
  { n: 4, t: "Published", d: "The version is fixed. It can be replaced later but never quietly edited." },
  { n: 5, t: "Switched on", d: "Turned on for a workspace. Work already running keeps the version it started with." },
];

// Matches admin-app.html's "Abilities" screen — five real registry kinds
// behind one tabbed table, each already CRUD-complete on its own dedicated
// page (SkillsPage/PromptsPage/ToolsPage/HooksPage/RegistryPage's playbooks);
// this view is the mockup's "one flat list per kind" read surface on top of
// that same data.
export default function AbilitiesPage() {
  const [tab, setTab] = useState<TabKey>("skills");
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    const load = async (): Promise<Row[]> => {
      if (tab === "skills") {
        const skills = await skillsApi.list();
        return skills.map((s: Skill) => ({ id: s.id, name: s.name, description: s.description, version: s.version, status: s.status }));
      }
      if (tab === "instructions") {
        const prompts = await promptsApi.list();
        return prompts.map((p: Prompt) => ({ id: p.id, name: p.name, description: p.description, version: p.version, status: p.status }));
      }
      if (tab === "tools") {
        const tools = await toolsApi.list();
        return tools.map((t: Tool) => ({ id: t.id, name: t.name, description: t.description, version: t.version, status: t.status }));
      }
      if (tab === "guardrails") {
        const hooks = await hooksApi.list();
        return hooks.map((h: Hook) => ({ id: h.id, name: h.name, description: h.description, version: h.version, status: h.status }));
      }
      const playbooks = await playbooksApi.list();
      return playbooks.map((p: Playbook) => ({ id: p.id, name: p.name, description: p.description, version: p.version, status: p.status }));
    };
    load()
      .then((r) => !cancelled && setRows(r))
      .catch((err) => !cancelled && setError(err instanceof ApiError ? err.message : "Failed to load"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [tab]);

  return (
    <div className="mds-col" style={{ maxWidth: 1040, gap: 30 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 24 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: 36, marginBottom: 8 }}>Abilities</h1>
          <p className="mds-lead" style={{ maxWidth: 640 }}>
            What the assistant knows how to do, and what it is allowed to touch. Nothing reaches a workspace until it is
            reviewed, published and switched on there.
          </p>
        </div>
      </div>

      {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

      <div className="mds-tabbar">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "on" : ""} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      <div>
        <div className="mds-table-head">
          <div className="mds-grow">Name</div>
          <div className="mds-fix" style={{ width: 100 }}>Version</div>
          <div className="mds-fix" style={{ width: 130 }}>Stage</div>
        </div>
        {loading ? (
          <p className="mds-muted" style={{ padding: "20px 12px" }}>Loading…</p>
        ) : rows.length === 0 ? (
          <p className="mds-muted" style={{ padding: "20px 12px" }}>Nothing here yet.</p>
        ) : (
          rows.map((r) => (
            <div className="mds-row" key={r.id}>
              <div className="mds-grow">
                <div className="mds-rname">{r.name}</div>
                <div className="mds-rsub">{r.description ?? "—"}</div>
              </div>
              <div className="mds-fix mds-muted" style={{ width: 100, fontSize: 13.5 }}>{r.version}</div>
              <div className="mds-fix" style={{ width: 130 }}>
                <span className={`mds-tag ${r.status === "Active" ? "mds-tag-accent" : r.status === "Deprecated" ? "mds-tag-outline" : "mds-tag-neutral"}`}>
                  {r.status}
                </span>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="mds-card">
        <div className="mds-kicker" style={{ marginBottom: 16 }}>How an ability reaches people</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)" }}>
          {LIFECYCLE.map((l, i) => (
            <div key={l.n} style={{ padding: "0 18px", borderRight: i < 4 ? "1px solid var(--mds-n300)" : undefined }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <div style={{ width: 19, height: 19, flex: "none", border: "1px solid var(--mds-a600)", color: "var(--mds-a700)", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--mds-font-head)", fontSize: 11, fontWeight: 600 }}>
                  {l.n}
                </div>
                <div style={{ fontFamily: "var(--mds-font-head)", fontSize: 15, fontWeight: 600 }}>{l.t}</div>
              </div>
              <div style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--mds-n800)" }}>{l.d}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
