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
