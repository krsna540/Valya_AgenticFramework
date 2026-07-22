import { api } from "./client";
import type { Persona, PersonaTraits, UserPersonaMapping } from "../types";

export interface PersonaPayload {
  name: string;
  description?: string | null;
  archetype?: string | null;
  base_model?: string | null;
  traits?: PersonaTraits;
  is_active?: boolean;
}

export const personasApi = {
  list: () => api.get<Persona[]>("/personas"),
  create: (payload: PersonaPayload) => api.post<Persona>("/personas", payload),
  update: (id: string, payload: Partial<PersonaPayload>) => api.put<Persona>(`/personas/${id}`, payload),
  remove: (id: string) => api.del<void>(`/personas/${id}`),

  listMyMappings: () => api.get<UserPersonaMapping[]>("/personas/mappings/me"),
  listAllMappings: () => api.get<UserPersonaMapping[]>("/personas/mappings"),
  createMapping: (payload: { user_id: string; persona_id: string; project_id?: string | null; is_default?: boolean }) =>
    api.post<UserPersonaMapping>("/personas/mappings", payload),
  removeMapping: (id: string) => api.del<void>(`/personas/mappings/${id}`),
};
