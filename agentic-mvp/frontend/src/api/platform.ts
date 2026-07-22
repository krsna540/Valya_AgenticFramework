import { api } from "./client";
import type {
  AdminUser,
  AuditLogEntry,
  CostByTenant,
  PlatformHealth,
  PlatformOverview,
  Role,
  Tenant,
  TenantSummary,
  UsageDailyPoint,
} from "../types";

// Super-Admin-exclusive endpoints (backend: app/api/routes/platform.py,
// gated by authorize_tenant()/require_super_admin — see
// docs/AUTHORIZATION.md). Tenant lifecycle (create/read/update/delete/list)
// and cross-tenant user/role management live here, never under /admin/*
// which is scoped to the caller's own tenant.

export interface PlatformAdminCreatePayload {
  email: string;
  full_name: string;
  password: string;
}

export interface PlatformUserRoleUpdatePayload {
  role: Role;
  tenant_id?: string | null;
}

export const platformApi = {
  listTenants: () => api.get<TenantSummary[]>("/platform/tenants"),
  createTenant: (payload: { name: string }) => api.post<Tenant>("/platform/tenants", payload),
  getTenant: (id: string) => api.get<Tenant>(`/platform/tenants/${id}`),
  updateTenant: (id: string, payload: { name?: string; is_active?: boolean }) =>
    api.put<Tenant>(`/platform/tenants/${id}`, payload),
  deleteTenant: (id: string) => api.del<void>(`/platform/tenants/${id}`),

  createTenantAdmin: (tenantId: string, payload: PlatformAdminCreatePayload) =>
    api.post<AdminUser>(`/platform/tenants/${tenantId}/admins`, payload),

  listUsers: (params?: { tenantId?: string; role?: string }) => {
    const q = new URLSearchParams();
    if (params?.tenantId) q.set("tenant_id", params.tenantId);
    if (params?.role) q.set("role", params.role);
    const qs = q.toString();
    return api.get<AdminUser[]>(`/platform/users${qs ? `?${qs}` : ""}`);
  },
  updateUserRole: (userId: string, payload: PlatformUserRoleUpdatePayload) =>
    api.put<AdminUser>(`/platform/users/${userId}/role`, payload),

  overview: () => api.get<PlatformOverview>("/platform/overview"),
  usageDaily: (days = 14) => api.get<UsageDailyPoint[]>(`/platform/usage/daily?days=${days}`),
  costByTenant: () => api.get<CostByTenant>("/platform/cost-by-tenant"),
  health: () => api.get<PlatformHealth>("/platform/health"),
  audit: (params?: { tenantId?: string; action?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.tenantId) q.set("tenant_id", params.tenantId);
    if (params?.action) q.set("action", params.action);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return api.get<AuditLogEntry[]>(`/platform/audit${qs ? `?${qs}` : ""}`);
  },
};
