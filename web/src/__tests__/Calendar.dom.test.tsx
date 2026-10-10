// ⚠️ 逃生舱修正：brief 的 import 里有 `within`，但**全文从未用到**。
// 本仓 `tsconfig.json` 的 `noUnusedLocals: true` + `tsc -b` 会把测试文件一起编译
// ⇒ 照抄 brief 会让 `npm run build` 报 TS6133 而 `REAL_EXIT=1`（与 T2 偏差 3 同形）。
// 纯 import 删减，不动任何断言。
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import Calendar from '../views/Calendar.tsx'
import { SNAPSHOT_STORAGE_KEY } from '../snapshot.ts'
import type { Item } from '../types.ts'

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

function item(id: number, deadline: number | null): Item {
  return {
    item_id: id,
    kind: 'notice',
    kind_label: '通知公告',
    kind_icon: '📋',
    title: `条目${id}`,
    detail: null,
    event_ts: 1_700_000_000,
    deadline_ts: deadline,
    group_id: 111,
    group_name: '甲群',
    actor: null,
    actor_uin: null,
    place: null,
    amount: null,
    links: [],
    source_count: 0,
  }
}

function installFetch(items: Item[]) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
      if (url.startsWith('/api/calendar')) return ok({ items, total: items.length })
      if (url.startsWith('/api/categories')) return ok({ categories: [] })
      return ok({})
    }),
  )
  return calls
}

/** 本机时区下某天的 epoch 秒。写测试时**不要硬编码时区**。 */
function at(y: number, mo: number, d: number): number {
  return Math.floor(new Date(y, mo - 1, d, 0, 0, 0).getTime() / 1000)
}

test('⚠️ 只标截止日、不显示时刻（spec §1.2 + G4）', async () => {
  // 固定"今天"到 2026-10，让 2026-10-20 是未来、2026-10-05 已过
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 9, 10, 12, 0, 0))
  installFetch([item(1, at(2026, 10, 20)), item(2, at(2026, 10, 5))])
  render(<Calendar />)
  await screen.findByText('2026年10月')
  const html = document.body.innerHTML
  // ⚠️ 变异反证：把 fmtDateTime 用进格子 ⇒ 本条必红
  expect(html).not.toContain('00:00')
})

test('点某天 ⇒ 列当天到期的条目', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 9, 10, 12, 0, 0))
  installFetch([item(1, at(2026, 10, 20)), item(2, at(2026, 10, 21))])
  render(<Calendar />)
  await screen.findByText('2026年10月')
  await userEvent.click(screen.getByRole('button', { name: /10 月 20 日/ }))
  expect(screen.getByText('条目1')).toBeTruthy()
  expect(screen.queryByText('条目2')).toBeNull()
})

test('⚠️ 跨月翻页（12 月 → 次年 1 月）', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 11, 15, 12, 0, 0)) // 2026-12
  installFetch([])
  render(<Calendar />)
  await screen.findByText('2026年12月')
  await userEvent.click(screen.getByRole('button', { name: '下个月' }))
  // ⚠️ 变异反证：把 `new Date(y, m + 1, 1)` 写成 `new Date(y + 1, m + 1, 1)` ⇒ 红
  expect(screen.getByText('2027年1月')).toBeTruthy()
  await userEvent.click(screen.getByRole('button', { name: '上个月' }))
  expect(screen.getByText('2026年12月')).toBeTruthy()
})

test('⚠️ 网络失败且无快照 ⇒ 说"离线"而不是"没有条目"（G10）', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }),
  )
  render(<Calendar />)
  const msg = await screen.findByText(/离线/)
  expect(msg.textContent).toContain('还没有本地快照')
})

test('⚠️ 网络失败但有快照 ⇒ 显示快照 + 同步时刻', async () => {
  // ⚠️ 逃生舱修正（brief 的断言与 brief 自己的 Step 4 实现**不相容**）：
  // brief 原写 `getByText(/条目7|10 月 20 日/)`，但
  //   ① 条目标题只在**点了某天之后**才渲染（日历首屏无意列表）；
  //   ② "10 月 20 日" 只作为格子按钮的 **aria-label** 存在，不是文本节点。
  // ⇒ 按"验证快照数据真的渲染出来了 + 同步时刻可见"这个**原意**重写为下面两条。
  // 固定"今天"到 2026-10，否则这一条会随真实日期漂移（20 号可能翻出当前月）。
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 9, 10, 12, 0, 0))
  localStorage.setItem(
    SNAPSHOT_STORAGE_KEY,
    JSON.stringify({
      synced_at: Math.floor(new Date(2026, 9, 9, 8, 30).getTime() / 1000),
      feed: [],
      calendar: [item(7, at(2026, 10, 20))],
      digests: [],
    }),
  )
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }),
  )
  render(<Calendar />)
  const banner = await screen.findByText(/快照/)
  // 同步时刻**逐字**可见（"不许假装实时"——G10 / 出口标准 5）
  expect(banner.textContent).toContain('10月9日 08:30')
  // 快照里的日历条目真的进了网格：10 月 20 日那格有一个到期点
  expect(screen.getByLabelText('1 条到期')).toBeTruthy()
})
