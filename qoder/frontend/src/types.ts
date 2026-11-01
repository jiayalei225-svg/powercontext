export interface PaperSummary {
  paper_id: string;
  title: string;
  year: number | null;
  venue: string;
  field: string;
  source: string;
  has_code: boolean;
  code_url: string | null;
  pages: number;
  chunks: number;
}

export interface ChunkDetail {
  chunk_id: string;
  text: string;
  page: number;
  seq: number;
}

export interface PaperDetail extends PaperSummary {
  chunk_details: ChunkDetail[];
  has_pdf: boolean;
}

export interface SearchHit {
  chunk_id: string;
  text: string;
  snippet: string;
  score: number | null;
  page: number;
  paper_id: string;
  title: string;
  year: number | null;
  venue: string;
  field: string;
  has_code: boolean;
  code_url: string | null;
  source: string;
}

export interface SearchFilters {
  year_from: number | null;
  year_to: number | null;
  venues: string[];
  field: string | null;
  paper_id: string | null;
  has_code: boolean | null;
}

export interface SearchResponse {
  query: string;
  terms: string[];
  literal: string | null;
  strategy: "hybrid" | "vector";
  results: SearchHit[];
  total: number;
  limit: number;
  filters: SearchFilters;
  applied: Record<string, unknown>;
  notes: string[];
  memory_connected: boolean;
  memory_error: string | null;
  elapsed_ms: number;
}

export interface SearchRequest {
  query: string;
  limit: number;
  year_from: number | null;
  year_to: number | null;
  venues: string[] | null;
  field: string | null;
  has_code: boolean | null;
  use_memory: boolean;
}

export interface IndexStats {
  collection: string;
  papers: number;
  chunks: number;
  embedding: string;
}

export interface Health {
  status: string;
  version: string;
  data_dir: string;
  index: IndexStats;
  memory: {
    connected: boolean;
    url: string;
    scope_id: string | null;
  };
}

export interface Preferences {
  year_from: number | null;
  venues: string[];
  only_with_code: boolean;
  field: string | null;
}

export interface SearchTrace {
  query: string;
  filters: Record<string, unknown>;
  hits: number;
  at: number;
  artifact?: string;
}

export interface MemorySnapshot {
  connected: boolean;
  scope_id: string | null;
  preferences: Preferences | Record<string, never>;
  searches: SearchTrace[];
  memories: Array<{
    artifact: string | null;
    revision: number | null;
    kind: string;
    state: string;
    saved_at: number;
    summary: string;
  }>;
  error?: string;
}
