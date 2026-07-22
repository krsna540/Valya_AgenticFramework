import { api } from "./client";
import type { Tool, ToolAnnotations } from "../types";

export interface ToolPayload {
  name: string;
  description?: string | null;
  is_active?: boolean;
  config?: Record<string, unknown>;
  version?: string;
  status?: "Active" | "Experimental" | "Deprecated";
  tool_type?: "function" | "mcp";
  mcp_transport?: "sse" | "stdio" | null;
  mcp_endpoint?: string | null;
  mcp_command?: string | null;
  mcp_tool_name?: string | null;
  input_schema?: Record<string, unknown> | null;
  permissions?: string[];
  rate_limit_per_min?: number;
  timeout_s?: number;
  tags?: string[];
  annotations?: ToolAnnotations;
}

export const toolsApi = {
  list: () => api.get<Tool[]>("/tools"),
  create: (payload: ToolPayload) => api.post<Tool>("/tools", payload),
  update: (id: string, payload: Partial<ToolPayload>) => api.put<Tool>(`/tools/${id}`, payload),
  remove: (id: string) => api.del<void>(`/tools/${id}`),
};
