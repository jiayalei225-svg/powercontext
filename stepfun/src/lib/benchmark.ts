import sampleCorpus from "../../data/sample-corpus.json";
import evalSet from "../../data/eval/queries.json";
import { api } from "./api";
import type { EmbeddingEngine, EngineInfo, InferenceBackend, ModelPrecision } from "./embedding/engine";
import { importDocuments } from "./ingest";
import { MODEL, compressionRatio } from "./model";
import type { IngestDocument, KnowledgeBase } from "./types";

export interface QualityMetrics {
  queries: number;
  recall5: number;
  ndcg5: number;
  mrr5: number;
  perQuery: Array<{ id: string; top: string[]; relevant: string[]; recall: number; ndcg: number; mrr: number }>;
}

export interface ModeQuality {
  hybrid: QualityMetrics;
  vector: QualityMetrics;
  fulltext: QualityMetrics;
}

export interface BatchResult {
  batchSize: number;
  texts: number;
  totalMs: number;
  textsPerSecond: number;
  runs: number;
}

export interface ConfigResult {
  id: string;
  label: string;
  backend: InferenceBackend;
  precision: ModelPrecision;
  engine: EngineInfo;
  modelBytes: number;
  compression: number;
  collection: { documents: number; chunks: number };
  ingestion: {
    chunkMs: number;
    embedMs: number;
    writeMs: number;
    refreshMs: number;
    roundTripMs: number;
    verified: boolean;
    chunks: number;
  };
  latency: {
    queryEmbedP50: number;
    queryEmbedP95: number;
    searchP50: number;
    searchP95: number;
    e2eP50: number;
    e2eP95: number;
  };
  quality: ModeQuality;
  batches: BatchResult[];
  skipped?: false;
}

export interface SkippedConfig {
  id: string;
  label: string;
  backend: InferenceBackend;
  precision: ModelPrecision;
  skipped: true;
  error: string;
}

export interface BenchmarkReport {
  schemaVersion: 1;
  createdAt: string;
  environment: {
    userAgent: string;
    hardwareConcurrency: number;
    deviceMemory: number | null;
    crossOriginIsolated: boolean;
    language: string;
    webgpu: boolean;
    gpuAdapter: string | null;
  };
  dataset: {
    documents: number;
    chunks: number;
    queries: number;
    source: string;
  };
  results: Array<ConfigResult | SkippedConfig>;
}

export type BenchmarkProgress = {
  phase: string;
  percent: number;
  message: string;
  config?: string;
};

const CONFIGS: Array<{ id: string; label: string; backend: InferenceBackend; precision: ModelPrecision }> = [
  { id: "fp32-wasm", label: "FP32 · WASM 基线", backend: "wasm", precision: "fp32" },
  { id: "q8-wasm", label: "INT8 · WASM", backend: "wasm", precision: "q8" },
  { id: "fp16-webgpu", label: "FP16 · WebGPU", backend: "webgpu", precision: "fp16" },
];

function percentile(values: number[], p: number) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1));
  return sorted[index];
}

function round(value: number, digits = 1) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function computeQuality(
  queryRuns: Array<{ id: string; relevant: string[]; top: string[] }>,
): QualityMetrics {
  const perQuery = queryRuns.map(({ id, relevant, top }) => {
    const top5 = top.slice(0, 5);
    const relevantSet = new Set(relevant);
    const hits = top5.filter((docId) => relevantSet.has(docId));
    const recall = relevant.length ? new Set(hits).size / relevant.length : 0;
    let dcg = 0;
    top5.forEach((docId, index) => {
      if (relevantSet.has(docId)) dcg += 1 / Math.log2(index + 2);
    });
    let idcg = 0;
    for (let i = 0; i < Math.min(5, relevant.length); i += 1) idcg += 1 / Math.log2(i + 2);
    const ndcg = idcg ? dcg / idcg : 0;
    const first = top5.findIndex((docId) => relevantSet.has(docId));
    const mrr = first >= 0 ? 1 / (first + 1) : 0;
    return { id, top: top5, relevant, recall, ndcg, mrr };
  });
  const count = perQuery.length || 1;
  return {
    queries: perQuery.length,
    recall5: perQuery.reduce((sum, item) => sum + item.recall, 0) / count,
    ndcg5: perQuery.reduce((sum, item) => sum + item.ndcg, 0) / count,
    mrr5: perQuery.reduce((sum, item) => sum + item.mrr, 0) / count,
    perQuery,
  };
}

