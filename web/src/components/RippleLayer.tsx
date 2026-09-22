import { useEffect } from 'react'

/**
 * 全局触点涟漪（**事件委托** + **伪元素**）。
 *
 * 为什么不"每个按钮包一层组件"：本仓有 60+ 个 button/chip/tab，逐个改会把「动效」这件事
 * 焊进每个调用点——而它其实是**主题资产**（每套主题自己给 `--v-ripple` 与 `--v-ripple-dur`）。
 * ⇒ 一个挂在 `document` 上的委托监听器；`--v-ripple` 是空/`transparent` 时**整个机制自关**
 * （默认主题与粗野主义就是这一档：零涟漪、零开销）。
 *
 * ⭐ **为什么画在伪元素上、而不是插一个 `<span>`**（reviewer 的 Important-1；
 * 第 0 步已复现，`index.css` 的 ④ 有完整记录）：
 * 旧实现 `el.appendChild(span)` 是**命令式往 React 管的 DOM 里塞节点** ⇒
 * React 19.3.0 的 `setTextContent`（`react-dom-client.development.js:2834/2846`）
 * 在按钮**文案更新**时会走 `node.textContent = text`（因为 `firstChild`（文本）≠
 * `lastChild`（span），快路径那条 `firstChild === lastChild && nodeType === 3` 不成立）
 * ⇒ **活着的涟漪 span 被整个抹掉**。伪元素不在 DOM 树里，React 怎么写都碰不到它。
 * ⚠️ 所以这里**只**做三件事：写三个 px 自定义属性、摘/挂一个类、在动画结束时摘类。
 * **不再碰 `Element.animate`**（动画由 CSS 的 `@keyframes vigil-ripple` 承担）——
 * 那条"jsdom 没有 Web Animations API"的边界因此按设计消失：本组件现在**不依赖** WAAPI。
 *
 * ⚠️ 三条边界（都有测试守）：
 * 1. **`prefers-reduced-motion` 必须尊重**——这是无障碍，不是可选装饰。
 * 2. **`disabled` 的按钮不插**（按不动的控件不该有反馈）。
 * 3. **右键不插**（`e.button !== 0`）——涟漪是"主键按下"的反馈。
 *
 * ⚠️ `main.tsx` 里本组件在 `StrictMode` 之下 ⇒ effect 会跑**两遍**（挂→卸→挂）。
 * 这是**正常**的，不是 bug：下面成对的 `addEventListener` / `removeEventListener`
 * （**两条监听器各一对**）就是为了它——卸的时候那两条被摘掉，重挂时再装两条，
 * **不会留下双监听器**。⛔ 别把双挂载当成需要修的缺陷。
 */
export default function RippleLayer() {
  useEffect(() => {
    function onPointerDown(e: PointerEvent) {
      if (e.button !== 0) return
      // ⚠️ 泛型必须是 `HTMLButtonElement`（计划原稿写的是 `HTMLElement`）：`.disabled`
      // 只存在于 `HTMLButtonElement` 上 ⇒ 用 `HTMLElement` 会被 `tsc -b` 以 TS2339 拒绝
      // （实测：`Property 'disabled' does not exist on type 'HTMLElement'`，**构建直接失败**）。
      // 选择器本来就是 `'button'`，所以这个收窄与运行时行为**完全一致**。
      const el = e.target instanceof Element ? e.target.closest<HTMLButtonElement>('button') : null
      if (el === null || el.disabled) return
      if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true) return

      // ⚠️ 这条读的是**计算值**（jsdom 不加载 CSS，所以测试里要在按钮上内联写 `--v-ripple`）。
      // 它同时是"这套主题要不要涟漪"的**唯一开关**——颜色本身由 CSS 的
      // `background: var(--v-ripple)` 去取，这里不把它抄进内联 style（少一份会漂移的副本）。
      const cs = getComputedStyle(el)
      const color = cs.getPropertyValue('--v-ripple').trim()
      if (color === '' || color === 'transparent') return

      const rect = el.getBoundingClientRect()
      const size = Math.max(rect.width, rect.height) * 2
      // ⭐ 三个**px 字面量**（`index.css` 的 ④ 直接把它们当长度用；写数字会被当成无单位
      // 长度而整条声明失效）。`--ripple-x/y` 给的是**中心点**，负 margin 在 CSS 里回正。
      el.style.setProperty('--ripple-x', `${e.clientX - rect.left}px`)
      el.style.setProperty('--ripple-y', `${e.clientY - rect.top}px`)
      el.style.setProperty('--ripple-size', `${size}px`)

      // ⭐ 重开动画的**唯一**可靠手法：摘类 → **强制重排** → 挂类。
      // 少了 `void el.offsetWidth` 这一步，浏览器会把"摘了又挂"合并成一次样式重算
      // ⇒ 类名没变 ⇒ 动画不重播（同一个按钮连按两下，第二下没有视觉反馈）。
      // ⚠️ 这一步**不能**省：它也是"上一轮的类没被 `animationend` 摘掉"时的兜底
      // （见下面那条监听器注释的第三段）。
      el.classList.remove('vigil-rippling')
      void el.offsetWidth
      el.classList.add('vigil-rippling')
    }

    /**
     * ⭐ 动画结束 ⇒ 把类摘掉（否则那个类会一直挂在按钮上）。
     *
     * ⚠️ **为什么用委托**（`document` 上与 `pointerdown` 同一种风格）：涟漪是挂在
     * 60+ 个按钮上的瞬时状态，逐个 `addEventListener` 就要逐个 `removeEventListener`
     * ——那正是"卸不干净 ⇒ 泄漏"的经典形态；委托只有两条、成对增删。
     * ⚠️ **为什么靠类名认人、不靠 `e.animationName`**：`animationend` 会从子元素
     * **冒泡**上来（子元素上任何动画结束都会以子元素为 `target` 冒到 `document`），
     * 而子元素**不带**这个类 ⇒ `classList.contains` 这一步就已经把冒泡来的事件挡掉了。
     * 再加一条 `animationName === 'vigil-ripple'` 的判据在**本仓测不出来**：
     * jsdom（30.1.0）**没有 `AnimationEvent`**（实测 `typeof AnimationEvent ===
     * 'undefined'`），只能派发普通 `Event`，其 `animationName` 是 `undefined`
     * ⇒ 那条分支在测试里**永远上不了场**（"空守卫的第 8 格"）。宁可不写。
     * ⚠️ 伪元素的动画事件**派发在它的宿主元素上**（就是那个 button），所以
     * `e.target` 正是要摘类的元素。
     * ⚠️ 万一 `animationend` 没来（元素被移出文档、或 jsdom 这种不跑 CSS 动画的环境），
     * 类会留着——但 `::after` 的 `fill: forwards` 停在 `opacity: 0`（看不见），
     * 且下一次 `pointerdown` 的"摘 → 重排 → 挂"会把状态重置。**不会卡死，也不会闪**。
     */
    function onAnimationEnd(e: AnimationEvent) {
      const el = e.target
      if (el instanceof Element && el.classList.contains('vigil-rippling')) {
        el.classList.remove('vigil-rippling')
      }
    }

    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('animationend', onAnimationEnd)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('animationend', onAnimationEnd)
    }
  }, [])

  return null
}
