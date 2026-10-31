import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api'
import { LibraryPanel } from './components/LibraryPanel'
import { MemoryPanel } from './components/MemoryPanel'
import { ResultCard } from './components/ResultCard'
import { UploadDialog } from './components/UploadDialog'
import type { Health, MemorySnapshot, Paper, Preferences, SearchResponse } from './types'

const EMPTY_MEMORY: MemorySnapshot = {
  connected: false,
  scope_id: null,
  preferences: {},
  searches: [],
  entries: [],
}

const EXAMPLES = ['过平滑', '混合检索为什么比纯向量好', '低秩适配怎么选秩', '位置编码是干什么的']

export default function App() {
  const [papers, setPapers] = useState<Paper[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [memory, setMemory] = useState<MemorySnapshot>(EMPTY_MEMORY)
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<SearchResponse | null>(null)
  const [searching, setSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activePaperId, setActivePaperId] = useState<string | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)

  const [yearFrom, setYearFrom] = useState('')
  const [yearTo, setYearTo] = useState('')
  const [venues, setVenues] = useState<string[]>([])
  const [hasCode, setHasCode] = useState(false)

  const venueOptions = useMemo(
    () => Array.from(new Set(papers.map((p) => p.venue).filter((v) => v && v !== '未标注'))).sort(),
    [papers],
  )

  const refreshBookshelf = useCallback(async () => {
    const [list, snapshot, status] = await Promise.all([api.papers(), api.memory(), api.health()])
    setPapers(list)
    setMemory(snapshot)
    setHealth(status)
  }, [])

  useEffect(() => {
    refreshBookshelf().catch((err) => setError(String(err.message ?? err)))
  }, [refreshBookshelf])

  const runSearch = useCallback(
    async (text: string) => {
      const trimmed = text.trim()
      if (!trimmed) return
      setSearching(true)
      setError(null)
      try {
        const response = await api.search(trimmed, {
          year_from: yearFrom ? Number(yearFrom) : null,
          year_to: yearTo ? Number(yearTo) : null,
          venues,
          paper_id: activePaperId,
          has_code: hasCode ? true : null,
        })
        setResult(response)
        api.memory().then(setMemory).catch(() => undefined)
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      } finally {
        setSearching(false)
      }
    },
    [activePaperId, hasCode, venues, yearFrom, yearTo],
  )

  async function deletePaper(paperId: string) {
    await api.deletePaper(paperId)
    if (activePaperId === paperId) setActivePaperId(null)
    await refreshBookshelf()
  }

  async function savePreferences(prefs: Preferences) {
    await api.savePreferences(prefs)
    const snapshot = await api.memory()
    setMemory(snapshot)
  }

  const activePaper = papers.find((p) => p.paper_id === activePaperId) ?? null

  return (
    <div className="flex h-full">
      <LibraryPanel
        papers={papers}
        activePaperId={activePaperId}
        onSelect={(id) => {
          setActivePaperId(id)
          if (result) runSearch(result.query)
        }}
        onImport={() => setUploadOpen(true)}
        onDelete={deletePaper}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-line px-5 py-4 sm:px-8">
          <div className="min-w-0">
            <h1 className="font-serif-cn text-[19px] leading-none tracking-tight">PaperDesk</h1>
            <p className="mt-1 truncate text-[11px] text-muted">文献检索工作台 · 记住你的读法</p>
          </div>
          <div className="ml-auto flex shrink-0 items-center gap-3 text-[11px] whitespace-nowrap text-muted">
            {health ? (
              <span className="hidden rounded-full bg-surface px-2.5 py-1 ring-1 ring-line sm:inline">
                {health.seekdb.embedding} · {health.seekdb.mode}
              </span>
            ) : null}
            <span className="flex items-center gap-1.5">
              <span className={`h-1.5 w-1.5 rounded-full ${memory.connected ? 'bg-accent' : 'bg-warn'}`} />
              {memory.connected ? '记忆已连接' : '记忆未连接'}
            </span>
          </div>
        </header>

        <div className="scroll-thin flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-5 py-7 sm:px-8">
            <form
              onSubmit={(e) => {
                e.preventDefault()
                runSearch(query)
              }}
              className="flex items-center gap-2 rounded-xl border border-line bg-surface px-4 py-2.5 shadow-[0_1px_2px_rgba(25,27,29,0.04)] focus-within:border-accent/50"
            >
              <span className="text-muted" aria-hidden>
                ⌕
              </span>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="用一句话描述你要找什么，比如「过平滑是怎么缓解的」"
                className="min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-muted/70"
              />
              <button
                type="submit"
                disabled={searching || !query.trim()}
                className="shrink-0 rounded-lg bg-accent px-3.5 py-1.5 text-[13px] text-white transition hover:bg-[#095a50] disabled:opacity-50"
              >
                {searching ? '检索中' : '检索'}
              </button>
            </form>

            <FilterBar
              yearFrom={yearFrom}
              yearTo={yearTo}
              onYearFrom={setYearFrom}
              onYearTo={setYearTo}
              venueOptions={venueOptions}
              venues={venues}
              onToggleVenue={(venue) =>
                setVenues((current) =>
                  current.includes(venue) ? current.filter((v) => v !== venue) : [...current, venue],
                )
              }
              hasCode={hasCode}
              onHasCode={setHasCode}
              activePaper={activePaper}
              onClearPaper={() => setActivePaperId(null)}
            />

            {error ? (
              <p className="mt-4 rounded-lg bg-warn-soft px-3 py-2 text-[12.5px] text-warn">{error}</p>
            ) : null}

            {!result && !searching ? (
              <section className="mt-14 text-center">
                <p className="font-serif-cn text-[15px] text-ink/75">几十篇文献里翻找一段话，不该靠 Ctrl+F。</p>
                <p className="mx-auto mt-2 max-w-md text-[12.5px] leading-6 text-muted">
                  问一个具体问题，它会同时做语义、关键词和条件筛选，并告诉你答案在第几页。
                </p>
                <div className="mt-5 flex flex-wrap justify-center gap-2">
                  {EXAMPLES.map((example) => (
                    <button
                      key={example}
                      type="button"
                      onClick={() => {
                        setQuery(example)
                        runSearch(example)
                      }}
                      className="rounded-full border border-line bg-surface px-3 py-1.5 text-[12px] text-ink/70 transition hover:border-accent/50 hover:text-accent"
                    >
                      {example}
                    </button>
                  ))}
                </div>
              </section>
            ) : null}

            {result ? (
              <section className="mt-6">
                {result.memory_notes.length > 0 ? (
                  <div className="mb-4 rounded-lg border border-accent/25 bg-accent-soft px-3.5 py-2.5">
                    <div className="text-[11px] tracking-wide text-accent">这次检索用了记忆里的偏好</div>
                    <ul className="mt-1 space-y-0.5">
                      {result.memory_notes.map((note) => (
                        <li key={note} className="text-[12px] leading-5 text-ink/75">
                          · {note}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                <div className="mb-3 flex items-baseline gap-2 text-[11.5px] text-muted">
                  <span className="text-ink/70">{result.total} 段命中</span>
                  {result.keyword ? <span>· 关键词「{result.keyword}」</span> : null}
                  <span>· 向量 + 全文混合排序</span>
                  {activePaper ? <span>· 限定《{activePaper.title}》</span> : null}
                </div>

                <div className="space-y-3 pb-10">
                  {result.results.map((hit) => (
                    <ResultCard
                      key={hit.chunk_id}
                      hit={hit}
                      keyword={result.keyword}
                      active={hit.paper_id === activePaperId}
                      onSelect={(id) => {
                        setActivePaperId(id)
                        runSearch(result.query)
                      }}
                    />
                  ))}
                  {result.results.length === 0 ? (
                    <div className="rounded-xl border border-line bg-surface px-5 py-8 text-center text-[13px] text-muted">
                      没有命中。试试放宽年份或 venue 条件，或者换个说法。
                    </div>
                  ) : null}
                </div>
              </section>
            ) : null}
          </div>
        </div>
      </main>

      <MemoryPanel snapshot={memory} onSave={savePreferences} onRefresh={() => api.memory().then(setMemory)} />

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={() => {
          refreshBookshelf().catch((err) => setError(String(err.message ?? err)))
        }}
      />
    </div>
  )
}

type FilterProps = {
  yearFrom: string
  yearTo: string
  onYearFrom: (value: string) => void
  onYearTo: (value: string) => void
  venueOptions: string[]
  venues: string[]
  onToggleVenue: (venue: string) => void
  hasCode: boolean
  onHasCode: (value: boolean) => void
  activePaper: Paper | null
  onClearPaper: () => void
}

function FilterBar(props: FilterProps) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-[11.5px] text-muted">
      <span className="text-muted/80">年份</span>
      <input
        value={props.yearFrom}
        onChange={(e) => props.onYearFrom(e.target.value.replace(/\D/g, '').slice(0, 4))}
        placeholder="起"
        className="w-14 rounded-md border border-line bg-surface px-1.5 py-1 text-center text-[12px] outline-none focus:border-accent/60"
      />
      <span>–</span>
      <input
        value={props.yearTo}
        onChange={(e) => props.onYearTo(e.target.value.replace(/\D/g, '').slice(0, 4))}
        placeholder="止"
        className="w-14 rounded-md border border-line bg-surface px-1.5 py-1 text-center text-[12px] outline-none focus:border-accent/60"
      />

      <span className="ml-2">venue</span>
      {props.venueOptions.map((venue) => {
        const on = props.venues.includes(venue)
        return (
          <button
            key={venue}
            type="button"
            onClick={() => props.onToggleVenue(venue)}
            className={`rounded-full border px-2 py-0.5 transition ${
              on ? 'border-accent/40 bg-accent-soft text-accent' : 'border-line bg-surface text-ink/60 hover:text-ink'
            }`}
          >
            {venue}
          </button>
        )
      })}

      <label className="ml-2 flex cursor-pointer items-center gap-1.5">
        <input
          type="checkbox"
          checked={props.hasCode}
          onChange={(e) => props.onHasCode(e.target.checked)}
          className="h-3 w-3 accent-[#0b6b5f]"
        />
        只看有代码
      </label>

      {props.activePaper ? (
        <button
          type="button"
          onClick={props.onClearPaper}
          className="ml-auto rounded-full bg-ink/5 px-2.5 py-0.5 text-ink/70"
        >
          取消限定《{props.activePaper.title.slice(0, 12)}》×
        </button>
      ) : null}
    </div>
  )
}
