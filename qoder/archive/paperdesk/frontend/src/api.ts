import type { Health, MemorySnapshot, Paper, Preferences, SearchFilters, SearchResponse } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* keep the status text */
    }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  health: () => request<Health>('/api/health'),
  papers: () => request<{ papers: Paper[] }>('/api/papers').then((r) => r.papers),
  memory: () => request<MemorySnapshot>('/api/memory'),
  preferences: () => request<{ preferences: Partial<Preferences>; memory_connected: boolean }>('/api/preferences'),
  savePreferences: (prefs: Preferences) =>
    request<{ artifact: unknown; preferences: Preferences; memory_connected: boolean }>('/api/preferences', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(prefs),
    }),
  search: (query: string, filters: Partial<SearchFilters>, limit = 12) =>
    request<SearchResponse>('/api/search', json({ query, ...filters, limit })),
  deletePaper: (paperId: string) => request<{ deleted: string }>(`/api/papers/${paperId}`, { method: 'DELETE' }),
  upload: (file: File, meta: { venue: string; field: string; year: string; has_code: boolean }) => {
    const form = new FormData()
    form.append('file', file)
    form.append('venue', meta.venue)
    form.append('field', meta.field)
    form.append('has_code', String(meta.has_code))
    if (meta.year) form.append('year', meta.year)
    return request<Paper & { chunks: number; pages: number }>('/api/papers/upload', { method: 'POST', body: form })
  },
}
