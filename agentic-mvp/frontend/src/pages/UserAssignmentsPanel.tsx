import { useEffect, useState } from "react";
import type { AdminUser, Persona, Policy, PolicyMapping, UserPersonaMapping } from "../types";
import { adminUsersApi } from "../api/admin";
import { personasApi } from "../api/personas";
import { policiesApi } from "../api/policies";
import { ApiError } from "../api/client";
import AdminUsersPage from "./AdminUsersPage";

// The Norms tab's "Users & assignments" sub-tab: full user CRUD (reused
// from AdminUsersPage) plus a real assignment matrix — which Persona and
// which Policies apply to each user, backed by UserPersonaMapping
// (app/models/persona.py) and the new UserPolicyMapping
// (app/models/policy.py). Tenant-wide assignments only (project_id=null
// for the persona mapping) — per-project persona overrides still happen
// from the Projects screen.
export default function UserAssignmentsPanel() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [personaMappings, setPersonaMappings] = useState<UserPersonaMapping[]>([]);
  const [policyMappings, setPolicyMappings] = useState<PolicyMapping[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [addingPolicyFor, setAddingPolicyFor] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [u, p, pol, pm, plm] = await Promise.all([
        adminUsersApi.list(),
        personasApi.list(),
        policiesApi.list(),
        personasApi.listAllMappings(),
        policiesApi.listMappings(),
      ]);
      setUsers(u);
      setPersonas(p);
      setPolicies(pol);
      setPersonaMappings(pm);
      setPolicyMappings(plm);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load assignments");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function tenantWideMapping(userId: string): UserPersonaMapping | undefined {
    return personaMappings.find((m) => m.user_id === userId && m.project_id === null);
  }

  async function setPersonaFor(userId: string, personaId: string) {
    const existing = tenantWideMapping(userId);
    try {
      if (existing) await personasApi.removeMapping(existing.id);
      if (personaId) await personasApi.createMapping({ user_id: userId, persona_id: personaId, is_default: true });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Persona assignment failed");
    }
  }

  async function addPolicyFor(userId: string, policyId: string) {
    if (!policyId) return;
    try {
      await policiesApi.createMapping({ user_id: userId, policy_id: policyId });
      setAddingPolicyFor(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Policy assignment failed");
    }
  }

  async function removePolicyMapping(mappingId: string) {
    try {
      await policiesApi.removeMapping(mappingId);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to remove policy assignment");
    }
  }

  return (
    <div>
      <AdminUsersPage />

      <div className="card" style={{ overflow: "hidden", marginTop: 16 }}>
        <div className="card-head">
          <span className="card-title">Persona &amp; policy assignment</span>
        </div>
        {error && <p className="error-text" style={{ margin: "12px 20px 0" }}>{error}</p>}
        {loading ? (
          <p className="empty-state">Loading...</p>
        ) : users.length === 0 ? (
          <p className="empty-state">No users in this tenant yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>User</th>
                <th>Persona</th>
                <th>Policies</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const mapping = tenantWideMapping(u.id);
                const userPolicyMappings = policyMappings.filter((m) => m.user_id === u.id);
                const assignedPolicyIds = new Set(userPolicyMappings.map((m) => m.policy_id));
                const availablePolicies = policies.filter((p) => !assignedPolicyIds.has(p.id));
                return (
                  <tr key={u.id}>
                    <td>
                      <div className="td-main">{u.full_name}</div>
                      <div className="td-dim" style={{ fontSize: 12 }}>{u.email}</div>
                    </td>
                    <td>
                      <select className="input" value={mapping?.persona_id ?? ""} onChange={(e) => setPersonaFor(u.id, e.target.value)}>
                        <option value="">(none)</option>
                        {personas.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                        {userPolicyMappings.map((pm) => {
                          const policy = policies.find((p) => p.id === pm.policy_id);
                          return (
                            <span key={pm.id} className="tag tag-neutral" style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
                              {policy?.name ?? "(deleted)"}
                              <button
                                type="button"
                                onClick={() => removePolicyMapping(pm.id)}
                                style={{ background: "none", border: "none", cursor: "pointer", color: "inherit", padding: 0, fontSize: 13, lineHeight: 1 }}
                                title="Remove"
                              >
                                ×
                              </button>
                            </span>
                          );
                        })}
                        {addingPolicyFor === u.id ? (
                          <select className="input" style={{ width: 160 }} autoFocus onBlur={() => setAddingPolicyFor(null)} onChange={(e) => addPolicyFor(u.id, e.target.value)}>
                            <option value="">Select policy…</option>
                            {availablePolicies.map((p) => (
                              <option key={p.id} value={p.id}>
                                {p.name}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <button type="button" className="btn btn-ghost btn-sm" onClick={() => setAddingPolicyFor(u.id)} disabled={availablePolicies.length === 0}>
                            + Add
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
