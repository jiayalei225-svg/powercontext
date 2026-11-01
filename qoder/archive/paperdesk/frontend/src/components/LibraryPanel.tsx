import type { Paper } from '../types'

type Props = {
  papers: Paper[]
  activePaperId: string | null
  onSelect: (paperId: string | null) => void
  onImport: () => void
  onDelete: (paperId: string) => void
}

export function LibraryPanel({ papers, activePaperId, onSelect, onImport, onDelete }: Props) {
  return (
    <aside className="hidden h-full w-[264px] shrink-0 flex-col border-r border-line bg-[#fbf9f4] md:flex">
      <div className="flex items-baseline justify-between px-5 pt-6 pb-1">
        <h2 className="font-serif-cn text-[15px] tracking-wide">文献库</h2>
        <span className="text-xs text-muted">{papers.length} 篇 · {papers.reduce((n, p) => n + p.chunks, 0)} 段</span>
      </div>

      <div className="px-4 pt-3 pb-2">
        <button
          type="button"
          onClick={onImport}
          className="w-full rounded-lg border border-dashed border-line bg-surface px-3 py-2.5 text-[13px] text-ink/70 transition hover:border-accent/50 hover:text-accent"
        >
          + 导入 PDF / Markdown
        </button>
      </div>

      <ul className="scroll-thin flex-1 overflow-y-auto px-2 pb-6">
        <li>
          <button
            type="button"
            onClick={() => onSelect(null)}
            className={`mb-1 w-full rounded-lg px-3 py-2 text-left text-[13px] transition ${
              activePaperId === null ? 'bg-accent-soft text-accent' : 'text-ink/70 hover:bg-black/[0.03]'
            }`}
          >
            全部文献
          </button>
        </li>
        {papers.map((paper) => {
          const active = activePaperId === paper.paper_id
          return (
            <li key={paper.paper_id} className="group/item relative">
              <button
                type="button"
                onClick={() => onSelect(active ? null : paper.paper_id)}
                className={`w-full rounded-lg px-3 py-2.5 text-left transition ${
                  active ? 'bg-accent-soft' : 'hover:bg-black/[0.03]'
                }`}
              >
                <span className={`block text-[13px] leading-5 ${active ? 'text-accent' : 'text-ink/85'}`}>
                  {paper.title}
                </span>
                <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted">
                  <span>{paper.venue}</span>
                  {paper.year ? <span>· {paper.year}</span> : null}
                  <span>· {paper.pages} 页</span>
                </span>
              </button>
              <button
                type="button"
                title="删除这篇文献"
                onClick={() => onDelete(paper.paper_id)}
                className="absolute top-2 right-2 hidden rounded px-1.5 text-[15px] leading-none text-muted hover:text-warn group-hover/item:block"
              >
                ×
              </button>
            </li>
          )
        })}
        {papers.length === 0 ? (
          <li className="px-3 py-6 text-[12.5px] leading-6 text-muted">
            还没有文献。点上面的按钮导入 PDF，或者运行
            <code className="mx-1 rounded bg-black/[0.05] px-1 py-0.5 text-[11px]">scripts/seed.py</code>
            载入示例。
          </li>
        ) : null}
      </ul>
    </aside>
  )
}
