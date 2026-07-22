import { API_BASE_URL, ApiError, api, getToken } from "./client";
import type { Skill } from "../types";

const API_PREFIX = "/api/v1";

async function uploadSkill(file: File): Promise<Skill> {
  const form = new FormData();
  form.append("file", file);

  const token = getToken();
  const res = await fetch(`${API_BASE_URL}${API_PREFIX}/skills/upload`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ? JSON.stringify(body.detail) : detail;
    } catch {
      // ignore
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as Skill;
}

async function getSkillMd(id: string): Promise<string> {
  const token = getToken();
  const res = await fetch(`${API_BASE_URL}${API_PREFIX}/skills/${id}/skill-md`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) throw new ApiError(res.status, "Failed to load SKILL.md");
  return res.text();
}

async function getSkillJson(id: string): Promise<string> {
  const token = getToken();
  const res = await fetch(`${API_BASE_URL}${API_PREFIX}/skills/${id}/skill-json`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) throw new ApiError(res.status, "Failed to load skill.json");
  return res.text();
}

async function getFileContent(id: string, path: string): Promise<string> {
  const token = getToken();
  const res = await fetch(`${API_BASE_URL}${API_PREFIX}/skills/${id}/files/${encodeURI(path)}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) throw new ApiError(res.status, "Failed to load file");
  return res.text();
}

function downloadUrl(id: string): string {
  const token = getToken();
  const url = `${API_BASE_URL}${API_PREFIX}/skills/${id}/download`;
  return token ? `${url}?access_token=${encodeURIComponent(token)}` : url;
}

export const skillsApi = {
  list: () => api.get<Skill[]>("/skills"),
  get: (id: string) => api.get<Skill>(`/skills/${id}`),
  upload: uploadSkill,
  getSkillMd,
  getSkillJson,
  getFileContent,
  downloadUrl,
  listFiles: (id: string) => api.get<string[]>(`/skills/${id}/files`),
  updateActive: (id: string, is_active: boolean) => api.put<Skill>(`/skills/${id}`, { is_active }),
  remove: (id: string) => api.del<void>(`/skills/${id}`),
};
