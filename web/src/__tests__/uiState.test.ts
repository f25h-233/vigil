import { afterEach, expect, test } from 'vitest'
import { DEFAULT_VIEW, VIEW_STORAGE_KEY, readView, writeView } from '../uiState.ts'

afterEach(() => localStorage.clear())

test('没存过 ⇒ 默认', () => {
  expect(readView()).toEqual(DEFAULT_VIEW)
})

test('存取一个完整视图', () => {
  writeView({ tab: 'digests', kinds: ['notice', 'life'], persons: [12345] })
  expect(readView()).toEqual({ tab: 'digests', kinds: ['notice', 'life'], persons: [12345] })
})

test('⚠️ 逐字段校验：坏的字段回落默认，好的字段保留', () => {
  // 一个坏字段（旧版本留下的 tab 名之类）不该毁掉整份记忆——
  // 那会让"记得我选的类目"这种小事变成"每次刷新都从头来"。
  localStorage.setItem(
    VIEW_STORAGE_KEY,
    JSON.stringify({ tab: 'gallery', kinds: ['notice', 42], persons: [1, -3, 'x'] }),
  )
  expect(readView()).toEqual({ tab: 'feed', kinds: ['notice'], persons: [1] })
})

test('垃圾 JSON / 非对象 ⇒ 默认，且不抛', () => {
  localStorage.setItem(VIEW_STORAGE_KEY, '{not json')
  expect(readView()).toEqual(DEFAULT_VIEW)
  localStorage.setItem(VIEW_STORAGE_KEY, '42')
  expect(readView()).toEqual(DEFAULT_VIEW)
})

test('kinds 去重、persons 去重', () => {
  localStorage.setItem(
    VIEW_STORAGE_KEY,
    JSON.stringify({ tab: 'feed', kinds: ['a', 'a'], persons: [7, 7, 8] }),
  )
  expect(readView().kinds).toEqual(['a'])
  expect(readView().persons).toEqual([7, 8])
})
