import { useEffect, useState } from 'react'
import type { MemorySnapshot, Preferences } from '../types'

type Props = {
  snapshot: MemorySnapshot
  onSave: (prefs: Preferences) => Promise<void>
  onRefresh: () => void
}

const EMPTY: Preferences = {
  default_year_from: null,
  default_venues: [],
  default_field: null,
  require_code: false,
  topics: [],
  reading_style: null,
}

const KIND_LABEL: Record<string, string> = {
  preference: '检索偏好',
  progress: '检索记录',
  state: '进度',
  constraint: '约束',
}

function splitList(raw: string): string[] {
  return raw
    .split(/[,，、\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function MemoryPanel({ snapshot, onSave, onRefresh }: Props) {
  const [draft, setDraft] = useState<Preferences>(EMPTY)
  const [venuesText, setVenuesText] = useState('')
  const [topicsText, setTopicsText] = useState('')
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const prefs = { ...EMPTY, ...snapshot.preferences } as Preferences
    setDraft(prefs)
    setVenuesText((prefs.default_venues || []).join('、'))
    setTopicsText((prefs.topics || []).join('、'))
  }, [snapshot.preferences])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setSaving(true)
    setError(null)
    try {
      await onSave({ ...draft, default_venues: splitList(venuesText), topics: splitList(topicsText) })
      setSavedAt(Date.now())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <aside className="scroll-thin hidden h-full w-[330px] shrink-0 overflow-y-auto border-l border-line bg-[#fbf9f4] xl:block">
      <div className="px-5 pt-6">
        <div className="flex items-center gap-2">
          <span
            className={`h-1.5 w-1.5 rounded-full ${snapshot.connected ? 'bg-accent' : 'bg-warn'}`}
            aria-hidden
          />
          <h2 className="font-serif-cn text-[15px]">记忆</h2>
          <span className="ml-auto text-[11px] text-muted">
            {snapshot.connected ? 'PowerContext 已连接' : '未连接'}
          </span>
        </div>
        <p className="mt-1.5 text-[11.5px] leading-5 text-muted">
          偏好存在 PowerContext 里，换一次会话、换一个入口都还在，检索时自动生效。
        </p>
      </div>

      <form onSubmit={submit} className="mt-4 space-y-3.5 px-5">
        <Field label="默认只看">
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={draft.default_year_from ?? ''}
              onChange={(e) =>
                setDraft({ ...draft, default_year_from: e.target.value ? Number(e.target.value) : null })
              }
              placeholder="不限"
              className="w-24 rounded-md border border-line bg-surface px-2 py-1.5 text-[13px] outline-none focus:border-accent/60"
            />
            <span className="text-[12px] text-muted">年及以后</span>
          </div>
        </Field>

        <Field label="常读 venue">
          <input
            value={venuesText}
            onChange={(e) => setVenuesText(e.target.value)}
            placeholder="NeurIPS、ICLR"
            className="w-full rounded-md border border-line bg-surface px-2 py-1.5 text-[13px] outline-none focus:border-accent/60"
          />
        </Field>

        <Field label="关注方向">
          <input
            value={topicsText}
            onChange={(e) => setTopicsText(e.target.value)}
            placeholder="图神经网络、检索增强"
            className="w-full rounded-md border border-line bg-surface px-2 py-1.5 text-[13px] outline-none focus:border-accent/60"
          />
        </Field>

        <Field label="阅读习惯">
          <input
            value={draft.reading_style ?? ''}
            onChange={(e) => setDraft({ ...draft, reading_style: e.target.value || null })}
            placeholder="先看摘要和方法"
            className="w-full rounded-md border border-line bg-surface px-2 py-1.5 text-[13px] outline-none focus:border-accent/60"
          />
        </Field>

        <label className="flex items-center gap-2 text-[13px] text-ink/80">
          <input
            type="checkbox"
            checked={draft.require_code}
            onChange={(e) => setDraft({ ...draft, require_code: e.target.checked })}
            className="h-3.5 w-3.5 accent-[#0b6b5f]"
          />
          排除没有开源代码的论文
        </label>

        <button
          type="submit"
          disabled={saving}
          className="w-full rounded-lg bg-accent px-3 py-2 text-[13px] text-white transition hover:bg-[#095a50] disabled:opacity-60"
        >
          {saving ? '写入中…' : '保存到记忆'}
        </button>
        {savedAt ? <p className="text-[11px] text-accent">已写入，下次检索自动应用。</p> : null}
        {error ? <p className="text-[11px] text-warn">{error}</p> : null}
      </form>

      <div className="mt-6 border-t border-line px-5 pt-4">
        <div className="flex items-center justify-between">
          <h3 className="text-[12px] tracking-wide text-muted">记忆条目</h3>
          <button type="button" onClick={onRefresh} className="text-[11px] text-accent">
            刷新
          </button>
        </div>
        <ul className="mt-2 space-y-1.5 pb-6">
          {snapshot.entries.slice(0, 8).map((entry, index) => (
            <li key={`${entry.artifact_id}-${index}`} className="rounded-md bg-surface px-2.5 py-2 text-[11.5px]">
              <div className="flex items-center gap-1.5 text-[10.5px] text-muted">
                <span className="rounded bg-accent-soft px-1.5 py-0.5 text-accent">
                  {KIND_LABEL[entry.kind] ?? entry.kind}
                </span>
                <span>rev {entry.revision}</span>
                <span className="ml-auto font-mono text-[9.5px]">{entry.artifact_id?.slice(4, 12)}</span>
              </div>
              <p className="mt-1 line-clamp-2 leading-5 text-ink/70">
                {entry.text.replace(/^paperdesk\.(prefs|search)\.v1\|/, '')}
              </p>
            </li>
          ))}
          {snapshot.entries.length === 0 ? (
            <li className="py-3 text-[11.5px] leading-5 text-muted">
              还没有记忆。设置一次偏好，或在检索框里搜一次，这里就会出现记录。
            </li>
          ) : null}
        </ul>
      </div>
    </aside>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[11.5px] text-muted">{label}</div>
      {children}
    </div>
  )
}
