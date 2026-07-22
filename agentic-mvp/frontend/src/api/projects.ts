import { api } from "./client";
import type { Binding, ComponentType, ExecutionMode, Project, ProjectTopology } from "../types";

export interface ProjectPayload {
  name: string;
  description?: string | null;
  cost_center?: string | null;
  execution_mode?: ExecutionMode;
  schedule_cron?: string | null;
  is_active?: boolean;
}

export const projectsApi = {
  list: () => api.get<Project[]>("/projects"),
  create: (payload: ProjectPayload) => api.post<Project>("/projects", payload),
  get: (id: string) => api.get<Project>(`/projects/${id}`),
  update: (id: string, payload: Partial<ProjectPayload>) => api.put<Project>(`/projects/${id}`, payload),
  remove: (id: string) => api.del<void>(`/projects/${id}`),

  listUsers: (id: string) => api.get<string[]>(`/projects/${id}/users`),
  addUser: (id: string, userId: string) => api.post(`/projects/${id}/users`, { user_id: userId }),
  removeUser: (id: string, userId: string) => api.del<void>(`/projects/${id}/users/${userId}`),

  addDatasource: (id: string, datasourceId: string) => api.post(`/projects/${id}/datasources`, { datasource_id: datasourceId }),
  removeDatasource: (id: string, datasourceId: string) => api.del<void>(`/projects/${id}/datasources/${datasourceId}`),

  listBindings: (id: string) => api.get<Binding[]>(`/projects/${id}/bindings`),
  createBinding: (id: string, componentType: ComponentType, componentId: string, versionPinned?: string | null) =>
    api.post<Binding>(`/projects/${id}/bindings`, {
      component_type: componentType,
      component_id: componentId,
      version_pinned: versionPinned ?? null,
    }),
  removeBinding: (id: string, bindingId: string) => api.del<void>(`/projects/${id}/bindings/${bindingId}`),

  availableAgents: (id: string) => api.get<{ id: string; name: string; version: string }[]>(`/projects/${id}/available-agents`),

  topology: (id: string) => api.get<ProjectTopology>(`/projects/${id}/topology`),
  freeze: (id: string) => api.post<ProjectTopology>(`/projects/${id}/freeze`),
  unfreeze: (id: string) => api.post<Project>(`/projects/${id}/unfreeze`),
  deploy: (id: string) => api.post<Project>(`/projects/${id}/deploy`),
};
