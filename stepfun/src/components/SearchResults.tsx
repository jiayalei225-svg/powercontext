import { useState } from "react";
import type { SearchResponse } from "../lib/types";
import { formatMs } from "../lib/model";
import { SearchIcon, SparkIcon, WarningIcon } from "./Icons";
import { Spinner, Tag } from "./Primitives";

export interface SearchTiming {
  embedMs: number;
  seekdbMs: number;
  e2eMs: number;
  renderMs: number;
}

export function SearchResults({
  query,
  mode,
  result,
  loading,
  error,
  timing,
  topK,
  onQuickQuery,
}: {
  query: string;
  mode: "hybrid" | "vector" | "fulltext";
  result: SearchResponse | null;
  loading: boolean;
  error: string | null;
  timing: SearchTiming | null;
  topK: number;
  onQuickQuery: (query: string) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const maxScore = result?.results.reduce((max, hit) => Math.max(max, Math.abs(hit.score)), 0) ?? 0;

  if (loading) {
    return (
      <section className="results-section" aria-busy="true">
        <div className="results-head">
          <div>
            <span className="eyebrow">RETRIEVAL / 检索中</span>
            <h2>在本地向量与全文索引中查找…</h2>
          </div>
          <Spinner size={19} />
        </div>
        <div className="result-skeleton">
          {[0, 1, 2].map((i) => (
            <div key={i} style={{ animationDelay: `${i * 120}ms` }}>
              <span />
              <span />
              <span />
            </div>
          ))}
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="results-section">
        <div className="inline-alert alert-error">
          <WarningIcon size={18} />
          <div>
            <strong>检索失败</strong>
            <p>{error}</p>
          </div>
        </div>
      </section>
    );
  }

  if (!result) {
    return (
      <section className="prompt-deck">
        <div className="prompt-head">
          <span className="eyebrow">TRY A QUERY / 试试这些问题</span>
          <p>查询会在浏览器内编码，然后由 seekdb 同时执行向量与 IK 全文检索。</p>
        </div>
        <div className="prompt-grid">
          {[
            {
              text: "浏览器不支持 WebGPU 时，应用怎样继续完成向量检索？",
              tag: "降级路径",
            },
            {
              text: "seekdb 如何把关键词和语义两路结果融合排序？",
              tag: "混合检索",
            },
            {
              text: "怎样把 95MB 的中文 BERT 模型压缩到 24MB 左右？",
              tag: "INT8 量化",
            },
            {
              text: "评测端侧检索需要固定哪些实验条件，如何计时？",
              tag: "基准方法",
            },
          ].map((prompt, index) => (
            <button key={prompt.text} className="prompt-card" onClick={() => onQuickQuery(prompt.text)}>
              <span className="prompt-index">0{index + 1}</span>
              <span className="prompt-tag">{prompt.tag}</span>
              <strong>{prompt.text}</strong>
              <span className="prompt-go">
                <SearchIcon size={15} />
              </span>
            </button>
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="results-section">
      <div className="results-head">
        <div>
          <span className="eyebrow">
            RETRIEVAL / {result.mode === "hybrid" ? "HYBRID" : result.mode === "vector" ? "VECTOR" : "FULLTEXT"}
          </span>
          <h2>
            {result.results.length} 篇文档<span className="muted"> · 从 {result.rawChunks} 个块聚合</span>
          </h2>
        </div>
        <div className="results-head-meta">
          <Tag tone={mode === "hybrid" ? "lime" : "neutral"}>{result.engine}</Tag>
          <span className="mono">topK {topK}</span>
        </div>
      </div>

      <div className="query-echo">
        <SearchIcon size={15} />
        <span>{query}</span>
        <em>{result.timings.seekdbMs} ms in seekdb</em>
      </div>

      {result.results.length === 0 ? (
        <div className="empty-results">
          <SparkIcon size={24} />
          <h3>没有检索到相关文档</h3>
          <p>尝试更短的关键词、切换为纯向量检索，或先导入更多语料。</p>
        </div>
      ) : (
        <div className="result-list">
          {result.results.map((hit, index) => {
            const isOpen = expanded === hit.chunkId;
            const width = maxScore > 0 ? Math.max(4, (Math.abs(hit.score) / maxScore) * 100) : 0;
            return (
              <article
                key={hit.chunkId}
                className={`result-card ${isOpen ? "expanded" : ""}`}
                style={{ animationDelay: `${index * 45}ms` }}
              >
                <button
                  className="result-summary"
                  onClick={() => setExpanded(isOpen ? null : hit.chunkId)}
                  aria-expanded={isOpen}
                >
                  <span className="result-rank">{String(index + 1).padStart(2, "0")}</span>
                  <span className="result-main">
                    <span className="result-kicker">
                      <span>{hit.category}</span>
                      <i />
                      <span className="mono">
                        chunk {hit.chunkIndex + 1}/{hit.chunkCount}
                      </span>
                      {hit.otherChunks > 0 ? (
                        <>
                          <i />
                          <span>同文档另有 {hit.otherChunks} 块命中</span>
                        </>
                      ) : null}
                    </span>
                    <strong className="result-title">{hit.title}</strong>
                    <p className="result-snippet">{highlight(hit.text, query)}</p>
                  </span>
                  <span className="result-score">
                    <span className="score-number">
                      {result.mode === "hybrid"
                        ? hit.score.toFixed(4)
                        : result.mode === "vector"
                          ? (1 - hit.score).toFixed(3)
                          : hit.score.toFixed(2)}
                    </span>
                    <span className="score-label">
                      {result.mode === "hybrid" ? "RRF" : result.mode === "vector" ? "cosine" : "fulltext"}
                    </span>
                    <span className="score-bar">
                      <i style={{ width: `${width}%` }} />
                    </span>
                  </span>
                </button>
                {isOpen ? (
                  <div className="result-expanded">
                    <div className="result-fulltext">{hit.text}</div>
                    <div className="result-meta">
                      <span>
                        docId <code>{hit.docId}</code>
                      </span>
                      <span>
                        source <code>{hit.source || "local"}</code>
                      </span>
                      <span>
                        chunk <code>{hit.chunkId.slice(0, 18)}</code>
                      </span>
                    </div>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      )}

      <div className="timing-strip">
        <span>
          <i>QUERY EMBED</i>
          <strong>{formatMs(timing?.embedMs)}</strong>
        </span>
        <span>
          <i>SEEKDB</i>
          <strong>{formatMs(timing?.seekdbMs)}</strong>
        </span>
        <span>
          <i>END-TO-END</i>
          <strong>{formatMs(timing?.e2eMs)}</strong>
        </span>
        <span className="timing-note">
          端到端含本地编码、HTTP、seekdb 检索与一次渲染 · 中位数在评测台查看
        </span>
      </div>
    </section>
  );
}

function escapeRegex(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlight(text: string, query: string) {
  const terms = new Set<string>();
  const cleaned = query.replace(/[，。？！、；：,.?!;:"“”'（）()]/g, " ").trim();
  if (cleaned.length > 1 && cleaned.length <= 16) terms.add(cleaned);
  for (const word of cleaned.split(/\s+/)) {
    if (word.length >= 2) terms.add(word);
  }
  const sorted = [...terms].sort((a, b) => b.length - a.length).slice(0, 6);
  if (sorted.length === 0) return text;
  const lowerTerms = new Set(sorted.map((term) => term.toLowerCase()));
  const regex = new RegExp(`(${sorted.map(escapeRegex).join("|")})`, "gi");
  const parts = text.split(regex);
  return parts.map((part, index) =>
    lowerTerms.has(part.toLowerCase()) ? (
      <mark key={`${part}-${index}`}>{part}</mark>
    ) : (
      <span key={`${part}-${index}`}>{part}</span>
    ),
  );
}
