import { api } from "./client";

export interface PolicyRule {
  name: string;
  detail: string;
  bound: string;
}

export interface PolicyRevision {
  id: string;
  revision_number: number;
  summary: string;
  rules: PolicyRule[];
  tests_passed: number;
  is_current: boolean;
  published_by_name: string | null;
  created_at: string;
}

export const platformRulesApi = {
  current: () => api.get<PolicyRevision>("/platform/rules/current"),
  revisions: () => api.get<PolicyRevision[]>("/platform/rules/revisions"),
  publish: (summary: string, rules: PolicyRule[]) => api.post<PolicyRevision>("/platform/rules/publish", { summary, rules }),
  rollback: (revisionId: string) => api.post<PolicyRevision>(`/platform/rules/revisions/${revisionId}/rollback`),
};
