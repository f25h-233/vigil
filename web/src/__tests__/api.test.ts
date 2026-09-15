import { describe, expect, it, vi } from 'vitest'
import { fetchItem, fetchItems } from '../api'

describe('fetchItems 的查询串', () => {
  it('丢掉 undefined / 空串，不发出空参数', async () => {
    const spy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
    })
    vi.stubGlobal('fetch', spy)
    await fetchItems({ kind: '', q: undefined, limit: 50 })
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
