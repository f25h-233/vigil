import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import ThemePicker from '../components/ThemePicker.tsx'

afterEach(() => document.documentElement.removeAttribute('data-theme'))

test('默认关闭；点 🎨 展开五套，当前那套被标为选中', async () => {
  render(<ThemePicker value="material" onChange={() => {}} />)
  expect(screen.queryByRole('menu')).toBeNull()
  await userEvent.click(screen.getByRole('button', { name: '切换主题' }))
  expect(screen.getAllByRole('menuitemradio')).toHaveLength(5)
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
