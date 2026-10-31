import type { EngineInfo, LoadProgress } from "../lib/embedding/engine";
import type { HealthResponse, KnowledgeBase } from "../lib/types";
import type { ImportOutcome } from "../lib/ingest";
import type { SearchTiming } from "./SearchResults";
import { MODEL, formatBytes, formatMs, formatTime, shortRevision } from "../lib/model";
import { BoltIcon, CpuIcon, DatabaseIcon, SettingsIcon, WarningIcon } from "./Icons";
import { ProgressBar, Tag } from "./Primitives";

export function Inspector({
  engineInfo,
  engineStatus,
  loadProgress,
  kb,
  health,
  lastImport,
  searchTiming,
  onOpenSettings,
}: {
  engineInfo: EngineInfo | null;
  engineStatus: "idle" | "loading" | "ready" | "error";
  loadProgress: LoadProgress | null;
  kb: KnowledgeBase | null;
  health: HealthResponse | null;
  lastImport: ImportOutcome | null;
  searchTiming: SearchTiming | null;
  onOpenSettings: () => void;
}) {
  const progress = loadProgress?.total
    ? (loadProgress.loaded / loadProgress.total) * 100
    : engineStatus === "loading"
      ? 8
      : 100;

  return (
    <aside className="inspector" aria-label="运行时状态">
      <div className="inspector-head">
        <span className="eyebrow">LIVE INSTRUMENTATION</span>
        <span className="live-pill">
          <i className={`status-dot status-${health?.ok ? "lime" : "coral"}`} />
          local
        </span>
      </div>

      <section className="panel inference-panel">
        <div className="panel-topline">
          <span className="panel-label">
            <CpuIcon size={15} /> INFERENCE
          </span>
          <button className="icon-button tiny" onClick={onOpenSettings} aria-label="打开运行时设置">
            <SettingsIcon size={15} />
          </button>
        </div>

        {engineStatus === "ready" && engineInfo ? (
          <>
            <div className="backend-display">
              <span className={`backend-mark ${engineInfo.backend}`}>
                {engineInfo.backend === "webgpu" ? "GPU" : "CPU"}
              </span>
              <div>
                <strong>{engineInfo.backend === "webgpu" ? "WEBGPU" : "WASM"}</strong>
                <span>{engineInfo.deviceLabel}</span>
              </div>
            </div>
            <div className="pill-row">
              <Tag tone={engineInfo.backend === "webgpu" ? "lime" : "amber"}>
                {MODEL.labels[engineInfo.precision]}
              </Tag>
              <Tag tone="neutral">{formatBytes(MODEL.sizes[engineInfo.precision])}</Tag>
              <Tag tone="neutral">{engineInfo.threads} threads</Tag>
            </div>
            <dl className="mini-facts">
              <div>
                <dt>model</dt>
                <dd>{MODEL.family}</dd>
              </div>
              <div>
                <dt>revision</dt>
                <dd className="mono">{shortRevision()}</dd>
              </div>
              <div>
                <dt>model init</dt>
                <dd>{formatMs(engineInfo.loadMs)}</dd>
              </div>
              <div>
                <dt>cross-origin isolated</dt>
                <dd>{engineInfo.crossOriginIsolated ? "yes" : "no"}</dd>
              </div>
            </dl>
            {engineInfo.fallbackReason ? (
              <div className="fallback-note">
                <WarningIcon size={14} />
                <span>{engineInfo.fallbackReason}</span>
              </div>
            ) : (
              <div className="local-note">
                <BoltIcon size={14} />
                <span>计算发生在当前浏览器进程，无云端推理请求。</span>
              </div>
            )}
          </>
        ) : engineStatus === "loading" ? (
          <div className="engine-loading">
            <div className="engine-loading-head">
              <span>加载 {MODEL.family}</span>
              <strong className="mono">{Math.round(progress)}%</strong>
            </div>
            <ProgressBar value={progress} />
            <p>
              {loadProgress?.file
                ? `${loadProgress.file.split("/").pop()} · ${formatBytes(loadProgress.loaded)}`
                : "初始化 tokenizer 与 ONNX 会话…"}
            </p>
          </div>
        ) : engineStatus === "error" ? (
          <div className="engine-error">
            <WarningIcon size={16} />
            <div>
              <strong>推理引擎未就绪</strong>
              <p>检查模型文件是否存在，或打开设置重试。</p>
              <button className="button button-ghost small" onClick={onOpenSettings}>
                打开设置
              </button>
            </div>
          </div>
        ) : null}
      </section>

      <section className="panel seekdb-panel">
        <div className="panel-topline">
          <span className="panel-label">
            <DatabaseIcon size={15} /> SEEKDB
          </span>
          <span className={`connection-state ${health?.ok ? "ok" : "bad"}`}>
            <i className={`status-dot status-${health?.ok ? "lime" : "coral"}`} />
            {health?.ok ? "connected" : "offline"}
          </span>
        </div>
        <div className="db-endpoint mono">
          {health?.seekdb.host ?? "127.0.0.1"}:{health?.seekdb.port ?? 2881}
          <span>/{health?.seekdb.database ?? "stepfun_kb"}</span>
        </div>
        {kb ? (
          <>
            <div className="db-counts">
              <div>
                <strong>{kb.documents}</strong>
                <span>documents</span>
              </div>
              <div>
                <strong>{kb.chunks}</strong>
                <span>vectors</span>
              </div>
              <div>
                <strong>{kb.embedding.dimension}</strong>
                <span>dims</span>
              </div>
            </div>
            <dl className="index-facts">
              <div>
                <dt>vector</dt>
                <dd>HNSW · cosine</dd>
              </div>
              <div>
                <dt>fulltext</dt>
                <dd>IK · smart</dd>
              </div>
              <div>
                <dt>fusion</dt>
                <dd>RRF k=60</dd>
              </div>
            </dl>
            <div className="collection-foot">
              <span className="mono">{kb.id}</span>
              <span>{formatTime(kb.lastImportAt)}</span>
            </div>
          </>
        ) : (
          <p className="panel-empty">正在读取集合状态…</p>
        )}
      </section>

      <section className="panel trace-panel">
        <div className="panel-topline">
          <span className="panel-label">
            <BoltIcon size={15} /> LAST PIPELINE
          </span>
          <span className="mono">{lastImport ? formatTime(Date.now()) : "—"}</span>
        </div>
        {lastImport ? (
          <>
            <div className="pipeline-metrics">
              <Metric label="chunk" value={formatMs(lastImport.timings.chunkMs)} width={28} />
              <Metric label="embed" value={formatMs(lastImport.timings.embedMs)} width={72} tone="coral" />
              <Metric
                label="write + refresh"
                value={formatMs(lastImport.timings.writeMs)}
                width={46}
                tone="amber"
              />
            </div>
            <div className="verified-row">
              <span className={`verify-dot ${lastImport.verified ? "ok" : "bad"}`} />
              {lastImport.verified
                ? `自查询验证通过 · ${lastImport.stats.chunks} chunks`
                : "索引刷新完成，自查询未命中"}
            </div>
          </>
        ) : (
          <p className="panel-empty">导入语料后，这里显示最后一次写入流水线。</p>
        )}
      </section>

      <section className="panel trace-panel">
        <div className="panel-topline">
          <span className="panel-label">QUERY TRACE</span>
          <span className="mono">{searchTiming ? "last query" : "idle"}</span>
        </div>
        {searchTiming ? (
          <div className="query-trace">
            <span style={{ width: `${Math.max(4, (searchTiming.embedMs / Math.max(searchTiming.e2eMs, 1)) * 100)}%` }} className="trace-embed" />
            <span style={{ width: `${Math.max(4, (searchTiming.seekdbMs / Math.max(searchTiming.e2eMs, 1)) * 100)}%` }} className="trace-db" />
            <span className="trace-rest" />
          </div>
        ) : null}
        <div className="trace-legend">
          <span>
            <i className="dot-embed" /> embed <strong>{formatMs(searchTiming?.embedMs)}</strong>
          </span>
          <span>
            <i className="dot-db" /> seekdb <strong>{formatMs(searchTiming?.seekdbMs)}</strong>
          </span>
          <span>
            <i className="dot-e2e" /> e2e <strong>{formatMs(searchTiming?.e2eMs)}</strong>
          </span>
        </div>
      </section>

      <div className="inspector-foot">
        <span>NO CLOUD INFERENCE</span>
        <span>seekdb-js / 1.4.0</span>
      </div>
    </aside>
  );
}

function Metric({
  label,
  value,
  width,
  tone = "lime",
}: {
  label: string;
  value: string;
  width: number;
  tone?: "lime" | "amber" | "coral";
}) {
  return (
    <div className="pipeline-metric">
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      <div className={`metric-track metric-${tone}`}>
        <i style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}
