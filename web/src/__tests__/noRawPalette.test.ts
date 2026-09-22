import { expect, test } from 'vitest'

/**
 * ⚠️ Node 内置模块在本仓**必须**用「具名变量说明符」动态 import——两条实测出来的墙
 * （T1 报告 §4 偏差 4/5；M7 勘误 E9）：
 *   ① 本仓没有 `@types/node`，而 `tsc -b`（`npm run build` 会跑）**会编译测试文件**
 *      ⇒ `import { readFileSync } from 'node:fs'` 直接 TS2307 让构建失败；
 *   ② `new URL('..', import.meta.url)` 第二个参数写成**字面量**时，Vite 的
 *      asset-import-meta-url 变换会接管，基准被换成 jsdom 的 document base
 *      （实测 → `http://localhost:3000/index.html`）；先取 `const HERE = import.meta.url` 再传就正常。
 * 故意**不用** `// @ts-expect-error`：将来真装了 @types/node 会变成 TS2578，又把构建搞坏一次。
 */
const NODE_FS = 'node:' + 'fs'
const NODE_PATH = 'node:' + 'path'
const NODE_URL = 'node:' + 'url'
const HERE = import.meta.url

const { readdirSync, readFileSync } = (await import(/* @vite-ignore */ NODE_FS)) as {
  readdirSync: (p: string, o: { withFileTypes: true }) => { name: string; isDirectory(): boolean }[]
  readFileSync: (p: string, enc: string) => string
}
const { join, relative } = (await import(/* @vite-ignore */ NODE_PATH)) as {
  join: (...p: string[]) => string
  relative: (a: string, b: string) => string
}
const { fileURLToPath } = (await import(/* @vite-ignore */ NODE_URL)) as {
  fileURLToPath: (u: URL) => string
}

/**
 * ⭐ 出口判据 4（浅色主题下无「深色残留」）的**入口守卫**：
 * 只要还有一处写死的 Tailwind 调色板类名，那处就在浅色主题里保持深色
 * ——而它可能藏在 1,023 行的 Settings.tsx 里，肉眼翻不到。
 *
 * ⚠️ 它**只证明"没有残留"，证明不了"映射对不对"**。映射的正确性由
 * `web/tools/retheme_m7.py` 的映射表（可审查）+ T3 的主题值 + 冒烟截图承担。
 */
const SRC = fileURLToPath(new URL('..', HERE))

// 与 codemod 的 --check 用**同一条**正则（两份副本；漂移由本测试兜底：它说了算）
const PALETTE =
  /\b(?:bg|text|border|ring|divide|from|to|via|placeholder|fill|stroke|shadow|outline|decoration|accent|caret)-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|white|black)(?:-\d{2,3})?(?:\/\d{1,3})?\b/g

// 语义 token 上的透明度修饰符：**禁用**（见 index.css 顶部 E3 的实测）
const TOKEN_WITH_ALPHA =
  /\b(?:bg|text|border|ring|from|to|via|placeholder|fill|stroke|decoration|accent|caret)-vigil-[a-z0-9-]+\/\d{1,3}\b/g

// 本文件自己带着这两条正则的字面量，必须排除（否则自己匹配自己）
const ALLOW = new Set(['__tests__/noRawPalette.test.ts'])

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name)
    if (e.isDirectory()) return walk(p)
    return /\.(ts|tsx)$/.test(e.name) ? [p] : []
  })
}

function scan(re: RegExp): string[] {
  const hits: string[] = []
  for (const f of walk(SRC)) {
    const rel = relative(SRC, f).replace(/\\/g, '/')
    if (ALLOW.has(rel)) continue
    const text = readFileSync(f, 'utf8')
    for (const m of text.matchAll(re)) {
      const line = text.slice(0, m.index).split('\n').length
      hits.push(`${rel}:${line}  ${m[0]}`)
    }
  }
  return hits
}

test('src 里不许再出现裸调色板类名（227 → 0）', () => {
  const hits = scan(PALETTE)
  expect(hits, `还有 ${hits.length} 处裸调色板类名：\n${hits.join('\n')}`).toEqual([])
})

test('语义 token 不许带透明度修饰符（E3：构建期会烘死一个 fallback）', () => {
  const hits = scan(TOKEN_WITH_ALPHA)
  expect(hits, `这些地方给 token 加了透明度：\n${hits.join('\n')}`).toEqual([])
})

