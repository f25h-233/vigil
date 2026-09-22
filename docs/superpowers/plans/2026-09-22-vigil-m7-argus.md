# VIGIL M7 · 追加任务 T8「Project ARGUS」彩蛋主题 — 实施计划（三个任务）

> **性质**：**用户 2026-09-22 追加的范围**（原话见 §0）。不在 spec §4.3 的四条里 ⇒ 单独立卷；
> 三个任务各自过「实现 → 独立审查 →（必要时）修复 → scoped re-review」，全部落地后对**这一卷的 diff** 做 delta 终审。
> **模式**：SDD `pipeline`｜**BASE**：实施时的 HEAD（T7 动效层之后）
> **依赖**：T1（token 层）、T4（`ThemePicker` / `THEMES`）、T7（动效 token，本卷的 `--v-motion-*` 值要与它共存）
>
> ⚠️ **勘误（T8-1 执行期）：本卷正文里凡写「`--v-argus` 六块都要有」的地方一律作废**——
> 那个 token 被证明是**死 token**（六块的值都等于各自的 `--v-accent`，零消费者），
> T8-1 已把它从六块**全部删除**（`1cf284c`）。parity 比的是"六块集合相同"，删全了照样过。
> ⛔ **不要给 parity 开旁路/忽略名单**（审查明说那比占位更坏）。

---

## 0. 用户原话与裁定（**逐条**，含一条对首版理解的更正）

> 「我们再补一个彩蛋主题，在主题切换里新增一个，会以乱码的形式保持几秒，之后才会显示这个主题的名字"Project ARGUS"，
> 需要给它专门画个体现百眼矩阵，孔雀尾，叶子的纯色图形 logo（由粗线条构成），放在右上角，加上大号的"ARGUS"，
> "ARGUS"下面再加上一行小字，"睡亦警觉，眼观六路"以取代"🏮VIGIL"，加上看起来像终端一样的主题（纯黑为底色。
> 一定要大变样，和现有的 UI 的按钮排布可以完全不同，但功能不能少就是），使用者还可以输入 /color <RGB>/"green"/"white"
> 来切换这一主题的颜色，且 logo 的颜色变化与这一主题的颜色变化同步。」

**用户当轮的三个裁定**：
1. **布局 = 重排级**：顶栏换成 `ARGUS:~$` 提示符 + 方括号命令式导航；撤销/主题切换变终端风文字动作；**四个页面与全部功能照旧**。
2. **乱码 = 每次都演 + 可点击跳过**（~2.5 秒；乱码期间点一下立即显名）。
3. ⚠️ **更正（用户画了图）**：**不是**"logo 放右上角"，而是 **一整块品牌区放左上角、整体取代「🏮 VIGIL」**——
   **左**＝圆角方框 logo（框内 **2×2 眼睛矩阵**）｜**右**＝大号 **ARGUS** + 其下**小字「睡亦警觉，眼观六路」**。
   孔雀尾 / 叶子的意象用"外框的叶尖 + 眼球由外向内收小"暗示，**主体照图**。
   默认色 = **荧光绿**（`/color white` 可换）。
- **controller 替用户先定（可推翻）**：这块品牌区**只在 ARGUS 主题下出现**（其余五套仍是「🏮 VIGIL」）。

## 0.1 ⭐ 一条技术判断：**颜色派生放在 JS 里，不放 CSS**

`/color` 看起来最省事的写法是"只设一个基色变量，其余层级用 `color-mix()` 派生"。**不行**：
本仓的对比度判据（`themePalette.test.ts` 的 `parse()`）只认 `#rrggbb` 与 `rgba(...)`，遇到 `color-mix(...)`
会直接抛"不认识的色值" ⇒ **等于把整套颜色验证弄瞎**（而这一卷恰恰要塞进一个全新的配色体系）。
⇒ 做法：**基色 → 全套派生**由 `argusColor.ts`（纯函数、可单测）算好，以**字面 `rgba()`** 写到 `:root` 的行内自定义属性上；
`index.css` 的 ARGUS 块里留的是**可解析的默认绿色字面值**（判据照常覆盖）。

⚠️ **行内自定义属性的优先级陷阱**（必须处理）：行内样式**赢过任何选择器**，包括 `[data-theme='material']`
⇒ 若切走 ARGUS 时不清掉那些行内变量，**material 的字色会被 ARGUS 的绿色残留顶掉**。
⇒ 切到非 ARGUS 主题时**必须 `clearArgusColor()`**（Task 1 的接口里就有它）。

## 0.2 ⚠️ 执行前必读：T7 那四个坑在本卷的**投影**（同一个作者，同一个毛病）

T7 执行期实测：**我手写的测试替身/断言有 4 处与本仓真实契约不符**（计划 §2.9 勘误 EMA–EMD）。
本卷的测试代码是**同一支笔**写的 ⇒ 先按这四条自查，别重蹈：

| 坑 | 本卷会不会撞 | 处置 |
|---|---|---|
| `vi.spyOn(window, 'matchMedia')` ⇒ `can only spy on a function`（**jsdom@30.1.0 整个 lib 里 0 处**） | **不会**（本卷没有需要 matchMedia 的用例） | ⛔ 也别**引入**它 |
| `.resolves.toBeUndefined()` 与实际兑现值不符（userEvent 的 `directApi.js:32` 兑现 System 实例） | 已在 T7 删掉 | 本卷断言"不抛"时用 `await`，别 `.resolves.toBe…` |
| `closest<HTMLElement>` ⇒ `tsc -b` **直接失败**（TS2339 `.disabled`） | **不会**（本卷无 closest） | 类型窄化宁可显式写 `HTMLButtonElement` |
| `{finished: Promise.resolve()}` 在微任务就兑现 ⇒ 断言"还没插就被移除" | **不会**（本卷不用 WAAPI） | 若将来用动画，替身必须**可控兑现** |
| ⭐ **假定时器 + `userEvent` 会互相咬** | **会**（ArgusLabel 的乱码测试原本要用两者） | **已改**：把 `ms` 调小 + 真实计时器（见 Task 3 的测试） |
| 命令式往 React 管的 DOM 里插节点（T7 的 span 被 `textContent` 快路径抹掉） | **不会**（本卷全是 React 渲染） | 若哪天要插：用**伪元素 + 自定义属性**，别插节点 |
---

