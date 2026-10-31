/// <reference lib="webworker" />

import { AutoTokenizer, env, pipeline } from "@huggingface/transformers";

const MODEL_ID = "Xenova/bge-small-zh-v1.5";
const QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章：";
const MODEL_FILES: Record<string, string> = {
  fp32: "model.onnx",
  fp16: "model_fp16.onnx",
  q8: "model_quantized.onnx",
};
const MAX_TOKENS = 400;
const OVERLAP_TOKENS = 60;
const MAX_MODEL_TOKENS = 512;

type Backend = "webgpu" | "wasm";
type Precision = "fp32" | "fp16" | "q8";

type InitRequest = {
  type: "init";
  id: string;
  backend: "auto" | Backend;
  precision: "auto" | Precision;
};

type EmbedRequest = {
  type: "embed";
  id: string;
  texts: string[];
  batchSize: number;
  purpose?: "document" | "query";
};

type ChunkRequest = {
  type: "chunk";
  id: string;
  documents: Array<{ id: string; title: string; content: string }>;
  maxTokens?: number;
  overlap?: number;
};

type Request = InitRequest | EmbedRequest | ChunkRequest;

let tokenizer: any = null;
let extractor: any = null;
let engineInfo: Record<string, unknown> | null = null;
let loadedKey = "";
let onnxBytes = 0;
let lastProgressAt = 0;

function post(type: string, id: string | null, payload: unknown) {
  self.postMessage({ type, id, payload });
}

function reportProgress(payload: any, phase: string) {
  const now = performance.now();
  const status = payload?.status ?? "progress";
  if (status === "progress" && now - lastProgressAt < 120) return;
  lastProgressAt = now;
  if (payload?.total && payload.file?.endsWith?.(".onnx")) {
    onnxBytes = Math.max(onnxBytes, Number(payload.total) || 0);
  }
  post("progress", null, {
    phase,
    status,
    file: payload?.file ?? payload?.name ?? "",
    loaded: Number(payload?.loaded ?? 0),
    total: Number(payload?.total ?? 0),
    progress: Number(payload?.progress ?? 0),
  });
}

function configureEnvironment() {
  env.allowLocalModels = true;
  env.allowRemoteModels = false;
  env.localModelPath = "/models/";
  env.useBrowserCache = false;
  env.useWasmCache = true;
  env.cacheKey = "edge-atlas-transformers-v1";
  const onnxEnv: any = env.backends.onnx;
  if (onnxEnv?.wasm) {
    onnxEnv.wasm.wasmPaths = "/ort/";
    onnxEnv.wasm.numThreads = self.crossOriginIsolated
      ? Math.max(1, Math.min(4, navigator.hardwareConcurrency || 2))
      : 1;
    onnxEnv.wasm.simd = true;
    onnxEnv.wasm.proxy = false;
  }
}

async function probeWebGPU() {
  const gpu = (navigator as any).gpu;
  if (!gpu) {
    return {
      ok: false,
      reason: "浏览器未提供 navigator.gpu（WebGPU 不可用）",
      label: "WebGPU 不可用",
      adapter: null,
    };
  }
  try {
    const adapter = await gpu.requestAdapter({
      powerPreference: "high-performance",
    });
    if (!adapter) {
      return {
        ok: false,
        reason: "navigator.gpu 存在，但 requestAdapter() 返回空适配器",
        label: "无可用 GPU 适配器",
        adapter: null,
      };
    }
    let label = "WebGPU adapter";
    try {
      const info = adapter.info ?? (await adapter.requestAdapterInfo?.()) ?? {};
      const bits = [info.vendor, info.architecture, info.device, info.description]
        .filter(Boolean)
        .map(String);
      if (bits.length) label = bits.join(" · ");
    } catch {
      // adapter.info is not available in every Chromium build.
    }
    return { ok: true, reason: null, label, adapter };
  } catch (error) {
    return {
      ok: false,
      reason: `WebGPU 适配器初始化失败：${String((error as Error)?.message ?? error)}`,
      label: "WebGPU 初始化失败",
      adapter: null,
    };
  }
}

