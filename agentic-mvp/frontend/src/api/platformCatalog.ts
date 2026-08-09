import { api } from "./client";

export interface CatalogItem {
  id: string;
  kind: "skill" | "prompt" | "tool" | "hook" | "plugin";
  name: string;
  description: string | null;
  version: string;
  status: string;
  forked_count: number;
  projects_in_use: number;
}

export const platformCatalogApi = {
  list: () => api.get<CatalogItem[]>("/platform/catalog"),
};
