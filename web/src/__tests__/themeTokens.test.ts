import { describe, expect, test } from 'vitest'
import { THEMES } from '../theme.ts'

// ⚠️ `node:fs` 的具名导入会让 `tsc -b` 以 TS2307 失败（本仓没有 `@types/node`，
// 而 package.json 不在 T1 的 Interfaces 里）——理由与替代方案的实测对照写在
// `theme.test.ts` 顶部同名注释里（同一处坑，两处都要绕）。
const NODE_FS = 'node:' + 'fs'
const { readFileSync } = (await import(/* @vite-ignore */ NODE_FS)) as {
  readFileSync: (p: URL, enc: string) => string
}

/**
 * ⭐ 主题层的**结构性守卫**。它守两条只有机械检查才抓得住的东西：
 *   ① **parity**：每套主题必须给**全部** token 一份值。缺一个 ⇒ CSS 继承
 *      `:root` 那一份（默认主题的值）⇒ **浅色主题里冒出深色残留**
 *      （出口判据 4 的真实形态），而肉眼要翻到那一页才看得见。
 *   ② **引用完整性**：`@theme inline` / `body{}` 里引用的 `--v-*` 必须存在。
 *      拼错的 token 名 **Tailwind 不会报错**，它只是不生成那个类 ⇒ 元素没样式、
 *      控制台一片安静。
 *
 * ⚠️ 解析用「选择器 + 花括号体」的粗切（本文件的 CSS 值都**不含嵌套花括号**；
 * 哪天有人写 `@media` 嵌进来，这条解析会先红——那是好事，它逼你换解析器）。
 * ⚠️ **必须先剥注释再解析**：本文件顶部那段说明里就含**示例 CSS**
 * （`{…}` 与 `var(--v-probe-radius)`），不剥的话它会被当成一个选择器块，
 * 而那个 `var(--v-probe-radius)` 会进"被引用但没定义"的名单 ⇒ **假红**。
 */

// ⚠️ 必须先把 `import.meta.url` 收进一个变量再用（实测，2026-09-22）：
// `new URL('…', import.meta.url)` 这种**第二个参数是字面量**的写法会被 Vite 的
// asset-import-meta-url 变换接管，解析基准变成 jsdom 的 document base
// （`http://localhost:3000/index.css`），而 `readFileSync` 只认 `file:`
// ⇒ 报 `ERR_INVALID_URL_SCHEME: The URL must be of scheme file`。
// 理由与实测对照写在 `theme.test.ts` 同名注释里（同一处坑）。
const HERE = import.meta.url

export const CSS = readFileSync(new URL('../index.css', HERE), 'utf8').replace(
  /\/\*[\s\S]*?\*\//g,
  '',
)

export type Block = { selector: string; body: string }

export function blocks(css: string): Block[] {
  return [...css.matchAll(/([^{}]*)\{([^{}]*)\}/g)].map((m) => ({
    selector: m[1].trim(),
    body: m[2],
  }))
}

function tokenNames(body: string): string[] {
  return [...body.matchAll(/(--v-[a-z0-9-]+)\s*:/g)].map((m) => m[1]).sort()
}

const ALL = blocks(CSS)
const root = ALL.find((b) => b.selector.includes("[data-theme='default']"))

/**
 * 取某套主题的某个 `--v-*` 的**值**（不是名字）。
 * ⚠️ 修复轮 F1 的 brief 假定这个助手**已经存在**，实际文件里没有（只有 `blocks()` /
 * `tokenNames()`，两个都只处理"名字"）⇒ 这里新建一个，解析沿用同一套「选择器 + 花括号体」
 * 粗切，所以它继承同一处已知缺口（嵌套块，见文件尾的 F4 守卫与报告 concerns）。
 * `'default'` 落到 `:root, [data-theme='default']` 那一块（默认主题与 `:root` 共用一块）。
 */
