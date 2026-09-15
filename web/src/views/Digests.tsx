import { useEffect, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import { fetchDigest, fetchDigests } from '../api.ts'
import ItemCard from '../components/ItemCard.tsx'
import type { DigestDetail, DigestSummary } from '../types.ts'

// 正在看的那一篇：id 与正文合成一个对象。拆成两个 state 的话，会出现
// 「标题已经是 A、正文还是 B」的中间帧——而屏幕上所有字都来自这个对象。
// detail 为 null = 这篇还没读到（请求在飞 / 刚失败），它**不是**空正文：
// 把「不知道」渲染成一篇没有内容的日报，就是拿失败冒充内容。
type Opened = { id: number; detail: DigestDetail | null }

export default function Digests() {
  // null = 还没读到过（请求在飞 / 列表读取失败）。
  // 它必须与「读到了、结果是 0 篇」分开：前者只能说「不确定」，
  // 后者才有资格说「还没有日报」。
  const [list, setList] = useState<DigestSummary[] | null>(null)
  const [opened, setOpened] = useState<Opened | null>(null)
  const [err, setErr] = useState<string | null>(null)
  // 重跑列表请求的手动扳机：没有它，列表读取失败后就没有可见的恢复入口
  const [reloadTick, setReloadTick] = useState(0)
  // 请求序号：连点两篇日报时，慢的先发请求不许晚到覆盖后点的
  const seq = useRef(0)

  useEffect(() => {
    const mine = ++seq.current
    // 新一轮读取开始，上一次的失败结论即刻作废：留着它，重试成功后
    // 横幅会继续描述一个已经不存在的状态。
    setErr(null)
    fetchDigests()
      .then((r) => {
        if (mine !== seq.current) return
        setList(r.digests)
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return
        setErr(e instanceof Error ? e.message : String(e))
        // ⚠️ 这里**不写 setList([])**：请求失败说的是「不知道有几篇」，
        // 写下 [] 就是把它记成「读到了 0 篇」，下一帧会渲染出
        // 「还没有日报。生成：`vigil digest`」——一句没有依据的话。
      })
  }, [reloadTick])

  function open(id: number) {
    const mine = ++seq.current
    setErr(null) // 请求一发，上一次的失败结论就不再描述当前状态
    // 只记「正在打开哪一篇」，不动 list：详情请求的抖动不该把用户
    // 正看着的列表从屏幕上抹掉（下面失败时仍渲染列表 + 一条横幅）。
    setOpened({ id, detail: null })
    fetchDigest(id)
      .then((d) => {
        if (mine !== seq.current) return
        setOpened({ id, detail: d })
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return
        setErr(e instanceof Error ? e.message : String(e))
      })
  }

  // 错误横幅上的「重试」。失败的是一次「打开详情」→ 重发那一篇；
  // 否则失败的是列表本身 → 重跑列表。
  // 两条路都必须**真的重发请求**：只清 err 会把「不知道」直接渲染成
  // 「还没有日报」，那是拿一次失败冒充一次空库。
  function retry() {
    if (opened !== null && opened.detail === null) open(opened.id)
    else setReloadTick((t) => t + 1)
  }

  // 已读到的正文。它是从 opened 派生的，不是独立 state——独立 state
  // 就有两处真相，迟早对不上。
  const cur = opened !== null ? opened.detail : null
  // 正在打开（或刚打开失败）的那一篇，用来在列表项上标出进度
  const pendingId = opened !== null ? opened.id : null

  if (cur !== null) {
    return (
      <div>
        <button
          onClick={() => setOpened(null)}
          className="mb-3 text-sm text-sky-400 active:opacity-70"
        >
          ‹ 返回日报列表
        </button>

        <article className="rounded-xl bg-white/5 p-4">
          {/* 这一天由数据层给出，是页面唯一的标题 */}
          <h1 className="text-lg font-semibold">{cur.day} 日报</h1>
          <div className="mt-3">
            {/* react-markdown 默认**不渲染原始 HTML**，日报正文里的尖括号
                不会变成可执行标记——不额外引 sanitizer 也能安全 */}
            <Markdown
              components={{
                // 正文的 h1 恒定是「# 守夜人日报 · {day}」这一行（digest.py 的
                // 固定开头），说的就是上面那行标题的事，正文其余标题一律是 h2/h3。
                // 不管它的话：Tailwind v4 的 preflight 把 h1 重置成 font-size/
                // font-weight: inherit，它会以正文的样子紧贴在标题下面——同一个
                // 标题读两遍，且 React 树里出现两个 h1，屏幕阅读器要念两遍。
                // 所以这里按「不重复」处理：这行头部不渲染，标题以数据层的 cur.day 为准。
                h1: () => null,
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
                // preflight 把 ul 的 list-style 重置成 none：不恢复的话日报
                // 每一条（- **{label}** {text} · {群名}）的圆点全没了，
                // 只剩加粗与行距，读起来像一串散句而不是一张清单
                ul: ({ children }) => (
                  <ul className="my-2 list-disc space-y-1.5 pl-5">
                    {children}
                  </ul>
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

  return (
    <div>
      {/* 失败横幅与列表同时在场：一次请求的抖动只该占一条横幅，不该把
          用户已经读到的列表从屏幕上抹掉（抹掉了就再也渲染不出列表按钮，
          err 也就永远清不掉了）。 */}
      {err !== null && (
        <div className="mb-3 rounded-lg bg-red-500/10 p-3 text-sm text-red-400">
          <p>日报读取失败：{err}</p>
          <button
            onClick={retry}
            className="mt-2 rounded-lg bg-red-500/15 px-3 py-1.5 text-xs text-red-200 active:bg-red-500/25"
          >
            重试
          </button>
        </div>
      )}

      {list === null ? (
        // 失败时横幅已经说了原因，这里不再说「读取中」——那会是一句谎话
        err === null && <p className="text-sm text-white/40">读取日报列表…</p>
      ) : list.length === 0 ? (
        <p className="text-center text-sm text-white/40">
          还没有日报。生成：<code className="text-white/60">vigil digest</code>
        </p>
      ) : (
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
                  {/* 列表留在原地，就得有「点击生效了」的痕迹，否则用户会
                      以为没点动（与 Feed 计数行的「读取中…」同一个理由）。
                      失败时同理明写，不能让这一项继续显示「打开中」。 */}
                  {d.digest_id === pendingId &&
                    (err === null ? ' · 打开中…' : ' · 打开失败')}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
