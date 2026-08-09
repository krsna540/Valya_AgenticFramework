import { NavLink, Outlet } from "react-router-dom";

// User shell — top tab bar (.mds-tabs/.mds-tab), matching user-app.html.
// No rail: the user app is workspace/chat-centric, not settings-table-
// centric, so the mockup deliberately drops the sidebar chrome entirely.
const TABS = [
  { to: "/app/u/home", label: "Home" },
  { to: "/app/u/workspace", label: "Workspace" },
  { to: "/app/u/activity", label: "Activity" },
  { to: "/app/u/sources", label: "Sources" },
  { to: "/app/u/settings", label: "Settings" },
];

export default function UserShell() {
  return (
    <div className="mds-root mds-app-tabs">
      <nav className="mds-tabs">
        <span className="brand">Assistant</span>
        {TABS.map((t) => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => `mds-tab ${isActive ? "on" : ""}`}>
            {t.label}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}