function getDtype(requested: string, backend: Backend) {
  if (requested !== "auto") return requested as Precision;
  return backend === "webgpu" ? "fp16" : "q8";
}

async function load(device: Backend, dtype: Precision) {
  configureEnvironment();
  tokenizer = null;
  extractor = null;
  onnxBytes = 0;
  const started = performance.now();
  const tokenizerStarted = performance.now();
  tokenizer = await AutoTokenizer.from_pretrained(MODEL_ID, {
    progress_callback: (p: any) => reportProgress(p, "tokenizer"),
  });
  const tokenizerMs = performance.now() - tokenizerStarted;
  const modelStarted = performance.now();
  extractor = await pipeline("feature-extraction", MODEL_ID, {
    device,
    dtype,
    progress_callback: (p: any) => reportProgress(p, "model"),
  });
  const modelMs = performance.now() - modelStarted;
  return {
    loadMs: Math.round(performance.now() - started),
    tokenizerMs: Math.round(tokenizerMs),
    modelMs: Math.round(modelMs),
    modelFile: MODEL_FILES[dtype],
    modelBytes: onnxBytes,
    dtype,
  };
}

async function init(request: InitRequest) {
  const probe = await probeWebGPU();
  const requestedBackend = request.backend;
  let backend: Backend =
    requestedBackend === "wasm" ? "wasm" : probe.ok ? "webgpu" : "wasm";
  let dtype = getDtype(request.precision, backend);
  let fallbackReason: string | null = null;
  let deviceLabel = backend === "webgpu" ? probe.label : "WebAssembly (CPU)";
  const key = `${requestedBackend}:${request.precision}`;
  if (engineInfo && loadedKey === key) {
    post("ready", request.id, engineInfo);
    return;
  }

  try {
    const loaded = await load(backend, dtype);
    engineInfo = {
      backend,
      precision: dtype,
      device: backend,
      deviceLabel,
      fallbackReason: requestedBackend === "auto" && backend === "wasm" ? probe.reason : null,
      ...loaded,
      requestedBackend,
      requestedPrecision: request.precision,
      crossOriginIsolated: self.crossOriginIsolated,
      threads: self.crossOriginIsolated
        ? Math.max(1, Math.min(4, navigator.hardwareConcurrency || 2))
        : 1,
    };
    loadedKey = key;
    post("ready", request.id, engineInfo);
    return;
  } catch (error) {
    if (requestedBackend !== "auto" || backend !== "webgpu") {
      throw error;
    }
    fallbackReason = `WebGPU 模型加载失败，已自动降级到 WASM：${
      String((error as Error)?.message ?? error)
    }`;
    backend = "wasm";
    dtype = getDtype(request.precision, backend);
    deviceLabel = "WebAssembly (CPU) · 自动降级";
    post("status", request.id, {
      message: "WebGPU 初始化失败，正在用 WASM 重新加载模型…",
      fallbackReason,
    });
    const loaded = await load(backend, dtype);
    engineInfo = {
      backend,
      precision: dtype,
      device: backend,
      deviceLabel,
      fallbackReason,
      ...loaded,
      requestedBackend,
      requestedPrecision: request.precision,
      crossOriginIsolated: self.crossOriginIsolated,
      threads: self.crossOriginIsolated
        ? Math.max(1, Math.min(4, navigator.hardwareConcurrency || 2))
        : 1,
    };
    loadedKey = key;
    post("ready", request.id, engineInfo);
  }
}