# Task 1: ARGUS 主题块与颜色引擎

**Dependencies**：T1、T7｜**Touches**：`web/src/index.css`、`web/src/theme.ts`、`web/index.html`、
`web/src/argusColor.ts`(新)、`web/src/__tests__/argusColor.test.ts`(新)、`web/src/__tests__/theme.test.ts`、
`web/src/__tests__/themeTokens.test.ts`

**Interfaces**
- **Produces**（`argusColor.ts`）：
  ```ts
  export const ARGUS_DEFAULT = '#00ff9c'
  export const ARGUS_NAMED: Record<string, string>   // green/white/amber/cyan/red/magenta
  export type ArgusColorResult = { ok: true; value: string } | { ok: false; reason: string }
  export function parseArgusColor(input: string): ArgusColorResult   // 具名/`#rgb`/`#rrggbb`；校验亮度
  export function deriveArgusVars(base: string): Record<string, string> // 12 个 CSS 变量的字面值
  export function applyArgusColor(input: string): ArgusColorResult   // 校验 → 写 :root 行内 + 落盘
  export function readArgusColor(): string                            // localStorage，非法回落默认
  export function clearArgusColor(): void                             // 抹掉行内变量（切走时必须调）
  export const ARGUS_COLOR_KEY = 'vigil.argus.color'
  ```
- **Produces**（CSS）：第六块 `[data-theme='argus']`（token 与其余五块**逐名相等**）
- **Consumes**：T1 的 `THEMES` / `ThemeId`；`index.html` 的防闪白名单（与新主题同步）

**Steps**

**1) 先写失败测试** `web/src/__tests__/argusColor.test.ts`：

```ts
import { afterEach, expect, test } from 'vitest'
import {
  ARGUS_COLOR_KEY,
  ARGUS_DEFAULT,
  applyArgusColor,
  clearArgusColor,
  deriveArgusVars,
  parseArgusColor,
  readArgusColor,
} from '../argusColor.ts'

afterEach(() => {
  localStorage.clear()
  clearArgusColor()
})

test('具名色与十六进制都能解析（含缩写 #rgb）', () => {
  expect(parseArgusColor('green')).toEqual({ ok: true, value: '#00ff9c' })
  expect(parseArgusColor('white')).toEqual({ ok: true, value: '#f2f2f2' })
  expect(parseArgusColor('#ff8800')).toEqual({ ok: true, value: '#ff8800' })
  expect(parseArgusColor('#f80')).toEqual({ ok: true, value: '#ff8800' })   // 缩写要展开
  expect(parseArgusColor('  WHITE ')).toEqual({ ok: true, value: '#f2f2f2' }) // 大小写与空白都容忍
})

test('⛔ 非法输入要给出**可读的理由**，而不是静默不改', () => {
  for (const bad of ['', 'zzz', '#12', '#gg0000', 'rgb(1,2,3)f']) {
    const r = parseArgusColor(bad)
    expect(r.ok, `"${bad}" 不该被接受`).toBe(false)
    if (!r.ok) expect(r.reason.length).toBeGreaterThan(3)
  }
})

test('⛔ 太暗的颜色必须拒（纯黑底上读不出来）——判据是亮度，不是"我觉得丑"', () => {
  // #101010 的 WCAG 相对亮度约 0.005 ⇒ 与纯黑底的对比度约 1.1，绝对读不出来
  const r = parseArgusColor('#101010')
  expect(r.ok).toBe(false)
  if (!r.ok) expect(r.reason).toContain('暗')
  expect(parseArgusColor('#767676').ok).toBe(true)   // 刚好够（约 4.5:1）
})

test('派生：正文字色=基色，其余层级是它的降透明版本（**字面 rgba**，判据能解析）', () => {
  const v = deriveArgusVars('#204060')
  expect(v['--v-fg']).toBe('#204060')
  expect(v['--v-accent']).toBe('#204060')
  expect(v['--v-fg-2']).toBe('rgba(32, 64, 96, 0.78)')
  expect(v['--v-border']).toBe('rgba(32, 64, 96, 0.45)')
  // ⛔ 不许出现 color-mix / var() —— 判据解析不了它们（见 §0.1）
  for (const val of Object.values(v)) expect(val).not.toContain('color-mix')
})

test('applyArgusColor：写 :root 行内 + 落盘；clearArgusColor 必须抹干净', () => {
  const r = applyArgusColor('white')
  expect(r.ok).toBe(true)
  const root = document.documentElement
  expect(root.style.getPropertyValue('--v-fg')).toBe('#f2f2f2')
  expect(root.style.getPropertyValue('--v-border')).toBe('rgba(242, 242, 242, 0.45)')
  expect(localStorage.getItem(ARGUS_COLOR_KEY)).toBe('#f2f2f2')

  clearArgusColor()
  expect(root.style.getPropertyValue('--v-fg')).toBe('')
  // ⚠️ 落盘**不清**：清的是"这次生效的覆盖"，盘上那份是用户的偏好
  expect(localStorage.getItem(ARGUS_COLOR_KEY)).toBe('#f2f2f2')
})

