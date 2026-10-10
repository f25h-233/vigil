import { afterEach, expect, test, vi } from 'vitest'
import {
  _resetForTests,
  isOnline,
  noteFetchResult,
  subscribeConnectivity,
} from '../connectivity.ts'

afterEach(() => {
  _resetForTests()
  vi.unstubAllGlobals()
})

test('初值取自 navigator.onLine', () => {
  _resetForTests()
  // jsdom 里 navigator.onLine 默认为 true
  expect(isOnline()).toBe(true)
})

test('⚠️ 请求失败 ⇒ 判定为不可用（不能只信 navigator.onLine）', () => {
  // 这是 Review Focus #1 的落点：本机实测过"Tailscale 转发活着、后端没起 = 502"，
  // 而 navigator.onLine 那一刻**是 true**。只看事件的实现会在本条上红。
  // ⚠️ 变异反证：把 noteFetchResult 改成空函数 ⇒ 本条必红。
  noteFetchResult(false)
  expect(isOnline()).toBe(false)
})

test('请求成功 ⇒ 回到可用', () => {
  noteFetchResult(false)
  noteFetchResult(true)
  expect(isOnline()).toBe(true)
})

test('订阅：状态变化时被通知，且只通知一次', () => {
  const fn = vi.fn()
  const off = subscribeConnectivity(fn)
  noteFetchResult(false)
  expect(fn).toHaveBeenCalledTimes(1)
  noteFetchResult(false) // 同值不变 ⇒ 不再通知
  expect(fn).toHaveBeenCalledTimes(1)
  off()
  noteFetchResult(true)
  expect(fn).toHaveBeenCalledTimes(1) // 已退订
})

test('浏览器 offline 事件 ⇒ 不可用；online 事件 ⇒ 可用', () => {
  window.dispatchEvent(new Event('offline'))
  expect(isOnline()).toBe(false)
  window.dispatchEvent(new Event('online'))
  expect(isOnline()).toBe(true)
})
