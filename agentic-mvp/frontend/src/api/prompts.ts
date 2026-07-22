import { api } from "./client";
import type { Prompt, PromptMessage, PromptModelParams, PromptVariable } from "../types";

export interface PromptPayload {
  name: string;
  description?: string | null;
  is_active?: boolean;
  version?: string;
  status?: "Active" | "Experimental" | "Deprecated";
  label?: string;
  tags?: string[];
  messages: PromptMessage[];
  variables?: PromptVariable[];
  model_params?: PromptModelParams;
}

export const promptsApi = {
  list: () => api.get<Prompt[]>("/prompts"),
  create: (payload: PromptPayload) => api.post<Prompt>("/prompts", payload),
  update: (id: string, payload: Partial<PromptPayload>) => api.put<Prompt>(`/prompts/${id}`, payload),
  remove: (id: string) => api.del<void>(`/prompts/${id}`),
};
