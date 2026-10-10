import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchCalendar } from '../api.ts'
import ItemCard from '../components/ItemCard.tsx'
import { isOnline, subscribeConnectivity } from '../connectivity.ts'
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

/**
 * 屏幕上这批日历数据，连同**它是实时还是快照**一起存。
 *
 * ⚠️ 为什么合成**一个** state（不是 `items` + `snapshotAt` 两个）：两个 state
 * 靠"每一次 setItems 都记得同时 setSnapshotAt"这条**纪律**维持一致——纪律不是
 * 结构，漏一处就会出现「快照的数据 + 实时的结论」这种半新半旧的屏幕。
 * 出口标准 5 的两半（有快照数据 ⇔ 有横幅）正是被这个形状**结构性**保证的。
 * `Feed.tsx` 的 `Shown` 是这个形状的原始出处（T5 做对了的那一份）。
 */
type Shown = {
  items: Item[]
  /** 这批数据来自快照时的同步时刻；实时数据时为 null。 */
  snapshotAt: number | null
}

export default function Calendar() {
  // null = 还没读到（请求在飞）；与「读到了、0 条」分开（G10 的同一条判据）
  const [shown, setShown] = useState<Shown | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [reloadTick, setReloadTick] = useState(0)

  // ── 在线/离线（F1/F2）：`connectivity.ts` 是状态的单一真相源 ─────────────
  //
  // ⚠️ 与 `Feed.tsx`/`Digests.tsx` 同一形状（spec R4：别让两个组件各自探测）。
  // ⚠️ effect **返回**退订函数 ⇒ 卸载时摘掉订阅，且 `StrictMode`（挂→卸→挂）
  //   下净剩**一个**订阅（「卸」摘掉第一个、「挂」再装一个）。
  //
  // ⚠️⚠️ 这一条状态**必须**有（F1）：`api.ts` 对 **4xx** 保持 `online===true`
  //   （`noteFetchResult(r.status < 500)`）⇒ 失败**不等于**离线。少了它，
  //   "后端活着但回 404"时下面两处会把"读不到"谎报成"离线"——一句
  //   用户无从分辨的假话（出口标准 5 /「只说自己有资格说的话」的反面）。
  const [online, setOnline] = useState(isOnline)
  useEffect(() => subscribeConnectivity(() => setOnline(isOnline())), [])

  /**
   * ⚠️ 由 `online` 派生的"重取一次"扳机，**专供下面那个 effect 的依赖数组**。
   *
   * 为什么不直接依赖 `online`：`online` 从 true→false 也会让 effect 重跑——
   * 那是**离线时白发一次必然失败的请求**（还会 `noteFetchResult(false)`
   * 把状态机再按一次离线）。
   * 为什么不写成「订阅回调里直接 `setReloadTick`」：那样**首帧**的 `isOnline()`
   * 初值就不生效了——初值本身是"挂载那一刻的真相"，而 effect 的依赖变化是
   * "之后每一次变化"，两个来源各管一段，才不会漏。
   *
   * ⚠️⚠️ 判据里 **`online` 是承重的**：`seenOnline.current` 记的是"上一次算这个
   * 值时在不在线"，所以只有**真的从离线变成在线**才会 `+1`。少了这个判据，
   * 任何一次无关的重渲染都会把 `online` 重新算成 `true` 并 `+1` ⇒ 每次渲染
   * 白拉一次日历（`Feed.tsx` 的同一条注释，变异 E 的教训）。
   */
  const [onlineEpoch, setOnlineEpoch] = useState(0)
  const seenOnline = useRef(online)
  useEffect(() => {
    const wasOnline = seenOnline.current
    seenOnline.current = online
    if (online && !wasOnline) setOnlineEpoch((t) => t + 1)
  }, [online])

  const today = dayKey(new Date())
  const [cursor, setCursor] = useState(() => {
    const now = new Date()
    return { y: now.getFullYear(), m: now.getMonth() }
  })
  const [picked, setPicked] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    // 新一轮读取开始，上一次的失败结论即刻作废：留着它，重试成功后横幅会
    // 继续描述一个已经不存在的状态。
    setErr(null)
    fetchCalendar()
      .then((r) => {
        if (!alive) return
        // ⚠️ 数据与"它是不是快照"**同时**写（同一个 `Shown`）：实时 ⇒ 两项一起
        // 换新，屏幕上不会出现"新数据 + 旧快照结论"的中间帧。
        setShown({ items: r.items, snapshotAt: null })
      })
      .catch((e: unknown) => {
        if (!alive) return
        // ⚠️ 失败了**才**回落快照。**三态必须分开**（spec 出口标准 5）：
        // 网络通没数据 / 断网有快照 / 断网无快照
        const snap = readSnapshot()
        if (snap !== null) {
          setShown({ items: snap.calendar, snapshotAt: snap.synced_at })
          // ⚠️⚠️ F1：**在线**失败（4xx：后端活着、这个请求有问题）时**保留**错误
          // ——回落到快照 == "屏幕上有东西看"，**不是**"什么都没发生"。少了这一行，
          // 在线 404 会既不说"离线"（横幅已被 `!online` 挡掉）又不报错 ⇒ 屏幕上
          // 只剩快照，用户以为那就是最新的实时日历。
          // 离线时清掉：那时**必然**失败是已知事实，横幅已说清"这是快照"，
          // 再挂一条"读取失败"是把预期内的离线报成意外。
          setErr(isOnline() ? (e instanceof Error ? e.message : String(e)) : null)
        } else {
          setShown(null)
          setErr(e instanceof Error ? e.message : String(e))
        }
      })
    return () => {
      alive = false
    }
    // ⚠️ `onlineEpoch` **承重**（F2 / 出口标准 4）：它只在"离线→在线"那个边沿
    // +1 ⇒ 网络恢复时重取一次实时数据，而不是**卡在快照上**。
  }, [reloadTick, onlineEpoch])

  // 按本地日分桶（⚠️ 与后端 `_day_start`/`_day_of` 同一个口径：本机时区）
  const byDay = useMemo(() => {
    const m = new Map<string, Item[]>()
    for (const it of shown?.items ?? []) {
      if (it.deadline_ts === null) continue
      const k = dayKey(new Date(it.deadline_ts * 1000))
      const arr = m.get(k)
      if (arr) arr.push(it)
      else m.set(k, [it])
    }
    return m
  }, [shown])

  const grid = useMemo(() => monthGrid(cursor.y, cursor.m), [cursor])
  const dayItems = picked !== null ? (byDay.get(picked) ?? []) : []

  return (
    <div>
      {/* ⚠️ 快照横幅：**必须**说清这是何时同步的，不许假装实时（G10 / 出口标准 5）。
          ⚠️⚠️ `!online` 是**承重**的（F1）：4xx 保持 `online===true`，回落快照
          **!=** 离线；少了它，在线 404 会把"读不到"谎报成"离线"（T5 在 Feed/Digests
          修掉的同一个缺陷，这里是第四个消费者）。 */}
      {shown !== null && shown.snapshotAt !== null && !online && (
        <div className="mb-3 rounded-lg bg-vigil-warn-soft p-3 text-sm text-vigil-warn">
          {/* ⚠️⚠️ 日历快照**是全量**，所以这里**刻意不写任何范围词**（T6-F1）。
              `syncSnapshot` 调的是 `fetchCalendar()`（无参）⇒ `api_calendar` 的
              缺省行为 = 全量带截止日的条目（`snapshot.ts` 的 `Snapshot.calendar`
              注释也写着"**全量**"）。真库实测：36 条横跨 4 个月，落进 5 天窗口的
              只有 5 条——所以在日历上写"最近 5 天"是**写在用户界面上的假话**
              （本项目守得最狠的那条："只说自己有资格说的话"）。
              ⇒ 与 `Feed`（确实只存最近 5 天）/`Digests`（确实只存 5 篇）**不同**：
              日历这条**不该**出现范围词。
              ⚠️ 判据见 `Calendar.dom.test.tsx`：断言横幅里**不出现"5 天"**
              —— 把"最近 5 天"加回来 ⇒ 必红（方向与 T6 那版相反）。 */}
          离线：下面是 <SnapshotTime ts={shown.snapshotAt} /> 同步的快照。
        </div>
      )}

      {err !== null && (
        <div className="mb-3 rounded-lg bg-vigil-danger-soft p-3 text-sm text-vigil-danger">
          <p>日历读取失败：{err}</p>
          {/* ⚠️ 三态分开（G10 / 出口标准 5）：读到**没有快照**时，必须明说"离线"，
              而不是让用户把"读不到"读成"没有条目"。
              ⚠️⚠️ `!online` 是**承重**的（F1）：失败横幅对"在线 4xx"同样会出现
              （那**是**错误，该出现），但"离线"这一句只有 `!online` 才配说。 */}
          {!online && <p className="mt-1 text-xs">离线，且还没有本地快照。</p>}
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
