import type { CSSProperties } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test } from 'vitest'
import RippleLayer from '../components/RippleLayer.tsx'

/**
 * ⭐ 这组用例守的是"动效的边界 + 它与 React 的写入不打架"，每一条都**必须能红**：
 *   ① 该有涟漪时**有**（否则等于没做）——形态是"按钮上出现 `vigil-rippling` 类 +
 *      `--ripple-x/y/size` 是 px 值"（**不再是**"插了一个 `.vigil-ripple` span"）；
 *   ② 该没事时**一个都没有**（主题不要 / 系统关了动效 / 右键 / disabled）；
 *   ③ ⭐ **核心守卫**：按钮**文案更新**后涟漪还在（react-dom 会覆写 `textContent`）；
 *   ④ 动画结束要**成对**把类摘掉（否则下次得靠重排硬刷）。
 *
 * ⚠️ **为什么断言从"span"改成"类"**（reviewer 的 Important-1）：旧实现把 span
 * **命令式插进 React 管的 DOM**，而 react-dom 19.3.0 的 `setTextContent`
 * （`react-dom-client.development.js:2834`）在按钮文案更新时会走
 * `node.textContent = text`（:2846，因为 `firstChild`（文本节点）≠ `lastChild`（span））
 * ⇒ **活着的 span 被整个抹掉**。复现与源码片段见 `task-7-fix-report.md` 第 0 步。
 * 涟漪因此改成伪元素（`index.css` 的 ④ + `button.vigil-rippling::after`），
 * 本文件断言的对象也随之从"DOM 里的节点"变成"按钮上的类与自定义属性"。
 *
 * ⚠️ jsdom 不加载 CSS ⇒ `getComputedStyle(el).getPropertyValue('--v-ripple')` 是空串。
 * 所以"该有涟漪"那条要在按钮上**内联**写这个自定义属性（计划期实测：jsdom 能读到内联自定义属性）。
 *
 * ⚠️ **Web Animations 的替身（`stubAnimate`）整段删掉了**，这不是"把断言改松"：
 * 新实现**完全不碰 `Element.animate`**（动画归 CSS），那条替身已经没有任何被测物
 * 在读它。⛔ 但**因此更强**：旧实现下"② 该没有"那几条在 jsdom 里是靠替身才验得动的
 * （没有替身时旧实现会"插了立刻移除"，`0` 与"根本没插"**分不开** ⇒ 假绿）；
 * 现在"该没有"= 类没出现，**不需要任何替身**就能红（变异记录见报告 §3）。
 */

const RIPPLE = 'vigil-rippling'

/** jsdom 不排版 ⇒ 默认 `getBoundingClientRect()` 全是 0，`--ripple-size` 会恒为 `0px`。
 *  给**这个元素实例**钉一个固定几何（不改 `Element.prototype`，因此**不需要还原**：
 *  元素随 unmount 一起消失），几何量才能逐字断言。 */
function stubRect(el: Element) {
  el.getBoundingClientRect = () =>
    ({
      x: 100,
      y: 200,
      left: 100,
      top: 200,
      width: 80,
      height: 40,
      right: 180,
      bottom: 240,
      toJSON: () => ({}),
    }) as DOMRect
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

const rippling = () => document.querySelectorAll(`.${RIPPLE}`)

test('① 有涟漪色的主题：按下挂上 vigil-rippling，且 --ripple-x/y/size 是 px 字面量', async () => {
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)' })}
    </>,
  )
  const btn = screen.getByRole('button', { name: '按我' })
  stubRect(btn)
  await userEvent.pointer({ keys: '[MouseLeft>]', target: btn, coords: { clientX: 150, clientY: 220 } })

  expect(rippling()).toHaveLength(1)
  expect(btn.classList.contains(RIPPLE)).toBe(true)
  // ⚠️ 三个都必须是**带 px 单位的字面量**：`index.css` 的 ④ 直接把它们当长度用
  //（`left: var(--ripple-x)` / `width: var(--ripple-size)`），写成裸数字 ⇒
  // 整条声明在计算值阶段失效 ⇒ **涟漪静默不显示**（而这里不会红，除非断言单位）。
  expect(btn.style.getPropertyValue('--ripple-size'), 'size = max(80,40)*2 = 160px').toBe('160px')
  // ⚠️ 值是**触点相对按钮左上角的坐标**（**中心点**，回正由 CSS 的两个负 margin 干）
  //——不是"左侧边界"：写错这一处，涟漪会整体偏半个直径（肉眼看得见，测试不写就看不见）。
  expect(btn.style.getPropertyValue('--ripple-x'), 'clientX 150 − rect.left 100').toBe('50px')
  expect(btn.style.getPropertyValue('--ripple-y'), 'clientY 220 − rect.top 200').toBe('20px')
})

