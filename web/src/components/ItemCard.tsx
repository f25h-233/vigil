import { useEffect, useState } from 'react'
import { deleteItem, fetchCategories, fetchItem, setItemKind } from '../api.ts'
import { fmtDate, relTime } from '../format.ts'
import type { Category, Item, Source } from '../types.ts'
import SourceList from './SourceList.tsx'

export default function ItemCard({
  item,
  onMutated,
  onSelect,
  selected,
}: {
  item: Item
  /** 改动成功后通知父级重取列表。不传则只读（日报页就是这样用的）。 */
  onMutated?: () => void
  /**
   * 传了才渲染多选框（信息流的批量改类目用它）。**不传 = 行为一个字不变**
   * （日报页就是这样用的：那一天的消息是归档，批量改它没有意义）。
   */
  onSelect?: (itemId: number) => void
  /** 只对 `onSelect` 有意义：这张卡片此刻是否被选中。 */
  selected?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [sources, setSources] = useState<Source[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  // 「请求在飞」。它**不是** `sources === null` 的同义词：后者把「还没读过」
  // 与「读失败了」混在一起，而这两句话对用户的意思完全不同。
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [actErr, setActErr] = useState<string | null>(null)
  const [cats, setCats] = useState<Category[]>([])

  // ⚠️ 依赖是「这张卡片可不可改」这个**布尔值**，不是 `onMutated` 本身：
  // Feed 传下来的 `reload` 是每次渲染新建的函数，直接依赖它会让一页 50 张
  // 卡片在父组件每次重渲染时各自重发一次 `/api/categories`。
  const mutable = onMutated !== undefined
  useEffect(() => {
    if (!mutable) return
    fetchCategories()
      .then((r) => setCats(r.categories))
      // 类目拉不到只该让下拉框空着，不该把整张卡片变成错误态：
      // 「改不了分类」与「读不到源消息」不是一回事。
      .catch(() => setCats([]))
  }, [mutable])

  async function changeKind(slug: string) {
    setBusy(true)
    setActErr(null)
    try {
      await setItemKind(item.item_id, slug)
      onMutated?.()
    } catch (e: unknown) {
      setActErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    setActErr(null)
    try {
      await deleteItem(item.item_id)
      onMutated?.()
    } catch (e: unknown) {
      setActErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  // 源消息**按需拉取**：列表一次 50 条，全带上原文会把响应撑大好几倍，
  // 而绝大多数条目用户不会展开。
  function load() {
    // 重发前清掉上一次的失败结论：留着它，重试成功后横幅会继续描述一个
    // 已经不存在的状态（Feed / Categories / Digests 三处同理）。
    setErr(null)
    setLoading(true)
    fetchItem(item.item_id)
      .then((d) => setSources(d.sources))
      .catch((e: unknown) =>
        setErr(e instanceof Error ? e.message : String(e)),
      )
      .finally(() => setLoading(false))
  }

  function toggle() {
    const next = !open
    setOpen(next)
    // ⚠️ 守卫是 `sources === null && !loading`——**刻意不含 `err === null`**。
    // 含了的话，失败一次 err 就永远非 null：收起再展开、关掉再点开都不再
    // 重发，用户唯一的出路是刷新整页——而出口标准 5 正是「点任意 item 看到
    // 源消息原文」。`loading` 是防重复请求的那一半：点完重试立刻收起再展开
    // 时请求还在飞，不该再发一次。
    if (next && sources === null && !loading) load()
  }

  return (
    <li className="rounded-xl bg-vigil-surface p-3 shadow-vigil-card backdrop-blur-vigil-panel">
      <div className="flex items-start gap-2">
        {/* ⚠️ 多选框**必须在外层 button 之外**：HTML 不允许 `<button>` 里嵌交互
            元素（`<input>` 也是），浏览器会把内层踢出来、点击行为变得不可预测
            ——与下面操作条是同一条理由。`aria-label` 带上标题，否则一页 50 个
            多选框在屏幕阅读器里全是"复选框"。 */}
        {onSelect && (
          <input
            type="checkbox"
            checked={selected === true}
            onChange={() => onSelect(item.item_id)}
            className="mt-1"
            aria-label={`选择 ${item.title}`}
          />
        )}
        <button onClick={toggle} className="w-full min-w-0 flex-1 text-left">
          <div className="flex flex-wrap items-center gap-x-2 text-xs text-vigil-accent">
            <span>
              {item.kind_icon} {item.kind_label}
            </span>
            <span className="text-vigil-fg-4">·</span>
            <span className="text-vigil-fg-3">{item.group_name}</span>
            <span className="ml-auto text-vigil-fg-4">
              {relTime(item.event_ts)}
            </span>
          </div>

          <p className="mt-1 text-[15px] leading-snug font-medium">
            {item.title}
          </p>
          {item.detail !== null && item.detail !== '' && (
            <p className="mt-1 text-sm text-vigil-fg-2">{item.detail}</p>
          )}

          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-vigil-fg-3">
            {/* 截止日只在数据层核验通过时才有值（NULL = 源文里找不到依据）*/}
            {item.deadline_ts !== null && (
              <span className="text-vigil-warn">
                ⏰ {fmtDate(item.deadline_ts)} 截止
              </span>
            )}
            {item.place !== null && item.place !== '' && (
              <span>📍 {item.place}</span>
            )}
            {item.amount !== null && item.amount !== '' && (
              <span>💰 {item.amount}</span>
            )}
            {item.actor !== null && item.actor !== '' && (
              <span>@{item.actor}</span>
            )}
            {item.source_count > 0 && (
              <span>
                {open ? '▾' : '▸'} {item.source_count} 条源消息
              </span>
            )}
          </div>
        </button>
      </div>

      {/* ⚠️ 操作条在**外层 button 之外**：`<button>` 里不能再放 `<select>`/`<button>`
          （HTML 不允许嵌套交互元素），浏览器会把内层踢出去、点击行为变得不可预测。 */}
      {onMutated && (
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-vigil-border-soft pt-2 text-xs">
          <select
            value={item.kind}
            disabled={busy}
            onChange={(e) => changeKind(e.target.value)}
            className="rounded-lg bg-vigil-inset px-2 py-1 text-xs text-vigil-fg-2 outline-none"
          >
            {cats.map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.icon} {c.label}
              </option>
            ))}
          </select>
          <button
            onClick={remove}
            disabled={busy}
            className="rounded-lg bg-vigil-danger-soft px-2 py-1 text-vigil-danger disabled:opacity-40"
          >
            删除
          </button>
          {actErr !== null && <span className="text-vigil-danger">{actErr}</span>}
        </div>
      )}

      {open && (
        <div className="mt-3 border-t border-vigil-border pt-3">
          {item.links.length > 0 && (
            <div className="mb-2 flex flex-col gap-1 text-xs">
              {item.links.map((l) => (
                <a
                  key={l}
                  href={l}
                  target="_blank"
                  rel="noreferrer"
                  className="break-all text-vigil-accent underline"
                >
                  {l}
                </a>
              ))}
            </div>
          )}
          {err !== null && (
            <div className="rounded-lg bg-vigil-danger-soft p-3 text-xs text-vigil-danger">
              <p>源消息读取失败：{err}</p>
              {/* 显式的恢复入口：没有这个按钮，用户就只能靠「收起再展开」
                  这类隐性绕路——而那条路以前也是死的（守卫含 err === null）。
                  它**重发请求**而不是只清 err：只清 err 会立刻渲染出
                  「读取源消息…」，然后停在没读到也没说为什么的状态。 */}
              <button
                onClick={load}
                className="mt-2 rounded-lg bg-vigil-danger-btn px-3 py-1.5 text-xs text-vigil-danger-text active:bg-vigil-danger-btn-active"
              >
                重试
              </button>
            </div>
          )}
          {/* 三态各说各的话：读取中 / 失败（上面那条横幅）/ 读到了。
              加载态必须显式——否则重试期间这里是一片空白 */}
          {loading && <p className="text-xs text-vigil-fg-4">读取源消息…</p>}
          {sources !== null && <SourceList sources={sources} />}
        </div>
      )}
    </li>
  )
}