async function probeEnvironment() {
  let webgpu = false;
  let gpuAdapter: string | null = null;
  try {
    const gpu = (navigator as any).gpu;
    if (gpu) {
      const adapter = await gpu.requestAdapter();
      if (adapter) {
        webgpu = true;
        const info = adapter.info ?? (await adapter.requestAdapterInfo?.()) ?? {};
        gpuAdapter = [info.vendor, info.architecture, info.device, info.description]
          .filter(Boolean)
          .join(" · ") || "WebGPU adapter";
      }
    }
  } catch {
    webgpu = false;
  }
  return {
    userAgent: navigator.userAgent,
    hardwareConcurrency: navigator.hardwareConcurrency || 0,
    deviceMemory: (navigator as any).deviceMemory ?? null,
    crossOriginIsolated: window.crossOriginIsolated,
    language: navigator.language,
    webgpu,
    gpuAdapter,
  };
}

export async function runBenchmark(options: {
  engine: EmbeddingEngine;
  onProgress: (progress: BenchmarkProgress) => void;
  includeBatchSweep?: boolean;
  includeModes?: boolean;
  keepCollections?: boolean;
}): Promise<BenchmarkReport> {
  const { engine, onProgress, includeBatchSweep = true, includeModes = true } = options;
  const documents = sampleCorpus.documents as IngestDocument[];
  const queries = evalSet.queries;
  const created: KnowledgeBase[] = [];
  const results: Array<ConfigResult | SkippedConfig> = [];
  let datasetChunks = 0;
  const original = engine.info;

  onProgress({ phase: "environment", percent: 1, message: "探测浏览器与 GPU 环境" });
  const environment = await probeEnvironment();

  try {
    for (let configIndex = 0; configIndex < CONFIGS.length; configIndex += 1) {
      const config = CONFIGS[configIndex];
      const basePercent = 5 + configIndex * (includeBatchSweep ? 28 : 38);
      onProgress({
        phase: "load",
        percent: basePercent,
        message: `加载 ${config.label} 模型`,
        config: config.id,
      });
      try {
        let info: EngineInfo;
        try {
          info = await engine.init({ backend: config.backend, precision: config.precision });
        } catch (error) {
          results.push({
            ...config,
            skipped: true,
            error: String((error as Error).message ?? error),
          });
          continue;
        }
        onProgress({
          phase: "ingest",
          percent: basePercent + 5,
          message: `${config.label} · 切分与本地向量化`,
          config: config.id,
        });
        const kb = await api.createKb({
          title: `评测 ${config.label} · ${new Date().toISOString().slice(11, 19)}`,
          description: "自动化性能与检索质量评测集合，完成后自动删除。",
        });
        created.push(kb.collection);
        const outcome = await importDocuments({
          documents,
          engine,
          kbId: kb.collection.id,
          batchSize: 16,
          onProgress: (progress) => {
            onProgress({
              phase: "ingest",
              percent: basePercent + 5 + progress.percent * 0.12,
              message: `${config.label} · ${progress.title} · ${progress.detail}`,
              config: config.id,
            });
          },
        });
        const detail = await api.getKb(kb.collection.id);
        datasetChunks = detail.collection.chunks;

        onProgress({
          phase: "quality",
          percent: basePercent + 18,
          message: `${config.label} · 运行 ${queries.length} 条查询与指标计算`,
          config: config.id,
        });
        const queryEmbedTimes: number[] = [];
        const searchTimes: number[] = [];
        const e2eTimes: number[] = [];
        const runsByMode: Record<"hybrid" | "vector" | "fulltext", Array<{ id: string; relevant: string[]; top: string[] }>> = {
          hybrid: [],
          vector: [],
          fulltext: [],
        };
        const modes: Array<"hybrid" | "vector" | "fulltext"> = includeModes
          ? ["hybrid", "vector", "fulltext"]
          : ["hybrid"];

        for (let qIndex = 0; qIndex < queries.length; qIndex += 1) {
          const query = queries[qIndex];
          const queryStart = performance.now();
          const embedStart = performance.now();
          const embedded = await engine.embed([query.query], 1, "query");
          const embedMs = performance.now() - embedStart;
          queryEmbedTimes.push(embedMs);
          const vector = embedded.vectors[0];
          for (const searchMode of modes) {
            const searchStart = performance.now();
            const response = await api.search(kb.collection.id, {
              query: query.query,
              embedding: vector,
              mode: searchMode,
              topK: 5,
            });
            const searchMs = performance.now() - searchStart;
            if (searchMode === "hybrid") {
              searchTimes.push(searchMs);
              e2eTimes.push(performance.now() - queryStart);
            }
            runsByMode[searchMode].push({
              id: query.id,
              relevant: query.relevant,
              top: response.results.map((hit) => hit.docId),
            });
          }
          onProgress({
            phase: "quality",
            percent: basePercent + 18 + ((qIndex + 1) / queries.length) * 8,
            message: `${config.label} · 查询 ${qIndex + 1}/${queries.length}`,
            config: config.id,
          });
        }

        const batches: BatchResult[] = [];
        if (includeBatchSweep) {
          onProgress({
            phase: "batch",
            percent: basePercent + 26,
            message: `${config.label} · batch size 吞吐扫描`,
            config: config.id,
          });
          const chunked = await engine.chunk(
            documents.map((doc) => ({ id: doc.id, title: doc.title, content: doc.content })),
          );
          const texts = chunked.documents
            .flatMap((doc) => doc.chunks.map((chunk) => chunk.text))
            .slice(0, 36);
          await engine.embed(texts.slice(0, 4), 4);
          for (const batchSize of [1, 8, 16, 32]) {
            const samples: number[] = [];
            for (let run = 0; run < 2; run += 1) {
              const started = performance.now();
              await engine.embed(texts, batchSize);
              samples.push(performance.now() - started);
            }
            samples.sort((a, b) => a - b);
            const median = samples[Math.floor(samples.length / 2)];
            batches.push({
              batchSize,
              texts: texts.length,
              totalMs: round(median, 1),
              textsPerSecond: round((texts.length / median) * 1000, 2),
              runs: samples.length,
            });
            onProgress({
              phase: "batch",
              percent: basePercent + 26 + (batches.length / 4) * 10,
              message: `${config.label} · batch ${batchSize} · ${round((texts.length / median) * 1000, 1)} texts/s`,
              config: config.id,
            });
          }
        }

        const quality: ModeQuality = {
          hybrid: computeQuality(runsByMode.hybrid),
          vector: computeQuality(runsByMode.vector),
          fulltext: computeQuality(runsByMode.fulltext),
        };
        results.push({
          id: config.id,
          label: config.label,
          backend: config.backend,
          precision: config.precision,
          engine: info,
          modelBytes: MODEL.sizes[config.precision],
          compression: round(compressionRatio(config.precision), 3),
          collection: {
            documents: detail.collection.documents,
            chunks: detail.collection.chunks,
          },
          ingestion: {
            chunkMs: outcome.timings.chunkMs,
            embedMs: outcome.timings.embedMs,
            writeMs: outcome.timings.writeMs,
            refreshMs: outcome.timings.refreshMs,
            roundTripMs: outcome.timings.roundTripMs,
            verified: outcome.verified,
            chunks: outcome.stats.chunks,
          },
          latency: {
            queryEmbedP50: round(percentile(queryEmbedTimes, 50)),
            queryEmbedP95: round(percentile(queryEmbedTimes, 95)),
            searchP50: round(percentile(searchTimes, 50)),
            searchP95: round(percentile(searchTimes, 95)),
            e2eP50: round(percentile(e2eTimes, 50)),
            e2eP95: round(percentile(e2eTimes, 95)),
          },
          quality,
          batches,
        });
        onProgress({
          phase: "config-done",
          percent: basePercent + 27,
          message: `${config.label} 完成`,
          config: config.id,
        });
      } catch (error) {
        results.push({
          ...config,
          skipped: true,
          error: String((error as Error).message ?? error),
        });
      }
    }
  } finally {
    if (!options.keepCollections) {
      for (const kb of created) {
        await api.deleteKb(kb.id).catch(() => {});
      }
    }
    try {
      if (original) {
        await engine.init({ backend: original.backend, precision: original.precision });
      } else {
        await engine.init({ backend: "auto", precision: "auto" });
      }
    } catch {
      // Benchmark output is still useful even if the runtime cannot be restored.
    }
  }

  onProgress({ phase: "done", percent: 100, message: "评测完成" });
  return {
    schemaVersion: 1,
    createdAt: new Date().toISOString(),
    environment,
    dataset: {
      documents: documents.length,
      chunks: datasetChunks,
      queries: queries.length,
      source: "data/sample-corpus.json + data/eval/queries.json",
    },
    results,
  };
}

