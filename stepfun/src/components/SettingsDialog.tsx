import type {
  BackendPreference,
  EngineInfo,
  LoadProgress,
  PrecisionPreference,
} from "../lib/embedding/engine";
import { MODEL, compressionRatio, formatBytes, shortRevision } from "../lib/model";
import { Modal, ProgressBar, Spinner, Tag } from "./Primitives";
import { CheckIcon, CpuIcon, RefreshIcon, WarningIcon } from "./Icons";

type EngineStatus = "idle" | "loading" | "ready" | "error";

const precisionOptions: Array<{
  value: PrecisionPreference;
  label: string;
  size: string;
  hint: string;
}> = [
  {
    value: "auto",
    label: "自动",
    size: "按后端",
    hint: "WebGPU → FP16 / WASM → INT8",
  },
  { value: "q8", label: "INT8", size: formatBytes(MODEL.sizes.q8), hint: `压缩 ${compressionRatio("q8").toFixed(2)}×` },
  { value: "fp16", label: "FP16", size: formatBytes(MODEL.sizes.fp16), hint: `压缩 ${compressionRatio("fp16").toFixed(2)}×` },
  { value: "fp32", label: "FP32", size: formatBytes(MODEL.sizes.fp32), hint: "量化前基线" },
];

export function SettingsDialog({
  open,
  onClose,
  backendPref,
  setBackendPref,
  precisionPref,
  setPrecisionPref,
  batchSize,
  setBatchSize,
  engineInfo,
  engineStatus,
  loadProgress,
  loadError,
  onReload,
}: {
  open: boolean;
  onClose: () => void;
  backendPref: BackendPreference;
  setBackendPref: (value: "auto" | "wasm") => void;
  precisionPref: PrecisionPreference;
  setPrecisionPref: (value: PrecisionPreference) => void;
  batchSize: number;
  setBatchSize: (value: number) => void;
  engineInfo: EngineInfo | null;
  engineStatus: EngineStatus;
  loadProgress: LoadProgress | null;
  loadError: string | null;
  onReload: () => void;
}) {
  const percent = loadProgress?.total
    ? Math.min(100, (loadProgress.loaded / loadProgress.total) * 100)
    : loadProgress?.phase === "tokenizer"
      ? 3
      : 0;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="推理与索引设置"
      eyebrow="RUNTIME / 端侧运行时"
      width="680px"
      footer={
        <>
          <div className="modal-footer-note">
            修改后端或精度会重新初始化 Worker；知识库向量维度保持 512 不变。
          </div>
          <button
            className="button button-primary"
            onClick={onReload}
            disabled={engineStatus === "loading"}
          >
            {engineStatus === "loading" ? <Spinner size={15} /> : <RefreshIcon size={15} />}
            重新加载模型
          </button>
        </>
      }
    >
      <section className="settings-section">
        <div className="settings-title">
          <span>执行后端</span>
          <span className={`status-dot status-${
            engineInfo?.backend === "webgpu" ? "lime" : engineInfo ? "amber" : "dim"
          }`} />
        </div>
        <div className="choice-grid choice-grid-2">
          <button
            className={`choice-card ${backendPref === "auto" ? "active" : ""}`}
            onClick={() => setBackendPref("auto")}
          >
            <span className="choice-icon">
              <CpuIcon size={19} />
            </span>
            <span className="choice-copy">
              <strong>自动 · 优先 WebGPU</strong>
              <small>不支持 WebGPU 或适配器失败时，自动重载 WASM 会话</small>
            </span>
            {backendPref === "auto" ? (
              <span className="choice-check">
                <CheckIcon size={14} />
              </span>
            ) : null}
          </button>
          <button
            className={`choice-card ${backendPref === "wasm" ? "active" : ""}`}
            onClick={() => setBackendPref("wasm")}
          >
            <span className="choice-icon">
              <span className="wasm-mark">W</span>
            </span>
            <span className="choice-copy">
              <strong>WASM · 兼容模式</strong>
              <small>CPU 执行，适合验证降级路径；默认使用 INT8</small>
            </span>
            {backendPref === "wasm" ? (
              <span className="choice-check">
                <CheckIcon size={14} />
              </span>
            ) : null}
          </button>
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-title">
          <span>模型精度</span>
          <Tag tone="neutral">同一模型 · 可互换量化</Tag>
        </div>
        <div className="precision-grid">
          {precisionOptions.map((option) => {
            const active = precisionPref === option.value;
            return (
              <button
                key={option.value}
                className={`precision-card ${active ? "active" : ""}`}
                onClick={() => setPrecisionPref(option.value)}
              >
                <strong>{option.label}</strong>
                <span>{option.size}</span>
                <small>{option.hint}</small>
                {active ? <i className="precision-check">●</i> : null}
              </button>
            );
          })}
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-title">
          <span>文档向量化批大小</span>
          <span className="mono muted">batch size</span>
        </div>
        <div className="segmented inline">
          {[4, 8, 16, 32].map((size) => (
            <button
              key={size}
              className={batchSize === size ? "active" : ""}
              onClick={() => setBatchSize(size)}
            >
              {size}
            </button>
          ))}
        </div>
        <p className="settings-help">
          批量越大吞吐通常越高，但更占内存并增加单批延迟。基准测试会比较 1 / 8 / 16 / 32。
        </p>
      </section>

      {engineStatus === "loading" ? (
        <div className="settings-loading">
          <div className="settings-loading-head">
            <Spinner size={16} />
            <span>
              正在加载 {MODEL.family}
              {loadProgress?.phase === "model" ? " 模型权重" : " tokenizer"}
              {loadProgress?.total
                ? ` · ${formatBytes(loadProgress.loaded)} / ${formatBytes(loadProgress.total)}`
                : "…"}
            </span>
          </div>
          <ProgressBar value={percent} />
        </div>
      ) : loadError ? (
        <div className="inline-alert alert-error">
          <WarningIcon size={16} />
          <div>
            <strong>模型加载失败</strong>
            <p>{loadError}</p>
          </div>
        </div>
      ) : engineInfo ? (
        <div className="runtime-facts">
          <div>
            <span>实际后端</span>
            <strong>{engineInfo.backend === "webgpu" ? "WEBGPU" : "WASM"}</strong>
          </div>
          <div>
            <span>实际精度</span>
            <strong>{MODEL.labels[engineInfo.precision]}</strong>
          </div>
          <div>
            <span>设备</span>
            <strong title={engineInfo.deviceLabel}>{engineInfo.deviceLabel}</strong>
          </div>
          <div>
            <span>WASM 线程</span>
            <strong>{engineInfo.threads}</strong>
          </div>
          <div>
            <span>模型加载</span>
            <strong>{engineInfo.loadMs} ms</strong>
          </div>
          <div>
            <span>模型 revision</span>
            <strong className="mono">{shortRevision()}</strong>
          </div>
        </div>
      ) : null}

      <section className="model-provenance">
        <div>
          <div className="eyebrow">MODEL PROVENANCE</div>
          <p>
            {MODEL.id} · {MODEL.layers} layers · {MODEL.dimension}d · max {MODEL.maxTokens} tokens
          </p>
          <p className="mono muted">
            来源 huggingface.co/{MODEL.id} @ {MODEL.revision.slice(0, 12)} · {MODEL.license}
          </p>
        </div>
        <div className="size-ladder">
          <span>FP32 {formatBytes(MODEL.sizes.fp32)}</span>
          <span>FP16 {formatBytes(MODEL.sizes.fp16)}</span>
          <span>INT8 {formatBytes(MODEL.sizes.q8)}</span>
        </div>
      </section>
    </Modal>
  );
}
