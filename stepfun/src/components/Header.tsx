import type { EngineInfo } from "../lib/embedding/engine";
import type { HealthResponse } from "../lib/types";
import { FlaskIcon, OrbitIcon, SettingsIcon } from "./Icons";
import { Spinner } from "./Primitives";

export function Header({
  engineInfo,
  engineStatus,
  health,
  view,
  onView,
  onSettings,
}: {
  engineInfo: EngineInfo | null;
  engineStatus: "idle" | "loading" | "ready" | "error";
  health: HealthResponse | null;
  view: "atlas" | "lab";
  onView: (view: "atlas" | "lab") => void;
  onSettings: () => void;
}) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">
          <OrbitIcon size={25} />
        </span>
        <span className="brand-copy">
          <strong>EDGE ATLAS</strong>
          <small>阶跃星辰 × seekdb</small>
        </span>
      </div>

      <div className="topbar-context">
        <span className="context-index">01</span>
        <span>browser-local embeddings</span>
        <i />
        <span className="context-index">02</span>
        <span>seekdb hybrid retrieval</span>
      </div>

      <div className="topbar-actions">
        <nav className="view-switch" aria-label="视图切换">
          <button className={view === "atlas" ? "active" : ""} onClick={() => onView("atlas")}>
            Atlas
          </button>
          <button className={view === "lab" ? "active" : ""} onClick={() => onView("lab")}>
            <FlaskIcon size={14} />
            Lab
          </button>
        </nav>
        <button className="runtime-pill" onClick={onSettings}>
          {engineStatus === "loading" ? (
            <Spinner size={12} />
          ) : (
            <i
              className={`status-dot status-${
                engineStatus === "ready" && engineInfo?.backend === "webgpu"
                  ? "lime"
                  : engineStatus === "ready"
                    ? "amber"
                    : "coral"
              }`}
            />
          )}
          <span className="mono">
            {engineStatus === "loading"
              ? "LOADING"
              : engineInfo
                ? `${engineInfo.backend === "webgpu" ? "WebGPU" : "WASM"} / ${
                    engineInfo.precision === "q8" ? "INT8" : engineInfo.precision.toUpperCase()
                  }`
                : "OFFLINE"}
          </span>
        </button>
        <button className="icon-button topbar-settings" onClick={onSettings} aria-label="运行时设置">
          <SettingsIcon size={17} />
        </button>
      </div>
      <div className="topbar-status-line" aria-hidden="true">
        <span className={health?.ok ? "on" : ""} />
      </div>
    </header>
  );
}