function v(themeId: string, name: string): string {
  const block = ALL.find((b) =>
    themeId === 'default'
      ? b.selector.includes("[data-theme='default']")
      : b.selector === `[data-theme='${themeId}']`,
  )
  expect(block, `index.css 里找不到 ${themeId} 的 token 块`).toBeTruthy()
  const m = block!.body.match(new RegExp(`${name}\\s*:\\s*([^;]+)`))
  expect(m, `${themeId} 块里找不到 ${name}`).toBeTruthy()
  return m![1].trim()
}

describe('token 层', () => {
  test(':root 与默认主题共用一块（否则"默认值"有两份）', () => {
    expect(root).toBeTruthy()
    expect(root!.selector).toContain(':root')
    expect(tokenNames(root!.body).length).toBeGreaterThanOrEqual(30)
  })

  // ⚠️ 只比**另外四套**（偏差 2，见 task-1-report.md）：默认那一份与 `:root`
  // **共用同一块**（选择器是 `:root, [data-theme='default']`）——Interfaces 写的是
  // 「`:root, [data-theme='default']` 与 **4 个** `[data-theme='x']` 块」，
  // 本文件第一条用例也断言了「共用一块」。若照原稿写 `for (const t of THEMES)`，
  // `t.id === 'default'` 那一轮要求存在一个选择器**恰好等于** `[data-theme='default']`
  // 的块 ⇒ 与"共用一块"直接冲突，**在本设计下永远不可能通过**；
  // 而且即便能通过，那也只是拿默认块和自己比，恒真、没有信息量。
  for (const t of THEMES.filter((x) => x.id !== 'default')) {
    test(`[data-theme='${t.id}'] 的 token 集合与默认**逐字相等**`, () => {
      const b = ALL.find((x) => x.selector === `[data-theme='${t.id}']`)
      expect(b, `index.css 缺 [data-theme='${t.id}'] 块`).toBeTruthy()
      expect(tokenNames(b!.body)).toEqual(tokenNames(root!.body))
    })
  }

  test('@theme inline 与 body 引用的每个 --v-* 都有定义', () => {
    const defined = new Set(tokenNames(root!.body))
    const referenced = [...CSS.matchAll(/var\(\s*(--v-[a-z0-9-]+)/g)].map((m) => m[1])
    expect(referenced.length).toBeGreaterThan(20)
    const missing = [...new Set(referenced)].filter((n) => !defined.has(n))
    expect(missing, `这些 token 被引用但没有定义：${missing.join(', ')}`).toEqual([])
  })

  // ⚠️ F1 的守卫**只守默认块**，而且**不守值**（parity 只比名字、不比值的同族缺口）：
  // 改默认块的字体栈不会有任何测试变红。它守的是"T1 的目标：默认主题 = 今天的基线"
  // 这件事的**唯一机械抓手**——一旦有人把 `system-ui` 挪到前面，基线就破了。
  test("默认主题的字体栈必须 'Segoe UI' 打头（M7 之前渲染拉丁文的就是它；改了=破基线）", () => {
    // 实测指纹：'AaBbGg123 !@#' 宽 —— "Segoe UI" 146.221 / Tailwind 旧栈 146.221（相同）
    // vs system-ui（本机→雅黑）158.857。数字见 T1 报告 §4 发现 B。
    expect(v('default', '--v-font-sans').startsWith("'Segoe UI'")).toBe(true)
  })
})

/**
 * 按**花括号层级**切规则：每条规则带上它**由外到内的祖先块**序列。
 * ⚠️ 为什么不能用 `blocks()` 那条 `/([^{}]*)\{([^{}]*)\}/`：它匹配不了嵌套块，
 * 遇到 `@layer base { … { … } }` 时会把**内层**规则当成一个**顶层**块（T1 已实测），
 * ⇒「这条规则在不在某个 `@layer base` 里」这个问题**根本问不出来**（不是答错，是问不出）。
 */
function rulesWithAncestors(css: string): { selector: string; ancestors: string[] }[] {
  const out: { selector: string; ancestors: string[] }[] = []
  const stack: string[] = []
  let buf = ''
  let quote: string | null = null
  for (let i = 0; i < css.length; i++) {
    const c = css[i]
    if (quote !== null) {
      buf += c
      if (c === quote && css[i - 1] !== '\\') quote = null
      continue
    }
    if (c === '"' || c === "'") {
      quote = c
      buf += c
      continue
    }
    if (c === '{') {
      stack.push(buf.trim().replace(/\s+/g, ' '))
      buf = ''
      continue
    }
    if (c === '}') {
      out.push({ selector: stack.pop()!, ancestors: [...stack] })
      buf = ''
      continue
    }
    buf += c
  }
  return out
}

/**
 * ⭐ F4 守卫。**它存在的原因 = reviewer 实测**：把 `button, input, textarea, select`
 * 外面那层 `@layer base` 去掉、规则一字不动 ⇒ **68/68 全绿 + build 成功**（0 条红）。
 * 而它的失败形态是本项目的"假绿家族"：那条规则一旦不属任何层，**未分层样式胜过一切
 * 分层样式** ⇒ 它压掉 utilities 层的 `text-*`，**所有按钮/输入框的字号偷偷跟着 UA 默认走**
 * （实测 8 个元素 12px → 16px、整页高度 1305 → 1287），而页面看着"只是有点怪"。
 * ⛔ 判据必须走**层级**：`CSS.includes('@layer base')` 之类的字符串包含会被注释或别的
 * `@layer` 满足，正是这里要挡的假绿。
 */
describe('表单控件规则的分层（F4 守卫）', () => {
  test('button,input,textarea,select 那条规则必须在 @layer base 之内（去掉层 = 0 条红）', () => {
    const WANT = ['button', 'input', 'select', 'textarea']
    const hits = rulesWithAncestors(CSS).filter((r) => {
      const parts = r.selector
        .split(',')
        .map((s) => s.trim())
        .sort()
      return parts.length === WANT.length && parts.every((p, i) => p === WANT[i])
    })
    expect(hits, 'index.css 里找不到 button,input,textarea,select 那条规则').toHaveLength(1)

    const rule = hits[0]
    const parent = rule.ancestors[rule.ancestors.length - 1] ?? '(未分层：没有任何外层块)'
    expect(
      parent,
      `这条规则直接待在 "${parent}" 里；未分层会压掉 utilities 层的 text-*`,
    ).toMatch(/^@layer\s+base\b/)
  })
})

/**
 * 结构维度的守卫：形状 / 字体 / 阴影 / 模糊 / 页面底图**也随主题走**。
 * 只换颜色的四套主题在这里会红——那正是这条断言存在的理由。
 *
 * ⚠️ brief（T3 Step 1）这段自带一个**内层** `const v = …`，它要求存在一个选择器
 * **恰好等于** `[data-theme='default']` 的块。**实测它解析不了 `'default'`**
 * （brief 原文照抄跑出来的红：「缺 [data-theme='default'] 块」，2026-09-22）：
 * 本设计里默认主题与 `:root` **共用一块**（选择器是 `:root,\n[data-theme='default']`，
 * 见文件首条用例），所以 `selector === "[data-theme='default']"` 恒为假。
 * ⇒ 这里**复用文件上方的模块级 `v()`**（它按 `includes` 找默认块，是内层版的严格超集），
 * 不留两份会漂移的取值助手。差异已写进 task-3-report.md 的偏差清单。
 */
test('结构维度每套主题各给一份，且与默认**不同**（否则"五套主题"只剩标签不同）', () => {
  expect(v('brutalism', '--v-radius-xl')).toBe('0px') // 方角是粗野主义的判据
  expect(v('brutalism', '--v-font-sans')).toContain('monospace')
  expect(v('brutalism', '--v-shadow-card')).not.toBe('none') // 硬阴影承担"厚边框"（E5）
  expect(v('glass', '--v-panel-blur')).not.toBe('0px')
  expect(v('glass', '--v-page-image')).toContain('gradient')
  expect(v('vaporwave', '--v-page-image')).toContain('gradient')
  expect(v('material', '--v-shadow-card')).not.toBe('none') // 抬升
  expect(v('default', '--v-shadow-card')).toBe('none') // 默认主题保持今天的观感
  expect(v('default', '--v-page-image')).toBe('none')
})
