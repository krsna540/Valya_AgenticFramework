import { useAuth } from "../../context/AuthContext";

// Matches user-app.html's "Workspace settings" screen. This build has no
// per-workspace settings resource (budgets/effort-limits/approval-routing
// are Agent.runtime_config, set by an Admin — see AdminExpertisePage), so
// rather than fabricate editable toggles this screen shows real identity
// facts plus the platform-wide defaults every workspace inherits (the same
// floor the Super Admin "Platform rules" screen manages) — labeled as
// such, not presented as something this screen can change.
export default function SettingsPage() {
  const { user } = useAuth();

  const groups: { title: string; rows: { name: string; value: string; detail: string }[] }[] = [
    {
      title: "You",
      rows: [
        { name: "Name", value: user?.full_name ?? "—", detail: "Shown on everything you approve or decline." },
        { name: "Email", value: user?.email ?? "—", detail: "Used to sign in." },
        { name: "Role", value: user?.role ?? "—", detail: "Set by your organisation's admin." },
      ],
    },
    {
      title: "How it works (platform floor — see your admin for anything stricter)",
      rows: [
        { name: "Ask before acting", value: "Anything that writes", detail: "The assistant stops and asks before any action that changes something outside this workspace." },
        { name: "Effort limit ceiling", value: "40 steps", detail: "The most any organisation can allow before a piece of work must check in." },
      ],
    },
    {
      title: "Record keeping",
      rows: [
        { name: "What it remembers", value: "Finished work only", detail: "It learns from work you accepted. Abandoned or blocked work leaves nothing behind." },
      ],
    },
  ];

  return (
    <section className="mds-screen center" style={{ display: "flex", justifyContent: "center", padding: "56px 32px", flex: 1, minHeight: 0, overflow: "auto" }}>
      <div className="mds-col" style={{ maxWidth: 680, gap: 40, width: "100%" }}>
        <div>
          <h1 style={{ fontSize: 34, marginBottom: 8 }}>Workspace settings</h1>
          <p className="mds-lead">How this workspace behaves for everyone in it.</p>
        </div>

        {groups.map((g) => (
          <div key={g.title} style={{ marginBottom: 6 }}>
            <div className="mds-kicker" style={{ marginBottom: 4 }}>{g.title}</div>
            {g.rows.map((r) => (
              <div key={r.name} style={{ display: "flex", gap: 24, alignItems: "center", padding: "18px 0", borderBottom: "1px solid var(--mds-n300)" }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 15.5, fontWeight: 600, marginBottom: 3 }}>{r.name}</div>
                  <div className="mds-muted" style={{ fontSize: 13.5, lineHeight: 1.5 }}>{r.detail}</div>
                </div>
                <div className="mds-fix" style={{ width: 170, textAlign: "right", fontSize: 14, color: "var(--mds-a700)" }}>{r.value}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
