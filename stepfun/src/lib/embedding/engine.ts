export type InferenceBackend = "webgpu" | "wasm";
export type ModelPrecision = "fp32" | "fp16" | "q8";
export type BackendPreference = "auto" | InferenceBackend;
export type PrecisionPreference = "auto" | ModelPrecision;

export interface EngineInfo {
  backend: InferenceBackend;
  precision: ModelPrecision;
  dtype: ModelPrecision;
  device: string;
  deviceLabel: string;
  fallbackReason: string | null;
  requestedBackend: BackendPreference;
  requestedPrecision: PrecisionPreference;
  loadMs: number;
  tokenizerMs: number;
  modelMs: number;
  modelFile: string;
  modelBytes: number;
  crossOriginIsolated: boolean;
  threads: number;
}

export interface LoadProgress {
  phase: "tokenizer" | "model" | "status";
  status: string;
  file: string;
  loaded: number;
  total: number;
  progress: number;
  message?: string;
}

export interface EmbedProgress {
  processed: number;
  total: number;
  batchIndex: number;
  batchMs: number;
}

interface WorkerMessage {
  type: string;
  id: string | null;
  payload: any;
}

type Listener<T> = (value: T) => void;

const INIT_TIMEOUT = 240_000;
const EMBED_TIMEOUT = 300_000;
const CHUNK_TIMEOUT = 120_000;

export class EmbeddingEngine {
  private worker: Worker | null = null;
  private counter = 0;
  private pending = new Map<
    string,
    {
      resolve: (value: any) => void;
      reject: (error: Error) => void;
      timer: ReturnType<typeof setTimeout>;
    }
  >();
  private loadProgress = new Set<Listener<LoadProgress>>();
  private embedProgress = new Set<Listener<EmbedProgress>>();
  private chunkProgress = new Set<Listener<{ processed: number; total: number; docId: string; chunks: number }>>();
  private statusListeners = new Set<Listener<{ message: string }>>();

  get isReady() {
    return Boolean(this.info);
  }

  info: EngineInfo | null = null;

  onLoadProgress(listener: Listener<LoadProgress>) {
    this.loadProgress.add(listener);
    return () => this.loadProgress.delete(listener);
  }

  onEmbedProgress(listener: Listener<EmbedProgress>) {
    this.embedProgress.add(listener);
    return () => this.embedProgress.delete(listener);
  }

  onChunkProgress(
    listener: Listener<{ processed: number; total: number; docId: string; chunks: number }>,
  ) {
    this.chunkProgress.add(listener);
    return () => this.chunkProgress.delete(listener);
  }

  onStatus(listener: Listener<{ message: string }>) {
    this.statusListeners.add(listener);
    return () => this.statusListeners.delete(listener);
  }

  private emitLoad(progress: LoadProgress) {
    for (const listener of this.loadProgress) listener(progress);
  }

  private createWorker() {
    const worker = new Worker(new URL("./embedding.worker.ts", import.meta.url), {
      type: "module",
      name: "edge-atlas-embedding",
    });
    worker.onmessage = (event: MessageEvent<WorkerMessage>) => {
      const { type, id, payload } = event.data ?? {};
      if (type === "progress") {
        this.emitLoad(payload as LoadProgress);
        return;
      }
      if (type === "status") {
        if (payload?.message) {
          for (const listener of this.statusListeners) listener(payload);
          this.emitLoad({
            phase: "status",
            status: "status",
            file: "",
            loaded: 0,
            total: 0,
            progress: 0,
            message: payload.message,
          });
        }
        return;
      }
      if (type === "embed-progress") {
        for (const listener of this.embedProgress) listener(payload as EmbedProgress);
        return;
      }
      if (type === "chunk-progress") {
        for (const listener of this.chunkProgress) listener(payload);
        return;
      }
      if (type === "error") {
        if (id) this.settleError(id, new Error(payload?.message ?? "推理 worker 错误"));
        else this.emitLoad({ ...emptyProgress(), message: payload?.message ?? "推理 worker 错误" });
        return;
      }
      if (type === "ready" || type === "embed-done" || type === "chunk-done") {
        if (id) this.settle(id, payload);
      }
    };
    worker.onerror = (event) => {
      const message = event.message || "推理 worker 无法启动";
      for (const [id, entry] of this.pending) {
        clearTimeout(entry.timer);
        entry.reject(new Error(message));
        this.pending.delete(id);
      }
    };
    return worker;
  }

  private settle(id: string, value: any) {
    const entry = this.pending.get(id);
    if (!entry) return;
    clearTimeout(entry.timer);
    this.pending.delete(id);
    entry.resolve(value);
  }

  private settleError(id: string, error: Error) {
    const entry = this.pending.get(id);
    if (!entry) return;
    clearTimeout(entry.timer);
    this.pending.delete(id);
    entry.reject(error);
  }

  private request<T>(
    type: "init" | "embed" | "chunk",
    payload: Record<string, unknown>,
    timeoutMs: number,
  ): Promise<T> {
    if (!this.worker) throw new Error("推理 worker 尚未创建。");
    const id = `${type}-${Date.now()}-${++this.counter}`;
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${type} 请求超时（${Math.round(timeoutMs / 1000)} 秒）`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.worker!.postMessage({ type, id, ...payload });
    });
  }

  async init(options: {
    backend?: BackendPreference;
    precision?: PrecisionPreference;
  } = {}): Promise<EngineInfo> {
    this.terminate();
    this.worker = this.createWorker();
    const info = await this.request<EngineInfo>(
      "init",
      {
        backend: options.backend ?? "auto",
        precision: options.precision ?? "auto",
      },
      INIT_TIMEOUT,
    );
    this.info = info;
    return info;
  }

  async embed(
    texts: string[],
    batchSize = 16,
    purpose: "document" | "query" = "document",
  ): Promise<{ vectors: number[][]; timings: { totalMs: number; batchTimes: number[]; textsPerSecond: number } }> {
    if (!this.worker || !this.info) throw new Error("模型尚未就绪。");
    return this.request("embed", { texts, batchSize, purpose }, EMBED_TIMEOUT);
  }

  async chunk(
    documents: Array<{ id: string; title: string; content: string }>,
    maxTokens = 400,
    overlap = 60,
  ): Promise<{
    documents: Array<{
      id: string;
      title: string;
      chunks: Array<{ text: string; charStart: number; index: number }>;
    }>;
    maxTokens: number;
    overlap: number;
  }> {
    if (!this.worker || !this.info) throw new Error("模型尚未就绪。");
    return this.request("chunk", { documents, maxTokens, overlap }, CHUNK_TIMEOUT);
  }

  terminate() {
    if (this.worker) {
      this.worker.terminate();
      this.worker = null;
    }
    for (const [id, entry] of this.pending) {
      clearTimeout(entry.timer);
      entry.reject(new Error("推理 worker 已重启。"));
      this.pending.delete(id);
    }
    this.info = null;
  }
}

function emptyProgress(): LoadProgress {
  return {
    phase: "model",
    status: "error",
    file: "",
    loaded: 0,
    total: 0,
    progress: 0,
  };
}

export const embeddingEngine = new EmbeddingEngine();
