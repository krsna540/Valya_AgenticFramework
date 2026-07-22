import { api } from "./client";
import type { Plugin } from "../types";

export interface PluginPayload {
  name: string;
  description?: string | null;
  is_active?: boolean;
  config?: Record<string, unknown>;
  version?: string;
  status?: "Active" | "Experimental" | "Deprecated";
  exports_skills?: string[];
  exports_hooks?: string[];
  exports_tools?: string[];
  exports_commands?: string[];
  requires_permissions?: string[];
  requires_env?: string[];
}

export const pluginsApi = {
  list: () => api.get<Plugin[]>("/plugins"),
  create: (payload: PluginPayload) => api.post<Plugin>("/plugins", payload),
  update: (id: string, payload: Partial<PluginPayload>) => api.put<Plugin>(`/plugins/${id}`, payload),
  remove: (id: string) => api.del<void>(`/plugins/${id}`),
};