async function embed(request: EmbedRequest) {
  if (!extractor) throw new Error("模型尚未加载。");
  const purpose = request.purpose ?? "document";
  const texts = request.texts.map((text) => {
    const clean = String(text ?? "").trim();
    return purpose === "query" ? `${QUERY_INSTRUCTION}${clean}` : clean;
  });
  if (texts.some((text) => !text || text === QUERY_INSTRUCTION)) {
    throw new Error("不能对空文本生成向量。");
  }
  const batchSize = Math.max(1, Math.min(64, Number(request.batchSize) || 8));
  const started = performance.now();
  const vectors: number[][] = [];
  const batchTimes: number[] = [];
  for (let start = 0; start < texts.length; start += batchSize) {
    const batch = texts.slice(start, start + batchSize);
    const batchStarted = performance.now();
    const output = await extractor(batch, {
      pooling: "cls",
      normalize: true,
      truncation: true,
      max_length: MAX_MODEL_TOKENS,
    });
    const batchVectors = output.tolist() as number[][];
    vectors.push(...batchVectors);
    batchTimes.push(performance.now() - batchStarted);
    post("embed-progress", request.id, {
      processed: Math.min(texts.length, start + batch.length),
      total: texts.length,
      batchIndex: batchTimes.length,
      batchMs: Math.round(batchTimes[batchTimes.length - 1] * 10) / 10,
    });
  }
  const totalMs = performance.now() - started;
  post("embed-done", request.id, {
    vectors,
    timings: {
      totalMs: Math.round(totalMs * 10) / 10,
      batchTimes: batchTimes.map((ms) => Math.round(ms * 10) / 10),
      textsPerSecond: Math.round((texts.length / totalMs) * 10000) / 10,
    },
  });
}

function tokenCount(text: string): number {
  return tokenizer.encode(text, { add_special_tokens: false }).length;
}

interface TextUnit {
  text: string;
  start: number;
  tokens: number;
}

function splitUnits(content: string): TextUnit[] {
  // Split on sentence and clause delimiters, keeping the delimiter attached to
  // the preceding unit. Unlike tokenizer.decode(), slicing the original string
  // preserves every character (including Chinese characters that map to [UNK]
  // in a BERT WordPiece vocabulary).
  const units: TextUnit[] = [];
  const regex = /[^。！？!?；;，,、：:\n]+[。！？!?；;，,、：:\n]?/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(content)) !== null) {
    const raw = match[0];
    const leading = raw.length - raw.trimStart().length;
    const text = raw.trim();
    if (!text) continue;
    units.push({
      text,
      start: match.index + leading,
      tokens: tokenCount(text),
    });
  }
  if (units.length === 0 && content.trim()) {
    units.push({ text: content.trim(), start: 0, tokens: tokenCount(content.trim()) });
  }
  return units;
}

