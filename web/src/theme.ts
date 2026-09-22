/**
 * 主题的**状态源**：id 列表、读取、落盘、应用。
 *
 * 三层分工（M7 全局约定）：
 *   ① 原始变量 `--v-*` 定义在 `index.css` 的 `:root` / `[data-theme='x']` 里；
 *   ② `@theme inline` 把它们接进 Tailwind 命名空间（调用点的类名固定，值随主题走）；
 *   ③ 这个文件只管「读 localStorage → 挂 `data-theme` → 同步 `<meta theme-color>`」。
 *
 * ⚠️ `theme-color` 的值**从 CSS 现读**，不在 TS 里再抄一份色表：抄一份就是两处真相，
 * 而 `index.html` 的防闪脚本已经证明这种重复必然漂移（那条白名单有测试钉着）。
 */

export type ThemeId = 'default' | 'material' | 'brutalism' | 'vaporwave' | 'glass'

export const THEMES: { id: ThemeId; label: string }[] = [
  { id: 'default', label: '默认' },
  { id: 'material', label: 'Material Design' },
  { id: 'brutalism', label: '粗野主义' },
  { id: 'vaporwave', label: '蒸汽波' },
  { id: 'glass', label: '毛玻璃' },
]

export const THEME_STORAGE_KEY = 'vigil.theme'

export function isThemeId(v: unknown): v is ThemeId {
  return typeof v === 'string' && THEMES.some((t) => t.id === v)
}

/** localStorage 可能整个不可用（无痕/被策略挡）——读写都要能静默失败。 */
function stored(): unknown {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY)
  } catch {
    return null
  }
}

export function readTheme(): ThemeId {
  const v = stored()
  return isThemeId(v) ? v : 'default'
}

/** 挂属性 + 落盘 + 同步 `theme-color`。出口判据 2「刷新后仍在」靠它。 */
export function applyTheme(id: ThemeId): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.setAttribute('data-theme', id)
  try {
    localStorage.setItem(THEME_STORAGE_KEY, id)
  } catch {
    // 存不下只影响「下次还记得」这一件事，不该让当前这次切换失败
  }
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta !== null) {
    // 属性刚改完，getComputedStyle 会强制样式重算 ⇒ 拿到的就是新主题的 --v-bg
    const bg = getComputedStyle(root).getPropertyValue('--v-bg').trim()
    if (bg !== '') meta.setAttribute('content', bg)
  }
}
