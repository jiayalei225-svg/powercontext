import type {
  HealthResponse,
  ImportResult,
  IngestChunk,
  KbDocument,
  KnowledgeBase,
  SearchResponse,
} from "./types";

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  const text = await response.text();
  let payload: any = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const message =
      payload?.error ??
      (response.status === 503
        ? "seekdb 尚未就绪，请检查本地数据库。"
        : `请求失败（HTTP ${response.status}）`);
    throw new ApiError(message, response.status, payload?.code);
  }
  return payload as T;
}

export interface ImportBatchResult {
  documents: Array<{
    docId: string;
    title: string;
    chunks: number;
    isReplace: boolean;
  }>;
  verified: boolean;
  retried: boolean;
  timings: { writeMs: number; verifyMs: number };
  stats: { documents: number; chunks: number };
}

export interface PreparedDocument {
  document: {
    id: string;
    title: string;
    category?: string;
    source?: string;
  };
  chunks: IngestChunk[];
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  meta: () =>
    request<{
      embedding: { model: string; revision: string; dimension: number };
      defaultCollectionTitle: string;
    }>("/api/meta"),
  listKbs: () =>
    request<{ collections: KnowledgeBase[]; defaultId: string | null }>("/api/kbs"),
  getKb: (id: string) =>
    request<{ collection: KnowledgeBase; documents: KbDocument[] }>(
      `/api/kbs/${encodeURIComponent(id)}`,
    ),
  createKb: (body: { title: string; description?: string }) =>
    request<{ collection: KnowledgeBase }>("/api/kbs", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteKb: (id: string) =>
    request<{ ok: true }>(`/api/kbs/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  importDocuments: (
    id: string,
    body: {
      documents: Array<{
        document: {
          id: string;
          title: string;
          category?: string;
          source?: string;
        };
        chunks: IngestChunk[];
        model: { precision: string; model: string; revision: string };
      }>;
      model: { precision: string; model: string; revision: string };
    },
  ) =>
    request<ImportBatchResult>(`/api/kbs/${encodeURIComponent(id)}/import`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  ingest: (
    id: string,
    body: {
      document: {
        id: string;
        title: string;
        category?: string;
        source?: string;
      };
      chunks: IngestChunk[];
      model: { precision: string; model: string; revision: string };
    },
  ) =>
    request<ImportResult>(`/api/kbs/${encodeURIComponent(id)}/documents`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteDocument: (id: string, docId: string) =>
    request<{ ok: boolean }>(
      `/api/kbs/${encodeURIComponent(id)}/documents/${encodeURIComponent(docId)}`,
      { method: "DELETE" },
    ),
  search: (
    id: string,
    body: {
      query: string;
      embedding: number[];
      mode: "hybrid" | "vector" | "fulltext";
      topK: number;
    },
  ) =>
    request<SearchResponse>(`/api/kbs/${encodeURIComponent(id)}/search`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
