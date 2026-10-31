import { useEffect, useRef, useState } from "react";
import sampleCorpus from "../../data/sample-corpus.json";
import type { IngestDocument, KnowledgeBase } from "../lib/types";
import type { EmbeddingEngine } from "../lib/embedding/engine";
import {
  documentFromPaste,
  documentsFromFiles,
  importDocuments,
  type ImportOutcome,
  type ImportProgress,
} from "../lib/ingest";
import { formatMs } from "../lib/model";
import { Modal, ProgressBar, Spinner, Tag } from "./Primitives";
import { ArrowUpRight, CheckIcon, FileIcon, SparkIcon, WarningIcon } from "./Icons";

type Tab = "files" | "paste" | "sample";

export function ImportDialog({
  open,
  onClose,
  kb,
  engine,
  batchSize,
  onImported,
  initialTab = "files",
}: {
  open: boolean;
  onClose: () => void;
  kb: KnowledgeBase | null;
  engine: EmbeddingEngine;
  batchSize: number;
  onImported: (outcome: ImportOutcome) => void;
  initialTab?: Tab;
}) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [files, setFiles] = useState<File[]>([]);
  const [pasteTitle, setPasteTitle] = useState("");
  const [pasteContent, setPasteContent] = useState("");
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<ImportProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<ImportOutcome | null>(null);
  const [embedSeen, setEmbedSeen] = useState({ processed: 0, total: 0 });
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setTab(initialTab);
    setError(null);
    setOutcome(null);
    setProgress(null);
    setEmbedSeen({ processed: 0, total: 0 });
    setBusy(false);
  }, [open, initialTab]);

  const sampleDocs = sampleCorpus.documents as IngestDocument[];
  const sampleChunksEstimate = sampleDocs.reduce(
    (sum, doc) => sum + Math.max(1, Math.ceil(doc.content.length / 360)),
    0,
  );
  const docsForTab =
    tab === "files"
      ? files.length
      : tab === "sample"
        ? sampleDocs.length
        : pasteContent.trim()
          ? 1
          : 0;

  const addFiles = (incoming: FileList | File[]) => {
    const accepted = [...incoming].filter((file) =>
      /\.(txt|md|markdown|text|json)$/i.test(file.name),
    );
    if (accepted.length === 0) {
      setError("请选择 .txt / .md / .json 文本文件。");
      return;
    }
    setError(null);
    setFiles((current) => {
      const map = new Map(current.map((file) => [`${file.name}:${file.size}`, file]));
      for (const file of accepted) map.set(`${file.name}:${file.size}`, file);
      return [...map.values()];
    });
  };

  const startImport = async () => {
    if (!kb) {
      setError("请先选择知识库。");
      return;
    }
    if (!engine.isReady) {
      setError("推理模型尚未就绪，请等待加载完成。");
      return;
    }
    setBusy(true);
    setError(null);
    setOutcome(null);
    setEmbedSeen({ processed: 0, total: 0 });
    let docs: IngestDocument[] = [];
    const unsubscribe = engine.onEmbedProgress((event) => {
      setEmbedSeen({ processed: event.processed, total: event.total });
    });
    try {
      if (tab === "files") {
        if (files.length === 0) throw new Error("请先选择要导入的文件。");
        setProgress({
          phase: "reading",
          percent: 1,
          title: "读取文件",
          detail: `${files.length} 个文件`,
        });
        docs = await documentsFromFiles(files);
      } else if (tab === "paste") {
        docs = [await documentFromPaste(pasteTitle, pasteContent)];
      } else {
        docs = sampleDocs;
      }
      const result = await importDocuments({
        documents: docs,
        engine,
        kbId: kb.id,
        batchSize,
        onProgress: setProgress,
      });
      setOutcome(result);
      onImported(result);
      setFiles([]);
      setPasteContent("");
      setPasteTitle("");
    } catch (err) {
      setError(String((err as Error).message ?? err));
    } finally {
      unsubscribe();
      setBusy(false);
    }
  };

  const percent =
    progress?.phase === "embedding" && embedSeen.total > 0
      ? 10 + 80 * (embedSeen.processed / embedSeen.total)
      : (progress?.percent ?? 0);

  const stageLabel =
    progress?.phase === "embedding"
      ? `${engine.info?.precision === "q8" ? "INT8" : engine.info?.precision?.toUpperCase() ?? ""} 本地推理 · ${embedSeen.processed}/${embedSeen.total} 块`
      : progress?.phase === "writing"
        ? "写入 + refresh_index + 自查询验证"
        : progress?.detail ?? "准备中";

  const footer = outcome ? (
    <>
      <div className="modal-footer-note">
        新文档已完成索引刷新并通过自查询验证，可立即检索。
      </div>
      <button className="button button-primary" onClick={onClose}>
        完成
      </button>
    </>
  ) : (
    <>
      <div className="modal-footer-note">
        {engine.isReady ? (
          <>
            全程在浏览器本地计算 · 当前 {engine.info?.backend === "webgpu" ? "WebGPU" : "WASM"} /{" "}
            {engine.info?.precision === "q8" ? "INT8" : engine.info?.precision?.toUpperCase()}
          </>
        ) : (
          "等待推理模型加载完成"
        )}
      </div>
      <button
        className="button button-primary"
        disabled={busy || !engine.isReady || docsForTab === 0}
        onClick={startImport}
      >
        {busy ? <Spinner size={15} /> : <ArrowUpRight size={15} />}
        {busy ? "正在导入" : "开始本地导入"}
      </button>
    </>
  );

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={outcome ? "导入完成" : "导入语料"}
      eyebrow={`INGEST / ${kb?.title ?? "未选择知识库"}`}
      width="760px"
      dismissible={!busy}
      footer={footer}
    >
      {outcome ? (
        <div className="import-success">
          <div className="success-mark">
            <CheckIcon size={28} />
          </div>
          <div>
            <h3>
              {outcome.perDocument.length} 篇文档 · {outcome.stats.chunks} 个向量块
            </h3>
            <p>
              seekdb 当前共有 {outcome.stats.documents} 篇文档。索引刷新与自查询验证
              {outcome.verified ? "通过" : "未命中"}。
            </p>
          </div>
          <div className="import-timing-grid">
            <div>
              <span>切分</span>
              <strong>{formatMs(outcome.timings.chunkMs)}</strong>
            </div>
            <div>
              <span>本地向量化</span>
              <strong>{formatMs(outcome.timings.embedMs)}</strong>
            </div>
            <div>
              <span>写入 + 刷新</span>
              <strong>{formatMs(outcome.timings.writeMs)}</strong>
            </div>
            <div>
              <span>HTTP 往返</span>
              <strong>{formatMs(outcome.timings.roundTripMs)}</strong>
            </div>
          </div>
          <div className="import-doc-list">
            {outcome.perDocument.map((doc) => (
              <div key={doc.docId} className="import-doc-row">
                <span className="mono doc-id">{doc.docId}</span>
                <span>{doc.title}</span>
                <Tag tone={doc.isReplace ? "amber" : "lime"}>
                  {doc.isReplace ? "替换" : "新增"} · {doc.chunks} 块
                </Tag>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <>
          <div className="segmented import-tabs">
            <button className={tab === "files" ? "active" : ""} onClick={() => setTab("files")}>
              文件导入
            </button>
            <button className={tab === "paste" ? "active" : ""} onClick={() => setTab("paste")}>
              粘贴文本
            </button>
            <button className={tab === "sample" ? "active" : ""} onClick={() => setTab("sample")}>
              示例语料
            </button>
          </div>

          {tab === "files" ? (
            <div className="import-pane">
              <div
                className={`drop-zone ${dragging ? "dragging" : ""}`}
                onDragOver={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragging(false);
                  addFiles(event.dataTransfer.files);
                }}
                onClick={() => inputRef.current?.click()}
                role="button"
                tabIndex={0}
                onKeyDown={(event) => {
                  if (event.key === "Enter") inputRef.current?.click();
                }}
              >
                <input
                  ref={inputRef}
                  type="file"
                  multiple
                  accept=".txt,.md,.markdown,.text,.json"
                  hidden
                  onChange={(event) => {
                    if (event.target.files) addFiles(event.target.files);
                    event.target.value = "";
                  }}
                />
                <div className="drop-icon">
                  <FileIcon size={22} />
                </div>
                <strong>拖入文本文件，或点击选择</strong>
                <span>.txt / .md / .json · 单文件 ≤ 1MB · 支持多选</span>
              </div>
              {files.length ? (
                <div className="file-queue">
                  {files.map((file) => (
                    <div className="file-row" key={`${file.name}:${file.size}`}>
                      <FileIcon size={15} />
                      <span>{file.name}</span>
                      <small>{formatBytes(file.size)}</small>
                      <button
                        className="icon-button tiny"
                        onClick={() => setFiles((current) => current.filter((item) => item !== file))}
                        aria-label={`移除 ${file.name}`}
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {tab === "paste" ? (
            <div className="import-pane">
              <div className="form-field">
                <label htmlFor="paste-title">标题</label>
                <input
                  id="paste-title"
                  className="text-input"
                  value={pasteTitle}
                  onChange={(event) => setPasteTitle(event.target.value)}
                  placeholder="例如：浏览器端量化实验记录"
                  maxLength={120}
                />
              </div>
              <div className="form-field">
                <label htmlFor="paste-content">正文</label>
                <textarea
                  id="paste-content"
                  className="text-input textarea tall"
                  value={pasteContent}
                  onChange={(event) => setPasteContent(event.target.value)}
                  placeholder="粘贴一段笔记、文档或会议记录。导入时会用 tokenizer 按 400 token / 60 overlap 切分…"
                  rows={9}
                />
                <div className="field-meta">
                  <span>{pasteContent.length.toLocaleString("zh-CN")} 字符</span>
                  <span>原文只写入本机 seekdb</span>
                </div>
              </div>
            </div>
          ) : null}

          {tab === "sample" ? (
            <div className="import-pane">
              <div className="sample-card">
                <div className="sample-card-head">
                  <span className="sample-glyph">
                    <SparkIcon size={22} />
                  </span>
                  <div>
                    <div className="eyebrow">CURATED CORPUS / 27 DOCS</div>
                    <h3>{sampleCorpus.name}</h3>
                    <p>{sampleCorpus.description}</p>
                  </div>
                  <Tag tone="lime">约 {sampleChunksEstimate} 块</Tag>
                </div>
                <div className="sample-topics">
                  {["WebGPU / WASM", "INT8 / FP16", "seekdb 混合检索", "HNSW / IK", "评测方法"].map(
                    (topic) => (
                      <span key={topic}>{topic}</span>
                    ),
                  )}
                </div>
                <div className="sample-list">
                  {sampleDocs.slice(0, 6).map((doc) => (
                    <div key={doc.id}>
                      <span>{doc.title}</span>
                      <small>{doc.category}</small>
                    </div>
                  ))}
                  <div className="sample-more">以及另外 {sampleDocs.length - 6} 篇技术卡片</div>
                </div>
              </div>
              <p className="settings-help">
                示例语料用于端到端演示与检索质量评测。导入会逐篇切块、在浏览器本地生成 512 维向量，并写入当前知识库。
              </p>
            </div>
          ) : null}

          {busy || progress ? (
            <div className="import-progress">
              <div className="import-progress-head">
                <div>
                  <span className="eyebrow">{progress?.title ?? "IMPORTING"}</span>
                  <strong>{stageLabel}</strong>
                </div>
                <span className="mono">{Math.round(percent)}%</span>
              </div>
              <ProgressBar value={percent} tone={percent === 100 ? "lime" : "amber"} />
              <div className="pipeline-steps">
                {[
                  { key: "chunking", label: "切分" },
                  { key: "embedding", label: "本地向量化" },
                  { key: "writing", label: "写入 seekdb" },
                  { key: "done", label: "刷新可检索" },
                ].map((step, index) => {
                  const order = ["chunking", "embedding", "writing", "done"];
                  const current = progress?.phase ?? "chunking";
                  const state =
                    order.indexOf(current) > index
                      ? "done"
                      : order.indexOf(current) === index
                        ? "active"
                        : "todo";
                  return (
                    <span key={step.key} className={`pipeline-step ${state}`}>
                      <i>{state === "done" ? "✓" : index + 1}</i>
                      {step.label}
                    </span>
                  );
                })}
              </div>
            </div>
          ) : null}

          {error ? (
            <div className="inline-alert alert-error">
              <WarningIcon size={16} />
              <p>{error}</p>
            </div>
          ) : null}
        </>
      )}
    </Modal>
  );
}

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
}
