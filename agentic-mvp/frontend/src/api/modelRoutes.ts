import { api } from "./client";
import type { ModelKind, ModelRoute, ModelStatus } from "../types";

export interface ModelRouteCreatePayload {
  name: string;
  provider: string;
  route: string;
  kind?: ModelKind;
  input_cost_per_1m?: number;
  output_cost_per_1m?: number | null;
  status?: ModelStatus;
  gateway_configured?: boolean;
  cost_meter_registered?: boolean;
  eval_faithfulness_threshold?: number;
  eval_task_completion_threshold?: number;
}

export interface ModelRouteUpdatePayload {
  provider?: string;
  route?: string;
  input_cost_per_1m?: number;
  output_cost_per_1m?: number | null;
  status?: ModelStatus;
  gateway_configured?: boolean;
  cost_meter_registered?: boolean;
  eval_faithfulness?: number;
  eval_task_completion?: number;
  eval_security_redteam_passed?: boolean;
  is_active?: boolean;
}

// Super Admin catalog CRUD lives at /platform/model-routes; the read-only
// "/available" (live-only) endpoint backs the Admin Expertise tab's model
// routing selects — see app/api/routes/platform.py.
export const modelRoutesApi = {
  list: () => api.get<ModelRoute[]>("/platform/model-routes"),
  listAvailable: () => api.get<ModelRoute[]>("/platform/model-routes/available"),
  create: (payload: ModelRouteCreatePayload) => api.post<ModelRoute>("/platform/model-routes", payload),
  update: (id: string, payload: ModelRouteUpdatePayload) => api.put<ModelRoute>(`/platform/model-routes/${id}`, payload),
  remove: (id: string) => api.del<void>(`/platform/model-routes/${id}`),
};