test('applyArgusColor 失败时**什么都不改**（不能改一半）', () => {
  applyArgusColor('green')
  const before = document.documentElement.style.getPropertyValue('--v-fg')
  const r = applyArgusColor('#101010')
  expect(r.ok).toBe(false)
  expect(document.documentElement.style.getPropertyValue('--v-fg')).toBe(before)
  expect(localStorage.getItem(ARGUS_COLOR_KEY)).toBe('#00ff9c')
})

test('readArgusColor：盘上是垃圾/太暗 ⇒ 回落默认', () => {
  expect(readArgusColor()).toBe(ARGUS_DEFAULT)
  localStorage.setItem(ARGUS_COLOR_KEY, 'nonsense')
  expect(readArgusColor()).toBe(ARGUS_DEFAULT)
  localStorage.setItem(ARGUS_COLOR_KEY, '#010101')
  expect(readArgusColor()).toBe(ARGUS_DEFAULT)
  localStorage.setItem(ARGUS_COLOR_KEY, '#abcdef')
  expect(readArgusColor()).toBe('#abcdef')
})
```

**2) 写 `web/src/argusColor.ts`**：

```ts
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
```

**3) `web/src/theme.ts`：加第六个主题**

```ts
export type ThemeId = 'default' | 'material' | 'brutalism' | 'vaporwave' | 'glass' | 'argus'

export const THEMES: { id: ThemeId; label: string }[] = [
  { id: 'default', label: '默认' },
  { id: 'material', label: 'Material Design' },
  { id: 'brutalism', label: '粗野主义' },
  { id: 'vaporwave', label: '蒸汽波' },
  { id: 'glass', label: '毛玻璃' },
  { id: 'argus', label: 'Project ARGUS' },   // ⚠️ 它在菜单里由 `ArgusLabel` 渲染成"先乱码后显名"（Task 3）
]
```
并加一个**切换时的颜色生命周期**（放 `theme.ts` 里最合适——它管"主题生效"这件事）：
```ts
import { applyArgusColor, clearArgusColor, readArgusColor } from './argusColor.ts'

/** 主题生效的**唯一入口**（`applyTheme` 内部调它）：ARGUS 要带上它的颜色覆盖，别的主题要清干净。 */
function syncArgusColor(id: ThemeId): void {
  if (id === 'argus') applyArgusColor(readArgusColor())
  else clearArgusColor()
}
```
`applyTheme(id)` 里 `root.setAttribute('data-theme', id)` **之后**调 `syncArgusColor(id)`；
`main.tsx` 的启动路径不用改（它已经调 `applyTheme(readTheme())`）。

**4) `web/index.html`**：防闪白名单加 `'argus'`（`ALLOWED` 数组）——⚠️ `theme.test.ts` 里那条漂移守卫就是干这个的，
不加它会红；**这不是"改测试迁就实现"，是同一条真相的第二份手写副本必须同步**。

**5) `web/src/index.css`：第六块 `[data-theme='argus']`**
⚠️ **token 与其余五块逐名相等**（parity 会逐字比）。值如下（`--v-argus` 一并在**六块**里都要有——
parity 要求集合相等；其余五块那份只是占位，注释写清"只有 argus 消费它"）：

```css
[data-theme='argus'] {
  /* 终端：纯黑底 + 等宽 + 分步动效；字色**就是**主题色（/color 可改，见 argusColor.ts） */
  --v-argus: #00ff9c;
  --v-bg: #000000;
  --v-header: rgba(0, 0, 0, 0.92);
  --v-page-image: none;
  --v-wallpaper: none;
  --v-wallpaper-size: auto;
  --v-wallpaper-pos: center top;
  --v-fg: #00ff9c;
  --v-fg-2: rgba(0, 255, 156, 0.78);
  --v-fg-3: rgba(0, 255, 156, 0.58);
  --v-fg-4: rgba(0, 255, 156, 0.38);
  --v-surface: rgba(0, 255, 156, 0.06);
  --v-surface-2: rgba(0, 255, 156, 0.14);
  --v-surface-solid: #050b09;
  --v-inset: rgba(0, 255, 156, 0.03);
  --v-border: rgba(0, 255, 156, 0.45);
  --v-border-soft: rgba(0, 255, 156, 0.22);
  --v-accent: #00ff9c;
  --v-accent-soft: rgba(0, 255, 156, 0.18);
  --v-accent-text: #00ff9c;
  --v-danger: #ff5f56;
  --v-danger-soft: rgba(255, 95, 86, 0.12);
  --v-danger-btn: rgba(255, 95, 86, 0.18);
  --v-danger-btn-active: rgba(255, 95, 86, 0.3);
  --v-danger-text: #ffb3ae;
  --v-warn: #ffbd2e;
  --v-warn-soft: rgba(255, 189, 46, 0.12);
  --v-warn-btn: rgba(255, 189, 46, 0.18);
  --v-warn-text: #ffe0a3;
  --v-radius-md: 2px;
  --v-radius-lg: 2px;
  --v-radius-xl: 2px;
  --v-radius-full: 2px;
  --v-shadow-card: 0 0 0 1px rgba(0, 255, 156, 0.18);
  --v-header-blur: 0px;
  --v-panel-blur: 0px;
  --v-font-sans: ui-monospace, 'Cascadia Mono', Consolas, 'Microsoft YaHei', monospace;
  --v-tracking: 0.02em;
  --v-motion-dur: 90ms;
  --v-motion-ease: steps(2, end);   /* 终端风：分步跳变，不是平滑过渡 */
  --v-ripple: transparent;          /* 终端不要涟漪 */
  --v-press-scale: 1;
}
```
> 其余五块各加一行 `--v-argus: <它们自己的强调色的字面值>;`（占位，不被消费）+ 一句注释。

**6) `themeTokens.test.ts`**：结构值表加 `argus` 一行（值照上面写死；T7 之后这张表已是"13 个 token × 非默认主题"）。
**`theme.test.ts`**：`expect(THEMES).toHaveLength(5)` → **6**（这是设计变更，不是放宽断言）。

**7) 收尾**：`cd web && npm test`（期望 **98 + 你新增的**）+ `npm run build`。
**变异反证**（各报原始输出）：① 把 `parseArgusColor` 的亮度校验删掉 ⇒ "太暗要拒"那条必红；
② 把 `applyTheme` 里的 `syncArgusColor(id)` 删掉 ⇒ **Task 2 的"切走要清干净"那条必红**（若 Task 2 还没写，
就用一条临时探针复现"material 的字色被 ARGUS 残留顶掉"，报告里留下证据）。
**commit**：`feat(web,argus): 第六个主题 Project ARGUS——纯黑终端 token + 颜色引擎（/color 的基色派生）`

---

### R10 / R11（controller 裁决，T8-1 执行期发现，**并入 Task 2 的范围**）

- **R10 · 颜色的 FOUC**：T8-1 实测指出的真问题——`index.html` 的防闪脚本只挂 `data-theme`，
  **读不到 `/color` 的落盘值** ⇒ 刷新后**首帧是默认绿**、再跳成用户色（而主题本身没有这个问题，因为它是脚本挂的）。
  **修法**：`applyArgusColor` 额外把**派生结果**（12 个变量的 JSON）落到 `vigil.argus.vars`；
  防闪脚本里若 `data-theme === 'argus'` 就把那份 JSON **行内应用**到 `:root`。
  ⛔ **不许**在防闪脚本里复制一份派生数学（复制 = 两处真相，必然漂移）。
  判据：模拟"盘上有 vars + 主题是 argus" ⇒ 首帧的 `--v-fg` 就已是用户色（不是默认绿）。
  ⛔ **安全约束（T8-1 审查提出，必须遵守）**：那份 JSON 是 **localStorage 可控的**，而键名会被喂给 `setProperty`
  ⇒ **任意行内样式注入**。必须**按形状白名单**：键名只允许匹配 `^--v-[a-z0-9-]+$`，
  值只允许匹配 `^#[0-9a-f]{6}$` 或 `^rgba?\([0-9., %]+\)$`；**不匹配的键直接丢弃**（而不是"试试看"）。
  另：这段逻辑必须**嵌在 `ALLOWED` 判定为 `argus` 的分支内**；`setAttribute('data-theme')` 在**前**、且与写样式**分两个 try**；
  新键名要**补一条守卫**（键名集合不许漂）；并注意 blob **陈旧性**（结构变了就丢弃重来，别硬套）。
