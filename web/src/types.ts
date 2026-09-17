// API 契约的 TypeScript 影子。
//
// ⚠️ 这个文件是**冻结契约**的前端一侧：字段名与后端 `vigil/api.py` 的
// 输出逐字对应，改任何一边都必须同时改另一边（波级窄审查专门核这件事）。
// 类型写错不会在构建期报错——它只会让页面静默少一栏，所以字段名不许凭记忆改。

export type Item = {
  item_id: number
  kind: string // slug，如 "academic"
  kind_label: string // 中文，如 "学业"
  kind_icon: string // emoji
  title: string
  detail: string | null
  event_ts: number // Unix 秒
  /** ⚠️ 已过数据层核验：NULL 表示源文里找不到依据，前端**不显示**它 */
  deadline_ts: number | null
  group_id: number
  group_name: string
  actor: string | null
  /** QQ 号（uin）。实名消息才有；匿名消息为 null，且不该被人物筛选中。 */
  actor_uin: number | null
  place: string | null
  amount: string | null
  links: string[]
  source_count: number
}

export type Source = {
  msg_id: number
  ts: number
  sender: string
  group_name: string
  content: string
}

export type ItemDetail = Item & { sources: Source[] }

export type ItemPage = {
  items: Item[]
  total: number
  limit: number
  offset: number
}

export type Category = {
  slug: string
  label: string
  icon: string
  count: number
}

export type DigestSummary = {
  digest_id: number
  day: string // YYYY-MM-DD
  window_from: number
  window_to: number
  created_at: number
  item_count: number
}

export type DigestDetail = DigestSummary & {
  body_md: string
  items: Item[]
}

/**
 * 一个被监视的人物。
 *
 * ⚠️ `count` 是"这个 uin 发过的条目数"，由后端算好——前端不要在拿到
 * 全部条目后自己数：那需要把整个库拉下来，而且计数会随筛选条件漂移。
 */
export type Person = {
  uin: number
  label: string
  note: string
  count: number
}
