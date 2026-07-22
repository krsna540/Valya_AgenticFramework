import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

// Super Admin flow shell — reuses the same dark-chrome sidebar primitives
// as the tenant Layout (.app-shell/.sidebar/.navlink/.user-row, see
// styles/index.css), just with the platform-level nav list from
// superadmin.html instead of workspace/catalog sections. Nav items map 1:1
// onto app/api/routes/platform.py's dashboard endpoints.
const NAV_ITEMS = [
  { to: "/app/platform/overview", label: "Overview" },
  { to: "/app/platform/tenants", label: "Tenants" },
  { to: "/app/platform/admins", label: "Admins" },
  { to: "/app/platform/models", label: "Models" },
  { to: "/app/platform/cost", label: "Cost & billing" },
  { to: "/app/platform/health", label: "Platform health" },
  { to: "/app/platform/audit", label: "Audit" },
];

export default function SuperAdminLayout() {
  const { user, logout } = useAuth();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="layerbar" />
          <div>
            <div>Knowledge Nexus</div>
            <span style={{ display: "block", fontFamily: "var(--font-mono)", fontSize: 11, color: "rgba(255,255,255,0.4)", fontWeight: 400 }}>
              super admin
            </span>
          </div>
        </div>

        <div className="sidebar-section">
          <nav>
            {NAV_ITEMS.map((item) => (
              <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "active" : "")}>
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="sidebar-spacer" />

        <div className="user-row">
          <div className="user-row-top">
            <div>
              <div className="user-name">{user?.full_name}</div>
              <div className="tag tag-accent" style={{ marginTop: 3 }}>
                Platform Ops
              </div>
            </div>
          </div>
          <button className="btn btn-secondary btn-block" onClick={logout}>
            Log out
          </button>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