test('② 这套主题不要涟漪（--v-ripple 缺失 ⇒ 读到空串）⇒ 一个都不挂', async () => {
  render(
    <>
      <RippleLayer />
      {rippleBtn()}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(rippling()).toHaveLength(0)
})

test('② 显式 transparent ⇒ 也不挂（"关掉"要有两种写法都行）', async () => {
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'transparent' })}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(rippling()).toHaveLength(0)
})

test('② 系统里关了动效（prefers-reduced-motion: reduce）⇒ 不挂', async () => {
  // ⚠️ 本机 jsdom（30.1.0）整个 lib 里没有一处 `matchMedia`（实测：
  // `typeof window.matchMedia === 'undefined'`，且 `grep -r matchMedia node_modules/jsdom/lib/` 为空）
  // ⇒ `vi.spyOn(window,'matchMedia')` 抛 `can only spy on a function`。
  // 处置沿用"显式存原值 + 显式还原"（没有原值时删回去），`afterEach` 里收。
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
  try {
    render(
      <>
        <RippleLayer />
        {rippleBtn({ ripple: 'rgba(0,0,0,.2)' })}
      </>,
    )
    await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
    expect(rippling()).toHaveLength(0)
  } finally {
    if (original === undefined) delete (window as { matchMedia?: unknown }).matchMedia
    else window.matchMedia = original
  }
})

test('② disabled 的按钮 ⇒ 不挂（按不动的控件不该有反馈）', async () => {
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)', disabled: true })}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseLeft>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(rippling()).toHaveLength(0)
})

test('② 右键 ⇒ 不挂（涟漪是"主键按下"的反馈）', async () => {
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)' })}
    </>,
  )
  await userEvent.pointer({ keys: '[MouseRight>]', target: screen.getByRole('button', { name: '按我' }) })
  expect(rippling()).toHaveLength(0)
})

/**
 * ⭐⭐ **本轮的核心守卫**（reviewer 的 Important-1）。
 *
 * 旧实现（把 span 命令式 append 进按钮）在**这条上必红**——而它红的原因**不是**
 * "断言写的是类、旧实现用的是 span"这种口径差，是**真的被抹掉了**：
 * react-dom 19.3.0 的 `setTextContent` 只在「唯一子节点是文本节点」时走快路径，
 * span 一挂上就不满足 ⇒ 落到 `node.textContent = text`（:2846）⇒ 子节点全清。
 * 第 0 步的复现输出（`.vigil-ripple` 计数 1 → 0）与临时把旧实现放回去跑这条的
 * 原始输出都在 `task-7-fix-report.md` §1/§6。
 *
 * ⚠️ 这条**必须**用"文案变、别的都不变"的形态（`rerender` 只改文本子节点）：
 * 换成"改 className / 改 style"触发不到 `setTextContent`，那条路径就上不了场。
 */
test('⭐ 文案更新（React 覆写 textContent）之后，涟漪类仍在', async () => {
  function Subject({ text }: { text: string }) {
    return <button style={{ '--v-ripple': 'rgba(0,0,0,.2)' } as CSSProperties}>{text}</button>
  }
  const { rerender } = render(
    <>
      <RippleLayer />
      <Subject text="按我" />
    </>,
  )
  const btn = screen.getByRole('button', { name: '按我' })
  await userEvent.pointer({ keys: '[MouseLeft>]', target: btn })
  expect(btn.classList.contains(RIPPLE), '按下后没挂上涟漪类（前置没上场）').toBe(true)

  rerender(
    <>
      <RippleLayer />
      <Subject text="换个文案" />
    </>,
  )

  expect(btn.textContent, '文案没换成 ⇒ 这条没测到 textContent 覆写').toBe('换个文案')
  expect(btn.classList.contains(RIPPLE), 'React 写 textContent 时把涟漪一起清掉了').toBe(true)
})

