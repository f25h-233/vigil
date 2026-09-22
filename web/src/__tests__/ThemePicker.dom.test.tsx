import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from '../App.tsx'
import ThemePicker from '../components/ThemePicker.tsx'

// ⚠️ 最后那条用例（走真实 `App` 接线的）会真的给 `<html>` 挂上 `data-theme`，
// 并在盘上留下 `vigil.theme` ——**这条负责清**（在这条用例出现之前，
// 它一直没有对象可清）。`theme.test.ts:27` 的 afterEach 清的是同一对；
// `vi.unstubAllGlobals` 撤掉那条用例打的 fetch 桩。
afterEach(() => {
  document.documentElement.removeAttribute('data-theme')
  localStorage.removeItem('vigil.theme')
  vi.unstubAllGlobals()
})

/**
 * `App` 会渲染 `Feed` ⇒ 一挂载就发请求。桩法与 `App.dom.test.tsx:8` 的
 * `installFetch` **同一套**（categories / persons / items / undo 各回一个空壳）。
 * 这里不记调用流水（这条用例只关心主题的两个落点），所以也不看 `init?.method`。
 */
function installFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
      if (url.startsWith('/api/undo')) return ok({ undone: false })
      if (url.startsWith('/api/categories')) return ok({ categories: [] })
      if (url.startsWith('/api/persons')) return ok({ persons: [] })
      if (url.startsWith('/api/items')) return ok({ items: [], total: 0, limit: 50, offset: 0 })
      return ok({})
    }),
  )
}

test('默认关闭；点 🎨 展开六套，当前那套被标为选中', async () => {
  render(<ThemePicker value="material" onChange={() => {}} />)
  expect(screen.queryByRole('menu')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: '切换主题' }))
  // ⭐ T8-1：5 → **6**（Project ARGUS）。与 `theme.test.ts` 那条同性质：**设计变更**，
  // 不是"把断言放宽到能过"——菜单项直接来自 `THEMES`，多一套就多一项，这条数字就是
  // "菜单渲染了几项"的唯一判据（漏渲染某一套时它必红）。
  expect(screen.getAllByRole('menuitemradio')).toHaveLength(6)
  // ⚠️ 本仓**没有** `@testing-library/jest-dom`（devDependencies 里没有、test-setup 也没引）
  // ⇒ `toHaveAttribute` 会以「Invalid Chai property」失败——那条失败与被测行为无关。
  // 按本仓既有写法（theme.test.ts:69/71/86）用 `getAttribute(...) + toBe(...)`，
  // 断言的**语义一字不改**（aria-checked 恰好是 'true' / 'false'）。
  expect(
    screen.getByRole('menuitemradio', { name: 'Material Design' }).getAttribute('aria-checked'),
  ).toBe('true')
  expect(
    screen.getByRole('menuitemradio', { name: '毛玻璃' }).getAttribute('aria-checked'),
  ).toBe('false')
})

test('选一套 ⇒ 回调收到它、菜单收起', async () => {
  const onChange = vi.fn()
  render(<ThemePicker value="default" onChange={onChange} />)
  await userEvent.click(screen.getByRole('button', { name: '切换主题' }))
  await userEvent.click(screen.getByRole('menuitemradio', { name: '蒸汽波' }))
  expect(onChange).toHaveBeenCalledWith('vaporwave')
  expect(screen.queryByRole('menu')).toBeNull()
})

test('点外面 / 按 Esc 都能关（没有这两条，手机上关不掉）', async () => {
  render(<ThemePicker value="default" onChange={() => {}} />)
  await userEvent.click(screen.getByRole('button', { name: '切换主题' }))
  await userEvent.click(document.body)
  expect(screen.queryByRole('menu')).toBeNull()

  await userEvent.click(screen.getByRole('button', { name: '切换主题' }))
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('menu')).toBeNull()
})

/**
 * ⭐ 这条守的是**里程碑判据 2**：「切换后刷新仍在」。
 *
 * ⚠️ 为什么必须走**真实 `App` 接线**：上面三条都只验 `onChange` 回调
 * （`render(<ThemePicker onChange={...} />)`），于是把 `App.tsx` 里的
 * `applyTheme(id)` 整个删掉、或把 `onChange` 接成 `() => {}`，
 * 那三条**照样全绿**——"刷新还在不在"没有任何一条在验。
 * 落盘与挂属性都发生在 App 的接线里（`pickTheme`），所以守卫得从 App 的门口进去。
 *
 * ⚠️ 变异反证：把 `App.tsx` 的 `pickTheme` 改成只有 `setTheme(id)`
 * （去掉 `applyTheme(id)`）⇒ 本条**必红**（两个断言各红一条）。
 *
 * ⚠️ 这里断言的是**字面量** `'vigil.theme'`，不是 `THEME_STORAGE_KEY`：
 * 判据 2 的另一半是 `index.html:25` 那段防闪脚本里的
 * `localStorage.getItem('vigil.theme')`——它读的就是这个字面量。
 * 用常量的话，日后改一次键名本条仍然绿，而防闪脚本会静默失效。
 */
test('切一套 ⇒ `data-theme` 挂上、盘上也写下（走真实 App 接线；守判据 2）', async () => {
  installFetch()
  render(<App />)
  await userEvent.click(screen.getByRole('button', { name: '切换主题' }))
  await userEvent.click(screen.getByRole('menuitemradio', { name: '蒸汽波' }))

  // 两处都得断言：只验一处就守不住判据 2 的另一半——
  // `data-theme` 只活到这次页面为止，「刷新后仍在」靠的是盘上那份。
  expect(document.documentElement.getAttribute('data-theme')).toBe('vaporwave')
  expect(localStorage.getItem('vigil.theme')).toBe('vaporwave')
})
