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
import { applyTheme } from '../theme.ts'

// ⚠️ Node 内置模块在本仓**必须**用「具名变量说明符」动态 import（两条实测出来的墙，
// 与 `themeTokens.test.ts` / `noRawPalette.test.ts` 顶部同一段：T1 报告 §4 偏差 4/5、M7 勘误 E9）：
//   ① 本仓没有 `@types/node`，而 `tsc -b`（`npm run build` 会跑）**会编译测试文件**
//      ⇒ `import { readFileSync } from 'node:fs'` 直接 TS2307 让构建失败；
//   ② `new URL('..', import.meta.url)` 第二个参数写成**字面量**时，Vite 的
//      asset-import-meta-url 变换会接管，基准被换成 jsdom 的 document base
//      ⇒ `readFileSync` 拿到 http: URL 后报 `ERR_INVALID_URL_SCHEME`。
// ⛔ 不用 `// @ts-expect-error`：将来真装了 @types/node 会变成 TS2578，又把构建搞坏一次。
const NODE_FS = 'node:' + 'fs'
const HERE = import.meta.url

const { readFileSync } = (await import(/* @vite-ignore */ NODE_FS)) as {
  readFileSync: (p: URL, enc: string) => string
}

afterEach(() => {
  localStorage.clear()
  clearArgusColor()
  // 本文件新增了走 `applyTheme` 的用例（F8），它会挂 `data-theme`
  // ⇒ 用完摘掉，别把状态漏给同文件的下一条（`theme.test.ts` 同款清理）。
  document.documentElement.removeAttribute('data-theme')
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
  // ⚠️ 修 F3 顺带改正的措辞：`#767676`（L=0.181164，4.623:1）**不是**"刚好够"——
  // 真临界灰见下一条（`#757575`）。它在这里只是"一个够亮的深灰"这个角色。
  expect(parseArgusColor('#767676').ok).toBe(true)
})

/**
 * ⭐ F3②（T8-1 fix 轮）：**把亮度闸门钉到边界上**。
 *
 * 为什么需要：审查实测 `MIN_LUMINANCE` 只被钉在 **(0.0052, 0.1812]**（35 倍宽）里——
 * 改成 0.02（= 1.4:1，闸门形同虚设）或 0.18，全量 113 条**一条不红**。而"阈值取
 * 4.5:1 反推"这句论证写在代码注释里，**注释不是判据**。
 *
 * 算式（灰色 ⇒ 三通道相同 ⇒ WCAG 相对亮度的三个权重和为 1，L = f(c)，f 见 `argusColor.ts`）：
 *   L(c) = ((c/255 + 0.055) / 1.055) ** 2.4  ≥  0.175
 *   ⇒ (c/255 + 0.055) / 1.055 ≥ 0.175 ** (1/2.4) = 0.48372572806426119
 *   ⇒ c/255 ≥ 0.48372572806426119 × 1.055 − 0.055 = 0.45533064310779561
 *   ⇒ c ≥ 116.10931399248784
 * ⇒ **116 是最大的"不够"、117 是最小的"够"**（相邻两档，差 1/255）：
 *   `#747474` L = 0.174647404（对比度 4.4929:1）**拒**；`#757575` L = 0.177888416（4.5578:1）**收**。
 * ⚠️ 用这一对而不是"随便找个深色"：常量往**任一方向**挪一点点，必有一条翻。
 */
test('⭐ F3②：亮度闸门钉在边界上（#757575 收 / #747474 拒，只差 1/255）', () => {
  const just_below = parseArgusColor('#747474')
  expect(just_below.ok, '#747474（L=0.174647404 < 0.175）必须拒——常量调高一点点就会漏过它').toBe(false)
  expect(parseArgusColor('#757575').ok, '#757575（L=0.177888416 ≥ 0.175）必须收——常量调低一点点就会误杀它').toBe(true)
})

/**
 * ⭐ F3①：**12 个值逐条写死**（`#204060` 这个基色，值一律照 `argusColor.ts` 抄死）。
 *
 * 为什么需要：审查实测 `deriveArgusVars` 的 9 个 alpha 里有 **6 个是"无判据的常量"**
 * （`--v-fg-3/4`、`--v-surface`、`--v-surface-2`、`--v-border-soft`、`--v-accent-soft`）——
 * 一起改成 0.99 全量 113 条**全绿**，而屏幕上 `--v-fg-3` 落在 `--v-surface-2` 上的
 * 对比度从 **5.09 崩到 1.01**（几乎看不见）。表驱动把这些数**逐个**钉住（G8）。
 * ⚠️ `toEqual` 顺带钉住**键集合与个数**（多/少/改名都会红）——这正是 `clearArgusColor`
 * 那条用例覆盖面所依赖的同一张表。
 */
