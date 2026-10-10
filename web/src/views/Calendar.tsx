import { useEffect, useMemo, useState } from 'react'
import { fetchCalendar } from '../api.ts'
import ItemCard from '../components/ItemCard.tsx'
import { readSnapshot } from '../snapshot.ts'
import type { Item } from '../types.ts'

/** 周一为首列（中文规划类应用的常见约定）。 */
const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

const pad = (n: number) => String(n).padStart(2, '0')

/** 本机时区的 `YYYY-MM-DD`。字符串比较即日期比较（同位数）。 */
function dayKey(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/**
 * 6×7 = 42 格的月历网格，从「含当月 1 号的那一周的周一」起算。
 * 固定 42 格 ⇒ 布局不随月份跳变（跨月/跨年由 `new Date(y, m, d)` 自己进位）。
 */
function monthGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1)
  const offset = (first.getDay() + 6) % 7 // 周一 = 0
  return Array.from({ length: 42 }, (_, i) => new Date(year, month, 1 - offset + i))
}

export default function Calendar() {
  // null = 还没读到（请求在飞）；与「读到了、0 条」分开（G10 的同一条判据）
  const [items, setItems] = useState<Item[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  /** 数据来自快照时的同步时刻；实时数据时为 null。 */
  const [snapshotAt, setSnapshotAt] = useState<number | null>(null)
  const [reloadTick, setReloadTick] = useState(0)

  const today = dayKey(new Date())
  const [cursor, setCursor] = useState(() => {
    const now = new Date()
    return { y: now.getFullYear(), m: now.getMonth() }
  })
  const [picked, setPicked] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setErr(null)
    fetchCalendar()
      .then((r) => {
        if (!alive) return
        setItems(r.items)
        setSnapshotAt(null)
      })
      .catch((e: unknown) => {
        if (!alive) return
        // ⚠️ 失败了才回落快照。**三态必须分开**（spec 出口标准 5）：
        // 网络通没数据 / 断网有快照 / 断网无快照
        const snap = readSnapshot()
        if (snap !== null) {
          setItems(snap.calendar)
          setSnapshotAt(snap.synced_at)
          setErr(null)
        } else {
          setItems(null)
          setErr(e instanceof Error ? e.message : String(e))
        }
      })
    return () => {
      alive = false
    }
  }, [reloadTick])

  // 按本地日分桶（⚠️ 与后端 `_day_start`/`_day_of` 同一个口径：本机时区）
  const byDay = useMemo(() => {
    const m = new Map<string, Item[]>()
    for (const it of items ?? []) {
      if (it.deadline_ts === null) continue
      const k = dayKey(new Date(it.deadline_ts * 1000))
      const arr = m.get(k)
      if (arr) arr.push(it)
      else m.set(k, [it])
    }
    return m
  }, [items])

  const grid = useMemo(() => monthGrid(cursor.y, cursor.m), [cursor])
  const dayItems = picked !== null ? (byDay.get(picked) ?? []) : []

  return (
    <div>
      {/* ⚠️ 快照横幅：**必须**说清这是何时同步的，不许假装实时（G10 / 出口标准 5） */}
      {snapshotAt !== null && (
        <div className="mb-3 rounded-lg bg-vigil-warn-soft p-3 text-sm text-vigil-warn">
          离线：下面是 <SnapshotTime ts={snapshotAt} /> 同步的快照。
        </div>
      )}

      {err !== null && (
        <div className="mb-3 rounded-lg bg-vigil-danger-soft p-3 text-sm text-vigil-danger">
          <p>日历读取失败：{err}</p>
          <p className="mt-1 text-xs">离线，且还没有本地快照。</p>
          <button
            onClick={() => setReloadTick((t) => t + 1)}
            className="mt-2 rounded-lg bg-vigil-danger-btn px-3 py-1.5 text-xs text-vigil-danger-text active:bg-vigil-danger-btn-active"
          >
            重试
          </button>
        </div>
      )}

      <div className="mb-2 flex items-center justify-between">
        <button
          onClick={() => setCursor((c) => shiftMonth(c, -1))}
          aria-label="上个月"
          className="rounded-md px-2 py-1 text-sm text-vigil-fg-3 active:bg-vigil-surface"
        >
          ‹
        </button>
        <span className="text-sm font-medium">
          {cursor.y}年{cursor.m + 1}月
        </span>
        <button
          onClick={() => setCursor((c) => shiftMonth(c, 1))}
          aria-label="下个月"
          className="rounded-md px-2 py-1 text-sm text-vigil-fg-3 active:bg-vigil-surface"
        >
          ›
        </button>
      </div>

      <div className="grid grid-cols-7 gap-1 text-center text-xs text-vigil-fg-4">
        {WEEKDAYS.map((w) => (
          <div key={w} className="py-1">
            {w}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7 gap-1">
        {grid.map((d) => {
          const k = dayKey(d)
          const n = byDay.get(k)?.length ?? 0
          const inMonth = d.getMonth() === cursor.m
          const isToday = k === today
          // ⚠️ "已过期" 用 **--v-fg-4**（最弱的前景 token），而不是给
          // `bg-vigil-accent` 挂一个 `/40` 透明度修饰符
          // ——语义 token 不许带透明度修饰符（G1 / 勘误 E3；`noRawPalette.test.ts` 守）。
          // ⚠️ 上面这句里那个修饰符**刻意拆开写**：本文件是 `.tsx`，
          // `noRawPalette.test.ts` 的 `TOKEN_WITH_ALPHA` 会按**纯文本**扫到散文字面量
          // （它自己的正则字面量也靠 `ALLOW` 跳过自己）。照抄 brief 的整串写法会让**全量测试红**。
          const overdue = k < today
          return (
            <button
              key={k}
              onClick={() => setPicked(k)}
              aria-label={`${d.getMonth() + 1} 月 ${d.getDate()} 日`}
              className={
                'flex flex-col items-center gap-1 rounded-md py-2 text-xs ' +
                (inMonth ? 'text-vigil-fg-2' : 'text-vigil-fg-4') +
                (picked === k ? ' bg-vigil-surface-2' : ' active:bg-vigil-surface') +
                (isToday ? ' outline outline-1 outline-vigil-accent' : '')
              }
            >
              <span>{d.getDate()}</span>
              {/* ⭐ 有截止日才打点；到期的实心亮、已过期的变淡（用户 Q2） */}
              {n > 0 && (
                <span
                  aria-label={`${n} 条到期`}
                  // `data-overdue` 是给测试用的**语义**钩子（T4 加固）：判据读它，
                  // 而不是读 `bg-vigil-fg-4` 那个**字面类名**（换 token / 调色会假红）。
                  // 它同时是"已过期以变淡区分"（用户 Q2）这条契约的**可查询**载体。
                  data-overdue={overdue ? 'true' : 'false'}
                  className={
                    'h-1.5 w-1.5 rounded-full ' +
                    (overdue ? 'bg-vigil-fg-4' : 'bg-vigil-accent')
                  }
                />
              )}
            </button>
          )
        })}
      </div>

      {picked !== null && (
        <div className="mt-4">
          <p className="mb-2 text-xs text-vigil-fg-4">{picked} 到期</p>
          {dayItems.length === 0 ? (
            <p className="text-sm text-vigil-fg-4">这一天没有到期的条目。</p>
          ) : (
            <ul className="space-y-2">
              {dayItems.map((it) => (
                // ⚠️ 不传 onMutated ⇒ 只读卡（与日报页同一个用法，勘误 E2）
                <ItemCard key={it.item_id} item={it} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function shiftMonth(c: { y: number; m: number }, delta: number): { y: number; m: number } {
  // `new Date(y, m + delta, 1)` 自己处理跨年进位，不手动算
  const d = new Date(c.y, c.m + delta, 1)
  return { y: d.getFullYear(), m: d.getMonth() }
}

/** 快照时刻，精确到分钟。**只用于横幅**，不进日历格。 */
function SnapshotTime({ ts }: { ts: number }) {
  const d = new Date(ts * 1000)
  return (
    <span>
      {d.getMonth() + 1}月{d.getDate()}日 {pad(d.getHours())}:{pad(d.getMinutes())}
    </span>
  )
}
