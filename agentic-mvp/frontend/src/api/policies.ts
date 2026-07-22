import { api } from "./client";
import type { Policy, PolicyMapping, PolicyMode } from "../types";

export interface PolicyCreatePayload {
  name: string;
  rule_expression: string;
  mode?: PolicyMode;
  is_active?: boolean;
}

export interface PolicyUpdatePayload {
  name?: string;
  rule_expression?: string;
  mode?: PolicyMode;
  is_active?: boolean;
}

// Tenant Admin Norms tab — "Access policies" list. Tenant-scoped CRUD, see
// app/api/routes/policies.py.
export const policiesApi = {
  list: () => api.get<Policy[]>("/policies"),
  create: (payload: PolicyCreatePayload) => api.post<Policy>("/policies", payload),
  update: (id: string, payload: PolicyUpdatePayload) => api.put<Policy>(`/policies/${id}`, payload),
  remove: (id: string) => api.del<void>(`/policies/${id}`),

  listMappings: () => api.get<PolicyMapping[]>("/policies/mappings"),
  createMapping: (payload: { user_id: string; policy_id: string }) => api.post<PolicyMapping>("/policies/mappings", payload),
  removeMapping: (id: string) => api.del<void>(`/policies/mappings/${id}`),
};
