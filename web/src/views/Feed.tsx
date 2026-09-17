import { useEffect, useRef, useState } from 'react'
import { fetchCategories, fetchItems } from '../api.ts'
import ItemCard from '../components/ItemCard.tsx'
import PersonPicker from '../components/PersonPicker.tsx'
import type { Category, Item } from '../types.ts'

const PAGE = 50

// 屏幕上这批数据，连同「它属于哪个查询」一起存。
// 拆成四个 state 的话，请求在飞的那段时间会拼出「新筛选的标签 + 上一次查询的数字」
// 这种半新半旧的句子——而计数行存在的意义恰恰是交代这个数字覆盖的范围，
// 拼错比不显示更糟。所以数据、总数、筛选条件三者同生同死。
type Shown = {
  items: Item[]
  total: number
  /** ⚠️ 存成 join 后的字符串：数组恒不等于自身，`switching` 的比较会永远为真。 */
  kindsKey: string
  personsKey: string
  q: string
}

export default function Feed({
  kinds,
  onKinds,
  persons,
  onPersons,
  reloadSignal,
}: {
  kinds: string[]
  onKinds: (k: string[]) => void
  persons: number[]
  onPersons: (p: number[]) => void
  /** 外部（App 的「撤销」）要求重取。变一次 = 重跑首屏一次。 */
  reloadSignal: number
}) {
  const [cats, setCats] = useState<Category[]>([])
  const [input, setInput] = useState('')
  const [q, setQ] = useState('')
  // null = 还没读到过（首屏请求在飞 / 读取失败已清空）。
  // 它必须与「读到了、结果是 0 条」分开：前者只能说不确定，后者才配说 0。
  const [shown, setShown] = useState<Shown | null>(null)
  // 初值 true：首帧 effect 还没 flush，先按「正在读」画，不许先画一句总数
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  // 重跑首屏的手动扳机：kind/q 都没变时也要能重新发请求。
  // 没有它，首屏失败后用户就没有任何可见的恢复入口（见下方 retry）。
  const [reloadTick, setReloadTick] = useState(0)
  // 请求序号：慢的旧请求晚于新请求返回时，不许覆盖新结果
  const seq = useRef(0)

  // ⚠️ 数组本身的引用每次渲染都变，直接拿它当依赖会让 effect 无限重跑；
  // 而直接对数组做比较又会让"选中顺序不同但集合相同"被当成换了筛选条件。
  // 排序后 join 成字符串：集合相同 ⇒ 串相同 ⇒ 不重跑。
  const kindsKey = [...kinds].sort().join(',')
  const personsKey = [...persons].sort().join(',')

  useEffect(() => {
    fetchCategories()
      .then((r) => setCats(r.categories))
      .catch(() => setCats([])) // 类目栏拉不到不该让信息流整页不可用
  }, [])

  // 输入防抖：中文输入法下每敲一下都发请求，手机上会明显卡顿
  useEffect(() => {
    const t = setTimeout(() => setQ(input.trim()), 300)
    return () => clearTimeout(t)
  }, [input])

  useEffect(() => {
    const mine = ++seq.current
    setLoading(true)
    // 新一轮查询开始，上一次的失败结论即刻作废。
    // 留着它的话，重试成功后横幅会继续描述一个已经不存在的状态。
    setErr(null)
    fetchItems({
      kinds,
      persons,
      q: q || undefined,
      limit: PAGE,
    })
      .then((page) => {
        if (mine !== seq.current) return
        setShown({ items: page.items, total: page.total, kindsKey, personsKey, q })
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return
        setErr(e instanceof Error ? e.message : String(e))
        // 清空而不是留着旧数据：旧数据标的是上一个筛选，留着会被读成本次结果
        setShown(null)
      })
      .finally(() => {
        if (mine === seq.current) setLoading(false)
      })
  }, [kindsKey, personsKey, q, reloadTick, reloadSignal])

  function loadMore() {
    // 没有可续的列表就不发请求：首屏失败后列表是空的，续页无从谈起
    if (shown === null) return
    const mine = seq.current
    setLoading(true)
    // 同上：重试一旦发出，横幅里那句失败就不再描述当前状态
    setErr(null)
    fetchItems({
      // 续的是屏幕上这批数据，用 shown 的条件，而不是用户刚点的新筛选。
      // ⚠️ 存的是 join 串，这里要还原成数组（空段滤掉：'' 不是有效 slug）。
      kinds: shown.kindsKey.split(',').filter(Boolean),
      persons: shown.personsKey.split(',').filter(Boolean).map(Number),
      q: shown.q || undefined,
      limit: PAGE,
      offset: shown.items.length,
    })
      .then((page) => {
        if (mine !== seq.current) return
        setShown((prev) =>
          prev ? { ...prev, items: [...prev.items, ...page.items] } : prev,
        )
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return
        setErr(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (mine === seq.current) setLoading(false)
      })
  }

  // 错误横幅上的「重试」。列表里还有东西 = 失败的是续页，接着续；
  // 列表是空的 = 首屏就没读到，重跑第一页。这是首屏失败后唯一可见的恢复入口。
  function retry() {
    if (shown !== null && shown.items.length > 0) loadMore()
    else setReloadTick((t) => t + 1)
  }

  // 人工干预（改分类 / 删除）成功后的重取。
  //
  // ⚠️ 这里**刻意不复用 `retry()`**：列表里还有数据时 `retry()` 走的是
  // `loadMore()`——那是**往后追加**，追加**不会刷新屏幕上那条已经变了的条目**：
  // 删掉的条目会继续留在列表里、改过的分类也还是旧的（实测：Step 10 真跑一次，
  // 「删一条 → 从列表消失」与「撤销 → 条目回来」两条都因此不成立）。
  // 干预改变的是集合本身，唯一正确的动作是重跑第一页。
  function reload() {
    setReloadTick((t) => t + 1)
  }

  // 计数行里的标签与数字都取自 shown：它们说的是「屏幕上有什么」，
  // 而不是「用户刚选了什么」——后者在请求回来之前只是一句许愿
  const pickedKinds =
    shown !== null
      ? cats.filter((c) => shown.kindsKey.split(',').includes(c.slug))
      : []
  // 「当前筛选范围」的人话描述。空结果文案与计数行共用同一套词，
  // 免得同一个筛选在两处被说成两样。
  const scopeLabels = [
    ...pickedKinds.map((c) => c.label),
    ...(shown !== null && shown.personsKey !== ''
      ? [`${shown.personsKey.split(',').length} 个人物`]
      : []),
  ]
  // 数据还是旧的、请求已经在飞：计数行继续描述旧数据，但要说明正在刷新，
  // 否则用户会以为点击没生效
  const switching =
    loading &&
    shown !== null &&
    (shown.kindsKey !== kindsKey || shown.personsKey !== personsKey || shown.q !== q)
  const countLine =
    shown === null
      ? loading
        ? '读取中…'
        : '条目数未知' // 没有依据就不给数字：0 说的是「一条都没有」，不是「不知道」
      : `共 ${shown.total} 条` +
        (pickedKinds.length > 0
          ? ` · ${pickedKinds.map((c) => c.label).join('、')}`
          : '') +
        (shown.personsKey ? ` · ${shown.personsKey.split(',').length} 个人物` : '') +
        (shown.q ? ` · 关键词「${shown.q}」` : '') +
        (switching ? ' · 读取中…' : '')

  return (
    <div>
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="搜标题或详情（两个字也能搜）"
        className="w-full rounded-xl bg-white/5 px-3 py-2.5 text-sm outline-none placeholder:text-white/30 focus:bg-white/10"
      />

      {/* 类目是**多选**：点一下切换，不是替换。选中的多个之间是并集。 */}
      <div className="mt-3 -mx-1 flex flex-wrap gap-1.5">
        <Chip active={kinds.length === 0} onClick={() => onKinds([])}>
          全部
        </Chip>
        {cats.map((c) => (
          <Chip
            key={c.slug}
            active={kinds.includes(c.slug)}
            onClick={() =>
              onKinds(
                kinds.includes(c.slug)
                  ? kinds.filter((k) => k !== c.slug)
                  : [...kinds, c.slug],
              )
            }
          >
            {c.icon} {c.label}
          </Chip>
        ))}
      </div>

      <PersonPicker selected={persons} onChange={onPersons} />

      {/* 说清「这句话覆盖的是什么」：带上筛选条件，别让一个数字看起来像全部 */}
      <p className="mt-3 text-xs text-white/40">{countLine}</p>

      {err !== null && (
        <div className="mt-3 rounded-lg bg-red-500/10 p-3 text-sm text-red-400">
          <p>读取失败：{err}</p>
          {/* 显式的恢复入口：首屏失败时列表为空，分页按钮不渲染，
              没有这个按钮用户就只能靠「切走再切回」这类隐性绕路 */}
          <button
            onClick={retry}
            className="mt-2 rounded-lg bg-red-500/15 px-3 py-1.5 text-xs text-red-200 active:bg-red-500/25"
          >
            重试
          </button>
        </div>
      )}

      {!loading &&
        err === null &&
        shown !== null &&
        shown.items.length === 0 && (
          <p className="mt-6 text-center text-sm text-white/40">
            {/* 空结果必须说清「搜索范围」，否则会被读成「库里就没有这件事」。
                ⚠️ 多选之后不能只报一个类目名：说出来的范围必须与上面那句
                计数行描述的是同一件事（类目 ∧ 人物 ∧ 关键词）。 */}
            {shown.q !== ''
              ? `没有匹配「${shown.q}」的条目。`
              : scopeLabels.length > 0
                ? `当前筛选（${scopeLabels.join(' · ')}）下还没有条目。`
                : '还没有任何条目。'}
          </p>
        )}

      <ul className="mt-3 space-y-2">
        {shown !== null &&
          shown.items.map((it) => (
            <ItemCard key={it.item_id} item={it} onMutated={reload} />
          ))}
      </ul>

      {shown !== null &&
        shown.items.length > 0 &&
        shown.items.length < shown.total && (
          <button
            onClick={loadMore}
            disabled={loading}
            className="mt-4 w-full rounded-xl bg-white/5 py-2.5 text-sm text-white/70 active:bg-white/10 disabled:opacity-40"
          >
            {loading
              ? '读取中…'
              : `加载更多（还有 ${shown.total - shown.items.length} 条）`}
          </button>
        )}
    </div>
  )
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={
        'rounded-full px-3 py-1 text-xs whitespace-nowrap transition-colors ' +
        (active ? 'bg-sky-500/20 text-sky-300' : 'bg-white/5 text-white/55')
      }
    >
      {children}
    </button>
  )
}
