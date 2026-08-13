import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";

// Admin shell — mid-steel rail (.mds-rail.role-admin), matching
// admin-app.html's identity.
const NAV = [
  { to: "/app/admin2/overview", label: "Overview" },
  { to: "/app/admin2/workspaces", label: "Workspaces" },
  { to: "/app/admin2/people", label: "People" },
  { to: "/app/admin2/sources", label: "Sources" },
  { to: "/app/admin2/abilities", label: "Abilities" },
  { to: "/app/admin2/rules", label: "Rules" },
];

// The registry authoring surfaces. These are the full create/edit/delete
// pages (pages/AgentsPage, SkillsPage, ToolsPage, PluginsPage, HooksPage,
// PromptsPage) — the "Abilities" screen above is only the mockup's flat
// read-only roll-up of the same rows, so without this group an Admin
// landing on this shell had no way to author anything. Mounted here under
// /app/admin2/* (see App.tsx) rather than left stranded on the legacy
// /app/admin layout, which the Admin role no longer lands on.
const BUILD_NAV = [
  { to: "/app/admin2/agents", label: "Agents" },
  { to: "/app/admin2/skills", label: "Skills" },
  { to: "/app/admin2/tools", label: "Tools" },
  { to: "/app/admin2/plugins", label: "Plugins" },
  { to: "/app/admin2/hooks", label: "Hooks" },
  { to: "/app/admin2/prompts", label: "Prompts" },
  { to: "/app/admin2/personas", label: "Personas" },
  { to: "/app/admin2/playbooks", label: "Playbooks" },
];

export default function AdminShell() {
  const { user, logout } = useAuth();

  return (
    <div className="mds-root mds-app">
      <aside className="mds-rail role-admin">
        <div className="top">
          <div className="org">{user?.tenant_id ? "Your organisation" : "Organisation"}</div>
          <div className="me">Admin · {user?.full_name}</div>
        </div>
        <div className="items">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `mds-navbtn ${isActive ? "on" : ""}`}>
              <span>{n.label}</span>
            </NavLink>
          ))}
          <div
            style={{
              margin: "16px 10px 6px",
              paddingTop: 14,
              borderTop: "1px solid var(--mds-a700)",
              fontSize: 11,
              letterSpacing: ".09em",
              textTransform: "uppercase",
              opacity: 0.7,
            }}
          >
            Build
          </div>
          {BUILD_NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `mds-navbtn ${isActive ? "on" : ""}`}>
              <span>{n.label}</span>
            </NavLink>
          ))}
        </div>
        <div className="foot">
          Changes here apply to work started afterwards. Anything already running keeps the setup it started with.
          <button
            onClick={logout}
            className="mds-btn mds-btn-sm mds-btn-block"
            style={{ marginTop: 14, borderColor: "var(--mds-bg)", color: "var(--mds-bg)" }}
          >
            Log out
          </button>
        </div>
      </aside>
      <section className="mds-screen">
        <Outlet />
      </section>
    </div>
  );
}