- **R11 · 一句无判据的声称**：`index.css` 的 argus 块里那些默认值，注释声称"≡ `deriveArgusVars(ARGUS_DEFAULT)`"。
  那是**声称**、不是判据 ⇒ 补一条测试：解析 CSS 的 argus 块，把它与 `deriveArgusVars(ARGUS_DEFAULT)` 的
  **12 个重叠变量逐个逐字比**（期望值写死；这是"两处真相必须机械对上"的典型）。

### R12（controller 裁决：把 T8-1 复审的三条**并入本任务**，别再多开一轮）

这三条都在本任务本就要改的文件里（`index.css` / `argusColor.test.ts`），合做最省：

- **R12-a（= 审查 F9，复审建议"本轮就补"）**：`ARGUS_NAMED.red = '#ff5f56'`（`argusColor.ts:20`）与
  CSS 的 `--v-danger: #ff5f56`（`index.css` 里 argus 块）是**两份手写字面值**，而注释声称二者相同 ——
  **又一次"无判据的声称"**（复审实测：全仓只此两处、`ARGUS_NAMED` 零测试引用、palette 测试只读 CSS）。
  ⇒ 复用本任务的 CSS 块解析助手，补一条**跨文件对账**断言（`ARGUS_NAMED` 的具名色 ↔ CSS 对应 token，逐字比）。
- **R12-b（= 复审 5.1）**：`index.css` 里还有**三处同类烂数**：`:106 另外四套`、`:110 五块`、`:164 五块` + 枚举漏了 argus 的 `2px`
  ⇒ 照实改（⚠️ 别再写具体数字进去，除非注明取数方式——本项目反复吃过"手写计数必然过期"的亏）。
- **R12-c（= 复审 5.2，⭐ 最值钱的一条）**：`luminance()` 的**三个 WCAG 权重无判据**——
  互换前两个权重 ⇒ **全量 116 全绿**（灰阶见证色对权重互换**不变**，因三权重和为 1）
  ⇒ 真实后果：`#d00000` 真 L=0.1312（3.62:1，**该拒**）会被算成 0.4418（9.8:1）**放行**。
  ⇒ 补一对**纯红边界见证**：取两个只差一点点的红色，一个该拒一个该收（把算式与 `#d00000` 的真值写进注释）。
- **R12-d（文书）**：本卷 `:330/:336/:380` 曾要求 `--v-argus`（与本轮相反）——已由上面那条勘误作废，不必改正文，但**别照旧实施**。

### R14（用户 2026-09-22 追加）· 品牌区的字标换成**新的美术资产**（必须随主题色变色）

