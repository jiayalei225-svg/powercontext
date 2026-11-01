type Props = {
  text: string
  keyword?: string | null
  limit?: number
}

/** Clip a chunk around the keyword and mark every occurrence. */
export function Snippet({ text, keyword, limit = 220 }: Props) {
  const flat = text.replace(/\s+/g, ' ').trim()
  let body = flat
  let prefix = ''
  let suffix = ''

  if (flat.length > limit) {
    const at = keyword ? flat.toLowerCase().indexOf(keyword.toLowerCase()) : -1
    const start = at > 60 ? at - 60 : 0
    body = flat.slice(start, start + limit)
    prefix = start > 0 ? '…' : ''
    suffix = start + limit < flat.length ? '…' : ''
  }

  if (!keyword) {
    return (
      <span>
        {prefix}
        {body}
        {suffix}
      </span>
    )
  }

  const parts: React.ReactNode[] = []
  const lower = body.toLowerCase()
  const needle = keyword.toLowerCase()
  let cursor = 0
  let index = lower.indexOf(needle)
  while (index !== -1) {
    if (index > cursor) parts.push(body.slice(cursor, index))
    parts.push(<mark key={`${index}-${parts.length}`}>{body.slice(index, index + keyword.length)}</mark>)
    cursor = index + keyword.length
    index = lower.indexOf(needle, cursor)
  }
  parts.push(body.slice(cursor))

  return (
    <span>
      {prefix}
      {parts}
      {suffix}
    </span>
  )
}
