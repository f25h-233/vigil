import { useEffect, useRef, useState } from 'react'
import { THEMES, type ThemeId } from '../theme.ts'

/**
 * 顶栏的紧凑切换器：一个 🎨 + 一个五项菜单。
 *
 * ⚠️ 它是**受控组件**（值在 App，不在自己手里）：主题是应用级状态，
 * 浮层只是它的一个视图——两处各持一份就会出现「菜单说材质、页面是蒸汽波」。
 */
export default function ThemePicker({
  value,
  onChange,
}: {
  value: ThemeId
  onChange: (id: ThemeId) => void
}) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onPointer(e: PointerEvent) {
      if (box.current !== null && !box.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        aria-label="切换主题"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="rounded-lg px-1.5 py-1 text-base active:bg-vigil-surface"
      >
        🎨
      </button>
      {open && (
        <ul
          role="menu"
          aria-label="主题"
          className="absolute right-0 z-30 mt-1 w-40 rounded-lg border border-vigil-border bg-vigil-surface-solid p-1 text-sm shadow-vigil-card"
        >
          {THEMES.map((t) => (
            <li key={t.id}>
              <button
                type="button"
                role="menuitemradio"
                aria-checked={t.id === value}
                onClick={() => {
                  onChange(t.id)
                  setOpen(false)
                }}
                className={
                  'w-full rounded px-2 py-1.5 text-left ' +
                  (t.id === value
                    ? 'bg-vigil-accent-soft text-vigil-accent-text'
                    : 'text-vigil-fg-2 active:bg-vigil-surface')
                }
              >
                {t.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