/**
 * ⭐ P0 守卫（M7 主题修订轮）：**「软底文字」这个 token 的合法语境只有一个**。
 *
 * `text-vigil-accent-text` 是"坐在 `bg-vigil-accent-soft` 上的字"——白卡片上的
 * 强调色**文字动作**该用 `text-vigil-accent`（`--v-accent` 本身就是强调色）。
 *
 * ⚠️ 它存在的理由 = **实际发生过一次**（`Settings.tsx:196/201`，本轮修订的 P0）：
 * 那两个按钮写的是 `text-vigil-accent-text` 而**没有**软底，落在白卡上；
 * 粗野主义的 `--v-accent-text` 是 `#ffffff` ⇒ **白字白底，按钮上的字看不见**。
 * 而它当时**零测试信号**——`themePalette.test.ts` 的对比度判据算的是
 * `--v-accent-text` **配** `--v-accent-soft` 那一面（这是唯一有意义的配对），
 * 所以这个漏网的调用点谁都不红；截图那一轮又只照了信息流，没照到这两个按钮。
 * ⇒ 判据得落在**"它有没有软底"**这件事上，而那件事只有**看源码**才知道。
 *
 * ⚠️ 它**只证明"没有裸用的 accent-text"，证明不了"长得对"**：`bg-vigil-accent-soft`
 * 是不是被 `disabled:opacity-40`、别的类名或父元素盖掉，静态扫描看不见——那部分
 * 归对比度判据与截图。
 *
 * ⚠️ 判据用**字符串字面量**（`'…'` / `"…"` / `` `…` ``）而不是"同一行"：
 * 该 token 的 12 个合法落点里有一半是三元里的 `'bg-vigil-accent-soft text-vigil-accent-text'`，
 * 按行判会**恒真**（同一行里当然同时有两个名字）；按"同一个类名字符串"判才是
 * 「这两个类名会一起挂到同一个元素上」的那个证据。注释里的提及一律跳过
 * （本文件与 `Settings.tsx` 的说明性注释都写着这两个名字）。
 */
const ACCENT_TEXT = 'text-vigil-accent-text'
const ACCENT_SOFT_BG = 'bg-vigil-accent-soft'

type Span = [number, number]

/** 扫出注释区间与字符串字面量区间（都记在**原文本**的坐标上，行号才算得对）。 */
function spans(text: string): { comments: Span[]; strings: Span[] } {
  const comments: Span[] = []
  const strings: Span[] = []
  let i = 0
  while (i < text.length) {
    const c = text[i]
    if (c === '/' && text[i + 1] === '/') {
      const e = text.indexOf('\n', i)
      comments.push([i, e < 0 ? text.length : e])
      i = e < 0 ? text.length : e
      continue
    }
    if (c === '/' && text[i + 1] === '*') {
      const e = text.indexOf('*/', i + 2)
      comments.push([i, e < 0 ? text.length : e + 2])
      i = e < 0 ? text.length : e + 2
      continue
    }
    if (c === "'" || c === '"' || c === '`') {
      let j = i + 1
      while (j < text.length) {
        if (text[j] === '\\') {
          j += 2
          continue
        }
        if (text[j] === c) break
        j++
      }
      strings.push([i, j])
      i = j + 1
      continue
    }
    i++
  }
  return { comments, strings }
}

test(`${ACCENT_TEXT} 只许出现在同时含 ${ACCENT_SOFT_BG} 的字符串里（P0：白字白底那个缺陷）`, () => {
  const hits: string[] = []
  for (const f of walk(SRC)) {
    const rel = relative(SRC, f).replace(/\\/g, '/')
    if (ALLOW.has(rel)) continue
    const text = readFileSync(f, 'utf8')
    const { comments, strings } = spans(text)
    for (const m of text.matchAll(new RegExp(ACCENT_TEXT, 'g'))) {
      const at = m.index
      if (comments.some(([a, b]) => at >= a && at < b)) continue // 注释里点名这个 token 是允许的
      const line = text.slice(0, at).split('\n').length
      const lit = strings.find(([a, b]) => at > a && at < b)
      const where = lit === undefined ? '(不在任何字符串字面量里)' : text.slice(lit[0], lit[1] + 1)
      if (!where.includes(ACCENT_SOFT_BG)) hits.push(`${rel}:${line}  ${m[0]}  ← 所在字符串 ${where}`)
    }
  }
  expect(
    hits,
    `这些地方用了"软底文字"却没有软底（粗野主义下就是白字白底、看不见）：\n${hits.join('\n')}`,
  ).toEqual([])
})
