import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import sampleCorpus from "../data/sample-corpus.json";
import { api, ApiError } from "./lib/api";
import { embeddingEngine, type EngineInfo, type LoadProgress } from "./lib/embedding/engine";
import { importDocuments, type ImportOutcome } from "./lib/ingest";
import { MODEL, formatMs, formatTime } from "./lib/model";
import type {
  HealthResponse,
  IngestDocument,
  KbDocument,
  KnowledgeBase,
  SearchResponse,
} from "./lib/types";
import { Header } from "./components/Header";
import { Library } from "./components/Library";
import { Inspector } from "./components/Inspector";
import { SearchResults, type SearchTiming } from "./components/SearchResults";
import { SettingsDialog } from "./components/SettingsDialog";
import { ImportDialog } from "./components/ImportDialog";
import { NewKbDialog } from "./components/NewKbDialog";
import { Modal, ProgressBar, Spinner, Tag, Toast } from "./components/Primitives";
import {
  ArrowRight,
  ArrowUpRight,
  BoltIcon,
  CheckIcon,
  ChevronDownIcon,
  CpuIcon,
  DatabaseIcon,
  FileIcon,
  PlusIcon,
  RefreshIcon,
  SearchIcon,
  SparkIcon,
  TrashIcon,
  WarningIcon,
} from "./components/Icons";
import { LabView } from "./lab/LabView";

type EngineStatus = "idle" | "loading" | "ready" | "error";
type SearchMode = "hybrid" | "vector" | "fulltext";

const SAMPLE_COUNT = sampleCorpus.documents.length;
const DEFAULT_QUERY = "seekdb 如何把关键词和语义两路结果融合排序？";

