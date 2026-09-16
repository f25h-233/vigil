import { useState } from 'react'
import { fetchItem } from '../api.ts'
import { fmtDate, relTime } from '../format.ts'
import type { Item, Source } from '../types.ts'
import SourceList from './SourceList.tsx'

export default function ItemCard({ item }: { item: Item }) {
  const [open, setOpen] = useState(false)
  const [sources, setSources] = useState<Source[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  // 「请求在飞」。它**不是** `sources === null` 的同义词：后者把「还没读过」
  // 与「读失败了」混在一起，而这两句话对用户的意思完全不同。
  const [loading, setLoading] = useState(false)

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
    <li className="rounded-xl bg-white/5 p-3">
      <button onClick={toggle} className="w-full text-left">
        <div className="flex flex-wrap items-center gap-x-2 text-xs text-sky-400">
          <span>
            {item.kind_icon} {item.kind_label}
          </span>
          <span className="text-white/30">·</span>
          <span className="text-white/45">{item.group_name}</span>
          <span className="ml-auto text-white/40">
            {relTime(item.event_ts)}
          </span>
        </div>

        <p className="mt-1 text-[15px] leading-snug font-medium">
          {item.title}
        </p>
        {item.detail !== null && item.detail !== '' && (
          <p className="mt-1 text-sm text-white/70">{item.detail}</p>
        )}

        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-white/50">
          {/* 截止日只在数据层核验通过时才有值（NULL = 源文里找不到依据）*/}
          {item.deadline_ts !== null && (
            <span className="text-amber-400">
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

      {open && (
        <div className="mt-3 border-t border-white/10 pt-3">
          {item.links.length > 0 && (
            <div className="mb-2 flex flex-col gap-1 text-xs">
              {item.links.map((l) => (
                <a
                  key={l}
                  href={l}
                  target="_blank"
                  rel="noreferrer"
                  className="break-all text-sky-400 underline"
                >
                  {l}
                </a>
              ))}
            </div>
          )}
          {err !== null && (
            <div className="rounded-lg bg-red-500/10 p-3 text-xs text-red-400">
              <p>源消息读取失败：{err}</p>
              {/* 显式的恢复入口：没有这个按钮，用户就只能靠「收起再展开」
                  这类隐性绕路——而那条路以前也是死的（守卫含 err === null）。
                  它**重发请求**而不是只清 err：只清 err 会立刻渲染出
                  「读取源消息…」，然后停在没读到也没说为什么的状态。 */}
              <button
                onClick={load}
                className="mt-2 rounded-lg bg-red-500/15 px-3 py-1.5 text-xs text-red-200 active:bg-red-500/25"
              >
                重试
              </button>
            </div>
          )}
          {/* 三态各说各的话：读取中 / 失败（上面那条横幅）/ 读到了。
              加载态必须显式——否则重试期间这里是一片空白 */}
          {loading && <p className="text-xs text-white/40">读取源消息…</p>}
          {sources !== null && <SourceList sources={sources} />}
        </div>
      )}
    </li>
  )
}