用户给了一份 "argus" 的**艺术字**（低写连笔、红底白背的位图），原话：
「品牌区那里的"argus"就用这个吧，**但注意它要能随主题色切换而变色，所以这个图片不能直接用**。
（但你也别好心把活在主会话里帮子agent做完，外包给他去）」

**做法（正解：把位图当蒙版用）**：
- 位图本身**不能**直接 `<img>`（颜色被烤死）⇒ 用 `mask-image: url(...)` + `background-color: currentColor`
  （Tailwind 的 `bg-current`）⇒ **形状来自资产、颜色来自主题色** ⇒ `/color` 一改，字标跟着变。
- 需要**预处理**那份位图：红笔画 → **不透明**、其余 → **全透明**的 RGBA PNG（`mask-image` 默认按 **alpha** 走），
  并裁到墨迹包围盒（顺带报出宽高比，便于排版）。
- 资产要进仓库（`web/src/assets/`，Vite 会指纹化）；
  ⚠️ **全程不许写 `C:`**——源图在用户的 `Pictures` 目录下，**先拷到 `D:/tmp/` 再处理**。
- **无障碍**：字标现在是图形 ⇒ 指定 `role="img"` + `aria-label="ARGUS"`；
  ⚠️ 既有用例 `getByText('ARGUS')` 会因此失配 ⇒ **按新语义改**（查 role/label），
  并在报告里说明这是**语义变更**而非放宽断言。
- **判据**（用户要求那条的机械形式）：扩展既有"纯色"守卫——字标元素**必须是 `bg-current`/`text-current`**，
  且**不许**出现任何写死颜色的类（`bg-[#…]` / `text-[#…]` / `bg-red-*` 等）。

### R13（用户定稿）· 徽记图形 = **D 版**（荒坂内核改 + 用户四条要求）

**用户 2026-09-22 定稿**：用户在看过 7 个候选后，指定「把荒坂（Arasaka）那个改一改」的 **D 版**。
四条改动（用户原话）：**① 删下面的字母 ② 删外边那个圆圈 ③ 把那三个球掏空成环 ④ 加两条扇骨（像 V2 那样）**。
迭代过程中 controller 实测出的**关键一改**：**支干必须只接到环的外缘、不许穿进去**——
原来三个球是实心的，线连上去看不出来；**掏空成环后，穿过去就像"环被划了一道"**（左环看着像 "Q"）。
⇒ 接点按「环心 + 单位向量 × (r + 0.9)」算。

**定稿的精确 SVG（照抄，勿重推几何）**：

```svg
<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M16 29 V 16" />
  <path d="M12.8 16 q-2.8 3.6 -3.4 7.6" />
  <path d="M19.2 16 q2.8 3.6 3.4 7.6" />
  <path d="M16 16 V 12.9" />
  <path d="M16 16 L 12.6 13.8" />
  <path d="M16 16 L 19.4 13.8" />
  <circle cx="16" cy="8.8" r="3.2" />
  <circle cx="7.6" cy="10.6" r="3.2" />
  <circle cx="24.4" cy="10.6" r="3.2" />
</svg>
```

⚠️ **全是 `currentColor` / `fill="none"`、无瞳孔、无写死颜色** ⇒ 品牌区里那条"纯色"守卫（逐属性检查）继续成立；
`ArgusBrand.tsx` 里的 `<ArgusLogo className="h-9 w-9 shrink-0" />` **不必改**（换的是 SVG 内部）。
预览材料：`_smoke/m7-shots/argus-logo-arasaka.png`（左起 D / E / A）与逐格 `argus-logo-{a,b,c,d,e}.png`。

# Task 2: ARGUS 品牌区 + 终端式头部 + `/color` 命令

**Dependencies**：Task 1｜**Touches**：`web/src/components/ArgusLogo.tsx`(新)、`web/src/components/ArgusBrand.tsx`(新)、
`web/src/components/ArgusCommand.tsx`(新)、`web/src/App.tsx`、`web/src/components/ThemePicker.tsx`（只加 `data-theme` 钩子，见下）、
`web/src/__tests__/argusBrand.dom.test.tsx`(新)、`web/src/__tests__/argusCommand.dom.test.tsx`(新)

**Interfaces**
- **Produces**：`ArgusLogo({ className })`（**纯 `currentColor`**，无任何字面色值）、`ArgusBrand()`、
  `ArgusCommand()`（提示符后的输入行，处理 `/color`）
- **Consumes**：Task 1 的 `applyArgusColor`；`THEMES` / `ThemePicker` / `App` 的既有接线

**Steps**

**1) 先写失败测试**（两个文件）：

```tsx
// web/src/__tests__/argusBrand.dom.test.tsx
import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import ArgusBrand from '../components/ArgusBrand.tsx'

test('品牌区三件套：徽记 + ARGUS + 小字', () => {
  render(<ArgusBrand />)
  expect(screen.getByRole('img', { name: 'ARGUS 徽记' })).toBeTruthy()
  expect(screen.getByText('ARGUS')).toBeTruthy()
  expect(screen.getByText('睡亦警觉，眼观六路')).toBeTruthy()
})

test('⛔ 徽记必须是**纯色**（全部 currentColor/无填充色）——这是"logo 颜色随主题色同步"的**唯一保证**', () => {
  // 这条不是格式洁癖：只要有一处写死了颜色，/color 改了主题色而 logo 不同步，
  // 而**没有任何别的东西会红**（真浏览器里才看得出来）。
  const { container } = render(<ArgusBrand />)
  const svg = container.querySelector('svg')!
  for (const el of Array.from(svg.querySelectorAll('*'))) {
    for (const attr of ['stroke', 'fill', 'color']) {
      const v = el.getAttribute(attr)
      if (v !== null) expect(['none', 'currentColor'], `${attr}=${v}`).toContain(v)
    }
  }
})
```

