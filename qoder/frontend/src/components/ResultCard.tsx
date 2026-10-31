import type { Hit } from '../types'
import { Snippet } from './Snippet'

type Props = {
  hit: Hit
  keyword: string | null
  active: boolean
  onSelect: (paperId: string) => void
}

export function ResultCard({ hit, keyword, active, onSelect }: Props) {
  return (
    <article
      className={`group rounded-xl border bg-surface px-5 py-4 transition ${
        active ? 'border-accent/50 shadow-[inset_3px_0_0_0_var(--color-accent)]' : 'border-line hover:border-accent/35'
      }`}
    >
      <header className="flex items-start justify-between gap-4">
        <h3 className="font-serif-cn text-[15px] leading-6 tracking-tight">{hit.title}</h3>
        <span className="shrink-0 rounded-md bg-paper px-2 py-0.5 text-[11px] text-muted">第 {hit.page} 页</span>
      </header>

      <p className="mt-2.5 text-[13.5px] leading-7 text-ink/85">
        <Snippet text={hit.text} keyword={keyword} />
      </p>

      <footer className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-muted">
        <span className="text-ink/70">{hit.venue}</span>
        {hit.year ? <span>· {hit.year}</span> : null}
        <span>· {hit.field}</span>
        <span
          className={`ml-1 rounded px-1.5 py-0.5 ${
            hit.has_code ? 'bg-accent-soft text-accent' : 'bg-paper text-muted'
          }`}
        >
          {hit.has_code ? '有开源代码' : '未见代码'}
        </span>
        <button
          type="button"
          onClick={() => onSelect(hit.paper_id)}
          className="ml-auto text-accent opacity-0 transition group-hover:opacity-100"
        >
          只看这篇
        </button>
      </footer>
    </article>
  )
}
