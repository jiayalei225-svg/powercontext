import { createHash } from "node:crypto";
import {
  FulltextIndexConfig,
  Schema,
  SeekdbAdminClient,
  SeekdbClient,
  VectorIndexConfig,
} from "seekdb";

export const EMBEDDING = Object.freeze({
  model: "Xenova/bge-small-zh-v1.5",
  revision: "75c43b069aac4d136ba6bc1122f995fedcfd2781",
  dimension: 512,
  distance: "cosine",
});

const REGISTRY_TABLE = "stepfun_kb_registry";
const DEFAULT_KB_ID = "kb_edge_atlas";
const DEFAULT_KB_TITLE = "端侧检索 · Edge Atlas";
const MAX_EMBEDDINGS_PER_REQUEST = 128;
const MAX_CHUNKS_PER_DOC = 256;
const MAX_DOC_BYTES = 8 * 1024 * 1024;

const now = () => Date.now();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const sha1 = (value) => createHash("sha1").update(value).digest("hex");

export class SeekdbService {
  constructor(config) {
    this.config = config;
    this.client = null;
    this.admin = null;
    this.ready = false;
    this.lastError = null;
    this.initializing = null;
    this.collections = new Map();
  }

  get status() {
    return {
      connected: this.ready && Boolean(this.client?.isConnected?.()),
      database: this.config.database,
      host: this.config.host,
      port: this.config.port,
      lastError: this.lastError,
      mode: "server",
    };
  }

