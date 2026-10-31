export interface EmbeddingMeta {
  model: string;
  revision: string;
  dimension: number;
  distance: string;
}

export interface KnowledgeBase {
  id: string;
  title: string;
  description: string;
  createdAt: number;
  updatedAt: number;
  lastImportAt: number | null;
  documents: number;
  chunks: number;
  precision?: "fp32" | "fp16" | "q8" | null;
  embedding: EmbeddingMeta;
  isDefault: boolean;
  index?: {
    vector: string;
    fulltext: string;
    mixed: string;
  };
}

export interface KbDocument {
  docId: string;
  title: string;
  category: string;
  source: string;
  importedAt: number;
  chunks: number;
  chars: number;
  preview: string;
  precision: string;
}

export interface SearchHit {
  chunkId: string;
  docId: string;
  title: string;
  category: string;
  source: string;
  text: string;
  chunkIndex: number;
  chunkCount: number;
  score: number;
  scoreKind: "rrf" | "cosine" | "fulltext";
  otherChunks: number;
}

export interface SearchResponse {
  mode: "hybrid" | "vector" | "fulltext";
  engine: string;
  query: string;
  topK: number;
  results: SearchHit[];
  rawChunks: number;
  dedupedDocuments: number;
  timings: { seekdbMs: number };
  index: { vector: string; fulltext: string; fusion: string | null };
  embedding: { model: string; revision: string; dimension: number };
}

export interface HealthResponse {
  ok: boolean;
  time: string;
  service: string;
  version: string;
  seekdb: {
    connected: boolean;
    database: string;
    host: string;
    port: number;
    lastError: string | null;
    mode: string;
  };
  embedding: EmbeddingMeta;
  runtime: {
    inference: string;
    cloudInference: boolean;
    expectedBackends: string[];
  };
}

export interface IngestChunk {
  text: string;
  embedding: number[];
  charStart: number;
}

export interface IngestDocument {
  id: string;
  title: string;
  category?: string;
  source?: string;
  content: string;
}

export interface ImportResult {
  docId: string;
  title: string;
  chunks: number;
  isReplace: boolean;
  verified: boolean;
  retried: boolean;
  timings: { writeMs: number; verifyMs: number };
  stats: { documents: number; chunks: number };
}

export interface SampleCorpus {
  version: number;
  name: string;
  description: string;
  documents: IngestDocument[];
}
