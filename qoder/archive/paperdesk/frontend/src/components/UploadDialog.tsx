import { useRef, useState } from 'react'
import { api } from '../api'

type Props = {
  open: boolean
  onClose: () => void
  onUploaded: () => void
}

export function UploadDialog({ open, onClose, onUploaded }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [venue, setVenue] = useState('')
  const [field, setField] = useState('')
  const [year, setYear] = useState('')
  const [hasCode, setHasCode] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  if (!open) return null

  function reset() {
    setFile(null)
    setVenue('')
    setField('')
    setYear('')
    setHasCode(false)
    setError(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      await api.upload(file, { venue, field, year, has_code: hasCode })
      reset()
      onUploaded()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 px-4" onClick={onClose}>
      <form
        onSubmit={submit}
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-md rounded-2xl border border-line bg-surface p-6 shadow-xl"
      >
        <h2 className="font-serif-cn text-lg">导入文献</h2>
        <p className="mt-1 text-[12px] leading-5 text-muted">
          支持 PDF 与 Markdown。解析后会按页切块，检索结果可以定位到具体页码。
        </p>

        <label className="mt-5 flex cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-line bg-paper px-4 py-6 text-center transition hover:border-accent/50">
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.md,.txt"
            className="hidden"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <span className="text-[13px] text-ink/80">{file ? file.name : '点击选择文件'}</span>
          <span className="mt-1 text-[11px] text-muted">{file ? `${(file.size / 1024).toFixed(0)} KB` : 'PDF / MD / TXT'}</span>
        </label>

        <div className="mt-4 grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-[11.5px] text-muted">会议 / 期刊</span>
            <input
              value={venue}
              onChange={(e) => setVenue(e.target.value)}
              placeholder="NeurIPS"
              className="w-full rounded-md border border-line px-2 py-1.5 text-[13px] outline-none focus:border-accent/60"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11.5px] text-muted">年份</span>
            <input
              value={year}
              onChange={(e) => setYear(e.target.value.replace(/\D/g, ''))}
              placeholder="2024"
              className="w-full rounded-md border border-line px-2 py-1.5 text-[13px] outline-none focus:border-accent/60"
            />
          </label>
          <label className="col-span-2 block">
            <span className="mb-1 block text-[11.5px] text-muted">领域</span>
            <input
              value={field}
              onChange={(e) => setField(e.target.value)}
              placeholder="信息检索"
              className="w-full rounded-md border border-line px-2 py-1.5 text-[13px] outline-none focus:border-accent/60"
            />
          </label>
        </div>

        <label className="mt-3 flex items-center gap-2 text-[12.5px] text-ink/80">
          <input
            type="checkbox"
            checked={hasCode}
            onChange={(e) => setHasCode(e.target.checked)}
            className="h-3.5 w-3.5 accent-[#0b6b5f]"
          />
          这篇论文附带开源代码
        </label>

        {error ? <p className="mt-3 text-[12px] text-warn">{error}</p> : null}

        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg px-3 py-2 text-[13px] text-muted hover:text-ink">
            取消
          </button>
          <button
            type="submit"
            disabled={!file || busy}
            className="rounded-lg bg-accent px-4 py-2 text-[13px] text-white transition hover:bg-[#095a50] disabled:opacity-50"
          >
            {busy ? '解析入库中…' : '导入'}
          </button>
        </div>
      </form>
    </div>
  )
}
