import type {
  Health,
  MemorySnapshot,
  PaperDetail,
  PaperSummary,
  Preferences,
  SearchRequest,
  SearchResponse,
  SearchTrace,
} from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) detail = payload.detail;
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/api/health"),
  papers: () => request<{ papers: PaperSummary[]; total: number }>("/api/papers"),
  paper: (id: string) => request<PaperDetail>(`/api/papers/${id}`),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ duplicate: boolean; added: number; paper: PaperSummary }>("/api/papers", {
      method: "POST",
      body: form,
    });
  },
  remove: (id: string) =>
    request<{ removed: boolean }>(`/api/papers/${id}`, { method: "DELETE" }),
  search: (body: SearchRequest) =>
    request<SearchResponse>("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  history: () =>
    request<{ connected: boolean; searches: SearchTrace[]; error?: string }>("/api/history"),
  preferences: () =>
    request<{ connected: boolean; preferences: Preferences | Record<string, never>; error?: string }>(
      "/api/preferences",
    ),
  savePreferences: (prefs: Preferences) =>
    request<{ connected: boolean; preferences: Preferences; artifact: string; revision: number }>(
      "/api/preferences",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(prefs),
      },
    ),
  memory: () => request<MemorySnapshot>("/api/memory"),
  exportReport: async (format: "md" | "csv", body: Omit<SearchRequest, "use_memory">) => {
    const path = format === "md" ? "/api/search/export" : "/api/search/export.csv";
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`导出失败：${response.status}`);
    return response.blob();
  },
};

export function download(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
