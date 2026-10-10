/**
 * 离线快照：把「最近一次在线同步到的数据」留在 localStorage，断网时读它。
 *
 * ⚠️ **为什么是 localStorage 不是 IndexedDB**（第三版 spec §1.6 实测）：
 * 快照体量 ≈ 47 KB（最近 5 天信息流 + 全量 36 条截止日 + 5 篇日报），
 * 而 localStorage 上限 ≈ 5 MB —— 用了不到 1%。为此引一个 `idb` 依赖 + 异步事务
 * 是**过度设计**；本仓现有的两个持久化（`theme.ts` / `uiState.ts`）也都在这里。
 *
 * ⚠️ **为什么不用 Service Worker 缓存 API**：`vite.config.ts` 的
 * `workbox.navigateFallbackDenylist = [/^\/api\//]` 明确把 `/api/` 排除在兜底之外
 * ⇒ SW **不会**缓存 API 响应，离线数据只能由应用层自己持有。
 *
 * ⚠️ 快照是**只读**的：离线时写操作不可用（spec §3.3/§3.4）。本模块只负责存/取。
 */

import { fetchCalendar, fetchDigest, fetchDigests, fetchItems } from './api.ts'
import type { DigestDetail, Item } from './types.ts'

export const SNAPSHOT_STORAGE_KEY = 'vigil.snapshot'

/** 信息流/日报各留最近几天。用户 2026-10-10 裁定（spec §6 Q1）。 */
const SNAPSHOT_DAYS = 5

/** 最近 5 篇日报。条数少是因为 `body_md` 已经很小（实测 99–431 B/篇，spec §1.6）。 */
const SNAPSHOT_DIGESTS = 5

/**
 * ⚠️ 拉"最近 5 天"时用 200 —— 它就是 `api.py` 的 `MAX_LIMIT`（勘误 E6）。
 * **若 5 天真的超过 200 条，快照会少收，而不是错收**。别以为拿全了。
 */
const SNAPSHOT_FEED_LIMIT = 200

export type Snapshot = {
  /** 快照生成时刻（Unix 秒）。**展示时必须用它**，不许假装数据是实时的。 */
  synced_at: number
  /** 最近 N 天的信息流条目。 */
  feed: Item[]
  /** **全量**带截止日的条目（日历用）。 */
  calendar: Item[]
  /** 最近 N 篇日报，含 `body_md`。 */
  digests: DigestDetail[]
}

/** 本地日 `YYYY-MM-DD`（与 `format.ts` 的本地时区口径一致）。 */
function localDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/**
 * 读快照。**任何异常/形状不对一律返回 `null`，绝不抛**（Review Focus #4：半写、
 * 被外力改过、localStorage 被清空）。
 *
 * ⚠️ 返回 `null` 的语义是「**没有快照**」，与「快照里是空的」是两件事——
 * 调用方必须分开说（G10）。
 */
export function readSnapshot(): Snapshot | null {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(SNAPSHOT_STORAGE_KEY)
  } catch {
    return null
  }
  if (raw === null) return null
  let o: unknown
  try {
    o = JSON.parse(raw)
  } catch {
    return null
  }
  if (typeof o !== 'object' || o === null) return null
  const s = o as Record<string, unknown>
  // ⚠️ 只校验**形状**（四个字段存在且类型对），不逐条校验 Item ——
  // 它们来自本程序自己的 API；逐字段深校验的收益不抵复杂度。
  if (typeof s.synced_at !== 'number') return null
  if (!Array.isArray(s.feed) || !Array.isArray(s.calendar) || !Array.isArray(s.digests)) {
    return null
  }
  return {
    synced_at: s.synced_at,
    feed: s.feed as Item[],
    calendar: s.calendar as Item[],
    digests: s.digests as DigestDetail[],
  }
}

/** 写快照。**存不下只影响「下次离线还能不能看」**，不该让当前这次同步失败。 */
export function writeSnapshot(s: Snapshot): void {
  try {
    localStorage.setItem(SNAPSHOT_STORAGE_KEY, JSON.stringify(s))
  } catch {
    // 配额满 / 无痕模式：静默失败。这不是当前交互的前提。
  }
}

export function clearSnapshot(): void {
  try {
    localStorage.removeItem(SNAPSHOT_STORAGE_KEY)
  } catch {
    /* 同上 */
  }
}

/**
 * 拉一次快照并落盘。**由 App 在挂载时与网络恢复时各调一次**（勘误 E1）——
 * 不挂在各视图的取数上，因为那样会漏掉用户没打开的视图。
 *
 * ⚠️ 任一请求失败 ⇒ **整个 `syncSnapshot` 失败，不写半份快照**：半份快照
 * （比如有信息流、没日报）会让离线时"日报不见了"，看起来像那些日报被删了。
 * 宁可没有快照（调用方说"离线，且还没有本地快照"），也不要一份残缺的快照。
 */
export async function syncSnapshot(): Promise<void> {
  const since = localDay(new Date(Date.now() - SNAPSHOT_DAYS * 86_400_000))
  const [feed, calendar, digestList] = await Promise.all([
    fetchItems({ since, limit: SNAPSHOT_FEED_LIMIT }),
    fetchCalendar(),
    fetchDigests(),
  ])
  const digests = await Promise.all(
    digestList.digests.slice(0, SNAPSHOT_DIGESTS).map((d) => fetchDigest(d.digest_id)),
  )
  writeSnapshot({
    synced_at: Math.floor(Date.now() / 1000),
    feed: feed.items,
    calendar: calendar.items,
    digests,
  })
}
