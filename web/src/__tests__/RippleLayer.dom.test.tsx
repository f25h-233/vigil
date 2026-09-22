import type { CSSProperties } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import RippleLayer from '../components/RippleLayer.tsx'

/**
 * ⭐ 这组用例守的是"动效的三个边界"，而它们每一条都**必须能红**：
 *   ① 该有涟漪时**有**（否则等于没做）；
 *   ② 该没事时**一个都没有**（主题不要 / 系统关了动效 / 右键 / disabled）；
 *   ③ jsdom 没有 Web Animations API 的现实下**不许抛**（否则挂载即崩，整站白屏）。
 *
 * ⚠️ jsdom 不加载 CSS ⇒ `getComputedStyle(el).getPropertyValue('--v-ripple')` 是空串。
 * 所以"该有涟漪"那条要在按钮上**内联**写这个自定义属性（计划期实测：jsdom 能读到内联自定义属性）。
 *
 * ⚠️ 替身必须**可还原**：直接给 `Element.prototype.animate` 赋值不是 `vi.spyOn` 的产物，
 * `vi.restoreAllMocks()` 收不回来 ⇒ 后面的"③ 没有 animate"那条会因为前一条留下的替身而假绿。
 * 所以这里显式存原值 + 显式还原（这就是"空守卫的第 8 格：反证的前置没上场"的预防）。
 *
 * ═══ 实施期（T7）对计划原稿的三处**按实际修正**（每处都有实测依据，见各自注释）═══
 *   A. ① 的 `finished` 从 `Promise.resolve()` 换成**显式可兑现的 deferred**；
 *   B. ② 的 reduced-motion 从 `vi.spyOn(window,'matchMedia')` 换成显式赋值 + 显式还原；
 *   C. ③ 去掉 `.resolves.toBeUndefined()`（**直接 API 的契约不是它**）。
 *   ⛔ 三处都**只改"怎么问"**，没有删掉任何一条断言所守的性质。
 */

/** A. ⚠️ `finished: Promise.resolve()` 会**在微任务里立刻兑现**，而 `await userEvent.pointer(...)`
 *  本身就要等好几个微任务 ⇒ `done()` 早在断言之前就跑完了：实测 ① 在 `expect(ripples()).toBe(1)`
 *  上红（`expected +0 to be 1`），而 `animate` 明明被调过一次。
 *  ⇒ 改成**显式兑现**：让"插进去了"与"动画结束自清"成为两个可分别观察的相位，
 *  而不是一场微任务竞速。这比原稿**更强**（原来那条断言其实测不到"插入"这个瞬间）。 */
let restoreAnimate: (() => void) | null = null
let resolveFinished: (() => void) | null = null

function stubAnimate() {
  const original = Element.prototype.animate
  const spy = vi.fn(() => ({
    finished: new Promise<void>((res) => {
      resolveFinished = () => res()
    }),
  }))
  Element.prototype.animate = spy as unknown as Element['animate']
  restoreAnimate = () => {
    if (original === undefined) {
      delete (Element.prototype as { animate?: unknown }).animate
    } else {
      Element.prototype.animate = original
    }
  }
  return spy
}

/** B. ⚠️ **本机 jsdom（30.1.0）整个 lib 里没有一处 `matchMedia`**（实测：
 *  `typeof window.matchMedia === 'undefined'`，且 `grep -r matchMedia node_modules/jsdom/lib/` 为空）
 *  ⇒ `vi.spyOn(window,'matchMedia')` 抛 `can only spy on a function`。
 *  处置沿用 `stubAnimate` 的同一条纪律：**显式存原值 + 显式还原**（没有原值时删回去）。 */
let restoreMatchMedia: (() => void) | null = null

function stubReducedMotion() {
  const original = window.matchMedia
  window.matchMedia = ((query: string) => ({
    matches: true,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
  restoreMatchMedia = () => {
    if (original === undefined) {
      delete (window as { matchMedia?: unknown }).matchMedia
    } else {
      window.matchMedia = original
    }
  }
}

function rippleBtn(props: { ripple?: string; disabled?: boolean } = {}) {
  return (
    <button
      disabled={props.disabled}
      style={props.ripple === undefined ? {} : ({ '--v-ripple': props.ripple } as CSSProperties)}
    >
      按我
    </button>
  )
}

const ripples = () => document.querySelectorAll('.vigil-ripple').length

afterEach(() => {
  restoreAnimate?.()
  restoreAnimate = null
  resolveFinished = null
  restoreMatchMedia?.()
  restoreMatchMedia = null
  vi.restoreAllMocks()
})

test('① 有涟漪色的主题：按下插一个，动画结束自己移除', async () => {
  const animate = stubAnimate()
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)' })}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(animate).toHaveBeenCalledTimes(1)
  expect(ripples()).toBe(1)
  expect(resolveFinished, 'animate 调过了，却没拿到 finished 的兑现句柄').toBeTruthy()
  resolveFinished!() // 兑现动画 ⇒ 自清
  await vi.waitFor(() => expect(ripples()).toBe(0)) // finished 兑现后自清
})

test('② 这套主题不要涟漪（--v-ripple 缺失 ⇒ 读到空串）⇒ 一个都不插', async () => {
  const animate = stubAnimate()
  render(
    <>
      <RippleLayer />
      {rippleBtn()}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(animate).not.toHaveBeenCalled()
  expect(ripples()).toBe(0)
})

test('② 显式 transparent ⇒ 也不插（"关掉"要有两种写法都行）', async () => {
  stubAnimate()
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'transparent' })}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(ripples()).toBe(0)
})

test('② 系统里关了动效（prefers-reduced-motion: reduce）⇒ 不插', async () => {
  stubAnimate()
  stubReducedMotion()
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)' })}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(ripples()).toBe(0)
})

test('② disabled 的按钮 ⇒ 不插（按不动的控件不该有反馈）', async () => {
  stubAnimate()
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)', disabled: true })}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(ripples()).toBe(0)
})

test('③ jsdom 的真实情况（没有 animate）⇒ 不抛、也不留残渣', async () => {
  // ⚠️ 这条**故意不打桩**（jsdom 的 Element.prototype.animate 不存在）；靠 afterEach 的还原保证前置干净
  expect(typeof Element.prototype.animate).toBe('undefined')
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)' })}
    </>,
  )
  // C. ⚠️ 这里**不能**写 `.resolves.toBeUndefined()`：`userEvent.pointer` 走的是**直接 API**
  //（`setup/directApi.js`：`return api.pointer(input).then(()=>system)`）⇒ 它兑现的是
  // **System 实例**，不是 `undefined`（实测红：`expected System{…} to be undefined`）。
  // "不抛"这个性质由 `await` 本身承担：抛了这条就红。**其余断言一字未动。**
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(ripples()).toBe(0)
})
