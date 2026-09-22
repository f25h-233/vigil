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
})
