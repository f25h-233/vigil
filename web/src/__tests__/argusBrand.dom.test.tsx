import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from '../App.tsx'
import ArgusBrand from '../components/ArgusBrand.tsx'
import ThemePicker from '../components/ThemePicker.tsx'
import { clearArgusColor } from '../argusColor.ts'
import { VIEW_STORAGE_KEY } from '../uiState.ts'

/**
 * `App` 会渲染 `Feed` ⇒ 一挂载就发请求。桩法与 `App.dom.test.tsx:8` 的
 * `installFetch` **同一套**，只多了三条**形状正确**的空壳（digests/groups/llm）：
 * 本文件要点 `[3]日报` / `[4]配置`——那里若拿到 `{}`，组件会读到 `undefined`
 * 再 `.map`/取字段，**报错与被测行为毫无关系**（本仓「桩的契约要对」那条老账）。
 */
function installFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
      if (url.startsWith('/api/undo')) return ok({ undone: false })
      if (url.startsWith('/api/categories/detailed')) return ok({ categories: [] })
      if (url.startsWith('/api/categories')) return ok({ categories: [] })
      if (url.startsWith('/api/digests')) return ok({ digests: [] })
      if (url.startsWith('/api/groups')) return ok({ groups: [], available: true })
      if (url.startsWith('/api/llm')) return ok({})
      if (url.startsWith('/api/persons')) return ok({ persons: [] })
      if (url.startsWith('/api/items')) return ok({ items: [], total: 0, limit: 50, offset: 0 })
      return ok({})
    }),
  )
}

// ⚠️ `vigil.theme` 在盘上会**真的**被 `applyTheme` 写（App 的 `pickTheme` 走它）
// ⇒ 逐条清干净，否则下一条是"从上一个用例留下的主题开跑"（M6 #27 的同族形态）。
// ⚠️ 行内变量也清：ARGUS 的头部用例会经 `applyTheme('argus')` 往 `:root` 上贴颜色。
afterEach(() => {
  localStorage.clear()
  clearArgusColor()
  document.documentElement.removeAttribute('data-theme')
  vi.unstubAllGlobals()
})

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

test('阴性对照：徽记的 `stroke` 不是"恰好没写"——根元素**显式**用它，否则上一条可以靠空 svg 混过去', () => {
  // ⚠️ 上一条是**全称否定**（"没有任何字面色值"），而空 svg / 不画线的 svg 也满足它
  // ⇒ 没有这一条，把 `stroke="currentColor"` 删掉（或整个 svg 删空）照样全绿，
  // 而屏幕上的徽记**是一条都看不见的空白**。这是本仓「全称否定必须有存在性对照」的老账。
  const { container } = render(<ArgusBrand />)
  const svg = container.querySelector('svg')!
  expect(svg.getAttribute('stroke')).toBe('currentColor')
  // 眼睛矩阵是 2×2：四条圆的**外圈**（`r=3.1`/`r=2.6` 两组）各自至少一个
  expect(svg.querySelectorAll('circle').length).toBeGreaterThanOrEqual(4)
  expect(svg.querySelectorAll('path').length).toBeGreaterThanOrEqual(2)
})

/**
 * ⭐ 头部替换（计划 Task 2 Step 3）：`theme === 'argus'` ⇒ 换掉整个 header。
 *
 * ⚠️ 起渲染的方式照计划 Step 5 写死的那条：`localStorage.setItem('vigil.theme','argus')`
 * ——`App` 的 `useState(readTheme)` 是惰性初始化，挂载时读一次盘。
 */
test('ARGUS 头部：品牌区**整体取代**「🏮 VIGIL」+ `ARGUS:~$` 提示符', async () => {
  localStorage.setItem('vigil.theme', 'argus')
  installFetch()
  render(<App />)
  expect(screen.getByRole('img', { name: 'ARGUS 徽记' })).toBeTruthy()
  expect(screen.getByText('ARGUS')).toBeTruthy()
  expect(screen.getByText('睡亦警觉，眼观六路')).toBeTruthy()
  expect(screen.getByText('ARGUS:~$')).toBeTruthy()
  expect(screen.queryByText('🏮 VIGIL'), 'ARGUS 下旧品牌区必须整体让位').toBeNull()
  // ⚠️ `/color` 的输入行必须在**头部**就活着（它是本主题的命令入口，不是某个页面里的控件）
  expect(screen.getByLabelText('ARGUS 命令')).toBeTruthy()
})

