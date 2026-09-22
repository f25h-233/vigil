import { useEffect } from 'react'

/**
 * 全局触点涟漪（**事件委托**）。
 *
 * 为什么不"每个按钮包一层组件"：本仓有 60+ 个 button/chip/tab，逐个改会把「动效」这件事
 * 焊进每个调用点——而它其实是**主题资产**（每套主题自己给 `--v-ripple` 与 `--v-motion-dur`）。
 * ⇒ 一个挂在 `document` 上的委托监听器；`--v-ripple` 是空/`transparent` 时**整个机制自关**
 * （默认主题与粗野主义就是这一档：零涟漪、零开销）。
 *
 * ⚠️ 三条边界（都有测试守）：
 * 1. **jsdom 没有 Web Animations API**（`span.animate === undefined`）⇒ 必须特性检测，
 *    否则挂载即抛 ⇒ 整站白屏。检测到没有就"插了立刻移除"，不留残渣。
 * 2. **`prefers-reduced-motion` 必须尊重**——这是无障碍，不是可选装饰。
 * 3. 涟漪是**命令式**插进 React 管的 DOM 里的：它**不是** React 的子节点，
 *    所以不许给它任何 React 状态；移除只由动画结束负责（两处 `.then` 都兜住）。
 *
 * ⚠️ `main.tsx` 里本组件在 `StrictMode` 之下 ⇒ effect 会跑**两遍**（挂→卸→挂）。
 * 这是**正常**的，不是 bug：上面成对的 `addEventListener` / `removeEventListener`
 * 就是为了它——卸的时候那条被摘掉，重挂时再装一条，**不会留下双监听器**
 * （留下双监听器的形态是"一次按下插两个涟漪"；别把双挂载当成需要修的缺陷）。
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

      const cs = getComputedStyle(el)
      const color = cs.getPropertyValue('--v-ripple').trim()
      if (color === '' || color === 'transparent') return

      const rect = el.getBoundingClientRect()
      const size = Math.max(rect.width, rect.height) * 2
      const span = document.createElement('span')
      span.className = 'vigil-ripple'
      span.style.width = `${size}px`
      span.style.height = `${size}px`
      span.style.left = `${e.clientX - rect.left - size / 2}px`
      span.style.top = `${e.clientY - rect.top - size / 2}px`
      span.style.background = color
      el.appendChild(span)

      if (typeof span.animate !== 'function') {
        span.remove()
        return
      }
      const durMs = Number.parseFloat(cs.getPropertyValue('--v-motion-dur').trim()) || 200
      const ease = cs.getPropertyValue('--v-motion-ease').trim() || 'ease-out'
      const anim = span.animate(
        [
          { transform: 'scale(0)', opacity: 0.9 },
          { transform: 'scale(1)', opacity: 0 },
        ],
        { duration: durMs * 2, easing: ease, fill: 'forwards' },
      )
      const done = () => span.remove()
      void anim.finished.then(done, done)
    }

    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [])

  return null
}
