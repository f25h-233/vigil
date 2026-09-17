import type {
  Category,
  DigestDetail,
  DigestSummary,
  ItemDetail,
  ItemPage,
  Person,
} from './types'

// ⚠️ `Person` 类型**定义在 `types.ts`**（Task 10 Step 4），这里只 import 再转出去。
// 两个文件各定义一份的话，TS 会以其中一份为准、另一份悄悄失效——
// 而 `types.ts` 是「与后端契约逐字对应」的那一份，它必须是唯一的真相源。
export type { Person }

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

async function sendJSON<T>(url: string, method: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      const b = (await r.json()) as { detail?: unknown }
      if (typeof b.detail === 'string') msg = b.detail
    } catch {
      /* 非 JSON 响应（比如未构建时的 503 HTML）就用状态码 */
    }
    throw new Error(msg)
  }
  // 204 没有 body——`r.json()` 会抛，必须显式短路
  if (r.status === 204) return undefined as T
  return (await r.json()) as T
}

export type ItemQuery = {
  /** ⚠️ 多值。**空数组与不传同义**（= 不筛选），别把 [] 拼成空参数。 */
  kinds?: string[]
  /** 人物维度，值是 uin（QQ 号）。 */
  persons?: number[]
  since?: string
  until?: string
  group?: number
  q?: string
  limit?: number
  offset?: number
}

export function fetchItems(query: ItemQuery): Promise<ItemPage> {
  const p = new URLSearchParams()
  // ⚠️ 必须用 append 而不是 set：set 会让后一个值覆盖前一个，
  // 于是"选了三个类目"发出去变成"只筛最后一个"，而**页面不会报错**。
  for (const k of query.kinds ?? []) {
    if (k) p.append('kind', k)
  }
  for (const u of query.persons ?? []) {
    p.append('person', String(u))
  }
  if (query.since) p.set('since', query.since)
  if (query.until) p.set('until', query.until)
  if (query.group !== undefined && query.group !== null) {
    p.set('group', String(query.group))
  }
  if (query.q) p.set('q', query.q)
  if (query.limit !== undefined) p.set('limit', String(query.limit))
  if (query.offset !== undefined) p.set('offset', String(query.offset))
  return getJSON<ItemPage>(`/api/items?${p.toString()}`)
}

export const fetchItem = (id: number) => getJSON<ItemDetail>(`/api/items/${id}`)

export const fetchCategories = () =>
  getJSON<{ categories: Category[] }>('/api/categories')

export const fetchDigests = () =>
  getJSON<{ digests: DigestSummary[] }>('/api/digests')

export const fetchDigest = (id: number) =>
  getJSON<DigestDetail>(`/api/digests/${id}`)

export const fetchPersons = () =>
  getJSON<{ persons: Person[] }>('/api/persons')

export const addPerson = (uin: number, label: string, note = '') =>
  sendJSON<{ uin: number; label: string }>('/api/persons', 'POST', {
    uin,
    label,
    note,
  })

export const removePerson = (uin: number) =>
  sendJSON<void>(`/api/persons/${uin}`, 'DELETE')

export const setItemKind = (itemId: number, kind: string) =>
  sendJSON<{ edit_id: number }>(`/api/items/${itemId}/kind`, 'POST', { kind })

export const deleteItem = (itemId: number) =>
  sendJSON<{ edit_id: number }>(`/api/items/${itemId}`, 'DELETE')

export const undoLast = (editId?: number) =>
  sendJSON<{ undone: boolean }>('/api/undo', 'POST', {
    edit_id: editId ?? null,
  })