test('⭐ F3①：派生结果与 12 项期望表逐条相等（每个 alpha 都有判据）', () => {
  const WANT: Record<string, string> = {
    '--v-fg': '#204060',
    '--v-fg-2': 'rgba(32, 64, 96, 0.78)',
    '--v-fg-3': 'rgba(32, 64, 96, 0.58)',
    '--v-fg-4': 'rgba(32, 64, 96, 0.38)',
    '--v-surface': 'rgba(32, 64, 96, 0.06)',
    '--v-surface-2': 'rgba(32, 64, 96, 0.14)',
    '--v-inset': 'rgba(32, 64, 96, 0.03)',
    '--v-border': 'rgba(32, 64, 96, 0.45)',
    '--v-border-soft': 'rgba(32, 64, 96, 0.22)',
    '--v-accent': '#204060',
    '--v-accent-soft': 'rgba(32, 64, 96, 0.18)',
    '--v-accent-text': '#204060',
  }
  const v = deriveArgusVars('#204060')
  expect(Object.keys(v)).toHaveLength(12)
  expect(v).toEqual(WANT)
  // ⛔ 不许出现 color-mix / var() —— 判据解析不了它们（见 §0.1）
  for (const val of Object.values(v)) expect(val).not.toContain('color-mix')
})

/**
 * ⭐ F2（= 计划的 **R11**）：`index.css` 的 argus 块 ≡ `deriveArgusVars(ARGUS_DEFAULT)`。
 *
 * ⚠️ **这条比的语义**：CSS 块里那份值与 JS 函数算出来那份**必须机械对上**——
 * 这**不是**"拿实现去验实现"（两边是**两处独立写下的真相**：一处是 CSS 字面值、
 * 一处是 TS 里的 alpha 表），而是"**两份默认值不许漂移**"。
 *
 * 为什么非要判据：① 稳态值**总是**来自 `deriveArgusVars`（`applyTheme('argus')` 每次都调
 * `applyArgusColor`）⇒ CSS 那份只在**首帧**与 `themePalette.test.ts` 里出现；
 * ② 而 `themePalette.test.ts` **只读 CSS**、不跑 JS。审查实测：把派生表的
 * `--v-surface-2` alpha 从 0.14 改成 **0.99**（CSS 一个字节不动）⇒ **全量 113 全绿**，
 * 而运行时真实对比度 `--v-fg-3` / `--v-surface-2` = **5.09 → 1.01**、`--v-accent-text` /
 * `--v-accent-soft` = 7.70 → 1.02 ⇒ **对比度判据验的是"用户看不到的那份值"**。
 *
 * ⚠️ **只比交集**：CSS 块给的是**整套 token**（parity 要求六块逐名相等），`deriveArgusVars`
 * 只算颜色这一族 ⇒ 两边数量本来就不同（评审核过：12 个键在 CSS 块里**全都有**）。
 * "交集恰好 12 个"这条断言就是"一个键名都没漂"的那个证据。
 */
