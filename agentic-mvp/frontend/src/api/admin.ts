import { api } from "./client";
import type { AdminUser, Tenant, TenantSettings } from "../types";

// Admins can only ever create plain "user" accounts through this endpoint —
// the backend's AdminUserCreate schema locks role to "user" at the Pydantic
// level. Promoting someone to admin/super_admin is a Super Admin action via
// /platform/users/{id}/role (see api/platform.ts).
export interface AdminUserCreatePayload {
  email: string;
  full_name: string;
  password: string;
}

// No `role` field: AdminUserUpdate no longer accepts one. Role changes are
// exclusively Super-Admin-only (see api/platform.ts).
export interface AdminUserUpdatePayload {
  full_name?: string;
  is_active?: boolean;
  password?: string;
}

export const adminUsersApi = {
  list: () => api.get<AdminUser[]>("/admin/users"),
  create: (payload: AdminUserCreatePayload) => api.post<AdminUser>("/admin/users", payload),
  update: (id: string, payload: AdminUserUpdatePayload) => api.put<AdminUser>(`/admin/users/${id}`, payload),
  remove: (id: string) => api.del<void>(`/admin/users/${id}`),
};

export const tenantApi = {
  me: () => api.get<Tenant>("/tenants/me"),
  update: (payload: { name?: string; is_active?: boolean; settings?: TenantSettings }) =>
    api.put<Tenant>("/tenants/me", payload),
};