test('ARGUS 头部：`[1]…[4]` 四个方括号导航都在，且**点它们真的切页**', async () => {
  localStorage.setItem('vigil.theme', 'argus')
  installFetch()
  render(<App />)
  for (const label of ['[1]信息流', '[2]类目', '[3]日报', '[4]配置']) {
    expect(screen.getByText(label), `少了 ${label}`).toBeTruthy()
  }
  // ⚠️ 判据用**落盘的 tab**（`writeView` 是 App 的既有出口）而不是"某个按钮多了个类名"：
  // 前者是"页面真的换了"的机械证据，后者只说明"样式变了"。
  const tab = () => JSON.parse(localStorage.getItem(VIEW_STORAGE_KEY) ?? '{}').tab
  await userEvent.click(screen.getByText('[2]类目'))
  await waitFor(() => expect(tab()).toBe('cats'))
  await userEvent.click(screen.getByText('[3]日报'))
  await waitFor(() => expect(tab()).toBe('digests'))
  await userEvent.click(screen.getByText('[4]配置'))
  await waitFor(() => expect(tab()).toBe('settings'))
  await userEvent.click(screen.getByText('[1]信息流'))
  await waitFor(() => expect(tab()).toBe('feed'))
})

test('阴性对照：非 ARGUS 主题下**不许**出现品牌区（它是这套主题的身份，其余五套保持「🏮 VIGIL」）', () => {
  installFetch() // 盘上没写主题 ⇒ `readTheme()` 回落 'default'
  render(<App />)
  expect(screen.queryByRole('img', { name: 'ARGUS 徽记' })).toBeNull()
  expect(screen.queryByText('睡亦警觉，眼观六路')).toBeNull()
  expect(screen.queryByText('ARGUS:~$')).toBeNull()
  expect(screen.getByText('🏮 VIGIL')).toBeTruthy()
  // 默认主题的导航是**没有方括号**的（两套头部不是"同一套加了个括号"）
  expect(screen.getByText('信息流')).toBeTruthy()
  expect(screen.queryByText('[1]信息流')).toBeNull()
})

test('`undoMsg` 在 ARGUS 头部里也有落点（终端风的一行小字）——功能不许少', async () => {
  localStorage.setItem('vigil.theme', 'argus')
  installFetch()
  render(<App />)
  await userEvent.click(screen.getByText('↶undo'))
  expect(await screen.findByText('没有可撤销的操作')).toBeTruthy()
})

/**
 * ⭐ Task 3 的钩子（本任务只**加钩子不加行为**）。
 *
 * ⚠️ 这条判据存在的理由：`data-theme-picker` 是**给别的任务用的接口**——
 * 没有测试钉着，它在任何一次"顺手清理 className/属性"里都会静默消失，
 * 而发现它的时刻是 T8-3 的渲染脚本里（那时候翻回来找，成本高得多）。
 * ⚠️ 顺带钉住"**没加行为**"：菜单照旧六项、照旧选得中。
 */
test('ThemePicker 的菜单容器带 `data-theme-picker` 钩子，且行为一字未改', async () => {
  const onChange = vi.fn()
  render(<ThemePicker value="argus" onChange={onChange} />)
  expect(document.querySelector('[data-theme-picker]'), '菜单没开时不该有这个节点').toBeNull()

  await userEvent.click(screen.getByRole('button', { name: '切换主题' }))
  const menu = document.querySelector('[data-theme-picker]')
  expect(menu, '菜单开着却找不到 data-theme-picker 钩子').toBeTruthy()
  expect(menu!.querySelectorAll('[role="menuitemradio"]')).toHaveLength(6)

  await userEvent.click(screen.getByRole('menuitemradio', { name: '毛玻璃' }))
  expect(onChange).toHaveBeenCalledWith('glass')
})
