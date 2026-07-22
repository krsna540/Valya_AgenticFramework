import { api } from "./client";
import type { AuthType, ConnectorType, ConnectorTypeInfo, Datasource, SecurityTier, SyncMode } from "../types";

export interface DatasourcePayload {
  name: string;
  description?: string | null;
  connector_type: ConnectorType;
  connection_config?: Record<string, unknown>;
  auth_config?: Record<string, unknown>;
  auth_type?: AuthType;
  security_classification?: SecurityTier;
  chunking_policy?: Record<string, unknown>;
  embedding_policy?: Record<string, unknown>;
  sync_mode?: SyncMode;
  sync_schedule_cron?: string | null;
  is_active?: boolean;
}

export const datasourcesApi = {
  list: () => api.get<Datasource[]>("/datasources"),
  listConnectorTypes: () => api.get<ConnectorTypeInfo[]>("/datasources/connector-types"),
  create: (payload: DatasourcePayload) => api.post<Datasource>("/datasources", payload),
  update: (id: string, payload: Partial<DatasourcePayload>) => api.put<Datasource>(`/datasources/${id}`, payload),
  remove: (id: string) => api.del<void>(`/datasources/${id}`),
  connect: (id: string) => api.post<Datasource>(`/datasources/${id}/connect`),
  sync: (id: string) => api.post<Datasource>(`/datasources/${id}/sync`),
};
