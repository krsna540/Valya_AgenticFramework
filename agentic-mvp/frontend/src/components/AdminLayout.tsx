import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

// Tenant Admin flow shell — dark topbar + the Knowledge/Expertise/Norms
// tri-layer tabs (see admin.html). Each tab's content lives at its own
// route so it gets its own URL/back-button behavior; the tab strip itself
// is just NavLink-driven, same active-state pattern as the other layouts.
const TABS = [
  { to: "/app/admin/knowledge", label: "Knowledge layer", sq: "knw" },
  { to: "/app/admin/expertise", label: "Expertise layer", sq: "exp" },
  { to: "/app/admin/norms", label: "Norms layer", sq: "nrm" },
];

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const initials = (user?.full_name ?? "AD")
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className="admin-shell">
      <header className="admin-topbar">
        <div className="admin-topbar-row">
          <div className="admin-brand">
            <div className="layerbar" />
            <div className="admin-brand-name">
              Knowledge Nexus <span className="sub">/ admin</span>
            </div>
          </div>
          <span className="admin-tenant-tag">tenant: {user?.tenant_id?.slice(0, 8) ?? "—"}</span>
          <div className="admin-topbar-links">
            <span className="text-muted">{user?.full_name}</span>
            <button onClick={logout}>Log out</button>
            <div className="admin-avatar">{initials}</div>
          </div>
        </div>

        <nav className="admin-tabs">
          {TABS.map((tab) => (
            <NavLink key={tab.to} to={tab.to} className={({ isActive }) => `admin-tabbtn${isActive ? " on" : ""}`}>
              {({ isActive }: { isActive: boolean }) => (
                <>
                  <span className="admin-tab-inner">
                    <span className={`admin-tab-sq ${tab.sq}`} />
                    {tab.label}
                  </span>
                  <span className={`admin-tab-underline ${tab.sq}`} style={{ display: isActive ? "block" : "none" }} />
                </>
              )}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="admin-page">
        <Outlet />
      </main>
    </div>
  );
}
