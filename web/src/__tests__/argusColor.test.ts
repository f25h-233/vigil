import { afterEach, expect, test } from 'vitest'
import {
  ARGUS_COLOR_KEY,
  ARGUS_DEFAULT,
  ARGUS_NAMED,
  ARGUS_VARS_KEY,
  applyArgusColor,
  argusVarsJson,
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
  // ⚠️ R10 的用例会让**防闪脚本**往 `:root` 上贴 `--v-*`，而它的白名单是**形状**白名单
  // （键名不是固定那 12 个）⇒ 落在 `deriveArgusVars` 之外的键不在 `clearArgusColor`
  // 的清理范围内，这里手工收尾。
  for (const k of ['--v-bg', '--v-old-token', '--v-page-image', '--v-x', '--v-y']) {
    document.documentElement.style.removeProperty(k)
  }
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

// ────────────────── R12（T8-1 复审的三条，controller 裁决并入 T8-2） ──────────────────

/**
 * ⭐ R12-a（= 复审 F9）：`ARGUS_NAMED` 的具名色 ↔ CSS token 的**跨文件对账**。
 *
 * 为什么需要：`argusColor.ts` 的 `red: '#ff5f56'` 与 `index.css` 的 `--v-danger: #ff5f56`
 * 是**两份手写的字面值**，而 CSS 里那句注释声称"用 `/color red` 与看错误提示是同一个红"
 * ——**又一处"无判据的声称"**（复审实测：全仓只此两处，且 palette 判据只读 CSS，看不这里）。
 * ⚠️ 这条比的**不是**"实现自洽"：两边是**两处独立写下的真相**（一份 TS 表、一份 CSS 字面值）
 * ⇒ 它验的是"两份不许漂"。
 */
test('⭐ R12-a：具名色 ↔ CSS token 的跨文件对账（只对账**真有声称**的那几对）', () => {
  const block = cssBlock("[data-theme='argus']")
  // ① CSS 注释点名的那个对账：`--v-danger` ≡ `ARGUS_NAMED.red`
  expect(
    block['--v-danger'],
    'argusColor.ts 的 ARGUS_NAMED.red 与 index.css 的 --v-danger 漂了',
  ).toBe(ARGUS_NAMED.red)
  // ② 默认基色 ≡ 具名 green；而 CSS 里默认基色的两个落点（正文与强调色）就是它
  expect(ARGUS_DEFAULT).toBe(ARGUS_NAMED.green)
  expect(block['--v-fg']).toBe(ARGUS_NAMED.green)
  expect(block['--v-accent']).toBe(ARGUS_NAMED.green)
  // ③ 其余四个具名色（white / amber / cyan / magenta）**没有** CSS 对账对象：
  //    `/color white` 是"把基色换成白"，不是"把 --v-warn / --v-danger 换成白"。
  //    ⚠️ 特别注明：`--v-warn: #ffbd2e` **不是** `ARGUS_NAMED.amber`（`#ffb000`）——
  //    两边**故意不同**（一个是 UI 的"提醒"、一个是终端色名）。下一个看到两个黄色的人
  //    会以为有一处漏改，这句注释就是给那一刻用的。
  // ⇒ 钉住具名色的**键集合**：加一个具名色 = 得想一次"它有没有 CSS 对账"。
  expect(Object.keys(ARGUS_NAMED).sort()).toEqual([
    'amber',
    'cyan',
    'green',
    'magenta',
    'red',
    'white',
  ])
})

/**
 * ⭐⭐ R12-c（= 复审 5.2，本卷最值钱的一条）：`luminance()` 的**三个 WCAG 权重本来没有判据**。
 *
 * **实测（复审）**：把前两个权重互换（`0.2126` ↔ `0.7152`）⇒ **全量 116 条全绿**。
 * 为什么能全绿：上面 F3② 那条边界见证用的是**灰**（`#747474` / `#757575`），而灰色三通道
 * 相同 ⇒ `L = (0.2126 + 0.7152 + 0.0722) · f(c) = f(c)`，**权重怎么换都是它**
 * ⇒ 那条守得住闸门的**位置**，守不住闸门的**算术**。
 *
 * **真值**（算式；本实现的公式）：
 *   f(c) = c/255 ≤ 0.03928 ? (c/255)/12.92 : ((c/255 + 0.055)/1.055) ** 2.4
 *   L = 0.2126·f(r) + 0.7152·f(g) + 0.0722·f(b)
 * ⚠️ 复审报告给的 `#d00000` 真值 **0.1312**（3.62:1）与"错权重下 0.4418（9.8:1）"是
 * **省掉 `+0.055 / 1.055` 那一步**（即拿 `(c/255) ** 2.4` 当 f）算出来的近似；
 * 本实现（含那一步）的真值是 **0.134098967**（3.6820:1）与 **0.451117504**（10.0224:1）。
 * 两边的**结论一致**（该拒 / 被错权重放行），差的只是小数第三位——记在这里，
 * 免得下一个照着 0.1312 去核而对不上（本仓"结论对、依据错"的老账）。
 *
 * **后果**：`#d00000` 真 L=0.134099 ⇒ **3.68:1，该拒**；错权重下算成 0.451118 ⇒
 * **10.02:1 放行** ⇒ 用户能把终端字色设成纯黑底上**几乎读不出来的暗红**，而全量一条不红。
 *
 * ⇒ 见证色必须**带颜色通道差异**（纯红）。边界（解 `0.2126·f(c) ≥ 0.175`）：
 *   `(c/255 + 0.055)/1.055 ≥ (0.175/0.2126) ** (1/2.4) = 0.823142… ** (1/2.4)`
 *   ⇒ `c ≥ 234.045` ⇒ **234（`#ea0000`）是最大的"不够"、235（`#eb0000`）是最小的"够"**。
 *   `L(#ea0000) = 0.174924251`（4.4985:1，**拒**）｜`L(#eb0000) = 0.176621676`（4.5324:1，**收**）。
 */
test('⭐⭐ R12-c：权重互换的见证色必须是**纯红**（灰阶见证色对这个变异是瞎的）', () => {
  // 复审点名的那个真色：它必须被拒（错权重下会被算成 10:1 放行）
  expect(
    parseArgusColor('#d00000').ok,
    '#d00000 真 L=0.134098967（3.68:1）必须拒',
  ).toBe(false)
  // 一对纯红边界见证：只差红通道的 1/255
  expect(parseArgusColor('#ea0000').ok, '#ea0000 L=0.174924251 < 0.175 必须拒').toBe(false)
  expect(parseArgusColor('#eb0000').ok, '#eb0000 L=0.176621676 ≥ 0.175 必须收').toBe(true)
})

// ────────────────── R10（颜色的 FOUC：防闪脚本要能读回用户的颜色） ──────────────────

const HTML = readFileSync(new URL('../../index.html', HERE), 'utf8')

/**
 * 取 `index.html` 里那段**内联**防闪脚本并**真跑一遍**。
 *
 * ⚠️ 这是本文件里唯一能直接验防闪脚本的办法（jsdom 不会去加载 `index.html`）。
 * 跑的是**原文**（不是抄一份逻辑——抄一份就是 R10 明令禁止的那件事），
 * 所以 `new Function` 在 jsdom 的全局环境里执行它时，`document` / `localStorage`
 * 就是被测的那两个对象。
 */
function runPreflash(): void {
  const m = HTML.match(/<script>([\s\S]*?)<\/script>/)
  expect(m, 'index.html 里找不到内联防闪脚本').toBeTruthy()
  new Function(m![1])()
}

test('⭐ R10①：`argusVarsJson(base)` 就是 `deriveArgusVars(base)` 的 JSON（可单测的那一半）', () => {
  for (const base of [ARGUS_DEFAULT, '#204060', '#f2f2f2']) {
    expect(JSON.parse(argusVarsJson(base)), `${base} 的 JSON 与派生表不一致`).toEqual(
      deriveArgusVars(base),
    )
  }
  // ⚠️ 它存在的理由 = R10 的"**不许**在防闪脚本里复制一份派生数学"：盘上那份 JSON 必须是
  // **同一个函数**的输出 ⇒ 前端回读时不需要知道任何 alpha，也就没有第二处真相。
  expect(Object.keys(JSON.parse(argusVarsJson(ARGUS_DEFAULT)) as object)).toHaveLength(12)
})

test('⭐ R10②：`applyArgusColor` 把派生结果落到 `vigil.argus.vars`；`clearArgusColor` **不动它**', () => {
  expect(ARGUS_VARS_KEY, '键名不许漂（防闪脚本里那份是字面量，静态钉子会逐字比）').toBe(
    'vigil.argus.vars',
  )
  expect(localStorage.getItem(ARGUS_VARS_KEY)).toBeNull()
  applyArgusColor('white')
  expect(localStorage.getItem(ARGUS_VARS_KEY)).toBe(argusVarsJson('#f2f2f2'))
  clearArgusColor()
  // ⚠️ 与 `ARGUS_COLOR_KEY` **同一条纪律**（见上一条用例末段的注释）：清的是
  // "这次生效的覆盖"，盘上那份是**用户的偏好**——清掉它，下次进 ARGUS 就回到默认绿了。
  expect(localStorage.getItem(ARGUS_VARS_KEY)).toBe(argusVarsJson('#f2f2f2'))
})

test('⛔ R10③：防闪脚本里**没有**第二份颜色数学（复制 = 两处真相，必然漂移）', () => {
  const src = HTML.match(/<script>([\s\S]*?)<\/script>/)![1]
  for (const smell of ['0.2126', '0.7152', '0.0722', '2.4', '0.78', '0.58', '0.38']) {
    expect(src, `防闪脚本里出现了派生用的常量 ${smell}——它在复制颜色数学`).not.toContain(smell)
  }
})

test('⭐ R10④ **静态钉子**：白名单的三条正则字面量与键名都在 index.html 里（防闪脚本无法被单测执行）', () => {
  // ⚠️ 这条钉的是"**白名单没被删 / 键名没漂 / 它嵌在 argus 分支里**"——**不是**"白名单生效"。
  // 生效由下面 ⑤⑥⑦ 三条**真跑那段脚本**的用例证明（读 index.html 原文 + `new Function`）。
  // ⚠️ 正则一律按**实际写在 index.html 里的字面量**钉（写法改了，这里跟着改）。
  expect(HTML).toContain('vigil.argus.vars')
  expect(HTML).toContain('/^--v-[a-z0-9-]+$/')
  expect(HTML).toContain('/^#[0-9a-f]{6}$/')
  expect(HTML).toContain('/^rgba?\\([0-9., %]+\\)$/')
  // 必须在 `ALLOWED` 判定为 argus 的**分支内**（不是"任何主题都贴一份行内样式"）
  const branch = HTML.indexOf("=== 'argus'")
  expect(branch, "防闪脚本里没有 `=== 'argus'` 分支").toBeGreaterThan(-1)
  for (const s of [
    'vigil.argus.vars',
    '/^--v-[a-z0-9-]+$/',
    '/^#[0-9a-f]{6}$/',
    '/^rgba?\\([0-9., %]+\\)$/',
  ]) {
    expect(HTML.indexOf(s), `${s} 出现在 argus 分支之前 ⇒ 不在分支内`).toBeGreaterThan(branch)
  }
  // 与"设 `data-theme`"那个 try **分开**（blob 读炸了不该把主题也带下水 ⇒ 两个 try）
  expect((HTML.match(/try \{/g) ?? []).length).toBeGreaterThanOrEqual(2)
})

test('⭐ R10⑤：盘上有 vars + 主题是 argus ⇒ **首帧**就是用户色（不是默认绿）', () => {
  localStorage.setItem('vigil.theme', 'argus')
  localStorage.setItem(ARGUS_VARS_KEY, argusVarsJson('#f2f2f2'))
  runPreflash()
  const root = document.documentElement
  expect(root.getAttribute('data-theme')).toBe('argus')
  // 逐键：12 个都要贴上（少一个 = 白名单把它筛掉了，或回读只贴了 `--v-fg`）
  for (const [k, v] of Object.entries(deriveArgusVars('#f2f2f2'))) {
    expect(root.style.getPropertyValue(k), `${k} 没被防闪脚本贴上`).toBe(v)
  }
  expect(root.style.getPropertyValue('--v-fg'), '首帧还是默认绿').not.toBe(ARGUS_DEFAULT)
})

test('⛔ R10⑥：那份 JSON 是 **localStorage 可控**的 ⇒ 白名单按形状**逐条丢弃**（不是"试试看"）', () => {
  localStorage.setItem('vigil.theme', 'argus')
  localStorage.setItem(
    ARGUS_VARS_KEY,
    JSON.stringify({
      '--v-fg': '#f2f2f2', // 合法 ⇒ 贴
      '--v-border': 'rgba(242, 242, 242, 0.45)', // 合法（第二种形状）⇒ 贴
      'background-color': 'red', // 键名不合形状 ⇒ 丢（这就是"任意行内样式注入"那个面）
      '--v-page-image': 'url(http://evil/x.png)', // 值不合形状 ⇒ 丢
      '--v-x': '#000000; background-image: url(http://evil)', // 值里夹带 ⇒ 丢
      '--v-y': 42, // 不是字符串 ⇒ 丢
    }),
  )
  runPreflash()
  const st = document.documentElement.style
  expect(st.getPropertyValue('--v-fg')).toBe('#f2f2f2')
  expect(st.getPropertyValue('--v-border')).toBe('rgba(242, 242, 242, 0.45)')
  for (const bad of ['background-color', '--v-page-image', '--v-x', '--v-y']) {
    expect(st.getPropertyValue(bad), `${bad} 不该被贴上`).toBe('')
  }
})

test('⛔ R10⑦：主题不是 argus / blob 是垃圾 ⇒ 防闪脚本**一个字都不许贴**，也不许抛', () => {
  // 别的主题下贴行内 ARGUS 变量 = §0.1 那个"行内顶掉别的主题"的缺陷换个入口重演
  localStorage.setItem('vigil.theme', 'material')
  localStorage.setItem(ARGUS_VARS_KEY, argusVarsJson('#f2f2f2'))
  runPreflash()
  expect(document.documentElement.style.getPropertyValue('--v-fg')).toBe('')
  expect(document.documentElement.getAttribute('data-theme')).toBe('material')
  // 主题是 argus、blob 是垃圾 ⇒ 保持 CSS 里的默认色 + **不抛**（防闪脚本不该是任何功能失败的原因）
  document.documentElement.removeAttribute('data-theme')
  localStorage.setItem('vigil.theme', 'argus')
  localStorage.setItem(ARGUS_VARS_KEY, '{not json')
  expect(() => runPreflash()).not.toThrow()
  expect(document.documentElement.style.getPropertyValue('--v-fg')).toBe('')
})

test('R10⑧：陈旧的 blob（少键 / 结构变了）不硬套：缺的键保持 CSS 默认，且下次 `applyArgusColor` 会整份刷新', () => {
  const full = deriveArgusVars(ARGUS_DEFAULT)
  localStorage.setItem('vigil.theme', 'argus')
  localStorage.setItem(
    ARGUS_VARS_KEY,
    JSON.stringify({
      '--v-fg': full['--v-fg'],
      '--v-fg-2': full['--v-fg-2'],
      '--v-fg-3': full['--v-fg-3'],
      '--v-old-token': full['--v-fg'], // 旧版本留下的键名（形状合法 ⇒ 会贴上）
    }),
  )
  runPreflash()
  const st = document.documentElement.style
  expect(st.getPropertyValue('--v-fg')).toBe(ARGUS_DEFAULT)
  expect(st.getPropertyValue('--v-border'), '旧 blob 里没有的键：保持 CSS 默认（不许瞎猜）').toBe('')
  // ⚠️ 已知且**可接受**的一条：白名单是**形状**白名单（不是 12 个键名的清单）⇒ 形状合法的
  // 陌生键名会被贴上。它改不动任何真实 token（没有消费者），而 `main.tsx` 的
  // `applyTheme(readTheme())` 在 App 启动时就调 `applyArgusColor` **重写整份 blob**
  // ⇒ 陈旧窗口只有"首帧到模块执行"这一段，这一句就是那个自愈的证据。
  expect(st.getPropertyValue('--v-old-token')).toBe(ARGUS_DEFAULT)
  applyArgusColor(readArgusColor())
  expect(JSON.parse(localStorage.getItem(ARGUS_VARS_KEY)!)).toEqual(full)
})
