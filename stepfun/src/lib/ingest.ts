import { api } from "./api";
import type { EmbeddingEngine } from "./embedding/engine";
import { MODEL } from "./model";
import type { IngestChunk, IngestDocument } from "./types";

export interface ImportProgress {
  phase: "reading" | "chunking" | "embedding" | "writing" | "done";
  percent: number;
  title: string;
  detail: string;
}

export interface ImportOutcome {
  stats: { documents: number; chunks: number };
  timings: {
    chunkMs: number;
    embedMs: number;
    writeMs: number;
    roundTripMs: number;
    refreshMs: number;
    verifyMs: number;
  };
  verified: boolean;
  perDocument: Array<{ docId: string; title: string; chunks: number; isReplace: boolean }>;
}

const MAX_FILE_BYTES = 1024 * 1024;
const ACCEPTED_EXTENSIONS = [".txt", ".md", ".markdown", ".text", ".json"];

export async function sha256(input: string) {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function cleanText(input: string) {
  return input
    .replace(/\u0000/g, "")
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

export async function documentsFromFiles(files: File[]): Promise<IngestDocument[]> {
  const docs: IngestDocument[] = [];
  for (const file of files) {
    const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
    if (!ACCEPTED_EXTENSIONS.includes(extension)) {
      throw new Error(`暂不支持 ${extension || "无扩展名"} 文件，请上传 .txt / .md / .json。`);
    }
    if (file.size > MAX_FILE_BYTES) {
      throw new Error(`「${file.name}」超过 1MB，请先拆分。`);
    }
    const raw = await file.text();
    if (extension === ".json") {
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed?.documents)) {
          const converted = parsed.documents
            .filter((doc: any) => doc?.content)
            .map((doc: any, index: number) => ({
              id: String(doc.id ?? `${file.name}-${index}`),
              title: String(doc.title ?? doc.id ?? `${file.name} #${index + 1}`),
              category: String(doc.category ?? "导入"),
              source: file.name,
              content: cleanText(String(doc.content)),
            }))
            .filter((doc: { content: string }) => doc.content.length > 0);
          docs.push(...converted);
          continue;
        }
      } catch {
        // Fall through: a JSON file without corpus structure is treated as text.
      }
    }
    const text = cleanText(raw);
    if (text.length < 20) {
      throw new Error(`「${file.name}」内容太短，至少需要 20 个字符。`);
    }
    const title = file.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim() || file.name;
    const id = `upload_${(await sha256(`${title}\n${text}`)).slice(0, 24)}`;
    docs.push({
      id,
      title,
      category: "本地导入",
      source: file.name,
      content: text,
    });
  }
  return docs;
}

export async function documentFromPaste(title: string, content: string): Promise<IngestDocument> {
  const text = cleanText(content);
  if (text.length < 20) throw new Error("粘贴内容太短，至少需要 20 个字符。");
  const finalTitle = title.trim() || text.slice(0, 24);
  const id = `paste_${(await sha256(`${finalTitle}\n${text}`)).slice(0, 24)}`;
  return {
    id,
    title: finalTitle,
    category: "手动笔记",
    source: "paste",
    content: text,
  };
}

export async function importDocuments(options: {
  documents: IngestDocument[];
  engine: EmbeddingEngine;
  kbId: string;
  batchSize: number;
  onProgress?: (progress: ImportProgress) => void;
}): Promise<ImportOutcome> {
  const { documents, engine, kbId, batchSize, onProgress } = options;
  if (!engine.isReady || !engine.info) throw new Error("推理引擎尚未就绪。");
  if (documents.length === 0) throw new Error("没有待导入的文档。");
  if (documents.length > 64) throw new Error("单次最多导入 64 篇文档。");

  const totalChars = documents.reduce((sum, doc) => sum + doc.content.length, 0);
  onProgress?.({
    phase: "chunking",
    percent: 3,
    title: "文本切分",
    detail: `${documents.length} 篇 · ${totalChars.toLocaleString("zh-CN")} 字符`,
  });
  const chunkStarted = performance.now();
  const chunked = await engine.chunk(
    documents.map((doc) => ({ id: doc.id, title: doc.title, content: doc.content })),
  );
  const chunkMs = performance.now() - chunkStarted;
  const totalChunks = chunked.documents.reduce((sum, doc) => sum + doc.chunks.length, 0);
  if (totalChunks === 0) throw new Error("切分后没有得到任何文本块。");

  const flatTexts = chunked.documents.flatMap((doc) => doc.chunks.map((chunk) => chunk.text));
  onProgress?.({
    phase: "embedding",
    percent: 10,
    title: "本地向量化",
    detail: `${totalChunks} 个文本块 · batch ${batchSize} · ${engine.info.precision === "q8" ? "INT8" : engine.info.precision.toUpperCase()} / ${engine.info.backend === "webgpu" ? "WebGPU" : "WASM"}`,
  });
  const embedStarted = performance.now();
  const embedding = await engine.embed(flatTexts, batchSize);
  const embedMs = performance.now() - embedStarted;
  if (embedding.vectors.length !== flatTexts.length) {
    throw new Error("生成的向量数量与文本块数量不一致。");
  }

  let cursor = 0;
  const payloadDocuments = chunked.documents.map((chunkedDoc) => {
    const original = documents.find((doc) => doc.id === chunkedDoc.id)!;
    const chunks: IngestChunk[] = chunkedDoc.chunks.map((chunk) => {
      const vector = embedding.vectors[cursor];
      cursor += 1;
      return {
        text: chunk.text,
        charStart: chunk.charStart,
        embedding: Array.from(vector, (value) => Math.round(value * 1e7) / 1e7),
      };
    });
    return {
      document: {
        id: original.id,
        title: original.title,
        category: original.category,
        source: original.source,
      },
      chunks,
      model: {
        precision: engine.info!.precision,
        model: MODEL.id,
        revision: MODEL.revision,
      },
    };
  });

  onProgress?.({
    phase: "writing",
    percent: 92,
    title: "写入 seekdb",
    detail: `${totalChunks} 个向量块 · 等待索引刷新`,
  });
  const writeRoundTripStarted = performance.now();
  const result = await api.importDocuments(kbId, {
    documents: payloadDocuments,
    model: {
      precision: engine.info.precision,
      model: MODEL.id,
      revision: MODEL.revision,
    },
  });
  const writeRoundTripMs = performance.now() - writeRoundTripStarted;

  onProgress?.({
    phase: "done",
    percent: 100,
    title: "索引可检索",
    detail: result.verified ? "自查询验证通过" : "刷新完成，验证未命中",
  });

  return {
    stats: result.stats,
    timings: {
      chunkMs: Math.round(chunkMs * 10) / 10,
      embedMs: Math.round(embedMs * 10) / 10,
      writeMs: result.timings.writeMs,
      roundTripMs: Math.round(writeRoundTripMs * 10) / 10,
      refreshMs: result.timings.writeMs,
      verifyMs: result.timings.verifyMs,
    },
    verified: result.verified,
    perDocument: result.documents,
  };
}
