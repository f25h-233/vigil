import { useEffect, useState } from 'react'

const GLYPHS = '▚▞▓▒░█▄▀◣◢◤◥╳╱╲#$%&@0123456789'

function scramble(n: number): string {
  let out = ''
  for (let i = 0; i < n; i += 1) out += GLYPHS[Math.floor(Math.random() * GLYPHS.length)]
  return out
}

/**
 * 主题切换里的「先乱码、后显名」。
 *
 * ⚠️ 三条约束：
 * 1. **只能是 `<span>`**：菜单项本身已经是 `<button role="menuitemradio">`，HTML 不许 button 嵌 button。
 *    ⇒ 跳过用的点击挂在 span 上 + `stopPropagation()`（点它是"揭晓"，不是"选中"）。
 *    无障碍的键盘路径 = 直接 Enter 选中该主题（乱码是**装饰**，不是功能）。
 * 2. 每次挂载都演一遍（用户的要求："每次都演"）⇒ 不需要 localStorage 开关。
 * 3. 显名后**必须清掉定时器**（判据在 `argusLabel.dom.test.tsx` 第三条：**观察
 *    `clearInterval` 被调用**——不是数 `vi.getTimerCount()`，那需要假定时器，
 *    而 `vi.useFakeTimers()` 与 `userEvent` 是已知会互相咬的组合）。
 */
export default function ArgusLabel({ text = 'Project ARGUS', ms = 2500 }: { text?: string; ms?: number }) {
  const [revealed, setRevealed] = useState(false)
  const [garbled, setGarbled] = useState(() => scramble(text.length))

  useEffect(() => {
    if (revealed) return
    const spin = window.setInterval(() => setGarbled(scramble(text.length)), 90)
    const done = window.setTimeout(() => setRevealed(true), ms)
    return () => {
      window.clearInterval(spin)
      window.clearTimeout(done)
    }
  }, [revealed, ms, text.length])

  return (
    <span
      data-testid="argus-label"
      title={revealed ? undefined : '点一下直接揭晓'}
      onClick={(e) => {
        e.stopPropagation()
        setRevealed(true)
      }}
    >
      {revealed ? text : garbled}
    </span>
  )
}
