import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import compression from "compression";
import express from "express";
import { SeekdbService, EMBEDDING, DEFAULT_KB_TITLE } from "./seekdb-service.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const envFile = path.join(root, ".env");
if (fs.existsSync(envFile)) {
  try {
    process.loadEnvFile(envFile);
  } catch (error) {
    console.warn("[env] 无法读取 .env：", error.message);
  }
}

const config = {
  host: process.env.SEEKDB_HOST ?? "127.0.0.1",
  port: Number(process.env.SEEKDB_PORT ?? 2881),
  user: process.env.SEEKDB_USER ?? "root",
  password: process.env.SEEKDB_PASSWORD ?? "",
  database: process.env.SEEKDB_DATABASE ?? "stepfun_kb",
  tenant: process.env.SEEKDB_TENANT || undefined,
};
const webPort = Number(process.env.PORT ?? 8787);
const serveStatic = process.env.SERVE_STATIC !== "0";
const distDir = path.join(root, "dist");

const service = new SeekdbService(config);
const app = express();
app.disable("x-powered-by");
app.use(
  compression({
    filter(req, res) {
      // ONNX and WASM files should keep Content-Length. Transformers.js and the
      // browser cache behave badly with chunked, brotli-compressed model bodies.
      if (req.path.startsWith("/models/") || req.path.startsWith("/ort/")) return false;
      return compression.filter(req, res);
    },
  }),
);
app.use((req, res, next) => {
  res.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  res.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
  res.setHeader("Cross-Origin-Resource-Policy", "same-origin");
  res.setHeader("X-Content-Type-Options", "nosniff");
  if (req.path.startsWith("/api/")) res.setHeader("Cache-Control", "no-store");
  next();
});
app.use(express.json({ limit: "12mb" }));

const asyncRoute = (handler) => (req, res, next) =>
  Promise.resolve(handler(req, res, next)).catch(next);

app.get(
  "/api/health",
  asyncRoute(async (_req, res) => {
    const db = await service.health();
    res.status(db.connected ? 200 : 503).json({
      ok: db.connected,
      time: new Date().toISOString(),
      service: "stepfun-edge-atlas",
      version: "1.0.0",
      seekdb: db,
      embedding: EMBEDDING,
      runtime: {
        inference: "browser-local",
        cloudInference: false,
        expectedBackends: ["webgpu", "wasm"],
      },
    });
  }),
);

app.get(
  "/api/meta",
  asyncRoute(async (_req, res) => {
    res.json({
      app: "Edge Atlas",
      defaultCollectionTitle: DEFAULT_KB_TITLE,
      embedding: EMBEDDING,
      seekdb: service.status,
      modelFiles: {
        fp32: "/models/Xenova/bge-small-zh-v1.5/onnx/model.onnx",
        fp16: "/models/Xenova/bge-small-zh-v1.5/onnx/model_fp16.onnx",
        q8: "/models/Xenova/bge-small-zh-v1.5/onnx/model_quantized.onnx",
      },
      serverTime: new Date().toISOString(),
    });
  }),
);

app.get(
  "/api/kbs",
  asyncRoute(async (_req, res) => {
    const collections = await service.listKnowledgeBases();
    res.json({
      collections,
      defaultId: collections.find((item) => item.isDefault)?.id ?? collections[0]?.id ?? null,
    });
  }),
);

app.post(
  "/api/kbs",
  asyncRoute(async (req, res) => {
    const { title, description, id } = req.body ?? {};
    const kb = await service.createKnowledgeBase({ id, title, description });
    res.status(201).json({ collection: kb });
  }),
);

app.get(
  "/api/kbs/:id",
  asyncRoute(async (req, res) => {
    const [collection, documents] = await Promise.all([
      service.getKnowledgeBase(req.params.id),
      service.listDocuments(req.params.id),
    ]);
    res.json({ collection, documents });
  }),
);

