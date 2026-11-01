import { useEffect, useState } from "react";
import { api } from "../api";
import type { MemorySnapshot, Preferences } from "../types";
import { describeFilters, shortId, timeLabel } from "./bits";
import type { ToastState } from "./Toast";

type Notify = (tone: ToastState["tone"], text: string) => void;

function splitVenues(value: string): string[] {
  return value
    .split(/[,，、\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function MemoryPanel({
  health,
  onChanged,
  notify,
}: {
  health: { memory: { connected: boolean; scope_id: string | null; url: string } } | null;
  onChanged: () => void;
  notify: Notify;
}) {
  const [snapshot, setSnapshot] = useState<MemorySnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [yearFrom, setYearFrom] = useState("");
  const [venues, setVenues] = useState("");
  const [field, setField] = useState("");
  const [onlyCode, setOnlyCode] = useState(false);
  const [saving, setSaving] = useState(false);

  function applyPrefs(prefs: Partial<Preferences>) {
    setYearFrom(prefs.year_from ? String(prefs.year_from) : "");
    setVenues((prefs.venues ?? []).join("、"));
    setField(prefs.field ?? "");
    setOnlyCode(Boolean(prefs.only_with_code));
  }

  async function load() {
    setLoading(true);
    setError("");
    try {
      const payload = await api.memory();
      setSnapshot(payload);
      applyPrefs(payload.preferences as Partial<Preferences>);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function save(clear = false) {
    const parsed = Number.parseInt(clear ? "" : yearFrom, 10);
    if (!clear && yearFrom && (!Number.isFinite(parsed) || parsed < 1900 || parsed > 2100)) {
      notify("error", "年份需要在 1900 到 2100 之间");
      return;
    }
    if (clear && !window.confirm("清除记忆中的检索偏好？检索轨迹会保留。")) return;
    const prefs: Preferences = {
      year_from: clear || !Number.isFinite(parsed) ? null : parsed,
      venues: clear ? [] : splitVenues(venues),
      only_with_code: clear ? false : onlyCode,
      field: clear ? null : field.trim() || null,
    };
    setSaving(true);
    try {
      const response = await api.savePreferences(prefs);
      notify("ok", clear ? "已清除记忆偏好" : `偏好已写入记忆 · revision ${response.revision}`);
      if (clear) applyPrefs({});
      await load();
      onChanged();
    } catch (err: unknown) {
      notify("error", err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const connected = snapshot?.connected ?? health?.memory.connected ?? false;
  const scope = snapshot?.scope_id ?? health?.memory.scope_id;

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <span className="eyebrow">PowerContext · 长期记忆</span>
          <h1>让检索记住你的口味</h1>
          <p className="lede">
            偏好以带版本的记忆条目保存，每次检索再作为进度轨迹写入。下一次提问时，未显式填写的条件会自动沿用——这里可以查看、修改或清除它。
          </p>
        </div>
      </header>

      <div className="memory-status">
        <div className={`memory-orb ${connected ? "is-on" : ""}`}>
          <span />
        </div>
        <div className="memory-status-copy">
          <strong>{connected ? "PowerContext 已连接" : "PowerContext 未连接"}</strong>
          <span className="mono">{health?.memory.url ?? "http://127.0.0.1:18000"}</span>
          <span className="mono muted">scope · {shortId(scope)}</span>
        </div>
        <button className="button ghost" onClick={() => void load()}>
          刷新记忆
        </button>
      </div>

      {error && <p className="inline-error">{error}</p>}
      {!connected && !loading && (
        <p className="warning-strip">
          记忆服务离线时，检索本身仍可正常使用，只是不会应用默认偏好，也不会写入新的轨迹。启动方式见运行说明中的 PowerContext 一节。
        </p>
      )}

      <div className="memory-layout">
        <section className="memory-form-card">
          <div className="card-title">
            <div>
              <span className="eyebrow">当前偏好</span>
              <h2>检索默认值</h2>
            </div>
            <span className="badge">{connected ? "已持久化" : "只读"}</span>
          </div>
          <p className="muted small">显式填写的检索条件永远优先于这里的默认值。</p>

          <label className="stack-field">
            <span>只看某年之后</span>
            <input
              value={yearFrom}
              onChange={(event) => setYearFrom(event.target.value)}
              inputMode="numeric"
              placeholder="例如 2024"
            />
          </label>
          <label className="stack-field">
            <span>常读会议 / 期刊</span>
            <input value={venues} onChange={(event) => setVenues(event.target.value)} placeholder="ACL、SIGIR" />
          </label>
          <label className="stack-field">
            <span>锁定研究方向</span>
            <input value={field} onChange={(event) => setField(event.target.value)} placeholder="检索增强生成" />
          </label>
          <label className="check-field">
            <input type="checkbox" checked={onlyCode} onChange={(event) => setOnlyCode(event.target.checked)} />
            <span>
              只看带开源代码的论文
              <em>含代码链接或代码字段的论文才会进入候选</em>
            </span>
          </label>

          <div className="form-actions">
            <button className="button primary" disabled={saving} onClick={() => void save()}>
              {saving ? "写入中…" : "保存到记忆"}
            </button>
            <button className="button ghost" disabled={saving} onClick={() => void save(true)}>
              清除偏好
            </button>
          </div>
        </section>

        <section className="memory-explain">
          <span className="eyebrow">记忆如何生效</span>
          <ol className="memory-steps">
            <li>
              <span>01</span>
              <div>
                <strong>偏好写入</strong>
                <p>保存时生成一个 preference 记忆条目，记录 artifact ID 与 revision，可追溯每一次修改。</p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>检索留痕</strong>
                <p>每次检索把查询、实际过滤条件与命中数写成 progress 轨迹，用来看见“记忆做了什么”。</p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <strong>下次复用</strong>
                <p>新检索只在用户没有显式填写时才套用偏好，并在检索计划里注明“记忆偏好”。</p>
              </div>
            </li>
          </ol>
        </section>
      </div>

      <div className="memory-grid">
        <section className="memory-list-card">
          <div className="card-title">
            <div>
              <span className="eyebrow">Recent traces</span>
              <h2>最近的检索轨迹</h2>
            </div>
            <span className="badge">{snapshot?.searches.length ?? 0} 条</span>
          </div>
          {loading ? (
            <div className="skeleton" />
          ) : snapshot?.searches.length ? (
            <ul className="trace-list">
              {snapshot.searches.slice(0, 8).map((trace, index) => (
                <li key={`${trace.at}-${index}`}>
                  <div>
                    <strong>{trace.query}</strong>
                    <span className="mono muted">{describeFilters(trace.filters)}</span>
                  </div>
                  <div className="trace-side">
                    <span>{trace.hits} 段</span>
                    <span className="muted">{timeLabel(trace.at)}</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">还没有检索轨迹。去检索一次，再回来看看。</p>
          )}
        </section>

        <section className="memory-list-card">
          <div className="card-title">
            <div>
              <span className="eyebrow">Artifacts</span>
              <h2>偏好版本</h2>
            </div>
            <span className="badge">{snapshot?.memories.length ?? 0} 个</span>
          </div>
          {loading ? (
            <div className="skeleton" />
          ) : snapshot?.memories.length ? (
            <ul className="artifact-list">
              {snapshot.memories.slice(0, 8).map((memory, index) => (
                <li key={`${memory.artifact}-${index}`}>
                  <div>
                    <strong>{memory.summary}</strong>
                    <span className="mono muted">
                      {shortId(memory.artifact)} · rev {memory.revision ?? "—"}
                    </span>
                  </div>
                  <span className="muted">{timeLabel(memory.saved_at)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">还没有保存过偏好。保存一次后，这里会出现对应的记忆版本。</p>
          )}
        </section>
      </div>
    </div>
  );
}
