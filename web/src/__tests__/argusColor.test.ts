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
