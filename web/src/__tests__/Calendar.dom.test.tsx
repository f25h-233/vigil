import { render, screen, waitFor, within } from '@testing-library/react'
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

/* ──────────────────────────────────────────────────────────────────────────
 * T4 加固（审查报出的两组 Important 覆盖缺口；brief 把测试面钉死了，故单开一轮）
 * ────────────────────────────────────────────────────────────────────────── */

/**
 * 取某一天格子里的"到期点"。用**语义**钩子 `data-overdue`，不读 `bg-vigil-fg-4`
 * 那个字面类名——换 token / 调色板时类名会变，而"过不过期"这件事不该跟着变。
 * 返回 undefined 表示那天没有点（没有截止日）。
 */
function dotOf(ariaLabel: string): HTMLElement | undefined {
  const cell = screen.getByRole('button', { name: ariaLabel })
  return within(cell).queryByLabelText(/条到期/) ?? undefined
}

test('⭐ 已过期的点**有**过期标记、未到期的点**没有**（用户 Q2：已过期以变淡区分）', async () => {
  // 今天 = 2026-10-10（冻结）。10-05 已过期、10-20 未到期。
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 9, 10, 12, 0, 0))
  installFetch([item(1, at(2026, 10, 5)), item(2, at(2026, 10, 20))])
  render(<Calendar />)
  await screen.findByText('2026年10月')

  const past = dotOf('10 月 5 日')
  const future = dotOf('10 月 20 日')
  expect(past, '10-05 应有到期点').toBeTruthy()
  expect(future, '10-20 应有到期点').toBeTruthy()
  // ⚠️ 变异反证：把 `k < today` 改成 `false` ⇒ `past` 的标记变 'false' ⇒ 本条红。
  expect(past?.getAttribute('data-overdue'), '已过期的那天必须被标成过期').toBe('true')
  expect(future?.getAttribute('data-overdue'), '未到期的那天不许被标成过期').toBe('false')

  // ⚠️ 变异反证：把过期点色 `bg-vigil-fg-4` 改成 `bg-vigil-accent`
  // ⇒ 两点**同一套类名** ⇒ 下面这条红。
  // ⚠️ 判据是"两者**不同**"（= 用户 Q2 的「变淡区分」这个契约），
  // **不是**"等于哪个字面类名"——后者换个 token 就假红。
  expect(past?.className, '过期与未到期的点必须**视觉可区分**（变淡）').not.toBe(future?.className)
})

test('⭐ 三态①：成功时**不许**挂快照横幅、**不许**弹错误框（通·无数据）', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 9, 10, 12, 0, 0))
  // 盘上**放一份快照**：成功路径若也读了它 / 也挂了横幅，下面两条就能抓到。
  localStorage.setItem(
    SNAPSHOT_STORAGE_KEY,
    JSON.stringify({
      synced_at: Math.floor(new Date(2026, 9, 9, 8, 30).getTime() / 1000),
      feed: [],
      calendar: [item(99, at(2026, 10, 20))],
      digests: [],
    }),
  )
  // 网络**通**，且返回**空**（三态里的第一条：通·无数据）
  installFetch([])
  render(<Calendar />)
  await screen.findByText('2026年10月')

  // ⚠️ 变异反证 X2：成功路径也 `setSnapshotAt(...)` ⇒ `快照` 横幅出现 ⇒ 本条红
  await waitFor(() => expect(screen.queryByText(/快照/), '成功时不许挂快照横幅').toBeNull())
  // ⚠️ 变异反证 X7：成功路径也 `setErr(...)` ⇒ `日历读取失败` 出现 ⇒ 本条红
  expect(screen.queryByText(/日历读取失败/), '成功时不许弹错误框').toBeNull()
  // 阴性对照：这一天**没有**条目 ⇒ 网格里一个到期点都没有（网络数据是空的那份）
  expect(screen.queryByLabelText(/条到期/)).toBeNull()
})

test('⭐ 三态②：有快照但网络通 ⇒ 显示**网络**数据、不挂横幅（X8：不许优先取快照）', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 9, 10, 12, 0, 0))
  // ⚠️ X8 的关键：**快照与网络数据必须不同**，否则测不出"优先取谁"。
  //   快照：10-05 一条（标记 item_id=888 不在）——用一个**不同的日子**当指纹。
  localStorage.setItem(
    SNAPSHOT_STORAGE_KEY,
    JSON.stringify({
      synced_at: Math.floor(new Date(2026, 9, 9, 8, 30).getTime() / 1000),
      feed: [],
      calendar: [item(888, at(2026, 10, 5))],
      digests: [],
    }),
  )
  // 网络：只有 10-20 一条（快照里**没有**这个日子）
  installFetch([item(7, at(2026, 10, 20))])
  render(<Calendar />)
  await screen.findByText('2026年10月')

  // ⚠️ 变异反证 X8：`.then` 里也 `readSnapshot()` 并 setItems(snap.calendar)
  // ⇒ 屏幕上出现的是**快照那份**（10-05 有点、10-20 没点）⇒ 下面两条红。
  await waitFor(() => expect(dotOf('10 月 20 日'), '应显示网络数据(10-20 有点)').toBeTruthy())
  expect(dotOf('10 月 5 日'), '快照那份(10-05)不许出现').toBeUndefined()
  expect(screen.queryByText(/快照/), '网络通时不挂横幅').toBeNull()
})
