import { api } from "./client";

// Mirrors app/schemas/playbook.py. Two field groups: the §11.5 procedural
// memory the Planner reads (when_to_use / canonical_steps /
// required_criteria / known_assumptions / supporting_stats) and the seven
// authoring components a human writes (objective through few_shot_examples).

export interface PlaybookStep {
  title: string;
  detail: string;
  /** Set together with else_detail to make the step conditional:
   *  IF condition THEN detail ELSE else_detail. Both null = plain step. */
  condition?: string | null;
  else_detail?: string | null;
}

export interface PlaybookAssumption {
  assumption: string;
  evidence_note: string;
}

export interface PlaybookOutOfScope {
  topic: string;
  handoff_to: string;
}

export type PlaybookInputKind = "datasource" | "tool" | "skill" | "data_property";

export interface PlaybookInput {
  name: string;
  kind: PlaybookInputKind;
  description: string;
  ref_id?: string | null;
}

export interface PlaybookGuardrail {
  rule: string;
  severity: "block" | "warn";
}

export interface PlaybookApprovalGate {
  name: string;
  condition: string;
  approver: string;
  threshold: string;
}

export interface PlaybookExchange {
  role: "user" | "agent";
  content: string;
  internal_note: string;
}

export interface PlaybookExample {
  title: string;
  exchanges: PlaybookExchange[];
}

export interface Playbook {
  id: string;
  tenant_id: string | null;
  name: string;
  description: string | null;
  is_active: boolean;
  version: string;
  status: string;

  when_to_use: string;
  canonical_steps: PlaybookStep[];
  required_criteria: string[];
  known_assumptions: PlaybookAssumption[];
  supporting_stats: Record<string, unknown>;

  objective: string;
  target_persona: string;
  out_of_scope: PlaybookOutOfScope[];
  inputs: PlaybookInput[];
  guardrails: PlaybookGuardrail[];
  approval_gates: PlaybookApprovalGate[];
  few_shot_examples: PlaybookExample[];

  access_class: string;
  visibility: string;
  forked_from_id: string | null;
  owner_user_id: string | null;
  created_at: string;
  updated_at: string;
}

/** POST body. `required_criteria` must be non-empty — the backend rejects an
 *  empty rubric (Frozen Spec invariant I6 applied to playbooks). */
export interface PlaybookCreatePayload {
  name: string;
  description?: string | null;
  is_active?: boolean;
  version?: string;
  status?: string;
  when_to_use: string;
  canonical_steps?: PlaybookStep[];
  required_criteria: string[];
  known_assumptions?: PlaybookAssumption[];
  objective?: string;
  target_persona?: string;
  out_of_scope?: PlaybookOutOfScope[];
  inputs?: PlaybookInput[];
  guardrails?: PlaybookGuardrail[];
  approval_gates?: PlaybookApprovalGate[];
  few_shot_examples?: PlaybookExample[];
}

export type PlaybookUpdatePayload = Partial<PlaybookCreatePayload>;

export const playbooksApi = {
  list: () => api.get<Playbook[]>("/playbooks"),
  get: (id: string) => api.get<Playbook>(`/playbooks/${id}`),
  create: (payload: PlaybookCreatePayload) => api.post<Playbook>("/playbooks", payload),
  update: (id: string, payload: PlaybookUpdatePayload) => api.put<Playbook>(`/playbooks/${id}`, payload),
  remove: (id: string) => api.del<void>(`/playbooks/${id}`),
  fork: (id: string) => api.post<Playbook>(`/playbooks/${id}/fork`),
};
