import { useState } from 'react'
import { fetchItem } from '../api.ts'
import { fmtDate, relTime } from '../format.ts'
import type { Item, Source } from '../types.ts'
import SourceList from './SourceList.tsx'

export default function ItemCard({ item }: { item: Item }) {
  const [open, setOpen] = useState(false)
  const [sources, setSources] = useState<Source[] | null>(null)
  const [err, setErr] = useState<string | null>(null)

  function toggle() {
    const next = !open
    setOpen(next)
    // 源消息**按需拉取**：列表一次 50 条，全带上原文会把响应撑大好几倍，
    // 而绝大多数条目用户不会展开。
    if (next && sources === null && err === null) {
      fetchItem(item.item_id)
        .then((d) => setSources(d.sources))
        .catch((e: unknown) =>
          setErr(e instanceof Error ? e.message : String(e)),
        )
    }
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
            <p className="text-xs text-red-400">源消息读取失败：{err}</p>
          )}
          {sources === null && err === null && (
            <p className="text-xs text-white/40">读取源消息…</p>
          )}
          {sources !== null && <SourceList sources={sources} />}
        </div>
      )}
    </li>
  )
}
