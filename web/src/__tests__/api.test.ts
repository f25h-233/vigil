import { describe, expect, it, vi } from 'vitest'
import {
  addPerson,
  deleteItem,
  fetchItem,
  fetchItems,
  removePerson,
  setItemKind,
  undoLast,
} from '../api'

describe('fetchItems 的查询串', () => {
  it('丢掉 undefined / 空串，不发出空参数', async () => {
    const spy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
    })
    vi.stubGlobal('fetch', spy)
    // ⚠️ Task 10 改了 `ItemQuery`：`kind: string` → `kinds: string[]`。
    // 空串那条覆盖**保留**（数组里混进空 slug 时不许发出 `kind=`），
    // 只是换了载体——原来验的是"空串字段"，现在验的是"数组里的空串"。
    await fetchItems({ kinds: [''], q: undefined, limit: 50 })
    const url = String(spy.mock.calls[0][0])
    expect(url).toBe('/api/items?limit=50')
  })

  it('参数照原样带上', async () => {
    const spy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 20, offset: 40 }),
    })
    vi.stubGlobal('fetch', spy)
    await fetchItems({ q: '选课', limit: 20, offset: 40 })
    expect(String(spy.mock.calls[0][0])).toBe(
      '/api/items?q=%E9%80%89%E8%AF%BE&limit=20&offset=40',
    )
  })
})

describe('错误处理', () => {
  it('把后端的 detail 当错误消息抛出来', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: '没有这条条目：999' }),
    }))
    await expect(fetchItem(999)).rejects.toThrow('没有这条条目：999')
  })

  it('响应体不是 JSON 时回落到状态码，不吞错', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => { throw new Error('not json') },
    }))
    await expect(fetchItem(1)).rejects.toThrow('HTTP 503')
  })
})

// ── Task 10：多值查询串 ──────────────────────────────────────────

it('多值 kind 用重复参数而不是逗号拼接', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
  })
  vi.stubGlobal('fetch', spy)

  await fetchItems({ kinds: ['notice', 'academic'], limit: 50 })
  expect(spy.mock.calls[0][0]).toBe(
    '/api/items?kind=notice&kind=academic&limit=50',
  )
})

it('多值 person 同理', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
  })
  vi.stubGlobal('fetch', spy)

  await fetchItems({ persons: [111, 222], limit: 50 })
  expect(spy.mock.calls[0][0]).toBe('/api/items?person=111&person=222&limit=50')
})

it('空数组等于不筛选', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
  })
  vi.stubGlobal('fetch', spy)

  await fetchItems({ kinds: [], persons: [], limit: 50 })
  expect(spy.mock.calls[0][0]).toBe('/api/items?limit=50')
})

it('两个维度同时在场（维度内并集 × 维度间交集）', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
  })
  vi.stubGlobal('fetch', spy)

  await fetchItems({ kinds: ['notice', 'academic'], persons: [7], limit: 50 })
  // 后端把同一维度的重复参数收成一个 IN（并集）、两个维度之间是 AND。
  // 前端这一侧的责任只是"别在拼串时把两个维度揉在一起"。
  expect(spy.mock.calls[0][0]).toBe(
    '/api/items?kind=notice&kind=academic&person=7&limit=50',
  )
})

// ── Task 10：写端点的封装（Step 3 新增的 sendJSON）─────────────────
//
// ⚠️ 这几条**不是** brief 要求的，是执行期补的：`sendJSON` 里有两处
// 会静默出错的形状——① 用 `set` 而不是 `append`；② 204 没有 body 却被
// `r.json()` 解。它们错了以后**页面只会报一句看不懂的错**，而 M5 出口
// 判据 6 的「删条目 / 撤销」两条全靠这几个封装。

it('改分类：POST 到 /api/items/{id}/kind，body 带 kind', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ edit_id: 3 }),
  })
  vi.stubGlobal('fetch', spy)

  await expect(setItemKind(42, 'academic')).resolves.toEqual({ edit_id: 3 })
  const [url, init] = spy.mock.calls[0]
  expect(url).toBe('/api/items/42/kind')
  expect(init.method).toBe('POST')
  expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
  expect(init.body).toBe(JSON.stringify({ kind: 'academic' }))
})

it('删除：DELETE 不带 body、不带 Content-Type', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ edit_id: 9 }),
  })
  vi.stubGlobal('fetch', spy)

  await expect(deleteItem(42)).resolves.toEqual({ edit_id: 9 })
  const [url, init] = spy.mock.calls[0]
  expect(url).toBe('/api/items/42')
  expect(init.method).toBe('DELETE')
  // body 为 undefined 时**不许**发 Content-Type：一个声明了 JSON 却没有
  // body 的请求，Starlette 会在读 body 时给一个与真实原因无关的错。
  expect(init.headers).toBeUndefined()
  expect(init.body).toBeUndefined()
})

it('撤销：edit_id 缺省时显式发 null（后端「撤最近一步」的判据是 None）', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ undone: true }),
  })
  vi.stubGlobal('fetch', spy)

  await expect(undoLast()).resolves.toEqual({ undone: true })
  const [url, init] = spy.mock.calls[0]
  expect(url).toBe('/api/undo')
  expect(init.method).toBe('POST')
  expect(JSON.parse(init.body)).toEqual({ edit_id: null })
})

it('撤销：给了 edit_id 就撤那一条', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ undone: true }),
  })
  vi.stubGlobal('fetch', spy)

  await undoLast(7)
  expect(JSON.parse(spy.mock.calls[0][1].body)).toEqual({ edit_id: 7 })
})

it('删人物：204 没有 body，不许去解 JSON', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    status: 204,
    // 照实模拟 204：真响应就是空 body，解它必然抛
    json: async () => {
      throw new Error('Unexpected end of JSON input')
    },
  })
  vi.stubGlobal('fetch', spy)

  await expect(removePerson(111)).resolves.toBeUndefined()
  expect(spy.mock.calls[0][0]).toBe('/api/persons/111')
  expect(spy.mock.calls[0][1].method).toBe('DELETE')
})

it('新增人物：201 有 body，按 JSON 解出来', async () => {
  const spy = vi.fn().mockResolvedValue({
    ok: true,
    status: 201,
    json: async () => ({ uin: 111, label: '张老师' }),
  })
  vi.stubGlobal('fetch', spy)

  await expect(addPerson(111, '张老师')).resolves.toEqual({
    uin: 111,
    label: '张老师',
  })
  expect(JSON.parse(spy.mock.calls[0][1].body)).toEqual({
    uin: 111,
    label: '张老师',
    note: '',
  })
})

it('写端点失败时把后端的 detail 当错误消息抛出来', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: false,
    status: 404,
    json: async () => ({ detail: '没有这条条目：999' }),
  }))
  await expect(deleteItem(999)).rejects.toThrow('没有这条条目：999')
})
