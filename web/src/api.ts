import type {
  Category,
  DigestDetail,
  DigestSummary,
  ItemDetail,
  ItemPage,
} from './types'

async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) {
    // 后端出错时给的是 {"detail": "..."}；拿不到就说状态码，
    // 但**绝不吞掉错误**——静默的空列表会被读成「没有数据」。
    let msg = `HTTP ${r.status}`
    try {
      const body = (await r.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') msg = body.detail
    } catch {
      // 响应不是 JSON（比如前端未构建时的 503 HTML），就用状态码
    }
    throw new Error(msg)
  }
  return (await r.json()) as T
}

export type ItemQuery = {
  kind?: string
  since?: string
  until?: string
  group?: number
  q?: string
  limit?: number
  offset?: number
}

export function fetchItems(query: ItemQuery): Promise<ItemPage> {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  }
  return getJSON<ItemPage>(`/api/items?${p.toString()}`)
}

export const fetchItem = (id: number) => getJSON<ItemDetail>(`/api/items/${id}`)

export const fetchCategories = () =>
  getJSON<{ categories: Category[] }>('/api/categories')

export const fetchDigests = () =>
  getJSON<{ digests: DigestSummary[] }>('/api/digests')

export const fetchDigest = (id: number) =>
  getJSON<DigestDetail>(`/api/digests/${id}`)
