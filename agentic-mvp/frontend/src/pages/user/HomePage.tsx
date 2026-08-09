import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../../api/client";
import { chatApi } from "../../api/chat";
import { agentsApi } from "../../api/registry";
import { useAuth } from "../../context/AuthContext";
import type { Conversation } from "../../types";

// Matches user-app.html's "Home" screen. "Workspace" in the mockup maps
// onto a real Conversation here (see WorkspacePage's docstring for why —
// short version: a plain "user" role can create conversations but not
// Projects, so a Conversation is the thing this screen can actually create
// end to end against real permissions).
export default function HomePage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [search, setSearch] = useState("");
  const [goal, setGoal] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    chatApi
      .listConversations()
      .then(setConversations)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load workspaces"));
  }, []);

  async function startGoal(e: FormEvent) {
    e.preventDefault();
    const g = goal.trim();
    if (!g) return;
    setStarting(true);
    setError(null);
    try {
      const agents = await agentsApi.list();
      if (agents.length === 0) {
        setError("No agents are available to talk to yet — ask your admin to add one.");
        return;
      }
      const convo = await chatApi.createConversation(agents[0].id, [], g.length > 60 ? `${g.slice(0, 60)}…` : g);
      navigate(`/app/u/workspace/${convo.id}?draft=${encodeURIComponent(g)}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start that");
    } finally {
      setStarting(false);
    }
  }

  const filtered = conversations.filter((c) => !search || c.title.toLowerCase().includes(search.toLowerCase()));

  return (
    <section className="mds-screen center" style={{ display: "flex", justifyContent: "center", padding: "56px 32px", flex: 1, minHeight: 0, overflow: "auto" }}>
      <div className="mds-col" style={{ maxWidth: 760, gap: 36, width: "100%" }}>
        <div>
          <div className="mds-kicker" style={{ marginBottom: 10 }}>{user?.full_name}</div>
          <h1 style={{ fontSize: 40, marginBottom: 10 }}>Good to see you</h1>
          <p className="mds-lead" style={{ maxWidth: 520 }}>Pick a workspace to carry on, or describe something new you want done.</p>
        </div>

        {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

        <form onSubmit={startGoal} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <label className="mds-kicker" htmlFor="newGoal">What do you need done?</label>
          <textarea
            id="newGoal"
            rows={3}
            placeholder="e.g. Check last quarter's supplier invoices against our books and flag anything unusual"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            style={{ resize: "none", fontSize: 16, lineHeight: 1.55 }}
          />
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <button type="submit" className="mds-btn mds-btn-primary" disabled={starting}>{starting ? "Starting…" : "Start"}</button>
            <span className="mds-muted" style={{ fontSize: 13 }}>A new workspace is created for it.</span>
          </div>
        </form>

        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 6 }}>
            <span className="mds-kicker">Your workspaces</span>
            <input placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} style={{ flex: 1, padding: "7px 12px", fontSize: 13.5 }} />
          </div>
          {filtered.length === 0 ? (
            <p className="mds-muted" style={{ padding: "16px 0" }}>Nothing yet — start something above.</p>
          ) : (
            filtered.map((c) => (
              <div className="mds-list-row" key={c.id} onClick={() => navigate(`/app/u/workspace/${c.id}`)}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: "var(--mds-font-head)", fontSize: 18, fontWeight: 600, marginBottom: 3 }}>{c.title}</div>
                  <div className="mds-muted" style={{ fontSize: 13.5 }}>{new Date(c.created_at).toLocaleString()}</div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
