import { useRef, useState } from "react";
import { api, download } from "../api";
import type { Health, SearchRequest, SearchResponse } from "../types";
import { Chip, Highlight, describeFilters } from "./bits";
import type { ToastState } from "./Toast";

const EXAMPLES = ["向量数据库里怎么做混合检索", "多轮对话里的记忆怎么保存", "长文档分块与重排序的权衡"];

type Notify = (tone: ToastState["tone"], text: string) => void;

function buildRequest(
  query: string,
  yearFrom: string,
  yearTo: string,
  venues: string,
  field: string,
  codeMode: "any" | "yes" | "no",
  useMemory: boolean,
): SearchRequest {
  const parsedFrom = Number.parseInt(yearFrom, 10);
  const parsedTo = Number.parseInt(yearTo, 10);
  return {
    query: query.trim(),
    limit: 12,
    year_from: Number.isFinite(parsedFrom) ? parsedFrom : null,
    year_to: Number.isFinite(parsedTo) ? parsedTo : null,
    venues: venues
      .split(/[,，、]/)
      .map((item) => item.trim())
      .filter(Boolean),
    field: field.trim() || null,
    has_code: codeMode === "any" ? null : codeMode === "yes",
    use_memory: useMemory,
  };
}

export function SearchPanel({
  health,
  onOpenPaper,
  notify,
}: {
  health: Health | null;
  onOpenPaper: (paperId: string) => void;
  notify: Notify;
}) {
  const [query, setQuery] = useState("");
  const [yearFrom, setYearFrom] = useState("");
  const [yearTo, setYearTo] = useState("");
  const [venues, setVenues] = useState("");
  const [field, setField] = useState("");
  const [codeMode, setCodeMode] = useState<"any" | "yes" | "no">("any");
  const [useMemory, setUseMemory] = useState(true);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState<"" | "md" | "csv">("");
  const [error, setError] = useState("");
  const resultsRef = useRef<HTMLDivElement>(null);

  async function runSearch(nextQuery?: string) {
    const text = (nextQuery ?? query).trim();
    if (!text) {
      setError("先写下一个问题，再开始检索。");
      return;
    }
    if (nextQuery !== undefined) setQuery(nextQuery);
    setBusy(true);
    setError("");
    try {
      const request = buildRequest(text, yearFrom, yearTo, venues, field, codeMode, useMemory);
      const payload = await api.search(request);
      setResult(payload);
      window.setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleExport(format: "md" | "csv") {
    if (!result) return;
    setExporting(format);
    try {
      const blob = await api.exportReport(format, {
        query: result.query,
        limit: result.limit,
        year_from: result.filters.year_from,
        year_to: result.filters.year_to,
        venues: result.filters.venues.length ? result.filters.venues : null,
        field: result.filters.field,
        has_code: result.filters.has_code,
      });
      const stamp = new Date().toISOString().slice(0, 16).replace(/[T:]/g, "-");
      download(blob, `paperdesk-${stamp}.${format}`);
      notify("ok", `已导出 ${format === "md" ? "Markdown" : "CSV"} 报告`);
    } catch (err: unknown) {
      notify("error", err instanceof Error ? err.message : String(err));
    } finally {
      setExporting("");
    }
  }

  const papers = health?.index.papers ?? 0;

  return (
    <div className="page search-page">
      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow">本地优先 · seekdb 混合检索 · PowerContext 记忆</span>
          <h1>
            从一句问题，
            <br />
            翻到论文里的<em>那一页</em>。
          </h1>
          <p className="lede">
            导入 PDF，向量语义与关键词字面同时召回，直接定位到具体段落；你的年份、会议与方向偏好会被记住，下次检索自动生效。
            索引、原文和记忆都留在本机。
          </p>
          <div className="hero-stats">
            <div>
              <strong>{papers}</strong>
              <span>篇演示论文</span>
            </div>
            <div>
              <strong>RRF</strong>
              <span>双路融合排序</span>
            </div>
            <div>
              <strong>{health?.memory.connected ? "在线" : "离线"}</strong>
              <span>长期记忆</span>
            </div>
          </div>
        </div>
        <div className="hero-card">
          <div className="hero-card-head">
            <span className="mono">RETRIEVAL_PLAN</span>
            <span className="hero-card-light" />
          </div>
          <div className="hero-card-body">
            <p>
              <span>query</span> 内存里的旧笔记如何被找回来？
            </p>
            <p>
              <span>dense</span> bge-small-zh · 512d
            </p>
            <p>
              <span>lexical</span> “记忆” · rarity probe
            </p>
            <p>
              <span>filter</span> year ≥ 2024 · has_code
            </p>
            <p>
              <span>memory</span> preference · artifact rev.2
            </p>
          </div>
          <div className="hero-card-foot">
            <span>seekdb hybrid_search</span>
            <span className="mono">RRF · 42ms</span>
          </div>
        </div>
      </section>

      <section className="search-shell" aria-label="检索表单">
        <form
          className="search-form"
          onSubmit={(event) => {
            event.preventDefault();
            void runSearch();
          }}
        >
          <div className="search-input-row">
            <span className="search-glyph" aria-hidden="true">
              ⌕
            </span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="比如：向量数据库里怎么做混合检索？"
              aria-label="检索问题"
              autoComplete="off"
            />
            <button className="primary" type="submit" disabled={busy}>
              {busy ? "检索中…" : "检索"}
            </button>
          </div>

          <div className="filter-row">
            <label className="field year-field">
              <span>年份从</span>
              <input
                value={yearFrom}
                onChange={(event) => setYearFrom(event.target.value)}
                inputMode="numeric"
                placeholder="不限"
              />
            </label>
            <label className="field year-field">
              <span>到</span>
              <input
                value={yearTo}
                onChange={(event) => setYearTo(event.target.value)}
                inputMode="numeric"
                placeholder="不限"
              />
            </label>
            <label className="field grow">
              <span>会议 / 期刊</span>
              <input
                value={venues}
                onChange={(event) => setVenues(event.target.value)}
                placeholder="ACL、SIGIR"
              />
            </label>
            <label className="field grow">
              <span>研究方向</span>
              <input
                value={field}
                onChange={(event) => setField(event.target.value)}
                placeholder="检索增强生成"
              />
            </label>
            <label className="field">
              <span>开源代码</span>
              <select value={codeMode} onChange={(event) => setCodeMode(event.target.value as "any" | "yes" | "no")}>
                <option value="any">全部</option>
                <option value="yes">仅开源</option>
                <option value="no">不含代码</option>
              </select>
            </label>
            <label className="memory-toggle">
              <input
                type="checkbox"
                checked={useMemory}
                onChange={(event) => setUseMemory(event.target.checked)}
              />
              <span>
                应用记忆偏好
                <em>{health?.memory.connected ? "PowerContext 在线" : "记忆服务离线"}</em>
              </span>
            </label>
          </div>
        </form>

        <div className="examples">
          <span>试试</span>
          {EXAMPLES.map((example) => (
            <button key={example} onClick={() => void runSearch(example)}>
              {example}
            </button>
          ))}
        </div>
        {error && <p className="inline-error">{error}</p>}
      </section>

      {result && (
        <section className="results" ref={resultsRef}>
          <header className="results-head">
            <div>
              <span className="eyebrow">检索结果</span>
              <h2>
                {result.total > 0 ? (
                  <>
                    找到 <em>{result.total}</em> 个相关段落
                  </>
                ) : (
                  "没有找到相关段落"
                )}
              </h2>
              <p className="muted">
                “{result.query}” · {result.elapsed_ms}ms ·{" "}
                {result.strategy === "hybrid" ? "向量 + 全文混合召回" : "纯向量召回"}
              </p>
            </div>
            <div className="results-actions">
              <button className="button ghost" disabled={exporting !== ""} onClick={() => void handleExport("md")}>
                {exporting === "md" ? "导出中…" : "Markdown"}
              </button>
              <button className="button ghost" disabled={exporting !== ""} onClick={() => void handleExport("csv")}>
                {exporting === "csv" ? "导出中…" : "CSV"}
              </button>
            </div>
          </header>

          <div className="results-layout">
            <aside className="plan-card">
              <div className="plan-head">
                <span>检索计划</span>
                <span className="mono">{result.elapsed_ms} ms</span>
              </div>
              <div className="plan-block">
                <label>查询词项</label>
                <div className="chip-line">
                  {result.terms.length ? (
                    result.terms.map((term) => <Chip key={term} tone="ink">{term}</Chip>)
                  ) : (
                    <span className="muted">无</span>
                  )}
                </div>
              </div>
              <div className="plan-block">
                <label>字面锚点</label>
                <div className="chip-line">
                  {result.literal ? <Chip tone="accent">{result.literal}</Chip> : <span className="muted">未使用</span>}
                </div>
              </div>
              <div className="plan-block">
                <label>结构过滤</label>
                <p>{describeFilters(result.filters)}</p>
              </div>
              <div className="plan-block">
                <label>记忆</label>
                {result.notes.length ? (
                  <ul className="plan-notes">
                    {result.notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                ) : (
                  <p>{result.memory_connected ? "本次没有应用记忆默认值" : "记忆服务不可用"}</p>
                )}
              </div>
              <div className="plan-foot">
                <span className={`dot ${result.memory_connected ? "dot-accent" : "dot-muted"}`} />
                {result.memory_connected ? "检索轨迹已写入 PowerContext" : "轨迹未写入记忆"}
              </div>
            </aside>

            <div className="result-list">
              {result.total === 0 && (
                <div className="empty-state">
                  <h3>换个问法试试</h3>
                  <p>可以放宽年份、移除会议限制，或者关闭“应用记忆偏好”后再检索一次。</p>
                </div>
              )}
              {result.results.map((hit, index) => (
                <article className="hit-card" key={hit.chunk_id} style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}>
                  <div className="hit-top">
                    <div>
                      <button className="hit-title" onClick={() => onOpenPaper(hit.paper_id)}>
                        {hit.title}
                      </button>
                      <div className="hit-meta">
                        <span>{hit.venue}</span>
                        <span>{hit.year ?? "年份未知"}</span>
                        <span>p.{hit.page}</span>
                        <span>{hit.field}</span>
                        <span className="mono muted">{hit.paper_id}</span>
                      </div>
                    </div>
                    {hit.has_code &&
                      (hit.code_url ? (
                        <a className="badge badge-code" href={hit.code_url} target="_blank" rel="noreferrer">
                          开源
                        </a>
                      ) : (
                        <span className="badge badge-code">开源</span>
                      ))}
                  </div>
                  <p className="hit-snippet">
                    <Highlight text={hit.snippet} terms={[result.literal ?? "", ...result.terms]} />
                  </p>
                  <footer className="hit-foot">
                    <span className="muted">{hit.source}</span>
                    <button className="link-button" onClick={() => onOpenPaper(hit.paper_id)}>
                      查看所在论文 →
                    </button>
                  </footer>
                </article>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
