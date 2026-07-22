import { useState } from "react";
import AgentsPage from "./AgentsPage";
import SkillsPage from "./SkillsPage";
import ToolsPage from "./ToolsPage";
import PluginsPage from "./PluginsPage";
import HooksPage from "./HooksPage";

type SubTab = "playbooks" | "skills" | "tools" | "plugins" | "hooks";

const SUB_TABS: { key: SubTab; label: string }[] = [
  { key: "playbooks", label: "Playbooks" },
  { key: "skills", label: "Skills" },
  { key: "tools", label: "Tools" },
  { key: "plugins", label: "Plugins" },
  { key: "hooks", label: "Hooks" },
];

// The Admin Expertise tab: full create/update/delete for every Expertise
// registry (Playbooks == Agents bound to skills/tools/plugins/hooks, see
// app/models/agent.py, plus the Skills/Tools/Plugins/Hooks catalogs each
// have their own full CRUD page already — this just brings them all
// under one tab via a sub-tab switcher instead of a read-only summary).
export default function AdminExpertisePage() {
  const [tab, setTab] = useState<SubTab>("playbooks");

  return (
    <div>
      <div className="page-header">
        <div>
          <h1>Playbooks, skills &amp; models</h1>
          <p>Define what your agents are good at: reusable playbooks, skills, plugins, hooks, and the models behind them.</p>
        </div>
      </div>

      <div className="tab-switch" style={{ marginBottom: 20, display: "inline-flex" }}>
        {SUB_TABS.map((t) => (
          <button key={t.key} type="button" className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "playbooks" && <AgentsPage />}
      {tab === "skills" && <SkillsPage />}
      {tab === "tools" && <ToolsPage />}
      {tab === "plugins" && <PluginsPage />}
      {tab === "hooks" && <HooksPage />}
    </div>
  );
}
