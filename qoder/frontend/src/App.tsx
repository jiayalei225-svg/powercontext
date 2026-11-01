import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Health } from "./types";
import { Header, type Tab } from "./components/Header";
import { LibraryPanel } from "./components/LibraryPanel";
import { MemoryPanel } from "./components/MemoryPanel";
import { PaperDrawer } from "./components/PaperDrawer";
import { SearchPanel } from "./components/SearchPanel";
import { Toast, type ToastState } from "./components/Toast";

const TABS: Tab[] = ["search", "library", "memory"];
const REPO_URL =
  "https://github.com/jiayalei225-svg/powercontext/tree/2026-competition-ecosystem/qoder";

function readTab(): Tab {
  const value = window.location.hash.replace(/^#\/?/, "");
  return TABS.includes(value as Tab) ? (value as Tab) : "search";
}

export default function App() {
  const [tab, setTab] = useState<Tab>(readTab);
  const [health, setHealth] = useState<Health | null>(null);
  const [drawer, setDrawer] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health());
    } catch {
      setHealth(null);
    }
  }, []);

  useEffect(() => {
    void refreshHealth();
    const timer = window.setInterval(() => void refreshHealth(), 45000);
    return () => window.clearInterval(timer);
  }, [refreshHealth]);

  useEffect(() => {
    const onHash = () => setTab(readTab());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = useCallback((next: Tab) => {
    setTab(next);
    window.location.hash = `/${next}`;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const notify = useCallback((tone: ToastState["tone"], text: string) => {
    setToast({ id: Date.now(), tone, text });
  }, []);

  return (
    <>
      <a className="skip-link" href="#main">
        跳到主要内容
      </a>
      <Header tab={tab} health={health} onTab={go} />
      <main id="main">
        {tab === "search" && (
          <SearchPanel health={health} onOpenPaper={setDrawer} notify={notify} />
        )}
        {tab === "library" && (
          <LibraryPanel
            health={health}
            onOpenPaper={setDrawer}
            onChanged={() => void refreshHealth()}
            notify={notify}
          />
        )}
        {tab === "memory" && (
          <MemoryPanel health={health} onChanged={() => void refreshHealth()} notify={notify} />
        )}
      </main>

      <footer className="site-footer">
        <div>
          <strong>PaperDesk 2.0</strong>
          <span>用 Qoder 构建 · seekdb 混合检索 · PowerContext 长期记忆 · 数据只在本机</span>
        </div>
        <nav>
          <a href={REPO_URL} target="_blank" rel="noreferrer">
            代码仓库
          </a>
          <a href="/api/docs" target="_blank" rel="noreferrer">
            API 文档
          </a>
          <span className="mono">v{health?.version ?? "2.0.0"}</span>
        </nav>
      </footer>

      <PaperDrawer paperId={drawer} onClose={() => setDrawer(null)} />
      <Toast toast={toast} onDone={() => setToast(null)} />
    </>
  );
}
