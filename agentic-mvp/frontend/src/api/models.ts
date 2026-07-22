import { api } from "./client";
import type { ModelInfo } from "../types";

export const modelsApi = {
  list: () => api.get<ModelInfo[]>("/models"),
};
