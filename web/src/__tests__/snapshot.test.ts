import { afterEach, expect, test } from 'vitest'
import type { DigestDetail, Item } from '../types.ts'
import {
  SNAPSHOT_STORAGE_KEY,
  clearSnapshot,
  readSnapshot,
  writeSnapshot,
} from '../snapshot.ts'

afterEach(() => localStorage.clear())

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
})

test('clearSnapshot 之后 ⇒ null', () => {
  writeSnapshot({ synced_at: 1, feed: [], calendar: [], digests: [] })
  clearSnapshot()
  expect(readSnapshot()).toBeNull()
})