export default function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [detail, setDetail] = useState<{
    collection: KnowledgeBase;
    documents: KbDocument[];
  } | null>(null);
  const [booted, setBooted] = useState(false);
  const [bootError, setBootError] = useState<string | null>(null);

  const [engineStatus, setEngineStatus] = useState<EngineStatus>("idle");
  const [engineInfo, setEngineInfo] = useState<EngineInfo | null>(null);
  const [loadProgress, setLoadProgress] = useState<LoadProgress | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [backendPref, setBackendPref] = useState<"auto" | "wasm">(
    () => (localStorage.getItem("edge-atlas-backend") as "auto" | "wasm") || "auto",
  );
  const [precisionPref, setPrecisionPref] = useState<"auto" | "fp32" | "fp16" | "q8">(
    () => (localStorage.getItem("edge-atlas-precision") as "auto" | "fp32" | "fp16" | "q8") || "auto",
  );
  const [batchSize, setBatchSize] = useState<number>(
    () => Number(localStorage.getItem("edge-atlas-batch")) || 16,
  );

  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [topK, setTopK] = useState(8);
  const [searching, setSearching] = useState(false);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchTiming, setSearchTiming] = useState<SearchTiming | null>(null);
  const [lastImport, setLastImport] = useState<ImportOutcome | null>(null);
  const [docsOpen, setDocsOpen] = useState(false);

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [newKbOpen, setNewKbOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importTab, setImportTab] = useState<"files" | "paste" | "sample">("files");
  const [view, setView] = useState<"atlas" | "lab">("atlas");
  const [toast, setToast] = useState<{ message: string; tone: "success" | "error" | "info" } | null>(
    null,
  );
  const [deleteKbTarget, setDeleteKbTarget] = useState<KnowledgeBase | null>(null);
  const [deleteDocTarget, setDeleteDocTarget] = useState<KbDocument | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const initSeq = useRef(0);
  const clientReady = health?.ok ?? false;
  const showOffline = health ? !health.ok : booted && Boolean(bootError);
  const activeKb = detail?.collection ?? kbs.find((kb) => kb.id === activeId) ?? null;
  const documents = detail?.documents ?? [];
  const hasDocs = (activeKb?.documents ?? 0) > 0;
  const canSearch = engineStatus === "ready" && hasDocs && clientReady && !searching;

  useEffect(() => {
    const offLoad = embeddingEngine.onLoadProgress((progress) => setLoadProgress(progress));
    const offStatus = embeddingEngine.onStatus((status) => {
      setLoadProgress((current) => ({
        phase: "status",
        status: "status",
        file: "",
        loaded: 0,
        total: 0,
        progress: 0,
        message: status.message,
        ...(current ?? {}),
      }));
    });
    return () => {
      offLoad();
      offStatus();
    };
  }, []);

  useEffect(() => {
    localStorage.setItem("edge-atlas-backend", backendPref);
    localStorage.setItem("edge-atlas-precision", precisionPref);
    localStorage.setItem("edge-atlas-batch", String(batchSize));
  }, [backendPref, precisionPref, batchSize]);

  const initializeEngine = useCallback(
    async (overridePrecision?: "auto" | "fp32" | "fp16" | "q8") => {
      const seq = ++initSeq.current;
      setEngineStatus("loading");
      setLoadError(null);
      setLoadProgress(null);
      try {
        const info = await embeddingEngine.init({
          backend: backendPref,
          precision: overridePrecision ?? precisionPref,
        });
        if (seq !== initSeq.current) return;
        setEngineInfo(info);
        setEngineStatus("ready");
        setLoadProgress(null);
        if (info.fallbackReason) {
          setToast({ message: "WebGPU 不可用，已自动降级到 WASM 后端。", tone: "info" });
        }
      } catch (error) {
        if (seq !== initSeq.current) return;
        setEngineInfo(null);
        setEngineStatus("error");
        setLoadError(String((error as Error).message ?? error));
      }
    },
    [backendPref, precisionPref],
  );

  useEffect(() => {
    void initializeEngine();
  }, [initializeEngine]);

  useEffect(() => {
    const kbPrecision = activeKb?.precision;
    if (!kbPrecision || precisionPref !== "auto" || engineStatus !== "ready" || !engineInfo) return;
    if (engineInfo.precision === kbPrecision) return;
    // Keep an existing collection searchable after a backend fallback or on a
    // machine where WebGPU is unavailable: rebuild the runtime in the same
    // precision the collection was indexed with.
    void initializeEngine(kbPrecision);
  }, [
    activeKb?.id,
    activeKb?.precision,
    precisionPref,
    engineStatus,
    engineInfo,
    initializeEngine,
  ]);

  const loadActive = useCallback(async (id: string, opts: { quiet?: boolean } = {}) => {
    try {
      const payload = await api.getKb(id);
      setDetail(payload);
      if (!opts.quiet) {
        setActiveId(id);
        localStorage.setItem("edge-atlas-active-kb", id);
      }
    } catch (error) {
      if (!opts.quiet) {
        setToast({ message: String((error as Error).message ?? error), tone: "error" });
      }
    }
  }, []);

  const refreshCollections = useCallback(
    async (preferredId?: string) => {
      const payload = await api.listKbs();
      setKbs(payload.collections);
      const stored = localStorage.getItem("edge-atlas-active-kb");
      const desired =
        preferredId ??
        (payload.collections.some((kb) => kb.id === activeId) ? activeId : null) ??
        (payload.collections.some((kb) => kb.id === stored) ? stored : null) ??
        payload.defaultId ??
        payload.collections[0]?.id ??
        null;
      if (desired) {
        setActiveId(desired);
        localStorage.setItem("edge-atlas-active-kb", desired);
        await loadActive(desired);
      } else {
        setDetail(null);
        setActiveId(null);
      }
      return payload.collections;
    },
    [activeId, loadActive],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [healthPayload, listPayload] = await Promise.all([api.health(), api.listKbs()]);
        if (cancelled) return;
        setHealth(healthPayload);
        setKbs(listPayload.collections);
        const stored = localStorage.getItem("edge-atlas-active-kb");
        const desired =
          listPayload.collections.find((kb) => kb.id === stored)?.id ??
          listPayload.defaultId ??
          listPayload.collections[0]?.id ??
          null;
        if (desired) {
          setActiveId(desired);
          localStorage.setItem("edge-atlas-active-kb", desired);
          await loadActive(desired, { quiet: true });
          if (!cancelled) setActiveId(desired);
        }
      } catch (error) {
        if (!cancelled) {
          setBootError(String((error as Error).message ?? error));
        }
      } finally {
        if (!cancelled) setBooted(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadActive]);

  useEffect(() => {
    const tick = async () => {
      try {
        const payload = await api.health();
        setHealth(payload);
        if (payload.ok && kbs.length === 0) {
          await refreshCollections();
        }
      } catch {
        setHealth((current) =>
          current
            ? { ...current, ok: false }
            : {
                ok: false,
                time: new Date().toISOString(),
                service: "stepfun-edge-atlas",
                version: "1.0.0",
                seekdb: {
                  connected: false,
                  database: "stepfun_kb",
                  host: "127.0.0.1",
                  port: 2881,
                  lastError: "unreachable",
                  mode: "server",
                },
                embedding: {
                  model: MODEL.id,
                  revision: MODEL.revision,
                  dimension: 512,
                  distance: "cosine",
                },
                runtime: {
                  inference: "browser-local",
                  cloudInference: false,
                  expectedBackends: ["webgpu", "wasm"],
                },
              },
        );
      }
    };
    const timer = window.setInterval(tick, 8000);
    return () => window.clearInterval(timer);
  }, [kbs.length, refreshCollections]);

  const runSearch = useCallback(
    async (textArg?: string, modeArg?: SearchMode) => {
      const text = (textArg ?? query).trim();
      const selectedMode = modeArg ?? mode;
      if (!text || !activeKb || !clientReady) return;
      if (engineStatus !== "ready" || !embeddingEngine.isReady) {
        setSearchError("推理引擎尚未就绪，请等待模型加载。");
        return;
      }
      if (!hasDocs) {
        setSearchError("当前知识库还没有文档，请先导入语料。");
        return;
      }
      setQuery(text);
      setSearching(true);
      setSearchError(null);
      setResult(null);
      const totalStart = performance.now();
      try {
        const embedStart = performance.now();
        const embedded = await embeddingEngine.embed([text], 1, "query");
        const embedMs = performance.now() - embedStart;
        const vector = embedded.vectors[0];
        const response = await api.search(activeKb.id, {
          query: text,
          embedding: vector,
          mode: selectedMode,
          topK,
        });
        const withoutRender = performance.now() - totalStart;
        setResult(response);
        setSearching(false);
        window.requestAnimationFrame(() => {
          const e2e = performance.now() - totalStart;
          setSearchTiming({
            embedMs,
            seekdbMs: response.timings.seekdbMs,
            e2eMs: e2e,
            renderMs: Math.max(0, e2e - withoutRender),
          });
        });
      } catch (error) {
        setSearchError(String((error as Error).message ?? error));
        setSearching(false);
      }
    },
    [query, mode, activeKb, clientReady, engineStatus, hasDocs, topK],
  );

  const openImport = (tab: "files" | "paste" | "sample" = "files") => {
    if (!activeKb) {
      setNewKbOpen(true);
      return;
    }
    setImportTab(tab);
    setImportOpen(true);
  };

  const handleCreated = async (kb: KnowledgeBase) => {
    setToast({ message: `知识库「${kb.title}」已创建。`, tone: "success" });
    await refreshCollections(kb.id);
    setResult(null);
  };

  const handleImported = async (outcome: ImportOutcome) => {
    setLastImport(outcome);
    await refreshCollections(activeId ?? undefined);
    setResult(null);
    setToast({
      message: `导入完成：${outcome.perDocument.length} 篇文档，索引已验证可检索。`,
      tone: "success",
    });
  };

  const requestDeleteKb = (kb: KnowledgeBase) => {
    setDeleteError(null);
    setDeleteKbTarget(kb);
  };

  const confirmDeleteKb = async () => {
    if (!deleteKbTarget) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.deleteKb(deleteKbTarget.id);
      const remaining = kbs.filter((kb) => kb.id !== deleteKbTarget.id);
      setDeleteKbTarget(null);
      setToast({ message: "知识库及其索引已删除。", tone: "success" });
      setResult(null);
      await refreshCollections(remaining[0]?.id);
    } catch (error) {
      setDeleteError(String((error as Error).message ?? error));
    } finally {
      setDeleteBusy(false);
    }
  };

  const confirmDeleteDoc = async () => {
    if (!deleteDocTarget || !activeKb) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.deleteDocument(activeKb.id, deleteDocTarget.docId);
      setDeleteDocTarget(null);
      setToast({ message: "文档及其向量块已从 seekdb 删除。", tone: "success" });
      await refreshCollections(activeKb.id);
      setResult(null);
    } catch (error) {
      setDeleteError(String((error as Error).message ?? error));
    } finally {
      setDeleteBusy(false);
    }
  };

  const engineBanner = useMemo(() => {
    if (engineStatus === "loading") {
      const percent = loadProgress?.total
        ? Math.min(100, (loadProgress.loaded / loadProgress.total) * 100)
        : 5;
      return (
        <div className="engine-banner loading">
          <div className="engine-banner-text">
            <Spinner size={14} />
            <span>
              正在准备端侧推理 ·{" "}
              {loadProgress?.phase === "tokenizer" ? "加载 tokenizer" : "加载 ONNX 权重"}
            </span>
            <small className="mono">
              {loadProgress?.file ? loadProgress.file.split("/").pop() : "initializing"}
            </small>
          </div>
          <ProgressBar value={percent} />
        </div>
      );
    }
    if (engineStatus === "error") {
      return (
        <div className="engine-banner error">
          <WarningIcon size={16} />
          <span>推理引擎加载失败：{loadError}</span>
          <button className="text-button light" onClick={() => void initializeEngine()}>
            重试
          </button>
        </div>
      );
    }
    return null;
  }, [engineStatus, loadProgress, loadError, initializeEngine]);

  if (view === "lab") {
    return (
      <div className="app-shell">
        <Header
          engineInfo={engineInfo}
          engineStatus={engineStatus}
          health={health}
          view={view}
          onView={setView}
          onSettings={() => setSettingsOpen(true)}
        />
        <LabView
          engine={embeddingEngine}
          engineInfo={engineInfo}
          health={health}
          activeKb={activeKb}
          onToast={setToast}
        />
        <SettingsDialog
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          backendPref={backendPref}
          setBackendPref={setBackendPref}
          precisionPref={precisionPref}
          setPrecisionPref={setPrecisionPref}
          batchSize={batchSize}
          setBatchSize={setBatchSize}
          engineInfo={engineInfo}
          engineStatus={engineStatus}
          loadProgress={loadProgress}
          loadError={loadError}
          onReload={() => void initializeEngine()}
        />
        {toast ? (
          <Toast message={toast.message} tone={toast.tone} onClose={() => setToast(null)} />
        ) : null}
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Header
        engineInfo={engineInfo}
        engineStatus={engineStatus}
        health={health}
        view={view}
        onView={setView}
        onSettings={() => setSettingsOpen(true)}
      />

      <div className="app-grid">
        <Library
          collections={kbs}
          activeId={activeId}
          onSelect={async (id) => {
            setActiveId(id);
            localStorage.setItem("edge-atlas-active-kb", id);
            setResult(null);
            setQuery("");
            setSearchError(null);
            await loadActive(id);
          }}
          onNew={() => setNewKbOpen(true)}
          onDelete={requestDeleteKb}
        />

        <main className="stage">
          {showOffline ? (
            <div className="offline-banner">
              <div className="offline-icon">
                <DatabaseIcon size={20} />
              </div>
              <div>
                <strong>seekdb 未连接</strong>
                <p>
                  应用正在自动重试 127.0.0.1:2881。启动本地数据库：{" "}
                  <code>docker compose up -d seekdb</code>
                  {bootError ? <span className="offline-raw"> · {bootError}</span> : null}
                </p>
              </div>
              <button className="button button-ghost small" onClick={() => void refreshCollections()}>
                <RefreshIcon size={14} /> 重试
              </button>
            </div>
          ) : null}

          {engineBanner}

          {activeKb ? (
            <>
              <section className="hero">
                <div className="hero-copy">
                  <div className="eyebrow hero-eyebrow">
                    <span className="pulse-dot" />
                    LOCAL KNOWLEDGE BASE
                    <span className="eyebrow-rule" />
                    <span className="mono">{activeKb.id}</span>
                  </div>
                  <h1>{activeKb.title}</h1>
                  <p className="hero-description">
                    {activeKb.description ||
                      "导入文本，在浏览器本地生成向量，再由 seekdb 完成语义与全文混合检索。原文与向量都留在你自己的设备里。"}
                  </p>
                  <div className="hero-meta">
                    <span>
                      <strong>{activeKb.documents}</strong> documents
                    </span>
                    <span>
                      <strong>{activeKb.chunks}</strong> vectors
                    </span>
                    <span>
                      <strong>{activeKb.embedding.dimension}</strong> dims
                    </span>
                    <span className="hero-meta-engine">
                      <i className={`status-dot status-${engineStatus === "ready" ? "lime" : "amber"}`} />
                      {engineInfo
                        ? `${engineInfo.backend === "webgpu" ? "WebGPU" : "WASM"} · ${
                            engineInfo.precision === "q8" ? "INT8" : engineInfo.precision.toUpperCase()
                          }`
                        : "model loading"}
                    </span>
                  </div>
                </div>
                <HeroDiagram />
              </section>

              <form
                className={`search-shell ${searching ? "busy" : ""}`}
                onSubmit={(event) => {
                  event.preventDefault();
                  void runSearch();
                }}
              >
                <div className="search-line">
                  <SearchIcon size={20} />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder={
                      hasDocs
                        ? "问一个需要跨文档理解的问题…"
                        : "这个知识库还没有内容，先导入语料"
                    }
                    aria-label="检索问题"
                    disabled={!canSearch && !searching}
                    autoComplete="off"
                  />
                  <kbd className="search-kbd">↵</kbd>
                  <button className="search-submit" type="submit" disabled={!canSearch || !query.trim()}>
                    {searching ? <Spinner size={16} /> : <ArrowUpRight size={17} />}
                    <span>{searching ? "检索中" : "检索"}</span>
                  </button>
                </div>
                <div className="search-options">
                  <div className="segmented mode-switch" role="group" aria-label="检索模式">
                    <button
                      type="button"
                      className={mode === "hybrid" ? "active" : ""}
                      onClick={() => {
                        setMode("hybrid");
                        if (result) void runSearch(query, "hybrid");
                      }}
                    >
                      混合检索 <small>HYBRID</small>
                    </button>
                    <button
                      type="button"
                      className={mode === "vector" ? "active" : ""}
                      onClick={() => {
                        setMode("vector");
                        if (result) void runSearch(query, "vector");
                      }}
                    >
                      纯向量 <small>VECTOR</small>
                    </button>
                    <button
                      type="button"
                      className={mode === "fulltext" ? "active" : ""}
                      onClick={() => {
                        setMode("fulltext");
                        if (result) void runSearch(query, "fulltext");
                      }}
                    >
                      全文 <small>FULLTEXT</small>
                    </button>
                  </div>
                  <div className="search-side-options">
                    <label>
                      topK
                      <select value={topK} onChange={(event) => setTopK(Number(event.target.value))}>
                        <option value={5}>5</option>
                        <option value={8}>8</option>
                        <option value={12}>12</option>
                      </select>
                    </label>
                    <span className="search-hint">查询向量仅在本机计算</span>
                  </div>
                </div>
              </form>

              {hasDocs ? (
                <SearchResults
                  query={query}
                  mode={mode}
                  result={result}
                  loading={searching}
                  error={searchError}
                  timing={searchTiming}
                  topK={topK}
                  onQuickQuery={(text) => void runSearch(text)}
                />
              ) : (
                <EmptyKnowledge
                  onImport={() => openImport("files")}
                  onSample={() => openImport("sample")}
                  onNewKb={() => setNewKbOpen(true)}
                />
              )}

              {hasDocs ? (
                <section className={`doc-shelf ${docsOpen ? "open" : ""}`}>
                  <button className="doc-shelf-head" onClick={() => setDocsOpen((open) => !open)}>
                    <span className="panel-label">
                      <FileIcon size={15} /> INDEXED DOCUMENTS
                    </span>
                    <span className="doc-shelf-count">
                      {documents.length} docs · {activeKb.chunks} chunks
                    </span>
                    <span className="doc-shelf-actions">
                      <span
                        className="text-button"
                        role="button"
                        tabIndex={0}
                        onClick={(event) => {
                          event.stopPropagation();
                          openImport("files");
                        }}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.stopPropagation();
                            openImport("files");
                          }
                        }}
                      >
                        <PlusIcon size={14} /> 增量导入
                      </span>
                      <ChevronDownIcon size={16} className="chevron" />
                    </span>
                  </button>
                  {docsOpen ? (
                    <div className="doc-table">
                      {documents.map((doc) => (
                        <div className="doc-row" key={doc.docId}>
                          <span className="doc-row-icon">
                            <FileIcon size={15} />
                          </span>
                          <div className="doc-row-main">
                            <strong>{doc.title}</strong>
                            <span className="mono">{doc.docId}</span>
                          </div>
                          <span className="doc-category">{doc.category}</span>
                          <span className="doc-chunks">{doc.chunks} chunks</span>
                          <span className="doc-time">{formatTime(doc.importedAt)}</span>
                          <button
                            className="icon-button tiny doc-delete"
                            onClick={() => {
                              setDeleteError(null);
                              setDeleteDocTarget(doc);
                            }}
                            aria-label={`删除 ${doc.title}`}
                          >
                            <TrashIcon size={14} />
                          </button>
                        </div>
                      ))}
                      {documents.length === 0 ? (
                        <div className="doc-empty">状态同步中…</div>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              ) : null}
            </>
          ) : (
            <div className="boot-state">
              {booted ? (
                <>
                  <DatabaseIcon size={28} />
                  <h1>等待 seekdb</h1>
                  <p>数据库连接恢复后会自动载入知识库。你也可以先检查本地服务。</p>
                  <button className="button button-primary" onClick={() => void refreshCollections()}>
                    <RefreshIcon size={15} /> 重新连接
                  </button>
                </>
              ) : (
                <>
                  <Spinner size={24} />
                  <p>正在载入知识库…</p>
                </>
              )}
            </div>
          )}

          <footer className="stage-foot">
            <span>EDGE ATLAS / 2026</span>
            <span>端侧推理 · seekdb 混合检索 · 无云端 API</span>
            <button className="text-button" onClick={() => setView("lab")}>
              <BoltIcon size={14} /> 打开性能评测台
            </button>
          </footer>
        </main>

        <Inspector
          engineInfo={engineInfo}
          engineStatus={engineStatus}
          loadProgress={loadProgress}
          kb={activeKb}
          health={health}
          lastImport={lastImport}
          searchTiming={searchTiming}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      </div>

      <SettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        backendPref={backendPref}
        setBackendPref={setBackendPref}
        precisionPref={precisionPref}
        setPrecisionPref={setPrecisionPref}
        batchSize={batchSize}
        setBatchSize={setBatchSize}
        engineInfo={engineInfo}
        engineStatus={engineStatus}
        loadProgress={loadProgress}
        loadError={loadError}
        onReload={() => void initializeEngine()}
      />

      <NewKbDialog open={newKbOpen} onClose={() => setNewKbOpen(false)} onCreated={handleCreated} />

      <ImportDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        kb={activeKb}
        engine={embeddingEngine}
        batchSize={batchSize}
        onImported={handleImported}
        initialTab={importTab}
      />

      <Modal
        open={Boolean(deleteKbTarget)}
        onClose={() => setDeleteKbTarget(null)}
        title="删除知识库？"
        eyebrow="DESTRUCTIVE ACTION"
        width="500px"
        dismissible={!deleteBusy}
        footer={
          <>
            <div className="modal-footer-note">此操作会删除 seekdb collection 及其中全部向量。</div>
            <button className="button button-danger" onClick={confirmDeleteKb} disabled={deleteBusy}>
              {deleteBusy ? <Spinner size={14} /> : <TrashIcon size={15} />} 确认删除
            </button>
          </>
        }
      >
        <p className="confirm-copy">
          知识库「<strong>{deleteKbTarget?.title}</strong>」中的{" "}
          <strong>{deleteKbTarget?.documents ?? 0}</strong> 篇文档与{" "}
          <strong>{deleteKbTarget?.chunks ?? 0}</strong> 个向量块将被永久删除。
        </p>
        {deleteError ? (
          <div className="inline-alert alert-error">
            <WarningIcon size={16} />
            <p>{deleteError}</p>
          </div>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(deleteDocTarget)}
        onClose={() => setDeleteDocTarget(null)}
        title="删除这篇文档？"
        eyebrow="REMOVE FROM INDEX"
        width="500px"
        dismissible={!deleteBusy}
        footer={
          <>
            <div className="modal-footer-note">索引刷新后，该文档将不再出现在检索结果中。</div>
            <button className="button button-danger" onClick={confirmDeleteDoc} disabled={deleteBusy}>
              {deleteBusy ? <Spinner size={14} /> : <TrashIcon size={15} />} 删除文档
            </button>
          </>
        }
      >
        <p className="confirm-copy">
          「<strong>{deleteDocTarget?.title}</strong>」的 {deleteDocTarget?.chunks ?? 0} 个文本块会从
          seekdb 中删除。
        </p>
        {deleteError ? (
          <div className="inline-alert alert-error">
            <WarningIcon size={16} />
            <p>{deleteError}</p>
          </div>
        ) : null}
      </Modal>

      {toast ? (
        <Toast message={toast.message} tone={toast.tone} onClose={() => setToast(null)} />
      ) : null}
    </div>
  );
}

function HeroDiagram() {
  return (
    <div className="hero-visual" aria-hidden="true">
      <div className="visual-coord top">LOCAL / 512D</div>
      <div className="radar">
        <div className="radar-ring ring-a" />
        <div className="radar-ring ring-b" />
        <div className="radar-ring ring-c" />
        <div className="radar-axis x" />
        <div className="radar-axis y" />
        <div className="radar-sweep" />
        <div className="radar-core">
          <strong>512</strong>
          <span>DIM</span>
        </div>
        <span className="radar-node node-1">
          <i />
          HNSW
        </span>
        <span className="radar-node node-2">
          <i />
          IK
        </span>
        <span className="radar-node node-3">
          <i />
          RRF
        </span>
        <span className="radar-node node-4">
          <i />
          LOCAL
        </span>
      </div>
      <div className="visual-coord bottom">36.08°N / 120.38°E</div>
    </div>
  );
}

function EmptyKnowledge({
  onImport,
  onSample,
  onNewKb,
}: {
  onImport: () => void;
  onSample: () => void;
  onNewKb: () => void;
}) {
  return (
    <section className="empty-knowledge">
      <div className="empty-head">
        <span className="empty-glyph">
          <SparkIcon size={26} />
        </span>
        <div>
          <span className="eyebrow">EMPTY COLLECTION / 0 VECTORS</span>
          <h2>把第一段知识放进来。</h2>
          <p>
            文档会在浏览器里切成 400 token 的块，由 BGE 生成 512 维向量，再写入 seekdb 的
            HNSW 与全文索引。
          </p>
        </div>
      </div>
      <div className="empty-actions">
        <button className="empty-action primary" onClick={onImport}>
          <span className="empty-action-icon">
            <FileIcon size={20} />
          </span>
          <strong>导入本地文件</strong>
          <span>.txt / .md / .json · 可多选</span>
          <ArrowRight size={17} />
        </button>
        <button className="empty-action" onClick={onSample}>
          <span className="empty-action-icon">
            <DatabaseIcon size={20} />
          </span>
          <strong>载入示例语料</strong>
          <span>{SAMPLE_COUNT} 篇技术卡片 · 20 条评测查询</span>
          <ArrowRight size={17} />
        </button>
      </div>
      <div className="empty-pipeline">
        {[
          { index: "01", title: "CHUNK", detail: "token 窗口切分" },
          { index: "02", title: "EMBED", detail: "浏览器本地推理" },
          { index: "03", title: "INDEX", detail: "seekdb HNSW + IK" },
          { index: "04", title: "RETRIEVE", detail: "DB 内 RRF 融合" },
        ].map((step) => (
          <div key={step.index}>
            <span className="mono">{step.index}</span>
            <strong>{step.title}</strong>
            <small>{step.detail}</small>
          </div>
        ))}
      </div>
      <button className="text-button empty-new-kb" onClick={onNewKb}>
        <PlusIcon size={14} /> 或创建一个新的独立知识库
      </button>
    </section>
  );
}
