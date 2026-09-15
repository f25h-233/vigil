// 时间格式化。**一律按本地时区**——与 M2 日报的「本地日」口径一致
// （M2 实测：用 UTC 解释同一个日期串会差 8 小时，报出的数就对不上）。

const pad = (n: number) => String(n).padStart(2, '0')

export function fmtDate(ts: number): string {
  const d = new Date(ts * 1000)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

export function fmtDateTime(ts: number): string {
  const d = new Date(ts * 1000)
  return `${d.getMonth() + 1}月${d.getDate()}日 ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function relTime(ts: number): string {
  const diff = Date.now() / 1000 - ts
  if (diff < 0) return fmtDate(ts) // 未来时间（脏数据）不编「-3 分钟前」
  if (diff < 3600) return `${Math.max(1, Math.floor(diff / 60))} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`
  return fmtDate(ts)
}
