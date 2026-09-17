import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from '../App.tsx'

type Call = { url: string; method: string }

function installFetch(undoResult: boolean) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, method: init?.method ?? 'GET' })
      const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
      if (url.startsWith('/api/undo')) return ok({ undone: undoResult })
      if (url.startsWith('/api/categories')) return ok({ categories: [] })
      if (url.startsWith('/api/persons')) return ok({ persons: [] })
      if (url.startsWith('/api/items')) return ok({ items: [], total: 0, limit: 50, offset: 0 })
      return ok({})
    }),
  )
  return calls
}

afterEach(() => vi.unstubAllGlobals())

test('撤销成功后必须让筛选列表重取一次', async () => {
  /**
   * ⭐ M5 A-Minor-7 缺陷 2 的守卫。
   *
   * ⚠️ 变异反证：把 `App.tsx` 的 `if (r.undone) setDataTick((t) => t + 1)`
   * 删掉 ⇒ 本条**必红**。
   */
  const calls = installFetch(true)
  render(<App />)
  await waitFor(() =>
    expect(calls.some((c) => c.url.startsWith('/api/items'))).toBe(true),
  )
  const before = calls.filter((c) => c.url.startsWith('/api/items')).length

  await userEvent.click(screen.getByRole('button', { name: /撤销/ }))

  await waitFor(() => {
    expect(calls.filter((c) => c.url.startsWith('/api/items')).length).toBeGreaterThan(before)
  }, { timeout: 2000 })
})

test('撤销**没撤成**时不许白白重取一次（阴性对照）', async () => {
  /**
   * ⭐ 这条是上一条的**阴性对照**，缺了它上一条就没有说服力。
   *
   * ⚠️ 没有它的话，「无条件 `setDataTick`」这个实现照样能让上一条绿——
   * 而那样每次点「撤销」都会白拉一次列表，包括栈空的时候
   * （而栈空恰恰是最常被点到的状态：用户点一下看看有没有东西可撤）。
   * 这与本项目「假绿」的判据是同一条：**一个只在"应该发生"时才发生的守卫，
   * 必须同时验"不该发生时它没发生"。**
   */
  const calls = installFetch(false)
  render(<App />)
  await waitFor(() =>
    expect(calls.some((c) => c.url.startsWith('/api/items'))).toBe(true),
  )
  const before = calls.filter((c) => c.url.startsWith('/api/items')).length

  await userEvent.click(screen.getByRole('button', { name: /撤销/ }))
  expect(await screen.findByText('没有可撤销的操作')).toBeTruthy()

  await new Promise((r) => setTimeout(r, 300))
  expect(calls.filter((c) => c.url.startsWith('/api/items')).length).toBe(before)
})
