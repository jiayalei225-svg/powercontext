import { useEffect, useRef, useState, type DragEvent } from "react";
import { api } from "../api";
import type { Health, PaperSummary } from "../types";
import type { ToastState } from "./Toast";

type Notify = (tone: ToastState["tone"], text: string) => void;

interface UploadItem {
  id: number;
  name: string;
  detail: string;
  tone: "busy" | "ok" | "error";
}

export function LibraryPanel({
  health,
  onOpenPaper,
  onChanged,
  notify,
}: {
  health: Health | null;
  onOpenPaper: (paperId: string) => void;
  onChanged: () => void;
  notify: Notify;
}) {
  const [papers, setPapers] = useState<PaperSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [dragging, setDragging] = useState(false);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const counter = useRef(0);

  async function refresh() {
    try {
      const payload = await api.papers();
      setPapers(payload.papers);
    } catch (err: unknown) {
      notify("error", err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleFiles(files: FileList | File[]) {
    const list = Array.from(files);
    if (!list.length) return;
    for (const file of list) {
      const id = ++counter.current;
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        setUploads((items) => [{ id, name: file.name, detail: "不是 PDF，已跳过", tone: "error" }, ...items]);
        notify("error", `${file.name} 不是 PDF`);
        continue;
      }
      setUploads((items) => [{ id, name: file.name, detail: "解析、分块、向量化中…", tone: "busy" }, ...items]);
      try {
        const payload = await api.upload(file);
        const detail = payload.duplicate
          ? "已存在，跳过重复入库"
          : `已入库 · ${payload.added} 个片段 · ${payload.paper.title}`;
        setUploads((items) =>
          items.map((item) => (item.id === id ? { ...item, detail, tone: "ok" } : item)),
        );
        notify("ok", `${file.name}：${payload.duplicate ? "已存在" : "导入完成"}`);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        setUploads((items) => items.map((item) => (item.id === id ? { ...item, detail: message, tone: "error" } : item)));
        notify("error", `${file.name}：${message}`);
      }
    }
    await refresh();
    onChanged();
  }

  async function removePaper(paper: PaperSummary) {
    if (!window.confirm(`确认从索引中删除《${paper.title}》？原文 PDF 也会一并移除。`)) return;
    try {
      await api.remove(paper.paper_id);
      notify("ok", `已删除《${paper.title}》`);
      await refresh();
      onChanged();
    } catch (err: unknown) {
      notify("error", err instanceof Error ? err.message : String(err));
    }
  }

  const totalChunks = papers.reduce((sum, paper) => sum + paper.chunks, 0);

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">文献库</span>
          <h1>你的检索底稿</h1>
          <p className="lede">每篇 PDF 在入库时被切成语义片段，写入 seekdb 的同一集合，供混合检索与标量过滤使用。</p>
        </div>
      </header>

      <div className="library-top">
        <div className="stat-grid">
          <div className="stat-card">
            <span>论文</span>
            <strong>{papers.length}</strong>
          </div>
          <div className="stat-card">
            <span>索引片段</span>
            <strong>{totalChunks}</strong>
          </div>
          <div className="stat-card">
            <span>向量模型</span>
            <strong className="stat-text">{health?.index.embedding ?? "—"}</strong>
          </div>
          <div className="stat-card">
            <span>集合</span>
            <strong className="stat-text mono">{health?.index.collection ?? "—"}</strong>
          </div>
        </div>

        <div
          className={`upload-zone ${dragging ? "is-dragging" : ""}`}
          onDragOver={(event: DragEvent<HTMLDivElement>) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event: DragEvent<HTMLDivElement>) => {
            event.preventDefault();
            setDragging(false);
            void handleFiles(event.dataTransfer.files);
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            multiple
            hidden
            onChange={(event) => {
              if (event.target.files) void handleFiles(event.target.files);
              event.target.value = "";
            }}
          />
          <div className="upload-mark">PDF</div>
          <div>
            <strong>拖入论文，或选择文件</strong>
            <p>文本型 PDF · 单篇不超过 40MB · 自动识别标题、年份、会议、方向与代码链接</p>
          </div>
          <button className="button primary compact" onClick={() => inputRef.current?.click()}>
            选择 PDF
          </button>
        </div>
      </div>

      {uploads.length > 0 && (
        <ul className="upload-list">
          {uploads.slice(0, 5).map((item) => (
            <li key={item.id} className={`upload-item is-${item.tone}`}>
              <span className="upload-dot" />
              <strong>{item.name}</strong>
              <span>{item.detail}</span>
            </li>
          ))}
        </ul>
      )}

      <section className="library-table-wrap">
        {loading ? (
          <div className="skeleton tall" />
        ) : papers.length === 0 ? (
          <div className="empty-state">
            <h3>文献库还是空的</h3>
            <p>
              拖入第一篇 PDF，或运行 <code>python scripts/seed.py</code> 导入五篇演示论文。
            </p>
          </div>
        ) : (
          <div className="paper-table">
            <div className="paper-row paper-head">
              <span>论文</span>
              <span>年份</span>
              <span>会议 / 期刊</span>
              <span>方向</span>
              <span>结构</span>
              <span>代码</span>
              <span />
            </div>
            {papers.map((paper) => (
              <div className="paper-row" key={paper.paper_id}>
                <div className="paper-main">
                  <button className="paper-title" onClick={() => onOpenPaper(paper.paper_id)}>
                    {paper.title}
                  </button>
                  <span className="paper-source mono">{paper.source}</span>
                </div>
                <span>{paper.year ?? "—"}</span>
                <span>{paper.venue}</span>
                <span>{paper.field}</span>
                <span className="muted">
                  {paper.chunks} 段 · {paper.pages} 页
                </span>
                <span>
                  {paper.has_code ? (
                    paper.code_url ? (
                      <a className="text-link" href={paper.code_url} target="_blank" rel="noreferrer">
                        开源
                      </a>
                    ) : (
                      "开源"
                    )
                  ) : (
                    "—"
                  )}
                </span>
                <span className="row-actions">
                  <button className="button ghost tiny" onClick={() => onOpenPaper(paper.paper_id)}>
                    详情
                  </button>
                  <button className="button danger tiny" onClick={() => void removePaper(paper)}>
                    删除
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
      <p className="table-note">删除会同时移除 seekdb 中的向量片段与本地上传的 PDF，论文可以从原文件重新导入。</p>
    </div>
  );
}