export function reportToCsv(report: BenchmarkReport) {
  const header = [
    "config",
    "backend",
    "precision",
    "model_mib",
    "compression",
    "load_ms",
    "doc_embed_ms",
    "write_refresh_ms",
    "query_embed_p50",
    "query_embed_p95",
    "search_p50",
    "search_p95",
    "e2e_p50",
    "e2e_p95",
    "recall5",
    "ndcg5",
    "mrr5",
    "vector_recall5",
    "fulltext_recall5",
  ];
  const rows = report.results
    .filter((item): item is ConfigResult => !("skipped" in item))
    .map((item) => [
      item.label,
      item.backend,
      item.precision,
      (item.modelBytes / 1024 / 1024).toFixed(2),
      item.compression,
      item.engine.loadMs,
      item.ingestion.embedMs,
      item.ingestion.writeMs,
      item.latency.queryEmbedP50,
      item.latency.queryEmbedP95,
      item.latency.searchP50,
      item.latency.searchP95,
      item.latency.e2eP50,
      item.latency.e2eP95,
      item.quality.hybrid.recall5.toFixed(4),
      item.quality.hybrid.ndcg5.toFixed(4),
      item.quality.hybrid.mrr5.toFixed(4),
      item.quality.vector.recall5.toFixed(4),
      item.quality.fulltext.recall5.toFixed(4),
    ]);
  return [header, ...rows].map((row) => row.join(",")).join("\n");
}
