import { api } from "./client";
import type {
  Agent,
  HandlerType,
  Hook,
  HookHandlerInfo,
  LifecycleEvent,
  LifecycleEventInfo,
  RegistryItem,
} from "../types";

export interface RegistryPayload {
  name: string;
  description?: string | null;
  is_active?: boolean;
  config?: Record<string, unknown>;
  version?: string;
  status?: "Active" | "Experimental" | "Deprecated";
}

export interface HookPayload {
  name: string;
  description?: string | null;
  is_active?: boolean;
  config?: Record<string, unknown>;
  scope: "global" | "agent";
  lifecycle_event: LifecycleEvent;
  handler_type: HandlerType;
  handler_key?: string | null;
  handler_config?: Record<string, unknown>;
  execution_policy?: Record<string, unknown>;
  version?: string;
  status?: "Active" | "Experimental" | "Deprecated";
  tags?: string[];
  author?: string | null;
}

export interface AgentPayload {
  name: string;
  description?: string | null;
  is_active?: boolean;
  system_prompt?: string | null;
  model_name?: string;
  version?: string;
  status?: "Active" | "Experimental" | "Deprecated";
  skill_ids?: string[];
  tool_ids?: string[];
  plugin_ids?: string[];
  hook_ids?: string[];
}

function makeRegistryApi(endpoint: string) {
  return {
    list: () => api.get<RegistryItem[]>(`/${endpoint}`),
    create: (payload: RegistryPayload) => api.post<RegistryItem>(`/${endpoint}`, payload),
    update: (id: string, payload: Partial<RegistryPayload>) =>
      api.put<RegistryItem>(`/${endpoint}/${id}`, payload),
    remove: (id: string) => api.del<void>(`/${endpoint}/${id}`),
  };
}

export const pluginsApi = makeRegistryApi("plugins");

export const hooksApi = {
  list: () => api.get<Hook[]>("/hooks"),
  listHandlers: () => api.get<HookHandlerInfo[]>("/hooks/handlers"),
  listLifecycleEvents: () => api.get<LifecycleEventInfo[]>("/hooks/lifecycle-events"),
  create: (payload: HookPayload) => api.post<Hook>("/hooks", payload),
  update: (id: string, payload: Partial<HookPayload>) => api.put<Hook>(`/hooks/${id}`, payload),
  remove: (id: string) => api.del<void>(`/hooks/${id}`),
};

// Skills now live in api/skills.ts (the folder-format upload/browse API) —
// this module used to also export a handler_key-bound skillsApi, retired
// along with that catalog. See docs/SKILL_STANDARD.md.

export const agentsApi = {
  list: () => api.get<Agent[]>("/agents"),
  create: (payload: AgentPayload) => api.post<Agent>("/agents", payload),
  update: (id: string, payload: Partial<AgentPayload>) => api.put<Agent>(`/agents/${id}`, payload),
  remove: (id: string) => api.del<void>(`/agents/${id}`),
};