  async connect({ createDefault = true } = {}) {
    if (this.ready) return this;
    if (this.initializing) return this.initializing;
    this.initializing = this.#connect({ createDefault }).finally(() => {
      this.initializing = null;
    });
    return this.initializing;
  }

  async #connect({ createDefault }) {
    this.lastError = null;
    this.admin = new SeekdbAdminClient({
      host: this.config.host,
      port: this.config.port,
      user: this.config.user,
      password: this.config.password,
      ...(this.config.tenant ? { tenant: this.config.tenant } : {}),
    });
    try {
      const databases = await this.admin.listDatabases();
      const names = databases.map((db) => (typeof db === "string" ? db : db.name));
      if (!names.includes(this.config.database)) {
        await this.admin.createDatabase(this.config.database);
      }
    } finally {
      await this.admin.close().catch(() => {});
      this.admin = null;
    }

    this.client = new SeekdbClient({
      host: this.config.host,
      port: this.config.port,
      user: this.config.user,
      password: this.config.password,
      database: this.config.database,
      queryTimeout: 180_000,
    });
    await this.client.execute("SELECT 1 AS ok");
    await this.client.execute("SET ob_query_timeout = 180000000").catch(() => {});
    await this.#ensureRegistry();
    this.ready = true;
    if (createDefault) {
      try {
        await this.#ensureDefault();
      } catch (error) {
        this.ready = false;
        throw error;
      }
    }
    return this;
  }

  async close() {
    if (this.client) await this.client.close().catch(() => {});
    this.client = null;
    this.ready = false;
    this.collections.clear();
  }

  requireReady() {
    if (!this.ready || !this.client) {
      const error = new Error(
        "seekdb 尚未连接。请先启动 seekdb server（默认 127.0.0.1:2881），应用会自动重试。",
      );
      error.status = 503;
      error.code = "SEEKDB_UNAVAILABLE";
      throw error;
    }
  }

  async #ensureRegistry() {
    await this.client.execute(`
      CREATE TABLE IF NOT EXISTS ${REGISTRY_TABLE} (
        name VARCHAR(64) PRIMARY KEY,
        title VARCHAR(191) NOT NULL,
        description TEXT,
        created_at BIGINT NOT NULL,
        updated_at BIGINT NOT NULL,
        embedding_model VARCHAR(128) NOT NULL,
        model_revision VARCHAR(64) NOT NULL,
        dimension INT NOT NULL,
        doc_count INT NOT NULL DEFAULT 0,
        chunk_count INT NOT NULL DEFAULT 0,
        last_import_at BIGINT NULL
      ) DEFAULT CHARSET=utf8mb4
    `);
  }

  async #ensureDefault() {
    const rows = await this.client.execute(`SELECT COUNT(*) AS total FROM ${REGISTRY_TABLE}`);
    if (Number(rows?.[0]?.total ?? 0) > 0) return;
    const exists = await this.client.hasCollection(DEFAULT_KB_ID);
    if (!exists) {
      await this.createKnowledgeBase({
        id: DEFAULT_KB_ID,
        title: DEFAULT_KB_TITLE,
        description: "端侧 AI、浏览器推理与 seekdb 混合检索的示例知识空间。",
      });
    } else {
      await this.#upsertRegistry({
        name: DEFAULT_KB_ID,
        title: DEFAULT_KB_TITLE,
        description: "端侧 AI、浏览器推理与 seekdb 混合检索的示例知识空间。",
        createdAt: now(),
        updatedAt: now(),
        docCount: 0,
        chunkCount: await this.#getCollection(DEFAULT_KB_ID).then((c) => c.count()),
        lastImportAt: null,
      });
    }
  }

  #schema() {
    return new Schema({
      vectorIndex: new VectorIndexConfig({
        hnsw: {
          dimension: EMBEDDING.dimension,
          distance: EMBEDDING.distance,
          type: "hnsw",
          m: 16,
          ef_construction: 200,
          ef_search: 100,
        },
        embeddingFunction: null,
      }),
      fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }),
    });
  }

  async #getCollection(name) {
    if (!this.collections.has(name)) {
      const collection = await this.client.getCollection({
        name,
        embeddingFunction: null,
      });
      this.collections.set(name, collection);
    }
    return this.collections.get(name);
  }

  async createKnowledgeBase({ id, title, description }) {
    this.requireReady();
    const name = id ?? `kb_${now().toString(36)}_${sha1(String(Math.random())).slice(0, 4)}`;
    if (!/^kb_[a-z0-9_]{2,61}$/.test(name)) {
      const error = new Error("知识库 ID 只能包含小写字母、数字和下划线，并以 kb_ 开头。");
      error.status = 400;
      throw error;
    }
    if (!title || typeof title !== "string" || title.trim().length === 0) {
      const error = new Error("知识库标题不能为空。");
      error.status = 400;
      throw error;
    }
    if (await this.client.hasCollection(name)) {
      const error = new Error("同名知识库已存在。");
      error.status = 409;
      throw error;
    }
    const collection = await this.client.createCollection({
      name,
      schema: this.#schema(),
    });
    this.collections.set(name, collection);
    const ts = now();
    try {
      await this.#upsertRegistry({
        name,
        title: title.trim().slice(0, 190),
        description: (description ?? "").trim().slice(0, 2000),
        createdAt: ts,
        updatedAt: ts,
        docCount: 0,
        chunkCount: 0,
        lastImportAt: null,
      });
    } catch (error) {
      await this.client.deleteCollection(name).catch(() => {});
      this.collections.delete(name);
      throw error;
    }
    return this.getKnowledgeBase(name);
  }

  async #upsertRegistry({
    name,
    title,
    description,
    createdAt,
    updatedAt,
    docCount,
    chunkCount,
    lastImportAt,
  }) {
    await this.client.execute(
      `INSERT INTO ${REGISTRY_TABLE}
        (name, title, description, created_at, updated_at, embedding_model, model_revision, dimension, doc_count, chunk_count, last_import_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON DUPLICATE KEY UPDATE
        title = VALUES(title), description = VALUES(description), updated_at = VALUES(updated_at),
        doc_count = VALUES(doc_count), chunk_count = VALUES(chunk_count), last_import_at = VALUES(last_import_at)`,
      [
        name,
        title,
        description,
        createdAt,
        updatedAt,
        EMBEDDING.model,
        EMBEDDING.revision,
        EMBEDDING.dimension,
        docCount,
        chunkCount,
        lastImportAt,
      ],
    );
  }

  async listKnowledgeBases() {
    this.requireReady();
    const rows =
      (await this.client.execute(
        `SELECT name, title, description, created_at, updated_at, doc_count, chunk_count, last_import_at
         FROM ${REGISTRY_TABLE} ORDER BY updated_at DESC`,
      )) ?? [];
    const result = [];
    for (const row of rows) {
      let liveChunks = Number(row.chunk_count ?? 0);
      let precision = null;
      try {
        const collection = await this.#getCollection(row.name);
        liveChunks = await collection.count();
        precision = await this.#detectPrecision(collection);
      } catch {
        // A registry row may survive an interrupted collection creation.
      }
      result.push({
        id: row.name,
        title: row.title,
        description: row.description,
        createdAt: Number(row.created_at),
        updatedAt: Number(row.updated_at),
        lastImportAt: row.last_import_at == null ? null : Number(row.last_import_at),
        documents: Number(row.doc_count ?? 0),
        chunks: liveChunks,
        precision,
        embedding: {
          model: EMBEDDING.model,
          revision: EMBEDDING.revision,
          dimension: EMBEDDING.dimension,
          distance: EMBEDDING.distance,
        },
        isDefault: row.name === DEFAULT_KB_ID,
      });
    }
    return result;
  }

  async #detectPrecision(collection) {
    try {
      const sample = await collection.get({ limit: 1, include: ["metadatas"] });
      return sample.metadatas?.[0]?.precision ?? null;
    } catch {
      return null;
    }
  }

  async #registryRow(name) {
    const rows = await this.client.execute(
      `SELECT name, title, description, created_at, updated_at, doc_count, chunk_count, last_import_at
       FROM ${REGISTRY_TABLE} WHERE name = ? LIMIT 1`,
      [name],
    );
    return rows?.[0] ?? null;
  }

  async getKnowledgeBase(name) {
    this.requireReady();
    if (!/^kb_[a-z0-9_]{2,61}$/.test(name)) {
      const error = new Error("非法知识库 ID。");
      error.status = 400;
      throw error;
    }
    const row = await this.#registryRow(name);
    if (!row) {
      const error = new Error("知识库不存在。");
      error.status = 404;
      throw error;
    }
    const collection = await this.#getCollection(name);
    const chunks = await collection.count();
    const precision = await this.#detectPrecision(collection);
    return {
      id: row.name,
      title: row.title,
      description: row.description,
      createdAt: Number(row.created_at),
      updatedAt: Number(row.updated_at),
      lastImportAt: row.last_import_at == null ? null : Number(row.last_import_at),
      documents: Number(row.doc_count ?? 0),
      chunks,
      precision,
      embedding: {
        model: EMBEDDING.model,
        revision: EMBEDDING.revision,
        dimension: EMBEDDING.dimension,
        distance: EMBEDDING.distance,
      },
      isDefault: row.name === DEFAULT_KB_ID,
      index: {
        vector: "HNSW · cosine · M=16 · ef_construction=200 · ef_search=100",
        fulltext: "IK smart · FulltextIndexConfig",
        mixed: "DBMS_HYBRID_SEARCH · RRF(k=60)",
      },
    };
  }

  async deleteKnowledgeBase(name) {
    this.requireReady();
    await this.getKnowledgeBase(name);
    await this.client.deleteCollection(name);
    this.collections.delete(name);
    await this.client.execute(`DELETE FROM ${REGISTRY_TABLE} WHERE name = ?`, [name]);
  }

  async listDocuments(name) {
    this.requireReady();
    await this.getKnowledgeBase(name);
    const collection = await this.#getCollection(name);
    const result = await collection.get({
      limit: 5000,
      include: ["documents", "metadatas"],
    });
    const byDoc = new Map();
    for (let i = 0; i < result.ids.length; i += 1) {
      const meta = result.metadatas?.[i] ?? {};
      const docId = String(meta.docId ?? result.ids[i]);
      const text = result.documents?.[i] ?? "";
      if (!byDoc.has(docId)) {
        byDoc.set(docId, {
          docId,
          title: String(meta.title ?? docId),
          category: String(meta.category ?? "未分类"),
          source: String(meta.source ?? ""),
          importedAt: Number(meta.importedAt ?? 0),
          chunks: 0,
          chars: 0,
          preview: text.slice(0, 180),
          precision: String(meta.precision ?? "unknown"),
        });
      }
      const doc = byDoc.get(docId);
      doc.chunks += 1;
      doc.chars += text.length;
    }
    return [...byDoc.values()].sort((a, b) => b.importedAt - a.importedAt);
  }

  async #assertEmbeddingSpace() {
    // The model id and revision are fixed for a collection. Precision variants
    // are interoperable runtime optimizations and do not create a new space.
    return true;
  }

  #validateEmbeddings(items) {
    if (!Array.isArray(items) || items.length === 0) {
      const error = new Error("缺少向量数据。");
      error.status = 400;
      throw error;
    }
    if (items.length > MAX_EMBEDDINGS_PER_REQUEST) {
      const error = new Error(`单次最多写入 ${MAX_EMBEDDINGS_PER_REQUEST} 个向量。`);
      error.status = 400;
      throw error;
    }
    return items.map((vector, index) => {
      if (!Array.isArray(vector) || vector.length !== EMBEDDING.dimension) {
        const error = new Error(`第 ${index + 1} 个向量维度不是 ${EMBEDDING.dimension}。`);
        error.status = 400;
        throw error;
      }
      let norm = 0;
      for (const value of vector) {
        if (!Number.isFinite(value)) {
          const error = new Error(`第 ${index + 1} 个向量包含非法数值。`);
          error.status = 400;
          throw error;
        }
        norm += value * value;
      }
      norm = Math.sqrt(norm);
      if (norm < 1e-8) {
        const error = new Error(`第 ${index + 1} 个向量范数为 0。`);
        error.status = 400;
        throw error;
      }
      return vector.map((value) => value / norm);
    });
  }

  async addDocument(name, body) {
    const result = await this.addDocuments(name, {
      documents: [{ document: body?.document, chunks: body?.chunks, model: body?.model }],
    });
    const first = result.documents[0];
    return {
      ...first,
      verified: result.verified,
      retried: result.retried,
      timings: result.timings,
      stats: result.stats,
    };
  }

  async addDocuments(name, body) {
    this.requireReady();
    await this.getKnowledgeBase(name);
    await this.#assertEmbeddingSpace();
    const inputs = body?.documents;
    if (!Array.isArray(inputs) || inputs.length === 0) {
      const error = new Error("缺少待导入文档。");
      error.status = 400;
      throw error;
    }
    if (inputs.length > 64) {
      const error = new Error("单次最多导入 64 篇文档。");
      error.status = 400;
      throw error;
    }
    if (JSON.stringify(inputs).length > MAX_DOC_BYTES) {
      const error = new Error("单次导入请求超过 8MB 限制。");
      error.status = 413;
      throw error;
    }

    const row = await this.#registryRow(name);
    const collection = await this.#getCollection(name);
    const allExisting = await collection.get({ limit: 5000, include: ["metadatas"] });
    const existingDocIds = new Set(
      (allExisting.metadatas ?? []).map((meta) => String(meta?.docId ?? "")).filter(Boolean),
    );
    const importedAt = now();
    const embeddingSpace = `${EMBEDDING.model}@${EMBEDDING.revision}/${EMBEDDING.dimension}`;
    const prepared = [];
    const seenDocIds = new Set();
    let totalChunks = 0;

    for (const input of inputs) {
      const { document, chunks } = input ?? {};
      if (!document || typeof document.id !== "string" || !document.id.trim()) {
        const error = new Error("缺少文档 ID。");
        error.status = 400;
        throw error;
      }
      if (!Array.isArray(chunks) || chunks.length === 0) {
        const error = new Error(`文档「${document.title ?? document.id}」没有文本块。`);
        error.status = 400;
        throw error;
      }
      if (chunks.length > MAX_CHUNKS_PER_DOC) {
        const error = new Error(`单篇文档最多 ${MAX_CHUNKS_PER_DOC} 个文本块。`);
        error.status = 400;
        throw error;
      }
      totalChunks += chunks.length;
      if (totalChunks > 512) {
        const error = new Error("单次导入最多 512 个文本块。");
        error.status = 400;
        throw error;
      }
      const docId = document.id.trim().slice(0, 160);
      if (seenDocIds.has(docId)) {
        const error = new Error(`文档 ID 重复：${docId}`);
        error.status = 400;
        throw error;
      }
      seenDocIds.add(docId);
      const title = String(document.title ?? docId).trim().slice(0, 190) || docId;
      const category = String(document.category ?? "未分类").trim().slice(0, 80);
      const source = String(document.source ?? "").slice(0, 500);
      const precision = String(input.model?.precision ?? body?.model?.precision ?? "unknown").slice(0, 16);
      const embeddings = this.#validateEmbeddings(chunks.map((chunk) => chunk.embedding));
      const ids = [];
      const documents = [];
      const metadatas = [];

      for (let i = 0; i < chunks.length; i += 1) {
        const text = String(chunks[i].text ?? "").trim();
        if (!text) {
          const error = new Error(`「${title}」第 ${i + 1} 个文本块为空。`);
          error.status = 400;
          throw error;
        }
        if (text.length > 16_000) {
          const error = new Error(`「${title}」第 ${i + 1} 个文本块超过 16000 字符。`);
          error.status = 413;
          throw error;
        }
        const hash = sha1(`${docId}:${i}:${text}`).slice(0, 32);
        ids.push(`c_${hash}`);
        documents.push(text);
        metadatas.push({
          docId,
          title,
          category,
          source,
          chunkIndex: i,
          chunkCount: chunks.length,
          charStart: Number(chunks[i].charStart ?? 0),
          importedAt,
          embeddingSpace,
          precision,
          contentHash: hash,
        });
      }
      prepared.push({
        docId,
        title,
        chunks: chunks.length,
        embeddings,
        ids,
        documents,
        metadatas,
        isReplace: existingDocIds.has(docId),
      });
    }

    const writeStarted = performance.now();
    const allIds = prepared.flatMap((item) => item.ids);
    let inserted = false;
    try {
      for (const item of prepared) {
        if (item.isReplace) await collection.delete({ where: { docId: item.docId } });
      }
      const flatIds = prepared.flatMap((item) => item.ids);
      const flatDocuments = prepared.flatMap((item) => item.documents);
      const flatMetadatas = prepared.flatMap((item) => item.metadatas);
      const flatEmbeddings = prepared.flatMap((item) => item.embeddings);
      const addBatchSize = 16;
      for (let start = 0; start < flatIds.length; start += addBatchSize) {
        const end = start + addBatchSize;
        await collection.add({
          ids: flatIds.slice(start, end),
          documents: flatDocuments.slice(start, end),
          metadatas: flatMetadatas.slice(start, end),
          embeddings: flatEmbeddings.slice(start, end),
        });
      }
      inserted = true;
      await collection.refresh_index();
      const verifyStarted = performance.now();
      let verified =
        (await this.#verifySearchable(collection, prepared[0].ids[0], prepared[0].embeddings[0])) &&
        (await this.#verifySearchable(
          collection,
          prepared[prepared.length - 1].ids[0],
          prepared[prepared.length - 1].embeddings[0],
        ));
      let retried = false;
      if (!verified) {
        retried = true;
        await sleep(120);
        await collection.refresh_index();
        verified = await this.#verifySearchable(
          collection,
          prepared[0].ids[0],
          prepared[0].embeddings[0],
        );
      }
      const writeMs = performance.now() - writeStarted;
      const verifyMs = performance.now() - verifyStarted;
      const chunkCount = await collection.count();
      const brandNew = prepared.filter((item) => !item.isReplace).length;
      const docCount = Number(row?.doc_count ?? 0) + brandNew;
      const ts = now();
      await this.#upsertRegistry({
        name,
        title: row?.title ?? "未命名知识库",
        description: row?.description ?? "",
        createdAt: Number(row?.created_at ?? ts),
        updatedAt: ts,
        docCount,
        chunkCount,
        lastImportAt: ts,
      });
      return {
        documents: prepared.map((item) => ({
          docId: item.docId,
          title: item.title,
          chunks: item.chunks,
          isReplace: item.isReplace,
        })),
        verified,
        retried,
        timings: {
          writeMs: Math.round(writeMs * 10) / 10,
          verifyMs: Math.round(verifyMs * 10) / 10,
        },
        stats: { documents: docCount, chunks: chunkCount },
      };
    } catch (error) {
      if (inserted) await collection.delete({ ids: allIds }).catch(() => {});
      throw error;
    }
  }

  async #verifySearchable(collection, id, embedding) {
    const result = await collection.query({
      queryEmbeddings: [embedding],
      nResults: 5,
      include: ["metadatas"],
    });
    return Boolean(result.ids?.[0]?.includes(id));
  }

  async deleteDocument(name, docId) {
    this.requireReady();
    await this.getKnowledgeBase(name);
    const collection = await this.#getCollection(name);
    const existing = await collection.get({ where: { docId }, limit: 1 });
    if (existing.ids.length === 0) {
      const error = new Error("文档不存在。");
      error.status = 404;
      throw error;
    }
    const started = performance.now();
    await collection.delete({ where: { docId } });
    await collection.refresh_index();
    const chunkCount = await collection.count();
    const row = await this.#registryRow(name);
    const ts = now();
    const docCount = Math.max(0, Number(row?.doc_count ?? 1) - 1);
    await this.#upsertRegistry({
      name,
      title: row?.title ?? "未命名知识库",
      description: row?.description ?? "",
      createdAt: Number(row?.created_at ?? ts),
      updatedAt: ts,
      docCount,
      chunkCount,
      lastImportAt: row?.last_import_at == null ? null : Number(row.last_import_at),
    });
    return {
      docId,
      timings: { deleteMs: Math.round((performance.now() - started) * 10) / 10 },
      stats: { documents: docCount, chunks: chunkCount },
    };
  }

  #sanitizeFulltext(query) {
    return String(query ?? "")
      .replace(/[+\-&|!(){}\[\]^"~*?:\\/]/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 300);
  }

  async search(name, body) {
    this.requireReady();
    await this.getKnowledgeBase(name);
    const query = String(body?.query ?? "").trim();
    if (!query) {
      const error = new Error("查询不能为空。");
      error.status = 400;
      throw error;
    }
    if (query.length > 600) {
      const error = new Error("查询过长。");
      error.status = 400;
      throw error;
    }
    const [queryEmbedding] = this.#validateEmbeddings([body?.embedding]);
    const mode = ["hybrid", "vector", "fulltext"].includes(body?.mode)
      ? body.mode
      : "hybrid";
    const topK = Math.min(20, Math.max(1, Number(body?.topK ?? 8)));
    const collection = await this.#getCollection(name);
    const safeText = this.#sanitizeFulltext(query);
    if (!safeText && mode !== "vector") {
      const error = new Error("查询中没有可用于全文检索的词项。");
      error.status = 400;
      throw error;
    }

    const started = performance.now();
    let raw;
    let engine;
    if (mode === "vector") {
      raw = await collection.query({
        queryEmbeddings: [queryEmbedding],
        nResults: Math.min(80, topK * 4),
        include: ["documents", "metadatas", "distances"],
      });
      engine = "seekdb HNSW · cosine";
    } else if (mode === "fulltext") {
      raw = await collection.hybridSearch({
        query: { whereDocument: { $contains: safeText } },
        nResults: Math.min(80, topK * 4),
        include: ["documents", "metadatas", "distances"],
      });
      engine = "seekdb DBMS_HYBRID_SEARCH · fulltext only";
    } else {
      raw = await collection.hybridSearch({
        query: { whereDocument: { $contains: safeText } },
        knn: {
          queryEmbeddings: [queryEmbedding],
          nResults: Math.min(80, topK * 4),
        },
        rank: { rrf: { rankWindowSize: 40, rankConstant: 60 } },
        nResults: Math.min(80, topK * 4),
        include: ["documents", "metadatas", "distances"],
      });
      engine = "seekdb DBMS_HYBRID_SEARCH · RRF(k=60)";
    }
    const seekdbMs = performance.now() - started;

    const ids = raw.ids?.[0] ?? [];
    const docs = raw.documents?.[0] ?? [];
    const metas = raw.metadatas?.[0] ?? [];
    const scores = raw.distances?.[0] ?? [];
    const grouped = new Map();
    let rawChunks = 0;
    for (let i = 0; i < ids.length; i += 1) {
      const meta = metas[i] ?? {};
      const docId = String(meta.docId ?? ids[i]);
      const score = Number(scores[i] ?? 0);
      rawChunks += 1;
      const previous = grouped.get(docId);
      if (previous) {
        previous.otherChunks += 1;
        continue;
      }
      grouped.set(docId, {
        chunkId: ids[i],
        docId,
        title: String(meta.title ?? docId),
        category: String(meta.category ?? "未分类"),
        source: String(meta.source ?? ""),
        text: String(docs[i] ?? ""),
        chunkIndex: Number(meta.chunkIndex ?? 0),
        chunkCount: Number(meta.chunkCount ?? 1),
        score,
        scoreKind:
          mode === "hybrid" ? "rrf" : mode === "vector" ? "cosine" : "fulltext",
        otherChunks: 0,
      });
    }
    const results = [...grouped.values()].slice(0, topK);
    return {
      mode,
      engine,
      query,
      topK,
      results,
      rawChunks,
      dedupedDocuments: grouped.size,
      timings: { seekdbMs: Math.round(seekdbMs * 10) / 10 },
      index: {
        vector: "HNSW cosine",
        fulltext: "IK smart",
        fusion: mode === "hybrid" ? "RRF rankConstant=60" : null,
      },
      embedding: {
        model: EMBEDDING.model,
        revision: EMBEDDING.revision,
        dimension: EMBEDDING.dimension,
      },
    };
  }

  async health() {
    if (!this.client) return { ...this.status, ok: false };
    try {
      await this.client.execute("SELECT 1 AS ok");
      return { ...this.status, ok: true };
    } catch (error) {
      return { ...this.status, ok: false, lastError: String(error?.message ?? error) };
    }
  }
}

export { DEFAULT_KB_ID, DEFAULT_KB_TITLE };
