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
