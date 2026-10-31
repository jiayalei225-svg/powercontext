import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const modelDir = path.join(root, "public", "models", "Xenova", "bge-small-zh-v1.5");
const ortSource = path.join(root, "node_modules", "onnxruntime-web", "dist");
const ortTarget = path.join(root, "public", "ort");
const manifestPath = path.join(root, "public", "model-manifest.json");

const required = [
  "config.json",
  "tokenizer.json",
  "tokenizer_config.json",
  "special_tokens_map.json",
  "onnx/model.onnx",
  "onnx/model_fp16.onnx",
  "onnx/model_quantized.onnx",
];

fs.mkdirSync(ortTarget, { recursive: true });
if (!fs.existsSync(ortSource)) {
  console.error("[assets] onnxruntime-web/dist not found. Run npm install first.");
  process.exitCode = 0;
} else {
  const candidates = fs
    .readdirSync(ortSource)
    .filter((name) => /^ort-wasm-simd-threaded[^/]*\.(mjs|wasm)$/.test(name));
  for (const name of candidates) {
    const source = path.join(ortSource, name);
    const target = path.join(ortTarget, name);
    const sourceStat = fs.statSync(source);
    if (fs.existsSync(target) && fs.statSync(target).size === sourceStat.size) continue;
    fs.copyFileSync(source, target);
    console.log(`[assets] copied ${name} (${(sourceStat.size / 1024 / 1024).toFixed(1)} MiB)`);
  }
}

const missing = required.filter((file) => !fs.existsSync(path.join(modelDir, file)));
if (missing.length > 0) {
  console.warn(
    "[assets] model files missing:\n  " +
      missing.join("\n  ") +
      "\n[assets] run `npm run setup:model` to download the pinned model files.",
  );
} else if (!fs.existsSync(manifestPath)) {
  const files = {};
  let total = 0;
  for (const file of required) {
    const full = path.join(modelDir, file);
    const bytes = fs.statSync(full).size;
    total += bytes;
    files[file] = {
      bytes,
      sha256: crypto.createHash("sha256").update(fs.readFileSync(full)).digest("hex"),
    };
  }
  const manifest = {
    model: "Xenova/bge-small-zh-v1.5",
    revision: "75c43b069aac4d136ba6bc1122f995fedcfd2781",
    dimension: 512,
    totalBytes: total,
    files,
    variants: {
      fp32: { file: "onnx/model.onnx", bytes: files["onnx/model.onnx"].bytes },
      fp16: { file: "onnx/model_fp16.onnx", bytes: files["onnx/model_fp16.onnx"].bytes },
      q8: { file: "onnx/model_quantized.onnx", bytes: files["onnx/model_quantized.onnx"].bytes },
    },
    createdAt: new Date().toISOString(),
  };
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2));
  console.log(`[assets] model manifest written (${(total / 1024 / 1024).toFixed(2)} MiB total)`);
} else {
  console.log("[assets] model manifest present");
}
