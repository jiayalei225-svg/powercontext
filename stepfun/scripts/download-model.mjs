import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const modelId = "Xenova/bge-small-zh-v1.5";
const revision = "75c43b069aac4d136ba6bc1122f995fedcfd2781";
const modelDir = path.join(root, "public", "models", modelId);
const manifestPath = path.join(root, "data", "models.lock.json");
const files = [
  "config.json",
  "tokenizer.json",
  "tokenizer_config.json",
  "special_tokens_map.json",
  "onnx/model.onnx",
  "onnx/model_fp16.onnx",
  "onnx/model_quantized.onnx",
];

const lock = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const onlyArg = process.argv.find((value) => value.startsWith("--only="));
const only = onlyArg ? onlyArg.slice("--only=".length).split(",") : null;
const selected = files.filter((file) => {
  if (!only) return true;
  const variant = file.includes("_fp16") ? "fp16" : file.includes("_quantized") ? "q8" : file.includes("model.onnx") ? "fp32" : "meta";
  return only.includes(variant) || only.includes("meta");
});

function sha256(file) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash("sha256");
    const stream = fs.createReadStream(file);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("end", () => resolve(hash.digest("hex")));
    stream.on("error", reject);
  });
}

function download(url, out) {
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const part = `${out}.part`;
  const args = [
    "-L",
    "--fail",
    "--retry",
    "5",
    "--retry-delay",
    "3",
    "--connect-timeout",
    "30",
    "--progress-bar",
    url,
    "-o",
    part,
  ];
  console.log(`[model] ${path.relative(root, out)}`);
  const result = spawnSync("curl", args, { stdio: "inherit" });
  if (result.error || result.status !== 0) {
    fs.rmSync(part, { force: true });
    throw new Error(
      `curl 下载失败（${result.status ?? result.error?.message}）。如果处于代理网络，请设置 HTTPS_PROXY 后重试。`,
    );
  }
  fs.renameSync(part, out);
}

fs.mkdirSync(modelDir, { recursive: true });
for (const file of selected) {
  const out = path.join(modelDir, file);
  const expected = lock.files[file];
  if (fs.existsSync(out) && fs.statSync(out).size === expected.bytes) {
    const actual = await sha256(out);
    if (actual === expected.sha256) {
      console.log(`[model] ok ${file}`);
      continue;
    }
  }
  const url = `https://huggingface.co/${modelId}/resolve/${revision}/${file}`;
  await download(url, out);
  const size = fs.statSync(out).size;
  if (size !== expected.bytes) {
    throw new Error(`${file} 大小不符：expected ${expected.bytes}, got ${size}`);
  }
  const actual = await sha256(out);
  if (actual !== expected.sha256) {
    throw new Error(`${file} SHA-256 校验失败：expected ${expected.sha256}, got ${actual}`);
  }
  console.log(`[model] verified ${file}`);
}

let total = 0;
for (const file of files) {
  const full = path.join(modelDir, file);
  if (fs.existsSync(full)) total += fs.statSync(full).size;
}
console.log(
  `[model] ready in ${path.relative(root, modelDir)} · ${(total / 1024 / 1024).toFixed(2)} MiB total`,
);