```tsx
// web/src/__tests__/argusCommand.dom.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test } from 'vitest'
import ArgusCommand from '../components/ArgusCommand.tsx'
import { clearArgusColor } from '../argusColor.ts'

afterEach(() => {
  localStorage.clear()
  clearArgusColor()
})

async function run(text: string) {
  const input = screen.getByLabelText('ARGUS 命令')
  await userEvent.clear(input)
  await userEvent.type(input, text)
  await userEvent.keyboard('{Enter}')
}

test('/color green ⇒ 写进 :root 并落盘，回一行确认', async () => {
  render(<ArgusCommand />)
  await run('/color green')
  expect(document.documentElement.style.getPropertyValue('--v-fg')).toBe('#00ff9c')
  expect(localStorage.getItem('vigil.argus.color')).toBe('#00ff9c')
  expect(await screen.findByText(/颜色已设为/)).toBeTruthy()
})

test('/color 不合法 ⇒ 回一行**错误**，且什么都不改', async () => {
  render(<ArgusCommand />)
  await run('/color zzz')
  expect(await screen.findByText(/认不出这个颜色/)).toBeTruthy()
  expect(document.documentElement.style.getPropertyValue('--v-fg')).toBe('')
})

test('/color 太暗 ⇒ 错误信息要说出"为什么"（纯黑底上读不出来）', async () => {
  render(<ArgusCommand />)
  await run('/color #101010')
  expect(await screen.findByText(/太暗/)).toBeTruthy()
})

test('未知命令 ⇒ 提示怎么用，而不是静默吞掉', async () => {
  render(<ArgusCommand />)
  await run('/nope')
  expect(await screen.findByText(/未知命令/)).toBeTruthy()
})

test('空行 Enter ⇒ 什么都不做（不报错、不写盘）', async () => {
  render(<ArgusCommand />)
  await userEvent.click(screen.getByLabelText('ARGUS 命令'))
  await userEvent.keyboard('{Enter}')
  expect(screen.queryByText(/错误|未知/)).toBeNull()
})
```

**2) 写三个组件**（`ArgusLogo` / `ArgusBrand` / `ArgusCommand`）——代码见下方"组件全文"。

**3) `App.tsx`：主题为 `argus` 时换头部**（`theme === 'argus' ? <ArgusHeader/> : <原来的 header>`，其余结构一字不动）：

```tsx
{theme === 'argus' ? (
  <header className="sticky top-0 z-10 border-b border-vigil-border bg-vigil-header">
    <div className="mx-auto max-w-3xl px-4 pt-2">
      <div className="flex items-start gap-2">
        <ArgusBrand />
        <button
          onClick={undo}
          className="ml-auto shrink-0 rounded-md px-2 py-1 text-xs text-vigil-fg-3 active:bg-vigil-surface"
        >
          ↶undo
        </button>
        <ThemePicker value={theme} onChange={pickTheme} />
      </div>
      <div className="flex items-center gap-2 pb-1 pt-1.5 text-sm">
        <span className="shrink-0 text-vigil-fg-4">ARGUS:~$</span>
        <ArgusCommand />
      </div>
      <nav className="flex gap-1 overflow-x-auto pb-2 text-sm">
        {TABS.map((t, i) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={
              'shrink-0 rounded-md px-1.5 py-1 transition-colors ' +
              (tab === t.key ? 'bg-vigil-surface-2 text-vigil-fg' : 'text-vigil-fg-3 active:bg-vigil-surface')
            }
          >
            [{i + 1}]{t.label}
          </button>
        ))}
      </nav>
    </div>
  </header>
) : (
  <header ...原样... />
)}
```
> ⚠️ `undoMsg` 在 ARGUS 头部里也要有落点（终端风：接在 `↶undo` 后面一行小字）——**功能不许少**。

**4) `ThemePicker.tsx`**：给菜单容器加 `data-theme-picker` 钩子（Task 3 要用）——**不加任何行为**。

**5) 收尾**：`npm test` + `npm run build`；并**核一条**：ARGUS 头部下 375px 不横向溢出
（`minTabW/maxTabH` 那两个量交给冒烟的渲染脚本，这里只做 DOM 结构断言：`[1]信息流` 等四个关键字都在、
点它们能切页——用 `App` 级用例，`localStorage.setItem('vigil.theme','argus')` 起渲染）。
**变异反证**：给 `ArgusLogo` 里塞一个写死的 `stroke="#fff"` ⇒ "纯色"那条必红。
**commit**：`feat(web,argus): 品牌区（百眼徽记 + ARGUS + 小字）+ 终端式头部 + /color 命令`

---

# Task 3: 乱码演出（主题切换里那个条目）

**Dependencies**：Task 1｜**Touches**：`web/src/components/ArgusLabel.tsx`(新)、
`web/src/components/ThemePicker.tsx`、`web/src/__tests__/argusLabel.dom.test.tsx`(新)

**Interfaces**
- **Produces**：`ArgusLabel({ text = 'Project ARGUS', ms = 2500 })`——挂载即乱码，`ms` 后显名；
  **乱码期间点一下立即显名**（点击**不**选中主题：`stopPropagation`）
- **Consumes**：`ThemePicker` 的菜单项渲染（`t.id === 'argus' ? <ArgusLabel/> : t.label`）

**Steps**

**1) 先写失败测试**：

