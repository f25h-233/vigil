import { useEffect, useState } from 'react'
import { fetchCategories } from '../api.ts'
import type { Category } from '../types.ts'

export default function Categories({
  onPick,
}: {
  onPick: (slug: string) => void
}) {
  const [cats, setCats] = useState<Category[]>([])
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fetchCategories()
      .then((r) => setCats(r.categories))
      .catch((e: unknown) =>
        setErr(e instanceof Error ? e.message : String(e)),
      )
  }, [])

  if (err !== null) {
    return (
      <p className="rounded-lg bg-red-500/10 p-3 text-sm text-red-400">
        类目读取失败：{err}
      </p>
    )
  }
  if (cats.length === 0) {
    return <p className="text-sm text-white/40">读取类目…</p>
  }

  return (
    <div>
      <p className="mb-3 text-xs text-white/40">
        七个类目 · 点一个看该类全部条目
      </p>
      <div className="grid grid-cols-2 gap-3">
        {cats.map((c) => (
          <button
            key={c.slug}
            onClick={() => onPick(c.slug)}
            className="rounded-xl bg-white/5 p-4 text-left transition-colors active:bg-white/10"
          >
            <div className="text-2xl">{c.icon}</div>
            <div className="mt-1 font-medium">{c.label}</div>
            <div className="text-xs text-white/45">{c.count} 条</div>
          </button>
        ))}
      </div>
    </div>
  )
}
