import { afterEach, expect, test, vi } from 'vitest'
import type { DigestDetail, Item } from '../types.ts'
import {
  SNAPSHOT_STORAGE_KEY,
  clearSnapshot,
  readSnapshot,
  syncSnapshot,
  writeSnapshot,
} from '../snapshot.ts'

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

function item(id: number, deadline: number | null): Item {
  return {
    item_id: id,
    kind: 'notice',
    kind_label: '通知公告',
    kind_icon: '📋',
    title: `条目 ${id}`,
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

const DIGEST: DigestDetail = {
  digest_id: 9,
  day: '2026-10-05',
  window_from: 1_700_000_000,
  window_to: 1_700_086_400,
  created_at: 1_700_090_000,
  item_count: 1,
  body_md: '# 守夜人日报',
  items: [item(1, null)],
}

// ⚠️ 期望值**逐字写死**，不许用 `toEqual(某个常量)` —— 那是自指的
// （见 `uiState.test.ts` 顶部那条 T5 review Low-1 的教训）。
test('没存过 ⇒ null', () => {
  expect(readSnapshot()).toBeNull()
})

test('存了再读 ⇒ 逐字相同', () => {
  writeSnapshot({
    synced_at: 1_700_000_000,
    feed: [item(1, null)],
    calendar: [item(2, 1_700_100_000)],
    digests: [DIGEST],
  })
  expect(readSnapshot()).toEqual({
    synced_at: 1_700_000_000,
    feed: [item(1, null)],
    calendar: [item(2, 1_700_100_000)],
    digests: [DIGEST],
  })
})

test('⚠️ 垃圾 JSON / 非对象 ⇒ null，且不抛', () => {
  localStorage.setItem(SNAPSHOT_STORAGE_KEY, '{not json')
  expect(readSnapshot()).toBeNull()
  localStorage.setItem(SNAPSHOT_STORAGE_KEY, '42')
  expect(readSnapshot()).toBeNull()
})

test('⚠️ 形状不对（缺 synced_at / 数组字段不是数组）⇒ null，不抛', () => {
  // 半写 / 被外力改过的快照必须被当成"没有快照"，而不是渲染出半个页面
  localStorage.setItem(SNAPSHOT_STORAGE_KEY, JSON.stringify({ feed: [] }))
  expect(readSnapshot()).toBeNull()
  localStorage.setItem(
    SNAPSHOT_STORAGE_KEY,
    JSON.stringify({ synced_at: 1, feed: 'nope', calendar: [], digests: [] }),
  )
  expect(readSnapshot()).toBeNull()
  // ⚠️ 上面两条**都到不了** `typeof s.synced_at !== 'number'` 那一行
  // （`{feed: []}` 被更早的数组守卫拦下；`feed: 'nope'` 也是）——
  // review 的 M1 变异证实：删掉 synced_at 守卫后它们仍全绿。这一条是
  // **唯一到达那一行的输入**：四个字段的数组都对，只有 synced_at 类型错。
  localStorage.setItem(
    SNAPSHOT_STORAGE_KEY,
    JSON.stringify({ synced_at: 'x', feed: [], calendar: [], digests: [] }),
  )
  expect(readSnapshot()).toBeNull()
})

test('clearSnapshot 之后 ⇒ null', () => {
  writeSnapshot({ synced_at: 1, feed: [], calendar: [], digests: [] })
  clearSnapshot()
  expect(readSnapshot()).toBeNull()
})

// ── T2 加固（review）：`syncSnapshot` 此前**全仓零测试调用** ────────────────
//
// ⚠️ 为什么非补不可：M4 变异（把 `calendar: calendar.items` 写成 `calendar: []`）
// 原本全绿——不是"变异全红但没测到"，而是"变异根本不红"：没有任何测试经过
// `syncSnapshot` 这条路径。它却是快照的唯一生产者，App 在挂载/网络恢复时调的就是它。

/** 造一个能认出来的 Item 体（字段齐，便于断言"这确实是那一块"）。 */
function feedItem(id: number): Item {
  return {
    item_id: id,
    kind: 'notice',
    kind_label: '通知公告',
    kind_icon: '📋',
    title: `信息流条目 ${id}`,
    detail: null,
    event_ts: 1_700_000_000,
    deadline_ts: null,
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

const CAL_ITEM = { ...feedItem(900), deadline_ts: 1_700_500_000 }
const DIGEST_DETAIL = {
  digest_id: 9,
  day: '2026-10-05',
  window_from: 1_700_000_000,
  window_to: 1_700_086_400,
  created_at: 1_700_090_000,
  item_count: 1,
  body_md: '# 守夜人日报',
  items: [feedItem(1)],
}

/** 按 URL 分发：三个端点各回一个**可识别**的体。 */
function stubApi() {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const u = String(url)
      if (u.startsWith('/api/items?')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ items: [feedItem(11)], total: 1, limit: 200, offset: 0 }) })
      }
      if (u === '/api/calendar') {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ items: [CAL_ITEM], total: 1 }) })
      }
      if (u === '/api/digests') {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ digests: [{ ...DIGEST_DETAIL, items: undefined }] }) })
      }
      if (u === '/api/digests/9') {
        return Promise.resolve({ ok: true, status: 200, json: async () => DIGEST_DETAIL })
      }
      return Promise.reject(new Error(`未预期的 URL：${u}`))
    }),
  )
}

test('syncSnapshot 把三块数据都收进快照（feed / calendar / digests 各一条）', async () => {
  stubApi()
  await syncSnapshot()
  const s = readSnapshot()
  expect(s).not.toBeNull()
  // 逐块断言：少收任何一块（比如 M4 去掉 fetchCalendar）这里必红。
  expect(s!.feed).toEqual([feedItem(11)])
  expect(s!.calendar).toEqual([CAL_ITEM])
  expect(s!.digests).toEqual([DIGEST_DETAIL])
  expect(typeof s!.synced_at).toBe('number')
})

test('⚠️ 任一请求失败 ⇒ 整个 syncSnapshot 抛，且**不写半份快照**', async () => {
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const u = String(url)
    if (u === '/api/digests') {
      return Promise.resolve({ ok: false, status: 500, json: async () => ({ detail: '内部错误' }) })
    }
    if (u.startsWith('/api/items?')) {
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ items: [feedItem(11)], total: 1, limit: 200, offset: 0 }) })
    }
    if (u === '/api/calendar') {
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ items: [CAL_ITEM], total: 1 }) })
    }
    return Promise.reject(new Error(`未预期的 URL：${u}`))
  }))
  await expect(syncSnapshot()).rejects.toThrow()
  // 半份快照（有信息流、没日报）会让离线时"日报不见了"，看起来像被删了。
  expect(readSnapshot()).toBeNull()
})
