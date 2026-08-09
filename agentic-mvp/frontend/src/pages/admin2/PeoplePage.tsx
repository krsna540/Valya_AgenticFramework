import { FormEvent, useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { adminUsersApi } from "../../api/admin";
import type { AdminUser } from "../../types";

// Matches admin-app.html's "People" screen — real tenant-scoped users
// (admins can only create role="user" accounts here; promoting to admin is
// a Super Admin action — see api/admin.ts's own comment).
function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

export default function PeoplePage() {
  const [people, setPeople] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showInvite, setShowInvite] = useState(false);
  const [form, setForm] = useState({ email: "", full_name: "", password: "" });
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    setLoading(true);
    try {
      setPeople(await adminUsersApi.list());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load people");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleInvite(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await adminUsersApi.create(form);
      setForm({ email: "", full_name: "", password: "" });
      setShowInvite(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Invite failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mds-col" style={{ maxWidth: 960, gap: 32 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 24 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ fontSize: 36, marginBottom: 8 }}>People</h1>
          <p className="mds-lead" style={{ maxWidth: 600 }}>
            Who is in this organisation and what they can do. Results are always filtered to what a person could already open
            themselves.
          </p>
        </div>
        <button className="mds-btn mds-btn-primary" onClick={() => setShowInvite(true)}>Invite someone</button>
      </div>

      {error && <p style={{ color: "var(--mds-a800)" }}>{error}</p>}

      {showInvite && (
        <form onSubmit={handleInvite} className="mds-card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", gap: 12 }}>
            <div style={{ flex: 1 }}>
              <label className="mds-kicker" style={{ display: "block", marginBottom: 6 }}>Full name</label>
              <input required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} style={{ width: "100%" }} />
            </div>
            <div style={{ flex: 1 }}>
              <label className="mds-kicker" style={{ display: "block", marginBottom: 6 }}>Email</label>
              <input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} style={{ width: "100%" }} />
            </div>
          </div>
          <div>
            <label className="mds-kicker" style={{ display: "block", marginBottom: 6 }}>Initial password</label>
            <input required minLength={8} type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} style={{ width: "100%" }} />
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button type="button" className="mds-btn" onClick={() => setShowInvite(false)}>Cancel</button>
            <button type="submit" className="mds-btn mds-btn-primary" disabled={submitting}>{submitting ? "Inviting…" : "Invite"}</button>
          </div>
        </form>
      )}

      <div>
        <div className="mds-table-head">
          <div className="mds-grow">Person</div>
          <div className="mds-fix" style={{ width: 150 }}>Role</div>
          <div className="mds-fix" style={{ width: 110 }}>Status</div>
        </div>
        {loading ? (
          <p className="mds-muted" style={{ padding: "20px 12px" }}>Loading…</p>
        ) : people.length === 0 ? (
          <p className="mds-muted" style={{ padding: "20px 12px" }}>No one here yet.</p>
        ) : (
          people.map((p) => (
            <div className="mds-row" key={p.id}>
              <div className="mds-grow" style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div className="mds-avatar">{initials(p.full_name)}</div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 15, fontWeight: 600 }}>{p.full_name}</div>
                  <div className="mds-muted" style={{ fontSize: 12.5 }}>{p.email}</div>
                </div>
              </div>
              <div className="mds-fix" style={{ width: 150 }}>
                <span className={`mds-tag ${p.role === "admin" ? "mds-tag-accent" : "mds-tag-neutral"}`}>{p.role}</span>
              </div>
              <div className="mds-fix" style={{ width: 110 }}>
                <span className={`mds-tag ${p.is_active ? "mds-tag-accent" : "mds-tag-outline"}`}>{p.is_active ? "Active" : "Disabled"}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
