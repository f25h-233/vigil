import { useSyncExternalStore } from 'react'
import { applyUpdate, getNeedRefresh, subscribe } from '../swUpdate.ts'

/**
 * 「有新版本，立即刷新」提示条。
 *
 * ⚠️ 为什么不自动刷新：`registerType: 'autoUpdate'` 会让新 SW 立刻接管，
 * 但**正在跑的那份 bundle 不会换**——自动 reload 会在用户打字/勾选的中途
 * 把页面抽走（本应用有表单与多选框）。所以是"提示 + 一次点击"。
 */
export default function SwUpdateToast() {
  const need = useSyncExternalStore(subscribe, getNeedRefresh)
  if (!need) return null
  return (
    <div
      role="status"
      className="fixed inset-x-4 bottom-4 z-40 mx-auto flex max-w-sm items-center gap-3 rounded-lg border border-vigil-border bg-vigil-surface-solid px-4 py-2 text-sm shadow-vigil-card"
    >
      <span className="text-vigil-fg-2">有新版本</span>
      <button
        onClick={applyUpdate}
        className="ml-auto rounded-lg bg-vigil-accent-soft px-3 py-1 text-vigil-accent-text"
      >
        立即刷新
      </button>
    </div>
  )
}
