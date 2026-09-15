import { useEffect, useRef, useState } from 'react'
import { fetchCategories, fetchItems } from '../api.ts'
import ItemCard from '../components/ItemCard.tsx'
import type { Category, Item } from '../types.ts'

const PAGE = 50

export default function Feed({
  kind,
  onKind,
}: {
  kind: string
  onKind: (k: string) => void
}) {
  const [cats, setCats] = useState<Category[]>([])
  const [input, setInput] = useState('')
  const [q, setQ] = useState('')
  const [items, setItems] = useState<Item[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  // 请求序号：慢的旧请求晚于新请求返回时，不许覆盖新结果
  const seq = useRef(0)

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
    setErr(null)
    fetchItems({ kind: kind || undefined, q: q || undefined, limit: PAGE })
      .then((page) => {
        if (mine !== seq.current) return
        setItems(page.items)
        setTotal(page.total)
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return
        setErr(e instanceof Error ? e.message : String(e))
        setItems([])
        setTotal(0)
      })
      .finally(() => {
        if (mine === seq.current) setLoading(false)
      })
  }, [kind, q])

  function loadMore() {
    const mine = seq.current
    setLoading(true)
    fetchItems({
      kind: kind || undefined,
      q: q || undefined,
      limit: PAGE,
      offset: items.length,
    })
      .then((page) => {
        if (mine !== seq.current) return
        setItems((prev) => [...prev, ...page.items])
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return
        setErr(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (mine === seq.current) setLoading(false)
      })
  }

  const picked = cats.find((c) => c.slug === kind)

  return (
    <div>
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="搜标题或详情（两个字也能搜）"
        className="w-full rounded-xl bg-white/5 px-3 py-2.5 text-sm outline-none placeholder:text-white/30 focus:bg-white/10"
      />

      <div className="mt-3 -mx-1 flex flex-wrap gap-1.5">
        <Chip active={kind === ''} onClick={() => onKind('')}>
          全部
        </Chip>
        {cats.map((c) => (
          <Chip
            key={c.slug}
            active={kind === c.slug}
            onClick={() => onKind(c.slug)}
          >
            {c.icon} {c.label}
          </Chip>
        ))}
      </div>

      <p className="mt-3 text-xs text-white/40">
        {/* 说清「这句话覆盖的是什么」：带上筛选条件，别让一个数字看起来像全部 */}
        {loading && items.length === 0
          ? '读取中…'
          : `共 ${total} 条${picked ? ` · ${picked.label}` : ''}${q ? ` · 关键词「${q}」` : ''}`}
      </p>

      {err !== null && (
        <p className="mt-3 rounded-lg bg-red-500/10 p-3 text-sm text-red-400">
          读取失败：{err}
        </p>
      )}

      {!loading && err === null && items.length === 0 && (
        <p className="mt-6 text-center text-sm text-white/40">
          {/* 空结果必须说清「搜索范围」，否则会被读成「库里就没有这件事」 */}
          {q !== ''
            ? `没有匹配「${q}」的条目。`
            : picked
              ? `「${picked.label}」下还没有条目。`
              : '还没有任何条目。'}
        </p>
      )}

      <ul className="mt-3 space-y-2">
        {items.map((it) => (
          <ItemCard key={it.item_id} item={it} />
        ))}
      </ul>

      {items.length > 0 && items.length < total && (
        <button
          onClick={loadMore}
          disabled={loading}
          className="mt-4 w-full rounded-xl bg-white/5 py-2.5 text-sm text-white/70 active:bg-white/10 disabled:opacity-40"
        >
          {loading ? '读取中…' : `加载更多（还有 ${total - items.length} 条）`}
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