```tsx
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import ArgusLabel from '../components/ArgusLabel.tsx'

/**
 * ⚠️ **不用假定时器**（执行前必读，T7 的教训）：`vi.useFakeTimers()` 与 `userEvent` 是已知会互相咬的组合
 * （userEvent 内部要推进计时器，默认配置下点击会卡住）。这里的做法是**把 `ms` 调小 + 用真实计时器**：
 * 一样确定性、零配置陷阱。
 * ⚠️ 另：jsdom 里**没有 `matchMedia`**（T7 grep 实证：jsdom@30.1.0 整个 lib 里 0 处）⇒ 别 `vi.spyOn(window, 'matchMedia')`
 * （会报 `can only spy on a function`）；本组件也不需要它。
 */

test('挂载时**不是**真名（乱码），到时后显名', async () => {
  render(<ArgusLabel ms={60} />)
  expect(screen.queryByText('Project ARGUS')).toBeNull()
  const garbled = screen.getByTestId('argus-label').textContent ?? ''
  expect(garbled.length).toBe('Project ARGUS'.length) // 长度先对齐，避免布局跳
  expect(await screen.findByText('Project ARGUS', undefined, { timeout: 2000 })).toBeTruthy()
})

test('⭐ 乱码期间点一下 ⇒ 立即显名，而且**不冒泡**（不能顺手把主题选了）', async () => {
  const onParent = vi.fn()
  render(
    <div onClick={onParent}>
      <ArgusLabel ms={10000} />   {/* 长到"不会自己揭晓"，于是这次揭晓只能来自点击 */}
    </div>,
  )
  await userEvent.click(screen.getByTestId('argus-label'))
  expect(screen.getByText('Project ARGUS')).toBeTruthy()
  expect(onParent).not.toHaveBeenCalled()
})

test('揭晓之后**不再有定时器在跑**（不许留着）', async () => {
  vi.spyOn(globalThis, 'clearInterval')
  render(<ArgusLabel ms={60} />)
  await screen.findByText('Project ARGUS', undefined, { timeout: 2000 })
  expect(vi.mocked(globalThis.clearInterval).mock.calls.length).toBeGreaterThan(0)
  vi.restoreAllMocks()
})
```
> 第三条把"定时器必须清"从"数 `vi.getTimerCount()`"（需要假定时器）换成"**观察 `clearInterval` 被调用**"——
> 这样三条用例都在真实计时器下跑，判据仍指向同一件事（显名后不留定时器）。

**2) 写 `ArgusLabel.tsx`**（全文见下），并把它接进 `ThemePicker` 的菜单项：
```tsx
{t.id === 'argus' ? <ArgusLabel /> : t.label}
```
⚠️ `ArgusLabel` 内部**只能是 `<span>`**（T4 的既有注释写明：HTML 不许 `<button>` 里嵌交互元素；
菜单项本身已经是 `role="menuitemradio"` 的 button）⇒ 跳过用的点击挂在 span 上 + `stopPropagation`，
**无障碍的键盘路径 = 直接 Enter 选中该主题**（乱码是装饰，写进注释）。
**3) 收尾**：`npm test` + `npm run build`。
**变异反证**：把 `stopPropagation` 删掉 ⇒ "不冒泡"那条必红。
**commit**：`feat(web,argus): 主题切换里 ARGUS 条目先乱码后显名（可点击跳过）`

---

## 组件全文（三个 + 一个 label）

```tsx
// web/src/components/ArgusLogo.tsx
/**
 * 「百眼矩阵」徽记：圆角方框 + 2×2 的眼睛（瞳孔 + 眼睑），**粗线条、纯色**。
 * 孔雀尾/叶子的暗示：外框左下收出一段叶尖，四只眼球由外向内略微收小（尾扇的层次）。
 *
 * ⚠️ 全部用 `currentColor`：颜色由外层文字色决定 ⇒ `/color` 改了主题色，徽记**自动**跟着变，
 * 不需要任何同步代码。**任何一处写死颜色都会打破这件事**（有测试逐属性守它）。
 */
export default function ArgusLogo({ className = '' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      className={className}
      role="img"
      aria-label="ARGUS 徽记"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* 外框：圆角方形，左下角收成叶尖 */}
      <path d="M6 4.5h19a3.5 3.5 0 0 1 3.5 3.5v13a3.5 3.5 0 0 1-3.5 3.5h-13c-3.3 0-5.4-2.1-6-5.5" />
      <path d="M6 19c2.6-.3 4.4-1.6 5.4-3.9" />
      {/* 百眼矩阵 */}
      <circle cx="12.5" cy="11.5" r="3.1" />
      <circle cx="12.5" cy="11.5" r="0.7" fill="currentColor" />
      <circle cx="20.5" cy="11.5" r="3.1" />
      <circle cx="20.5" cy="11.5" r="0.7" fill="currentColor" />
      <circle cx="13.5" cy="19.5" r="2.6" />
      <circle cx="13.5" cy="19.5" r="0.6" fill="currentColor" />
      <circle cx="20.5" cy="19.5" r="2.6" />
      <circle cx="20.5" cy="19.5" r="0.6" fill="currentColor" />
    </svg>
  )
}
```

```tsx
// web/src/components/ArgusBrand.tsx
import ArgusLogo from './ArgusLogo.tsx'

/** 左上角的品牌区：徽记 + 大号 ARGUS + 小字。它**整体取代**「🏮 VIGIL」（只在 ARGUS 主题下）。 */
export default function ArgusBrand() {
  return (
    <div className="flex items-center gap-2">
      <ArgusLogo className="h-9 w-9 shrink-0" />
      <div className="leading-none">
        <div className="text-lg font-bold tracking-[0.28em]">ARGUS</div>
        <div className="mt-1 text-[10px] tracking-[0.18em] text-vigil-fg-3">睡亦警觉，眼观六路</div>
      </div>
    </div>
  )
}
```

