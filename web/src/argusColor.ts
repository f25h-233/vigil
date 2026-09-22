/**
 * ARGUS 主题的颜色引擎：**基色 → 整套 CSS 变量**。
 *
 * 为什么不交给 CSS 的 `color-mix()`（见计划 §0.1）：本仓的对比度判据解析不了 `color-mix`，
 * 那等于把这一卷新增的整套配色弄成"没人能验"。派生放这里 ⇒ **纯函数、可单测**，
 * 写出去的一律是 `rgba(r, g, b, a)` 字面值。
 *
 * ⚠️ 写的是 `:root` 的**行内**自定义属性——行内赢过任何选择器（包括 `[data-theme='material']`）
 * ⇒ 切到别的主题时**必须** `clearArgusColor()`，否则材料主题的字色会被 ARGUS 的颜色残留顶掉。
 */
export const ARGUS_DEFAULT = '#00ff9c'
export const ARGUS_COLOR_KEY = 'vigil.argus.color'

/**
 * 派生表落盘的键（⭐ R10：**防闪**那一半）。
 *
 * ⚠️ 为什么盘上要**整份 JSON**、而不是只存基色让防闪脚本自己算：
 * `applyArgusColor` 是模块加载**之后**才跑的，而 `index.html` 的防闪脚本在**首帧之前**
 * ——那一段窗口里 `:root` 上没有任何行内变量 ⇒ 页面先画成 CSS 里的**默认绿**，再跳成
 * 用户的颜色（手机上就是一道闪）。防闪脚本要贴出**用户色**，就得能在不加载任何模块的
 * 前提下拿到那 12 个值。
 * ⛔ 让它"照着基色自己算一份" = 把 alpha 表复制进 `index.html`（两处真相，必然漂移）
 * ⇒ 存 `deriveArgusVars` 的**原样输出**：算的地方只有这一个函数。
 * ⚠️ 与 `ARGUS_COLOR_KEY` **同一条纪律**：`clearArgusColor` 只清"这次生效的覆盖"
 * （行内变量），盘上这份与基色一样是**用户的偏好**，不清。
 */
export const ARGUS_VARS_KEY = 'vigil.argus.vars'

/** 具名色：不是 CSS 的 green（#008000 在纯黑底上偏暗），而是终端色 */
export const ARGUS_NAMED: Record<string, string> = {
  green: '#00ff9c',
  white: '#f2f2f2',
  amber: '#ffb000',
  cyan: '#22d3ee',
  red: '#ff5f56',
  magenta: '#ff5fd2',
}

export type ArgusColorResult = { ok: true; value: string } | { ok: false; reason: string }

type RGB = [number, number, number]

function toHex([r, g, b]: RGB): string {
  return `#${[r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('')}`
}

function parseHex(s: string): RGB | null {
  const m = s.trim().toLowerCase()
  if (/^#[0-9a-f]{3}$/.test(m)) {
    return [
      parseInt(m[1] + m[1], 16),
      parseInt(m[2] + m[2], 16),
      parseInt(m[3] + m[3], 16),
    ]
  }
  if (/^#[0-9a-f]{6}$/.test(m)) {
    return [parseInt(m.slice(1, 3), 16), parseInt(m.slice(3, 5), 16), parseInt(m.slice(5, 7), 16)]
  }
  return null
}

