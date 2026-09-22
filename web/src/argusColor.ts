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

export function applyArgusColor(input: string): ArgusColorResult {
  const parsed = parseArgusColor(input)
  if (!parsed.ok) return parsed
  const vars = deriveArgusVars(parsed.value)
  const root = document.documentElement
  for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v)
  try {
    localStorage.setItem(ARGUS_COLOR_KEY, parsed.value)
  } catch {
    // 存不下只影响"下次还记得"，不该让这次切换失败
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
