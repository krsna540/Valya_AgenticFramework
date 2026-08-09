import { api } from "./client";

export interface ApprovalItem {
  id: string;
  title: string;
  detail: string;
  project_name: string | null;
  created_at: string | null;
}

export interface RecentItem {
  id: string;
  time: string | null;
  summary: string;
  context: string;
  status: string;
}

export interface AdminOverview {
  workspaces_active_7d: number;
  work_finished_7d: number;
  waiting_on_person: number;
  sources_connected: number;
  approvals: ApprovalItem[];
  recent: RecentItem[];
}

export const adminOverviewApi = {
  get: () => api.get<AdminOverview>("/admin/overview"),
};
