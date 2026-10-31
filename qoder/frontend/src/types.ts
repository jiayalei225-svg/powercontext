export type Paper = {
  paper_id: string
  title: string
  year: number | null
  venue: string
  field: string
  source: string
  has_code: boolean
  pages: number
  chunks: number
}

export type Hit = {
  chunk_id: string
  text: string
  page: number
  paper_id: string
  title: string
  year: number | null
  venue: string
  field: string
  source: string
  has_code: boolean
  score: number | null
}

export type SearchFilters = {
  year_from: number | null
  year_to: number | null
  venues: string[]
  field: string | null
  paper_id: string | null
  has_code: boolean | null
}

export type SearchResponse = {
  query: string
  keyword: string | null
  results: Hit[]
  filters: Record<string, unknown>
  applied_from_memory: Record<string, unknown>
  memory_notes: string[]
  memory_connected: boolean
  total: number
}

export type Preferences = {
  default_year_from: number | null
  default_venues: string[]
  default_field: string | null
  require_code: boolean
  topics: string[]
  reading_style: string | null
}

export type MemoryEntry = {
  artifact_id: string | null
  revision: number | null
  kind: string
  text: string
  state: string | null
}

export type MemorySnapshot = {
  connected: boolean
  scope_id: string | null
  preferences: Partial<Preferences>
  searches: { query: string; hits: number; at: number }[]
  entries: MemoryEntry[]
}

export type Health = {
  seekdb: { collection: string; papers: number; chunks: number; embedding: string; mode: string }
  memory: boolean
  memory_url: string
}
