import type { Health } from "../types";

export type Tab = "search" | "library" | "memory";

const TABS: Array<{ key: Tab; label: string; hint: string }> = [
  { key: "search", label: "检索", hint: "问题 → 原文段落" },
  { key: "library", label: "文献库", hint: "导入与管理" },
  { key: "memory", label: "记忆", hint: "偏好与轨迹" },
];

export function Header({
  tab,
  health,
  onTab,
}: {
  tab: Tab;
  health: Health | null;
  onTab: (tab: Tab) => void;
}) {
  const chunks = health?.index.chunks ?? 0;
  const connected = health?.memory.connected ?? false;
  return (
    <header className="site-header">
      <div className="header-inner">
        <button className="brand" onClick={() => onTab("search")} aria-label="回到检索">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span className="brand-copy">
            <strong>PaperDesk</strong>
            <em>文献检索工作台</em>
          </span>
        </button>

        <nav className="tabs" aria-label="主导航">
          {TABS.map((item) => (
            <button
              key={item.key}
              className={`tab ${tab === item.key ? "is-active" : ""}`}
              onClick={() => onTab(item.key)}
              aria-current={tab === item.key ? "page" : undefined}
              title={item.hint}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <div className="header-status">
          <span className="status-pill" title="seekdb 索引片段数">
            <i className="dot dot-teal" />
            seekdb · {chunks} 片段
          </span>
          <span className={`status-pill ${connected ? "" : "is-off"}`} title="PowerContext 记忆服务">
            <i className={`dot ${connected ? "dot-accent" : "dot-muted"}`} />
            记忆 · {connected ? "已连接" : "离线"}
          </span>
        </div>
      </div>
    </header>
  );
}
