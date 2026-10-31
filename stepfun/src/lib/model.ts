export const MODEL = {
  id: "Xenova/bge-small-zh-v1.5",
  family: "bge-small-zh-v1.5",
  upstream: "BAAI/bge-small-zh-v1.5",
  revision: "75c43b069aac4d136ba6bc1122f995fedcfd2781",
  upstreamRevision: "7999e1d3359715c523056ef9478215996d62a620",
  dimension: 512,
  layers: 4,
  maxTokens: 512,
  pooling: "CLS",
  source: "https://huggingface.co/Xenova/bge-small-zh-v1.5",
  license: "MIT",
  sizes: {
    fp32: 95_292_210,
    fp16: 47_937_760,
    q8: 24_451_175,
  },
  onnxSizes: {
    fp32: 94_851_877,
    fp16: 47_497_427,
    q8: 24_010_842,
  },
  tokenizerBytes: 440_333,
  labels: {
    fp32: "FP32",
    fp16: "FP16",
    q8: "INT8",
  } as const,
  files: {
    fp32: "onnx/model.onnx",
    fp16: "onnx/model_fp16.onnx",
    q8: "onnx/model_quantized.onnx",
  },
};

export function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function formatMiB(bytes: number) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

export function compressionRatio(precision: "fp32" | "fp16" | "q8") {
  return MODEL.sizes.fp32 / MODEL.sizes[precision];
}

export function shortRevision() {
  return MODEL.revision.slice(0, 8);
}

export function formatMs(ms: number | null | undefined) {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 1) return "<1 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatTime(ts: number | null | undefined) {
  if (!ts) return "尚未导入";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(ts));
}