app.delete(
  "/api/kbs/:id",
  asyncRoute(async (req, res) => {
    await service.deleteKnowledgeBase(req.params.id);
    res.json({ ok: true });
  }),
);

app.post(
  "/api/kbs/:id/documents",
  asyncRoute(async (req, res) => {
    const result = await service.addDocument(req.params.id, req.body);
    res.status(201).json(result);
  }),
);

app.post(
  "/api/kbs/:id/import",
  asyncRoute(async (req, res) => {
    const result = await service.addDocuments(req.params.id, req.body);
    res.status(201).json(result);
  }),
);

app.delete(
  "/api/kbs/:id/documents/:docId",
  asyncRoute(async (req, res) => {
    const result = await service.deleteDocument(req.params.id, req.params.docId);
    res.json(result);
  }),
);

app.post(
  "/api/kbs/:id/search",
  asyncRoute(async (req, res) => {
    const result = await service.search(req.params.id, req.body);
    res.json(result);
  }),
);

if (serveStatic) {
  app.use(
    "/models",
    express.static(path.join(distDir, "models"), {
      maxAge: "7d",
      setHeaders(res, filePath) {
        res.setHeader("Cross-Origin-Resource-Policy", "same-origin");
        // Chromium's disk cache intermittently rejects large model bodies with
        // net::ERR_CACHE_WRITE_FAILURE. Disable HTTP caching for ONNX payloads
        // to make WebGPU/WASM startup deterministic; small config files and
        // ORT runtime assets remain cacheable.
        if (filePath.endsWith(".onnx")) {
          res.setHeader("Cache-Control", "no-store");
        }
      },
    }),
  );
  app.use(
    "/ort",
    express.static(path.join(distDir, "ort"), {
      maxAge: "7d",
      setHeaders(res) {
        res.setHeader("Cross-Origin-Resource-Policy", "same-origin");
      },
    }),
  );
  app.use(
    express.static(distDir, {
      maxAge: "1h",
      setHeaders(res, filePath) {
        if (filePath.includes(`${path.sep}assets${path.sep}`)) {
          res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
        }
      },
    }),
  );
  app.use((req, res, next) => {
    if (req.method !== "GET" || req.path.startsWith("/api/")) return next();
    const indexFile = path.join(distDir, "index.html");
    if (!fs.existsSync(indexFile)) {
      return res
        .status(503)
        .type("text/plain")
        .send("前端尚未构建。请先运行 npm run build，或使用 npm run dev 启动开发模式。");
    }
    return res.sendFile(indexFile);
  });
}

app.use((req, res) => {
  res.status(404).json({ error: "Not found", path: req.path });
});

app.use((error, _req, res, _next) => {
  const status = Number(error.status ?? 500);
  if (status >= 500) {
    console.error("[api]", error);
  } else {
    console.warn("[api]", status, error.message);
  }
  res.status(status).json({
    error: error.message ?? "服务端错误",
    code: error.code ?? "INTERNAL_ERROR",
  });
});

const server = app.listen(webPort, process.env.HOST ?? "127.0.0.1", () => {
  console.log(`[edge-atlas] http://127.0.0.1:${webPort}`);
  console.log(
    `[edge-atlas] seekdb ${config.host}:${config.port}/${config.database} · 浏览器端推理 · 无云端 API`,
  );
});

let retryTimer = null;
async function connectWithRetry() {
  try {
    await service.connect();
    console.log("[seekdb] connected, registry and default collection ready");
  } catch (error) {
    console.error("[seekdb] connect failed:", error.message);
    retryTimer = setTimeout(connectWithRetry, 5000);
    retryTimer.unref?.();
  }
}
connectWithRetry();

async function shutdown(signal) {
  console.log(`\n[edge-atlas] ${signal}, shutting down...`);
  if (retryTimer) clearTimeout(retryTimer);
  server.close();
  await service.close();
  process.exit(0);
}
process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
