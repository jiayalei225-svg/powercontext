import { useEffect, useState } from "react";
import { api } from "../api";
import type { PaperDetail } from "../types";

export function PaperDrawer({ paperId, onClose }: { paperId: string | null; onClose: () => void }) {
  const [detail, setDetail] = useState<PaperDetail | null>(null);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!paperId) {
      setDetail(null);
      setError("");
      return;
    }
    let active = true;
    setDetail(null);
    setError("");
    setExpanded(false);
    api
      .paper(paperId)
      .then((data) => {
        if (active) setDetail(data);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      active = false;
    };
  }, [paperId]);

  useEffect(() => {
    if (!paperId) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    document.body.classList.add("no-scroll");
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.classList.remove("no-scroll");
    };
  }, [paperId, onClose]);

  if (!paperId) return null;
  const chunks = detail?.chunk_details ?? [];
  const visible = expanded ? chunks : chunks.slice(0, 4);

  return (
    <div
      className="drawer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title">
        <header className="drawer-head">
          <div>
            <span className="eyebrow">论文详情 · 原文片段</span>
            <h2 id="drawer-title">{detail?.title ?? (error ? "无法载入" : "载入中…")}</h2>
            {detail && (
              <div className="drawer-meta">
                <span>{detail.venue}</span>
                <span>{detail.year ?? "年份未知"}</span>
                <span>{detail.field}</span>
                <span>{detail.pages} 页</span>
                <span>{detail.chunks} 个检索片段</span>
                {detail.has_code && <span className="badge badge-code">开源</span>}
              </div>
            )}
          </div>
          <div className="drawer-actions">
            {detail?.has_pdf && (
              <a className="button ghost" href={`/api/papers/${detail.paper_id}/file`} target="_blank" rel="noreferrer">
                打开 PDF
              </a>
            )}
            {detail?.code_url && (
              <a className="button ghost" href={detail.code_url} target="_blank" rel="noreferrer">
                代码链接
              </a>
            )}
            <button className="icon-button" onClick={onClose} aria-label="关闭">
              ×
            </button>
          </div>
        </header>

        <div className="drawer-body">
          {error && <p className="inline-error">{error}</p>}
          {!detail && !error && <div className="skeleton tall" />}
          {detail && chunks.length === 0 && <p className="muted">这篇论文没有可展示的片段。</p>}
          {visible.map((chunk) => (
            <article className="chunk" key={chunk.chunk_id}>
              <div className="chunk-head">
                <span className="page-stamp">P.{chunk.page}</span>
                <span className="mono muted">片段 {String(chunk.seq + 1).padStart(2, "0")}</span>
              </div>
              <p>{chunk.text}</p>
            </article>
          ))}
          {chunks.length > 4 && (
            <button className="button subtle wide" onClick={() => setExpanded((value) => !value)}>
              {expanded ? "收起片段" : `展开剩余 ${chunks.length - 4} 个片段`}
            </button>
          )}
        </div>

        <footer className="drawer-foot">
          <span className="mono">{detail?.paper_id ?? paperId}</span>
          <span className="muted">来源：{detail?.source ?? "—"}</span>
        </footer>
      </section>
    </div>
  );
}
