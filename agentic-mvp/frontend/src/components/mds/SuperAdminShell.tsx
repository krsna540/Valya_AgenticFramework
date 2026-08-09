import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";

// Super Admin shell — dark chrome rail (.mds-rail.role-superadmin), matching
// superadmin-app.html's identity. Badge counts are wired where the data is
// cheap to have on hand already (waiting-on-a-person via runs list on the
// Health page's own load — kept static here to avoid a second network round
// trip just for a nav badge; see HealthPage for the real number).
const NAV = [
  { to: "/app/sa/health", label: "Platform health" },
  { to: "/app/sa/tenants", label: "Organisations" },
  { to: "/app/sa/catalog", label: "Platform catalog" },
  { to: "/app/sa/models", label: "Models" },
  { to: "/app/sa/rules", label: "Platform rules" },
  { to: "/app/sa/audit", label: "Audit log" },
];

export default function SuperAdminShell() {
  const { user, logout } = useAuth();

  return (
    <div className="mds-root mds-app">
      <aside className="mds-rail role-superadmin">
        <div className="top">
          <div className="org">Platform</div>
          <div className="me">Super admin · {user?.full_name}</div>
        </div>
        <div className="items">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `mds-navbtn ${isActive ? "on" : ""}`}>
              <span>{n.label}</span>
            </NavLink>
          ))}
        </div>
        <div className="foot">
          You can see every organisation from here. You cannot read the contents of anyone's work.
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