/**
 * ④ 动画结束 ⇒ 摘类。
 *
 * ⚠️ jsdom **不跑 CSS 动画**（没有布局/合成器）⇒ `animationend` 永远不会自然到来
 *（真浏览器里由 `::after` 上那条 `animation` 触发、派发在宿主 button 上）。
 * 所以这里**手派**一个冒泡的 `animationend` ⇒ 走 document 上的委托监听器。
 * ⚠️ 用普通 `Event` 而不是 `AnimationEvent`：jsdom（30.1.0）**没有这个构造函数**
 *（实测 `typeof AnimationEvent === 'undefined'`），构造会直接抛。
 * ⇒ 实现里那条监听器**只认类名、不认 `animationName`**（理由写在组件里）。
 */
test('④ 动画结束（animationend）⇒ 类被摘掉；子元素冒泡上来的不算', async () => {
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)' })}
    </>,
  )
  const btn = screen.getByRole('button', { name: '按我' })
  stubRect(btn)
  await userEvent.pointer({ keys: '[MouseLeft>]', target: btn })
  expect(btn.classList.contains(RIPPLE)).toBe(true)

  // 子元素上的动画结束**也会**冒到 document：它不带这个类 ⇒ 不该摘按钮的类。
  const child = document.createElement('span')
  btn.appendChild(child)
  child.dispatchEvent(new Event('animationend', { bubbles: true }))
  expect(btn.classList.contains(RIPPLE), '子元素冒泡上来的 animationend 误摘了按钮的类').toBe(true)

  // 宿主元素自己的 ⇒ 摘掉。
  btn.dispatchEvent(new Event('animationend', { bubbles: true }))
  expect(rippling()).toHaveLength(0)
})

/**
 * ⑤ "重开动画"这个手势的**顺序**：摘类 → **强制重排** → 挂类。
 *
 * ⚠️ 为什么这条非有不可（变异 **M8** 实测）：把 `void el.offsetWidth` 那一行删掉，
 * 上面 8 条**一条都不红**（jsdom 没有布局引擎，读 `offsetWidth` 本来就只有副作用、
 * 没有回值）。而它是**真浏览器里唯一**让连按第二下能重播动画的东西——浏览器会把
 * "摘了又挂"合并成一次样式重算 ⇒ 类名没变 ⇒ 动画不重播。**测试装看不见的，
 * 恰恰是用户唯一能感觉到的那一半**。
 * ⇒ 判据只能落在**机制本身**上：读 `offsetWidth`（= 强制重排那一下）**就是**
 * 这个机制，所以把它替身成一个"记账"的 getter——它既必须被读到，**又必须是在
 * 类已摘掉之后**被读到（顺序反了同样等于没重排）。
 * ⚠️ 如实记：这是**代理断言**（断言的是"读了 offsetWidth"，不是"浏览器真重排了"）；
 * 它能红、能挡住"顺手删掉那一行"，但挡不住"浏览器行为变了"——那部分只能靠冒烟。
 */
test('⑤ 重开动画的顺序：摘类 → 强制重排（读 offsetWidth）→ 挂类', async () => {
  render(
    <>
      <RippleLayer />
      {rippleBtn({ ripple: 'rgba(0,0,0,.2)' })}
    </>,
  )
  const btn = screen.getByRole('button', { name: '按我' })
  stubRect(btn)

  let reflows = 0
  /** 读到的**那一刻**类在不在——`null` 表示这行从来没被读到过。 */
  let classAtReflow: boolean | null = null
  Object.defineProperty(btn, 'offsetWidth', {
    configurable: true,
    get() {
      reflows += 1
      classAtReflow = btn.classList.contains(RIPPLE)
      return 0
    },
  })

  await userEvent.pointer({ keys: '[MouseLeft>]', target: btn })

  expect(reflows, '没读 offsetWidth ⇒ 浏览器不会重算样式 ⇒ 连按第二下没有动画').toBeGreaterThan(0)
  expect(classAtReflow, '强制重排时类还在 ⇒ "摘了又挂"被合并成一次 ⇒ 动画不重播').toBe(false)
  expect(btn.classList.contains(RIPPLE), '重排之后没把类挂回去').toBe(true)
})

/**
 * ⚠️ 这里**故意没有**"卸载后不再监听"的用例：那种写法是**空守卫**——`document.body`
 * 里本来就没有 button，`closest('button')` 恒为 null ⇒ 无论监听器有没有卸掉都会绿。
 * 成对增删（StrictMode 双挂载）由**代码形态**保证：两条监听器在同一个 effect 里
 * 一加一删，且类操作是幂等的（`classList.add` 重复调用没有可见差别，
 * 所以"双监听器"在**类**这个载体上不再有可观察形态——旧 span 方案才有"一次按下插两个"）。
 */
