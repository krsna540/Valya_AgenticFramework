import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

// Three OPA-backed flows (see docs/AUTHORIZATION.md):
//   user        — Chat + read-only Agents/Projects/Prompts only.
//   admin       — everything under their own tenant (catalogs + user mgmt).
//   super_admin — no tenant of their own; Platform > Tenants instead, plus
//                 (per Rego) unrestricted read/write across every tenant's
//                 catalogs, so the same catalog links apply to them too.
// This list only controls whether a nav link appears — the OPA policy is
// still the real enforcement, each page's own calls will 403/400 if a link
// is ever reached in a way the backend disallows.
const WORKSPACE_NAV_ITEMS = [
  { to: "/app/chat", label: "Chat", icon: ICON_CHAT },
  { to: "/app/projects", label: "Projects", icon: ICON_PROJECTS },
];

// Readable by every role, incl. plain "user" (read-only for them).
const USER_READABLE_CATALOG_ITEMS = [
  { to: "/app/agents", label: "Agents", icon: ICON_AGENTS },
  { to: "/app/prompts", label: "Prompts", icon: ICON_PROMPTS },
];

// Admin/Super Admin only — plain "user" role has no OPA grant for these.
const MANAGE_CATALOG_ITEMS = [
  { to: "/app/skills", label: "Skills", icon: ICON_SKILLS },
  { to: "/app/tools", label: "Tools", icon: ICON_TOOLS },
  { to: "/app/plugins", label: "Plugins", icon: ICON_PLUGINS },
  { to: "/app/hooks", label: "Hooks", icon: ICON_HOOKS },
  { to: "/app/personas", label: "Personas", icon: ICON_PERSONAS },
  { to: "/app/datasources", label: "Datasources", icon: ICON_DATASOURCES },
];

const ADMIN_NAV_ITEMS = [{ to: "/app/admin/users", label: "Tenant & Users", icon: ICON_ADMIN }];

const PLATFORM_NAV_ITEMS = [{ to: "/app/platform/tenants", label: "Tenants", icon: ICON_PLATFORM }];

function ICON_CHAT() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
    </svg>
  );
}
function ICON_PROJECTS() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M12 2 2 7l10 5 10-5-10-5z" />
      <path d="m2 17 10 5 10-5" />
      <path d="m2 12 10 5 10-5" />
    </svg>
  );
}
function ICON_AGENTS() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="4" y="4" width="16" height="16" />
      <rect x="9" y="9" width="6" height="6" />
    </svg>
  );
}
function ICON_SKILLS() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" />
    </svg>
  );
}
function ICON_TOOLS() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M14.7 6.3a4 4 0 0 1-5.1 5.1L4 17l3 3 5.6-5.6a4 4 0 0 1 5.1-5.1l-3 3-2-2z" />
    </svg>
  );
}
function ICON_PLUGINS() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M9 3h4a1 1 0 0 1 1 1v2.2a1.8 1.8 0 1 0 0 3.6V12a1 1 0 0 1-1 1h-2.2a1.8 1.8 0 1 0-3.6 0H5a1 1 0 0 1-1-1V9a1.8 1.8 0 1 0 0-3.6V4a1 1 0 0 1 1-1h2.2a1.8 1.8 0 1 0 3.6 0z" />
    </svg>
  );
}
function ICON_HOOKS() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M9 17H7A5 5 0 0 1 7 7h2" />
      <path d="M15 7h2a5 5 0 1 1 0 10h-2" />
      <line x1="8" y1="12" x2="16" y2="12" />
    </svg>
  );
}
function ICON_PROMPTS() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6" />
      <line x1="8" y1="13" x2="16" y2="13" />
      <line x1="8" y1="17" x2="16" y2="17" />
    </svg>
  );
}
function ICON_PERSONAS() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-4 4-6 8-6s8 2 8 6" />
    </svg>
  );
}
function ICON_DATASOURCES() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
      <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
    </svg>
  );
}
function ICON_ADMIN() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  );
}
function ICON_PLATFORM() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M3 5v6c0 1.7 4 3 9 3s9-1.3 9-3V5" />
      <path d="M3 11v6c0 1.7 4 3 9 3s9-1.3 9-3v-6" />
    </svg>
  );
}

const ROLE_LABELS: Record<string, string> = {
  super_admin: "Super Admin",
  admin: "Admin",
  user: "User",
};

export default function Layout() {
  const { user, logout } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";
  const isAdmin = user?.role === "admin";
  const canManageCatalog = isAdmin || isSuperAdmin;

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="blueprint brand-mark">
            <i className="corner tl" />
            <i className="corner tr" />
            <i className="corner bl" />
            <i className="corner br" />
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <rect x="4" y="4" width="16" height="16" />
              <rect x="9" y="9" width="6" height="6" />
            </svg>
          </div>
          <span>Agentic AI Platform</span>
        </div>

        <div className="sidebar-section">
          <h6>Workspace</h6>
          <nav>
            {WORKSPACE_NAV_ITEMS.map((item) => (
              <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "active" : "")}>
                <item.icon />
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>

        <div className="sidebar-section">
          <h6>Intelligence Catalog</h6>
          <nav>
            {USER_READABLE_CATALOG_ITEMS.map((item) => (
              <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "active" : "")}>
                <item.icon />
                {item.label}
              </NavLink>
            ))}
            {canManageCatalog &&
              MANAGE_CATALOG_ITEMS.map((item) => (
                <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "active" : "")}>
                  <item.icon />
                  {item.label}
                </NavLink>
              ))}
          </nav>
        </div>

        {isAdmin && (
          <div className="sidebar-section">
            <h6>Admin</h6>
            <nav>
              {ADMIN_NAV_ITEMS.map((item) => (
                <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "active" : "")}>
                  <item.icon />
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
        )}

        {isSuperAdmin && (
          <div className="sidebar-section">
            <h6>Platform</h6>
            <nav>
              {PLATFORM_NAV_ITEMS.map((item) => (
                <NavLink key={item.to} to={item.to} className={({ isActive }) => (isActive ? "active" : "")}>
                  <item.icon />
                  {item.label}
                </NavLink>
              ))}
            </nav>
          </div>
        )}

        <div className="sidebar-spacer" />

        <div className="user-row">
          <div className="user-row-top">
            <div>
              <div className="user-name">{user?.full_name}</div>
              <div className={`tag ${canManageCatalog ? "tag-accent" : "tag-neutral"}`} style={{ marginTop: 3 }}>
                {user ? ROLE_LABELS[user.role] : ""}
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
