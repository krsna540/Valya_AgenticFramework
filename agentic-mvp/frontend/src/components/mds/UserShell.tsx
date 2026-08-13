import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";

// User shell — top tab bar (.mds-tabs/.mds-tab), matching user-app.html.
// No rail: the user app is workspace/chat-centric, not settings-table-
// centric, so the mockup deliberately drops the sidebar chrome entirely.
//
// Because there is no rail, there was also nowhere for the "Log out" button
// the other two shells put in their rail footer — a user signed in through
// this shell had no way out short of clearing the token by hand. It lives
// at the right-hand end of the tab bar instead, pushed there by a spacer.
const TABS = [
  { to: "/app/u/home", label: "Home" },
  { to: "/app/u/workspace", label: "Workspace" },
  { to: "/app/u/activity", label: "Activity" },
  { to: "/app/u/sources", label: "Sources" },
  { to: "/app/u/settings", label: "Settings" },
];

export default function UserShell() {
  const { user, logout } = useAuth();

  return (
    <div className="mds-root mds-app-tabs">
      <nav className="mds-tabs">
        <span className="brand">Assistant</span>
        {TABS.map((t) => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => `mds-tab ${isActive ? "on" : ""}`}>
            {t.label}
          </NavLink>
        ))}
        <span style={{ flex: 1 }} />
        {user?.full_name && (
          <span className="mds-muted" style={{ fontSize: 12.5, marginRight: 10 }}>
            {user.full_name}
          </span>
        )}
        <button type="button" className="mds-tab" onClick={logout}>
          Log out
        </button>
      </nav>
      <Outlet />
    </div>
  );
}
