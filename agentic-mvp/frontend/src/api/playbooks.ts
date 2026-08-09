import { api } from "./client";

export interface Playbook {
  id: string;
  tenant_id: string | null;
  name: string;
  description: string | null;
  is_active: boolean;
  version: string;
  status: string;
  when_to_use: string;
  canonical_steps: { title: string; detail: string }[];
  required_criteria: string[];
  known_assumptions: { assumption: string; evidence_note: string }[];
  supporting_stats: Record<string, unknown>;
  access_class: string;
  visibility: string;
  forked_from_id: string | null;
  owner_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export const playbooksApi = {
  list: () => api.get<Playbook[]>("/playbooks"),
  fork: (id: string) => api.post<Playbook>(`/playbooks/${id}/fork`),
};
