import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EmbeddingEngine, EngineInfo } from "../lib/embedding/engine";
import type { HealthResponse, KnowledgeBase } from "../lib/types";
import {
  reportToCsv,
  runBenchmark,
  type BenchmarkProgress,
  type BenchmarkReport,
  type ConfigResult,
  type SkippedConfig,
} from "../lib/benchmark";
import { MODEL, formatMs } from "../lib/model";
import { BoltIcon, CheckIcon, FlaskIcon, WarningIcon } from "../components/Icons";
import { ProgressBar, Spinner, Tag } from "../components/Primitives";

export function LabView({
  engine,
  engineInfo,
  health,
  activeKb,
  onToast,
}: {
  engine: EmbeddingEngine;
  engineInfo: EngineInfo | null;
  health: HealthResponse | null;
  activeKb: KnowledgeBase | null;
  onToast: (toast: { message: string; tone: "success" | "error" | "info" } | null) => void;
}) {
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState<BenchmarkProgress | null>(null);
  const [report, setReport] = useState<BenchmarkReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [includeBatch, setIncludeBatch] = useState(true);
  const [includeModes, setIncludeModes] = useState(true);
  const reportRef = useRef<BenchmarkReport | null>(null);

  const start = useCallback(async () => {
    if (running) return null;
    if (!health?.ok) {
      setError("seekdb 未连接，评测需要真实写入与检索。");
      return null;
    }
    setRunning(true);
    setError(null);
    setReport(null);
    setProgress({ phase: "start", percent: 0, message: "准备评测环境" });
    try {
      const next = await runBenchmark({
        engine,
        includeBatchSweep: includeBatch,
        includeModes,
        onProgress: setProgress,
      });
      setReport(next);
      reportRef.current = next;
      onToast({ message: "评测完成，结果已生成。", tone: "success" });
      return next;
    } catch (err) {
      setError(String((err as Error).message ?? err));
      return null;
    } finally {
      setRunning(false);
    }
  }, [engine, health?.ok, includeBatch, includeModes, onToast, running]);

  useEffect(() => {
    const api = {
      run: () => start(),
      getReport: () => reportRef.current,
      isRunning: () => running,
    };
    (window as any).__EDGE_ATLAS_LAB__ = api;
    return () => {
      if ((window as any).__EDGE_ATLAS_LAB__ === api) {
        delete (window as any).__EDGE_ATLAS_LAB__;
      }
    };
  }, [start, running]);

  const download = (format: "json" | "csv") => {
    if (!report) return;
    const content = format === "json" ? JSON.stringify(report, null, 2) : reportToCsv(report);
    const blob = new Blob([content], {
      type: format === "json" ? "application/json" : "text/csv",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `edge-atlas-benchmark-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.${format}`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const successful = useMemo(
    () => report?.results.filter((item): item is ConfigResult => !("skipped" in item)) ?? [],
    [report],
  );
  const skipped = useMemo(
    () => report?.results.filter((item): item is SkippedConfig => "skipped" in item) ?? [],
    [report],
  );
  const maxBatch = useMemo(() => {
    let max = 0;
    for (const config of successful) {
      for (const batch of config.batches) max = Math.max(max, batch.textsPerSecond);
    }
    return max || 1;
  }, [successful]);

  return (
    <div className="lab-page">
      <section className="lab-hero">
        <div>
          <div className="eyebrow">
            <FlaskIcon size={14} /> PERFORMANCE LAB / 评测台
          </div>
          <h1>Measure the edge.</h1>
          <p>
            在同一设备、同一语料和同一查询集上，比较 FP32 基线、INT8/WASM 与 FP16/WebGPU
            的加载、向量化、seekdb 检索和检索质量。所有向量都由当前浏览器计算。
          </p>
        </div>
        <div className="lab-hero-side">
          <div className="lab-stat">
            <span>DATASET</span>
            <strong>27 docs</strong>
            <small>20 queries · 512d</small>
          </div>
          <div className="lab-stat">
            <span>RUNTIME</span>
            <strong>{engineInfo ? (engineInfo.backend === "webgpu" ? "WebGPU" : "WASM") : "…"}</strong>
            <small>{navigator.hardwareConcurrency} logical cores</small>
          </div>
        </div>
      </section>

      <section className="lab-control-panel">
        <div className="lab-control-copy">
          <span className="eyebrow">EXPERIMENT CONFIG</span>
          <h2>端到端、可复现、原始数据可导出</h2>
          <p>
            评测会临时创建 seekdb collection，完成导入与索引刷新后执行查询，最后自动删除临时集合。
            每个配置重复测试并报告中位数与 p95。
          </p>
        </div>
        <div className="lab-controls">
          <label className="switch-row">
            <input
              type="checkbox"
              checked={includeModes}
              onChange={(event) => setIncludeModes(event.target.checked)}
            />
            <span>
              <strong>对比三种检索模式</strong>
              <small>hybrid / vector / fulltext</small>
            </span>
          </label>
          <label className="switch-row">
            <input
              type="checkbox"
              checked={includeBatch}
              onChange={(event) => setIncludeBatch(event.target.checked)}
            />
            <span>
              <strong>扫描 batch size</strong>
              <small>1 / 8 / 16 / 32 · 吞吐</small>
            </span>
          </label>
          <button
            className="button button-primary lab-run"
            onClick={() => void start()}
            disabled={running || !health?.ok}
          >
            {running ? <Spinner size={16} /> : <BoltIcon size={16} />}
            {running ? "评测进行中" : report ? "重新运行评测" : "运行完整评测"}
          </button>
        </div>
      </section>

      {report ? (
        <section className="lab-environment">
          <div>
            <span className="eyebrow">ENVIRONMENT</span>
            <span className="mono">{report.environment.userAgent}</span>
          </div>
          <div className="env-pills">
            <Tag tone={report.environment.webgpu ? "lime" : "amber"}>
              {report.environment.webgpu ? "WebGPU adapter" : "WebGPU unavailable"}
            </Tag>
            <Tag tone="neutral">{report.environment.hardwareConcurrency} cores</Tag>
            <Tag tone="neutral">
              cross-origin isolated {String(report.environment.crossOriginIsolated)}
            </Tag>
            <Tag tone="neutral">
              {report.dataset.documents} docs / {report.dataset.chunks} chunks
            </Tag>
          </div>
        </section>
      ) : null}

      {running && progress ? (
        <section className="lab-progress">
          <div className="lab-progress-head">
            <div>
              <span className="eyebrow">{progress.phase.toUpperCase()}</span>
              <h3>{progress.message}</h3>
            </div>
            <span className="mono">{Math.round(progress.percent)}%</span>
          </div>
          <ProgressBar value={progress.percent} tone="amber" />
          <div className="lab-progress-steps">
            {["FP32 · WASM 基线", "INT8 · WASM", "FP16 · WebGPU"].map((label, index) => {
              const thresholds = [5, 33, 61];
              const state =
                progress.percent > thresholds[index] + 27
                  ? "done"
                  : progress.percent >= thresholds[index]
                    ? "active"
                    : "todo";
              return (
                <span key={label} className={state}>
                  <i>{state === "done" ? "✓" : index + 1}</i>
                  {label}
                </span>
              );
            })}
          </div>
        </section>
      ) : null}

      {error ? (
        <div className="inline-alert alert-error">
          <WarningIcon size={17} />
          <p>{error}</p>
        </div>
      ) : null}

      {report ? (
        <>
          <section className="lab-results">
            <div className="lab-results-head">
              <div>
                <span className="eyebrow">RESULTS / 实测结果</span>
                <h2>同一语料，三种运行时。</h2>
              </div>
              <div className="lab-export">
                <button className="button button-ghost small" onClick={() => download("json")}>
                  导出 JSON
                </button>
                <button className="button button-ghost small" onClick={() => download("csv")}>
                  导出 CSV
                </button>
              </div>
            </div>

            {successful.length ? (
              <div className="lab-table-wrap">
                <table className="lab-table">
                  <thead>
                    <tr>
                      <th>配置</th>
                      <th>模型体积</th>
                      <th>加载</th>
                      <th>文档向量化</th>
                      <th>查询编码 p50</th>
                      <th>seekdb 检索 p50</th>
                      <th>端到端 p50</th>
                      <th>Recall@5</th>
                      <th>nDCG@5</th>
                      <th>MRR@5</th>
                    </tr>
                  </thead>
                  <tbody>
                    {successful.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <strong>{item.label}</strong>
                          <span className="mono table-sub">
                            {item.backend} / {item.precision === "q8" ? "INT8" : item.precision.toUpperCase()}
                          </span>
                        </td>
                        <td>
                          {(item.modelBytes / 1024 / 1024).toFixed(1)} MiB
                          <span className="mono table-sub">{item.compression.toFixed(2)}×</span>
                        </td>
                        <td>{formatMs(item.engine.loadMs)}</td>
                        <td>
                          {formatMs(item.ingestion.embedMs)}
                          <span className="mono table-sub">{item.ingestion.chunks} chunks</span>
                        </td>
                        <td>{formatMs(item.latency.queryEmbedP50)}</td>
                        <td>{formatMs(item.latency.searchP50)}</td>
                        <td>{formatMs(item.latency.e2eP50)}</td>
                        <td>{item.quality.hybrid.recall5.toFixed(3)}</td>
                        <td>{item.quality.hybrid.ndcg5.toFixed(3)}</td>
                        <td>{item.quality.hybrid.mrr5.toFixed(3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="panel-empty">没有完成任何配置，请检查 seekdb 与模型文件。</p>
            )}

            {skipped.length ? (
              <div className="lab-skipped">
                <WarningIcon size={15} />
                <div>
                  {skipped.map((item) => (
                    <p key={item.id}>
                      <strong>{item.label}</strong> 未运行：{item.error}
                    </p>
                  ))}
                </div>
              </div>
            ) : null}
          </section>

          {successful.length ? (
            <div className="lab-grid">
              <section className="lab-card">
                <div className="lab-card-head">
                  <div>
                    <span className="eyebrow">QUALITY / 检索质量</span>
                    <h3>量化前后的质量变化</h3>
                  </div>
                  <Tag tone="lime">20 queries</Tag>
                </div>
                <div className="quality-bars">
                  {successful.map((item) => (
                    <div key={item.id} className="quality-row">
                      <span>{item.label}</span>
                      <div className="quality-bar">
                        <i style={{ width: `${item.quality.hybrid.recall5 * 100}%` }} />
                      </div>
                      <strong>{item.quality.hybrid.recall5.toFixed(3)}</strong>
                    </div>
                  ))}
                </div>
                <p className="lab-note">
                  Recall@5 基于文档级 qrels，检索由 seekdb 执行；混合检索使用 RRF(k=60)。
                </p>
              </section>

              <section className="lab-card">
                <div className="lab-card-head">
                  <div>
                    <span className="eyebrow">LATENCY / 延迟</span>
                    <h3>查询编码与数据库检索</h3>
                  </div>
                  <Tag tone="amber">p50 / p95</Tag>
                </div>
                <div className="latency-table">
                  {successful.map((item) => (
                    <div key={item.id}>
                      <span>{item.label}</span>
                      <div>
                        <i style={{ width: `${Math.min(100, (item.latency.e2eP50 / 600) * 100)}%` }} />
                      </div>
                      <strong>{item.latency.e2eP50.toFixed(0)} ms</strong>
                      <small>p95 {item.latency.e2eP95.toFixed(0)}</small>
                    </div>
                  ))}
                </div>
                <p className="lab-note">
                  端到端 = 查询本地编码 + HTTP + seekdb 检索，不含 React 渲染。Atlas 的实际会话计时另含渲染。
                </p>
              </section>
            </div>
          ) : null}

          {successful.some((item) => item.quality.hybrid.queries > 0) && includeModes ? (
            <section className="lab-card mode-compare">
              <div className="lab-card-head">
                <div>
                  <span className="eyebrow">RETRIEVAL MODES / 三路对照</span>
                  <h3>混合检索是否比单独一路更好？</h3>
                </div>
                <Tag tone="neutral">Recall@5</Tag>
              </div>
              <div className="mode-table">
                <div className="mode-table-head">
                  <span>配置</span>
                  <span>Hybrid</span>
                  <span>Vector</span>
                  <span>Fulltext</span>
                </div>
                {successful.map((item) => (
                  <div key={item.id} className="mode-table-row">
                    <span>{item.label}</span>
                    <strong>{item.quality.hybrid.recall5.toFixed(3)}</strong>
                    <strong>{item.quality.vector.recall5.toFixed(3)}</strong>
                    <strong>{item.quality.fulltext.recall5.toFixed(3)}</strong>
                  </div>
                ))}
              </div>
              <p className="lab-note">
                全文分支使用 IK 分词与 query string；向量分支使用 BGE 查询向量。混合检索在 seekdb
                内完成 RRF 融合。
              </p>
            </section>
          ) : null}

          {successful.some((item) => item.batches.length > 0) ? (
            <section className="lab-card">
              <div className="lab-card-head">
                <div>
                  <span className="eyebrow">THROUGHPUT / 吞吐</span>
                  <h3>batch size 与每秒文本块</h3>
                </div>
                <Tag tone="neutral">texts / second</Tag>
              </div>
              <div className="batch-groups">
                {successful
                  .filter((item) => item.batches.length > 0)
                  .map((item) => (
                    <div key={item.id} className="batch-group">
                      <div className="batch-group-title">
                        <strong>{item.label}</strong>
                        <span className="mono">{item.engine.modelFile}</span>
                      </div>
                      <div className="batch-bars">
                        {item.batches.map((batch) => (
                          <div key={batch.batchSize} className="batch-row">
                            <span className="mono">b{batch.batchSize}</span>
                            <div>
                              <i style={{ width: `${(batch.textsPerSecond / maxBatch) * 100}%` }} />
                            </div>
                            <strong>{batch.textsPerSecond.toFixed(1)}</strong>
                            <small>{batch.totalMs.toFixed(0)} ms</small>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
              </div>
              <p className="lab-note">
                固定 36 个文本块，预热后每档重复两轮取中位数；只改变 batch size，其他条件保持一致。
              </p>
            </section>
          ) : null}

          <section className="lab-method">
            <div>
              <span className="eyebrow">METHOD / 口径</span>
              <p>
                设备与浏览器版本见环境信息；模型均为同一 revision 的 ONNX 变体；语料与 qrels 固定；
                每个配置临时 collection 的维度、距离和全文分词器一致；模型体积按 ONNX + tokenizer
                配置文件总字节数统计；查询性能来自实际 seekdb 查询，非客户端重排。
              </p>
            </div>
            <div className="method-facts">
              <span>
                <CheckIcon size={14} /> 20 queries × 5 topK
              </span>
              <span>
                <CheckIcon size={14} /> {MODEL.id}
              </span>
              <span>
                <CheckIcon size={14} /> seekdb 1.4.0
              </span>
            </div>
          </section>
        </>
      ) : !running ? (
        <section className="lab-empty">
          <span className="lab-empty-mark">
            <FlaskIcon size={32} />
          </span>
          <h3>还没有实测数据</h3>
          <p>
            点击“运行完整评测”。评测会真实导入 27 篇文档、生成全部向量、写入 seekdb，并执行 20
            条查询；完整跑完通常需要几分钟。
          </p>
          <div className="lab-empty-stats">
            <div>
              <strong>3</strong>
              <span>runtime configs</span>
            </div>
            <div>
              <strong>20</strong>
              <span>queries</span>
            </div>
            <div>
              <strong>60</strong>
              <span>retrieval runs</span>
            </div>
            <div>
              <strong>4</strong>
              <span>batch sizes</span>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