/** WCAG 相对亮度（与 `themePalette.test.ts` 同一套算法） */
function luminance([r, g, b]: RGB): number {
  const f = (c: number) => {
    const x = c / 255
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}

/**
 * ⛔ 太暗的颜色要拒：终端主题是**纯黑底**，一个接近黑的前景色等于把整个界面读没
 * （而它会静默生效 ⇒ 用户只会觉得"这个主题坏了"）。
 * 阈值取 4.5:1 对纯黑底反推出的亮度下界：L ≥ 0.175 ⇒ 对比度 = (L+0.05)/0.05 ≥ 4.5。
 */
const MIN_LUMINANCE = 0.175

export function parseArgusColor(input: string): ArgusColorResult {
  const key = input.trim().toLowerCase()
  if (key === '') return { ok: false, reason: '用法：/color green｜white｜#rgb｜#rrggbb' }
  const named = ARGUS_NAMED[key]
  const rgb = parseHex(named ?? key)
  if (rgb === null) {
    return { ok: false, reason: `认不出这个颜色：${input.trim()}（试试 /color green 或 /color #ff8800）` }
  }
  if (luminance(rgb) < MIN_LUMINANCE) {
    return { ok: false, reason: `这个颜色太暗了，在纯黑底上读不出来：${toHex(rgb)}` }
  }
  return { ok: true, value: toHex(rgb) }
}

/** 基色 → 12 个变量的字面值（层级用降透明，与主题体系里"面/边框"的既有做法一致） */
export function deriveArgusVars(base: string): Record<string, string> {
  const rgb = parseHex(base)
  if (rgb === null) throw new Error(`deriveArgusVars 需要 #rrggbb，收到 ${base}`)
  const [r, g, b] = rgb
  const a = (alpha: number) => `rgba(${r}, ${g}, ${b}, ${alpha})`
  return {
    '--v-fg': base,
    '--v-fg-2': a(0.78),
    '--v-fg-3': a(0.58),
    '--v-fg-4': a(0.38),
    '--v-surface': a(0.06),
    '--v-surface-2': a(0.14),
    '--v-inset': a(0.03),
    '--v-border': a(0.45),
    '--v-border-soft': a(0.22),
    '--v-accent': base,
    '--v-accent-soft': a(0.18),
    '--v-accent-text': base,
  }
}

/**
 * 派生表 → JSON（⭐ R10 的**可单测的那一半**）。
 *
 * 存在的唯一理由：`index.html` 的防闪脚本要**原样读回**这套变量，而它不许复制派生数学
 * （R10③ 那条判据就是钉这个的）。⇒ 盘上那份必须是**同一个函数**的输出
 * ⇒ 前端回读时不需要知道任何 alpha，也就没有第二处真相。
 */
export function argusVarsJson(base: string): string {
  return JSON.stringify(deriveArgusVars(base))
}

/**
 * 基色 → 写 `:root` 行内变量 + 落盘。**它只负责"写变量"，不负责"判断该不该写"**。
 *
 * ⚠️ F7（T8-1 fix 轮）：这里**没有**"当前主题必须是 argus"的前置条件——按本仓纪律，
 * 引擎保持纯（可单测、无环境依赖），**门放在调用点**：`theme.ts` 的 `syncArgusColor()`
 * **只在 `id === 'argus'` 时**才调它，其余主题走 `clearArgusColor()`。
 * ⇒ 任何新调用点：要么经由 `applyTheme`（推荐），要么自己承担这个判断；直接调它
 * 而在非 argus 主题下就是 §0.1 那个"行内覆盖顶掉别的主题"的缺陷换个入口重演。
 */
export function applyArgusColor(input: string): ArgusColorResult {
  const parsed = parseArgusColor(input)
  if (!parsed.ok) return parsed
  const vars = deriveArgusVars(parsed.value)
  const root = document.documentElement
  for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v)
  try {
    localStorage.setItem(ARGUS_COLOR_KEY, parsed.value)
    // ⭐ R10：盘上再存一份**派生结果的 JSON**——`index.html` 的防闪脚本靠它把用户色
    // 赶在首帧之前贴上去（它能读盘，但加载不了任何模块、也不许自己算）。
    // ⚠️ 同一句 try 保证的是**失败不外溢**（存不下不该让这次切换失败），
    // ⛔ 而**不是**"两份都不动"——`setItem` 之间**没有原子性**：第一条成功、第二条因
    // 配额/被策略挡而抛，落盘的正是"**基色新、变量旧**"的错位（T8-2 复审 F-A3：原注释
    // 把 try 当成了事务，那是错的论证）。后果仅一帧旧色：`main.tsx` 启动时
    // `applyTheme(readTheme())` 会**整份重写**变量、把错位自愈。
    // ⇒ 要真正消除错位得把两条合成**一个** key（`{base, vars}`，代价是读侧解析变复杂）。
    localStorage.setItem(ARGUS_VARS_KEY, argusVarsJson(parsed.value))
  } catch {
    // 存不下只影响"下次还记得"（含防闪），不该让这次切换失败
  }
  return parsed
}

export function readArgusColor(): string {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(ARGUS_COLOR_KEY)
  } catch {
    return ARGUS_DEFAULT
  }
  if (raw === null) return ARGUS_DEFAULT
  const parsed = parseArgusColor(raw)
  return parsed.ok ? parsed.value : ARGUS_DEFAULT
}

export function clearArgusColor(): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  for (const k of Object.keys(deriveArgusVars(ARGUS_DEFAULT))) root.style.removeProperty(k)
}
