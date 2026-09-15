import { useEffect, useState } from 'react'
import Markdown from 'react-markdown'
import { fetchDigest, fetchDigests } from '../api.ts'
import ItemCard from '../components/ItemCard.tsx'
import type { DigestDetail, DigestSummary } from '../types.ts'

export default function Digests() {
  const [list, setList] = useState<DigestSummary[] | null>(null)
  const [cur, setCur] = useState<DigestDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fetchDigests()
      .then((r) => setList(r.digests))
      .catch((e: unknown) => {
        setErr(e instanceof Error ? e.message : String(e))
        setList([])
      })
  }, [])

  function open(id: number) {
    setErr(null)
    fetchDigest(id)
      .then(setCur)
      .catch((e: unknown) =>
        setErr(e instanceof Error ? e.message : String(e)),
      )
  }

  if (err !== null && cur === null) {
    return (
      <p className="rounded-lg bg-red-500/10 p-3 text-sm text-red-400">
        日报读取失败：{err}
      </p>
    )
  }

  if (cur !== null) {
    return (
      <div>
        <button
          onClick={() => setCur(null)}
          className="mb-3 text-sm text-sky-400 active:opacity-70"
        >
          ‹ 返回日报列表
        </button>

        <article className="rounded-xl bg-white/5 p-4">
          <h1 className="text-lg font-semibold">{cur.day} 日报</h1>
          <div className="mt-3">
            {/* react-markdown 默认**不渲染原始 HTML**，日报正文里的尖括号
                不会变成可执行标记——不额外引 sanitizer 也能安全 */}
            <Markdown
              components={{
                h2: ({ children }) => (
                  <h2 className="mt-4 mb-2 text-base font-semibold text-white/90">
                    {children}
                  </h2>
                ),
                h3: ({ children }) => (
                  <h3 className="mt-3 mb-1 text-sm font-semibold text-white/80">
                    {children}
                  </h3>
                ),
                ul: ({ children }) => (
                  <ul className="my-2 space-y-1.5">{children}</ul>
                ),
                li: ({ children }) => (
                  <li className="text-sm leading-relaxed text-white/75">
                    {children}
                  </li>
                ),
                p: ({ children }) => (
                  <p className="my-1.5 text-sm leading-relaxed text-white/75">
                    {children}
                  </p>
                ),
                strong: ({ children }) => (
                  <strong className="font-semibold text-white/95">
                    {children}
                  </strong>
                ),
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    className="break-all text-sky-400 underline"
                  >
                    {children}
                  </a>
                ),
              }}
            >
              {cur.body_md}
            </Markdown>
          </div>
        </article>

        {cur.items.length > 0 && (
          <>
            <p className="mt-5 mb-2 text-xs text-white/40">
              这篇日报引用的 {cur.items.length} 条条目（点开可看源消息）
            </p>
            <ul className="space-y-2">
              {cur.items.map((it) => (
                <ItemCard key={it.item_id} item={it} />
              ))}
            </ul>
          </>
        )}
      </div>
    )
  }

  if (list === null) {
    return <p className="text-sm text-white/40">读取日报列表…</p>
  }

  if (list.length === 0) {
    return (
      <p className="text-center text-sm text-white/40">
        还没有日报。生成：<code className="text-white/60">vigil digest</code>
      </p>
    )
  }

  return (
    <ul className="space-y-2">
      {list.map((d) => (
        <li key={d.digest_id}>
          <button
            onClick={() => open(d.digest_id)}
            className="w-full rounded-xl bg-white/5 p-4 text-left transition-colors active:bg-white/10"
          >
            <div className="font-medium">{d.day}</div>
            <div className="mt-0.5 text-xs text-white/45">
              {d.item_count} 条条目
            </div>
          </button>
        </li>
      ))}
    </ul>
  )
}