function splitOversizedUnit(unit: TextUnit, budget: number): [TextUnit, TextUnit] {
  const text = unit.text;
  let low = 1;
  let high = text.length;
  let best = 1;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    const candidate = text.slice(0, mid).trim();
    if (candidate && tokenCount(candidate) <= budget) {
      best = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  let cut = Math.max(1, Math.min(text.length - 1, best));
  // Do not split a surrogate pair.
  const code = text.charCodeAt(cut - 1);
  if (code >= 0xd800 && code <= 0xdbff) cut -= 1;
  const headText = text.slice(0, cut).trim();
  const tailRaw = text.slice(cut);
  const tailLeading = tailRaw.length - tailRaw.trimStart().length;
  const tailText = tailRaw.trim();
  return [
    { text: headText, start: unit.start, tokens: tokenCount(headText) },
    {
      text: tailText,
      start: unit.start + cut + tailLeading,
      tokens: tokenCount(tailText),
    },
  ];
}

function tokenChunks(
  content: string,
  maxTokens: number,
  overlap: number,
): Array<{ text: string; charStart: number }> {
  const normalized = content.replace(/\r\n/g, "\n").trim();
  if (!normalized) return [];
  const totalTokens = tokenCount(normalized);
  if (totalTokens <= maxTokens) {
    return [{ text: normalized, charStart: 0 }];
  }

  const units = splitUnits(normalized);
  const budget = Math.max(32, maxTokens - 6);
  const chunks: Array<{ text: string; charStart: number }> = [];
  let index = 0;
  let carry: TextUnit[] = [];
  let carryTokens = 0;

  const finalize = (parts: TextUnit[]) => {
    const text = parts.map((part) => part.text).join("").trim();
    if (!text) return;
    const last = chunks[chunks.length - 1];
    if (last && last.text === text) return;
    chunks.push({ text, charStart: parts[0]?.start ?? 0 });
  };

  while (index < units.length || carry.length > 0) {
    const parts: TextUnit[] = [];
    let tokens = 0;
    const startIndex = index;
    const initialCarryLength = carry.length;
    if (carry.length > 0 && index < units.length) {
      parts.push(...carry);
      tokens += carryTokens;
    }
    carry = [];
    carryTokens = 0;

    while (index < units.length) {
      const unit = units[index];
      if (unit.tokens > budget && parts.length === 0) {
        const [head, tail] = splitOversizedUnit(unit, budget);
        parts.push(head);
        tokens += head.tokens;
        units[index] = tail;
        break;
      }
      if (tokens + unit.tokens > budget) {
        break;
      }
      parts.push(unit);
      tokens += unit.tokens;
      index += 1;
    }

    if (parts.length === 0) break;
    // The overlap alone filled the budget and no new text was consumed. Drop
    // the overlap so the loop always makes forward progress.
    if (index === startIndex && parts.length === initialCarryLength) {
      continue;
    }
    finalize(parts);

    // Build a small tail for the next chunk from the last units of this chunk.
    if (index < units.length && overlap > 0 && units[index]?.tokens <= budget) {
      let tailTokens = 0;
      for (let i = parts.length - 1; i >= 0; i -= 1) {
        const unit = parts[i];
        if (tailTokens + unit.tokens > overlap) break;
        carry.unshift(unit);
        tailTokens += unit.tokens;
      }
      // Avoid carrying the entire chunk forward, which would create a loop.
      if (carry.length === parts.length) {
        carry = [];
        tailTokens = 0;
      }
      carryTokens = tailTokens;
    }
  }

  return chunks;
}

async function chunkDocuments(request: ChunkRequest) {
  if (!tokenizer) throw new Error("Tokenizer 尚未加载。");
  const maxTokens = Math.max(64, Math.min(240, request.maxTokens ?? MAX_TOKENS));
  const overlap = Math.max(0, Math.min(maxTokens - 1, request.overlap ?? OVERLAP_TOKENS));
  const docs = [];
  for (let i = 0; i < request.documents.length; i += 1) {
    const doc = request.documents[i];
    const content = String(doc.content ?? "").replace(/\r\n/g, "\n").trim();
    const chunks = tokenChunks(content, maxTokens, overlap).map((chunk, index) => ({
      ...chunk,
      index,
    }));
    docs.push({ id: doc.id, title: doc.title, chunks });
    post("chunk-progress", request.id, {
      processed: i + 1,
      total: request.documents.length,
      docId: doc.id,
      chunks: chunks.length,
    });
  }
  post("chunk-done", request.id, { documents: docs, maxTokens, overlap });
}

configureEnvironment();

self.onmessage = async (event: MessageEvent<Request>) => {
  const request = event.data;
  const id = request?.id ?? null;
  try {
    if (request.type === "init") await init(request);
    else if (request.type === "embed") await embed(request);
    else if (request.type === "chunk") await chunkDocuments(request);
    else throw new Error(`未知 worker 请求：${(request as any)?.type}`);
  } catch (error) {
    console.error("[embedding-worker]", error);
    post("error", id, {
      message: String((error as Error)?.message ?? error),
      stack: (error as Error)?.stack ?? null,
    });
  }
};

export {};
