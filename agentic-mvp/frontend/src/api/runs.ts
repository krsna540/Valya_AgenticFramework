import { api } from "./client";

// Backs "Waiting on a person" panels across all three apps and the
// approval card in the User workspace right panel. See
// backend/app/api/routes/runs.py.
export interface RunSummary {
  id: string;
  tenant_id: string | null;
  project_id: string | null;
  project_name: string | null;
  agent_id: string;
  agent_name: string | null;
  objective: string;
  status: string;
  phase: string;
  needs_human_review: boolean;
  final_answer: string | null;
  created_at: string | null;
}

export const runsApi = {
  list: (params?: { awaitingHuman?: boolean; projectId?: string; statusFilter?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.awaitingHuman) q.set("awaiting_human", "true");
    if (params?.projectId) q.set("project_id", params.projectId);
    if (params?.statusFilter) q.set("status_filter", params.statusFilter);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return api.get<RunSummary[]>(`/runs${qs ? `?${qs}` : ""}`);
  },
  get: (id: string) => api.get<RunSummary>(`/runs/${id}`),
  decide: (id: string, approved: boolean, note = "") => api.post<RunSummary>(`/runs/${id}/decision`, { approved, note }),
};
