import { expect, test } from 'vitest'
import { THEMES } from '../theme.ts'

// ⚠️ Node 内置模块的写法与理由见 `noRawPalette.test.ts` 顶部那段（M7 勘误 E9 的两条墙）
const NODE_FS = 'node:' + 'fs'
const HERE = import.meta.url
const { readFileSync } = (await import(/* @vite-ignore */ NODE_FS)) as {
  readFileSync: (p: URL, enc: string) => string
}

/**
 * ⭐ 调色板的**可读性守卫**。它回答两个肉眼会漏的问题：
 *   ① 浅色主题**真的**是浅色吗（出口判据 4 的反面：深色残留）
 *   ② 弱化文字 / 软底按钮上的文字**读得清**吗（主题化最容易在"某一套"上翻车）
 *
 * ⚠️ 期望值一律**逐字写死**，绝不写成"读 CSS 再比 CSS"（空守卫的经典形状）。
 * ⚠️ 已知近似：玻璃主题的真实底是**渐变**，而这里只能拿 `--v-bg`（不透明基色）算
 *    ⇒ 故 `--v-bg` 取渐变中位色。这条近似**写在这里**，不许被说成"渐变也验过了"。
 * ⚠️ 剥注释再解析（理由同 `themeTokens.test.ts`：注释里含示例 CSS）。
 */
const CSS = readFileSync(new URL('../index.css', HERE), 'utf8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
)

type RGBA = [number, number, number, number]

function value(theme: string, token: string): string {
  const m = CSS.match(
    new RegExp(`\\[data-theme='${theme}'\\][^{]*\\{[^}]*${token}\\s*:\\s*([^;]+);`),
  )
  if (m === null) throw new Error(`找不到 ${theme} 的 ${token}`)
  return m[1].trim()
}

function parse(s: string): RGBA {
  const hex = s.match(/^#([0-9a-f]{6})$/i)
  if (hex !== null) {
    const n = parseInt(hex[1], 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255, 1]
  }
  const rgba = s.match(/rgba?\(([^)]+)\)/)
  if (rgba !== null) {
    const p = rgba[1].split(',').map((x) => parseFloat(x.trim()))
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]
  }
  throw new Error(`不认识的色值：${s}`)
}

/** 半透明层叠在不透明底上（默认主题的面几乎都是 rgba，不算这步全错） */
function over(top: RGBA, bottom: RGBA): RGBA {
  const a = top[3]
  return [
    top[0] * a + bottom[0] * (1 - a),
    top[1] * a + bottom[1] * (1 - a),
    top[2] * a + bottom[2] * (1 - a),
    1,
  ]
}

function luminance([r, g, b]: RGBA): number {
  const f = (c: number) => {
    const x = c / 255
    return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}

function contrast(a: RGBA, b: RGBA): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

test('四套非默认主题的两个"面"色都不等于默认主题（否则它没换过）', () => {
  for (const t of THEMES.filter((x) => x.id !== 'default')) {
    expect(value(t.id, '--v-surface'), `${t.id} 的 --v-surface`).not.toBe(
      value('default', '--v-surface'),
    )
    expect(value(t.id, '--v-bg'), `${t.id} 的 --v-bg`).not.toBe(value('default', '--v-bg'))
  }
})

test('浅色主题真的是浅色、深色主题真的是深色（出口判据 4 的静态形式）', () => {
  const light = ['material', 'brutalism']
  for (const t of THEMES) {
    const L = luminance(parse(value(t.id, '--v-bg')))
    if (light.includes(t.id)) {
      expect(L, `${t.id} 的 --v-bg 应该是浅色`).toBeGreaterThan(0.5)
    } else {
      expect(L, `${t.id} 的 --v-bg 应该是深色`).toBeLessThan(0.5)
    }
  }
})

test('正文与弱化文字在面板上都读得清（WCAG：正文 ≥4.5 / 弱化文字 ≥3）', () => {
  for (const t of THEMES) {
    const bg = parse(value(t.id, '--v-bg'))
    const card = over(parse(value(t.id, '--v-surface')), bg)
    // ⚠️ 软底 / 危险按钮的底**也是半透明的**（默认主题与蒸汽波、玻璃都是 rgba）
    // ⇒ 必须先合成到卡片底上再算对比度。拿**未合成**的色值去比，等于把
    // 「深底上的 20% 浅蓝」当成「浅蓝实底」——结论正好反过来：实测默认主题
    // `--v-accent-soft` 未合成时按 #38bdf8 算 ⇒ 1.61（**假红**，而默认块是 T1
    // 冻结的基线、不许改值）；合成到卡片底 ≈rgb(30,59,75) 后 ⇒ 8.84（真值）。
    // ⚠️ 判据（≥4.5 / ≥3）一个字没动，动的是"底该取哪个值"。合成用 `card` 而
    // 不是 `bg`：卡片比页面底**浅**，浅底 ⇒ 对比度更低 ⇒ 取更严的那一侧。
    // 这条修正的完整依据（四套主题两种算法的逐项数字）见 task-3-report.md 偏差 1。
    const soft = over(parse(value(t.id, '--v-accent-soft')), card)
    const dangerBtn = over(parse(value(t.id, '--v-danger-btn')), card)
    expect(contrast(parse(value(t.id, '--v-fg')), card), `${t.id} 正文/卡片`).toBeGreaterThanOrEqual(4.5)
    expect(contrast(parse(value(t.id, '--v-fg-3')), card), `${t.id} 弱化文字/卡片`).toBeGreaterThanOrEqual(3)
    expect(
      contrast(parse(value(t.id, '--v-accent-text')), soft),
      `${t.id} 软底按钮文字`,
    ).toBeGreaterThanOrEqual(3)
    expect(
      contrast(parse(value(t.id, '--v-danger-text')), dangerBtn),
      `${t.id} 危险按钮文字`,
    ).toBeGreaterThanOrEqual(3)
  }
})