const CSS = readFileSync(new URL('../index.css', HERE), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

/** 取一张主题块的 `名 → 值` 表（解析沿用 `themeTokens.test.ts` 的「选择器 + 花括号体」粗切，先剥注释）。 */
function cssBlock(selector: string): Record<string, string> {
  const m = [...CSS.matchAll(/([^{}]*)\{([^{}]*)\}/g)].find((x) => x[1].trim() === selector)
  expect(m, `index.css 里找不到 ${selector} 块`).toBeTruthy()
  const out: Record<string, string> = {}
  for (const d of m![2].matchAll(/(--v-[a-z0-9-]+)\s*:\s*([^;]+)/g)) out[d[1]] = d[2].trim()
  return out
}

test("⭐ F2/R11：index.css 的 argus 块与 deriveArgusVars(ARGUS_DEFAULT) 必须机械对上", () => {
  const block = cssBlock("[data-theme='argus']")
  const derived = deriveArgusVars(ARGUS_DEFAULT)
  const overlap = Object.keys(derived).filter((k) => k in block)
  expect(
    overlap,
    `CSS 块与派生表的交集不是 12 个（实际 ${overlap.length}）——有键名对不上了`,
  ).toHaveLength(12)
  for (const [k, want] of Object.entries(derived)) {
    expect(block[k], `${k} 在两处不一致（CSS 字面值 vs deriveArgusVars 的输出）`).toBe(want)
  }
})

test('applyArgusColor：写 :root 行内 + 落盘；clearArgusColor 必须**每一个键**都抹掉', () => {
  const ALL = Object.keys(deriveArgusVars(ARGUS_DEFAULT))
  expect(ALL, '派生表的键数变了？下面两条断言的覆盖面跟着它走（这里只是把"12"钉住）').toHaveLength(12)
  const r = applyArgusColor('white')
  expect(r.ok).toBe(true)
  const root = document.documentElement
  expect(root.style.getPropertyValue('--v-fg')).toBe('#f2f2f2')
  expect(root.style.getPropertyValue('--v-border')).toBe('rgba(242, 242, 242, 0.45)')
  expect(localStorage.getItem(ARGUS_COLOR_KEY)).toBe('#f2f2f2')
  // ⭐ F1：先钉"写进去的是**全集**"——否则下面那条"清干净"可以靠"本来就没写"混过去
  //（两个方向都要钉：只写 3 个键的实现不该过得去，只清 3 个键的也不该）。
  for (const k of ALL) {
    expect(root.style.getPropertyValue(k), `${k} 没被 applyArgusColor 写到行内`).not.toBe('')
  }

  clearArgusColor()
  // ⭐⭐ F1（Important）：**逐键**断言，不是只问 `--v-fg`。审查实测：把循环改成只清前 3 个键
  // ⇒ **全量 113 条全绿**，而真实泄漏 9 个键——**含 `--v-accent` / `--v-accent-text` /
  // `--v-border`**，正是计划 §0.1 点名要用 `clearArgusColor` 挡住的那三个
  //（行内赢过任何选择器 ⇒ "从 ARGUS 切到 material"会把材料的强调色与边框顶成 ARGUS 的颜色）。
  // ⚠️ 用 `Object.keys(...)` 驱动、**不手抄 12 个名字**：常量表一改，这里自动跟上。
  for (const k of ALL) {
    expect(root.style.getPropertyValue(k), `${k} 没被 clearArgusColor 清掉`).toBe('')
  }
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

/**
 * ⭐ F8（= 审查 F6）：**发布路径**（`applyTheme`）的判据。
 *
 * 为什么需要：`syncArgusColor` 是 `theme.ts` 的**模块私有**函数，上面那些用例都是
 * **直接调 `applyArgusColor` / `clearArgusColor`**，完全绕过 `applyTheme`
 * ⇒ "切走 ARGUS 要清干净"这条接线**零发布覆盖**：审查实测删掉 `applyTheme` 里那行
 * `syncArgusColor(id)`，全量 113 条**一条不红**，而用户看到的是
 * "`data-theme` 已是 material、屏幕上是荧光绿"。
 *
 * ⚠️ 所以这条必须走**真实入口**（`applyTheme`，也就是 `main.tsx` 与主题菜单用的那个），
 * 并且**逐键**断言——只问 `--v-fg` 的话，"清得只剩 3 个键"那种实现照样过。
 */
test('⭐ F8：经 applyTheme 切换（真实入口）——切到 material 必须清干行内变量', () => {
  applyArgusColor('white') // 盘上/行内的用户色（模拟"用户在 ARGUS 下 /color white 过"）
  // `applyTheme('argus')` 会 `applyArgusColor(readArgusColor())` ⇒ 行内是 `#f2f2f2`
  applyTheme('argus')
  const root = document.documentElement
  expect(root.getAttribute('data-theme')).toBe('argus')
  expect(root.style.getPropertyValue('--v-fg')).toBe('#f2f2f2')

  applyTheme('material')
  expect(root.getAttribute('data-theme')).toBe('material')
  expect(root.style.getPropertyValue('--v-fg'), '切到 material 后 ARGUS 的字色还压着').toBe('')
  for (const k of Object.keys(deriveArgusVars(ARGUS_DEFAULT))) {
    expect(root.style.getPropertyValue(k), `切到 material 后 ${k} 还留在行内`).toBe('')
  }
})