```tsx
// web/src/components/ArgusCommand.tsx
import { useState } from 'react'
import { applyArgusColor } from '../argusColor.ts'

/**
 * 提示符后面的输入行：目前只认 `/color`。
 * ⚠️ 错误**必须说出来**（认不出 / 太暗 / 未知命令）——终端里静默吞掉输入是最糟的形态。
 */
export default function ArgusCommand() {
  const [line, setLine] = useState('')
  const [msg, setMsg] = useState<{ text: string; bad: boolean } | null>(null)

  function run(raw: string) {
    const text = raw.trim()
    if (text === '') return
    if (text === '/color' || text.startsWith('/color ')) {
      const r = applyArgusColor(text.slice('/color'.length))
      setMsg(r.ok ? { text: `颜色已设为 ${r.value}`, bad: false } : { text: `错误：${r.reason}`, bad: true })
      return
    }
    setMsg({ text: `未知命令：${text.split(' ')[0]}（试试 /color green）`, bad: true })
  }

  return (
    <div className="min-w-0 flex-1">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          run(line)
          setLine('')
        }}
      >
        <input
          aria-label="ARGUS 命令"
          value={line}
          onChange={(e) => setLine(e.target.value)}
          placeholder="/color green"
          spellCheck={false}
          autoComplete="off"
          className="w-full bg-transparent text-vigil-fg outline-none placeholder:text-vigil-fg-4"
        />
      </form>
      {msg !== null && (
        <p className={'truncate text-xs ' + (msg.bad ? 'text-vigil-danger' : 'text-vigil-fg-3')}>{msg.text}</p>
      )}
    </div>
  )
}
```

```tsx
// web/src/components/ArgusLabel.tsx
import { useEffect, useState } from 'react'

const GLYPHS = '▚▞▓▒░█▄▀◣◢◤◥╳╱╲#$%&@0123456789'

function scramble(n: number): string {
  let out = ''
  for (let i = 0; i < n; i += 1) out += GLYPHS[Math.floor(Math.random() * GLYPHS.length)]
  return out
}

/**
 * 主题切换里的「先乱码、后显名」。
 *
 * ⚠️ 三条约束：
 * 1. **只能是 `<span>`**：菜单项本身已经是 `<button role="menuitemradio">`，HTML 不许 button 嵌 button。
 *    ⇒ 跳过用的点击挂在 span 上 + `stopPropagation()`（点它是"揭晓"，不是"选中"）。
 *    无障碍的键盘路径 = 直接 Enter 选中该主题（乱码是**装饰**，不是功能）。
 * 2. 每次挂载都演一遍（用户的要求："每次都演"）⇒ 不需要 localStorage 开关。
 * 3. 显名后**必须清掉定时器**（有测试数 `vi.getTimerCount()`）。
 */
export default function ArgusLabel({ text = 'Project ARGUS', ms = 2500 }: { text?: string; ms?: number }) {
  const [revealed, setRevealed] = useState(false)
  const [garbled, setGarbled] = useState(() => scramble(text.length))

  useEffect(() => {
    if (revealed) return
    const spin = window.setInterval(() => setGarbled(scramble(text.length)), 90)
    const done = window.setTimeout(() => setRevealed(true), ms)
    return () => {
      window.clearInterval(spin)
      window.clearTimeout(done)
    }
  }, [revealed, ms, text.length])

  return (
    <span
      data-testid="argus-label"
      title={revealed ? undefined : '点一下直接揭晓'}
      onClick={(e) => {
        e.stopPropagation()
        setRevealed(true)
      }}
    >
      {revealed ? text : garbled}
    </span>
  )
}
```

## 渲染验证（三任务全部落地后，一次做）

`_smoke/` 下一次性脚本（Playwright + msedge）：
1. 切到 ARGUS ⇒ 截图（桌面 + 手机）：**纯黑**、等宽、`ARGUS:~$` 提示符、`[1]…[4]` 关键字、**左上角品牌区**（徽记 + ARGUS + 小字）；
2. `/color white` ⇒ 截图 ⇒ **逐像素比对**：徽记区域与正文字色变成白（"logo 随主题色同步"的机械证据）；
3. 菜单里 ARGUS 那一条：开菜单**立刻**截一张（应是乱码）→ 3 秒后再截（应是「Project ARGUS」）⇒ 两张必须不同；
4. 375px：`clippedHeaderCount == 0`、`maxTabH ≤ 40`；
5. **四个页面都点一遍**（`[1]…[4]`）确认功能没少（每页 `elems/textLen` 非空、console 错误 0）；
6. 其余五套主题与上一轮渲染**无回归**（像素差只应出现在本次改动的地方）。

## 不做

| 项 | 为什么 |
|---|---|
| 页面内的组件也重排成终端（把表单改成问答式） | 用户选的是**重排级**（顶栏 + 导航 + 视觉），四个页面的内部结构保持不变才是"功能不许少"的最稳实现 |
| `/color` 支持更多命令（`/theme`、`/export`…） | 用户只要了 `/color`；多做的每一条都要单独设计错误形态 |
| 把 ARGUS 品牌区也用于其它主题 | 它是**彩蛋主题的身份**；其余五套保持「🏮 VIGIL」（controller 先定，用户可推翻） |
| 乱码用真·随机字体/字宽 | 会引发布局跳动；当前实现**长度对齐**（同字数），只换字形 |
```
