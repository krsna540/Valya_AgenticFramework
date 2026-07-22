import { API_BASE_URL, ApiError, getToken } from "./client";
import type { UploadedFileMeta } from "../types";

const API_PREFIX = "/api/v1";

export async function uploadFile(file: File): Promise<UploadedFileMeta> {
  const form = new FormData();
  form.append("file", file);

  const token = getToken();
  const res = await fetch(`${API_BASE_URL}${API_PREFIX}/files/upload`, {
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

  return (await res.json()) as UploadedFileMeta;
}

export function fileContentUrl(fileId: string): string {
  const token = getToken();
  const url = `${API_BASE_URL}${API_PREFIX}/files/${fileId}/content`;
  return token ? `${url}?access_token=${encodeURIComponent(token)}` : url;
}
