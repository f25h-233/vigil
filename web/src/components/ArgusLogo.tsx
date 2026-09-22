/**
 * 「百眼矩阵」徽记：圆角方框 + 2×2 的眼睛（瞳孔 + 眼睑），**粗线条、纯色**。
 * 孔雀尾/叶子的暗示：外框左下收出一段叶尖，四只眼球由外向内略微收小（尾扇的层次）。
 *
 * ⚠️ 全部用 `currentColor`：颜色由外层文字色决定 ⇒ `/color` 改了主题色，徽记**自动**跟着变，
 * 不需要任何同步代码。**任何一处写死颜色都会打破这件事**（有测试逐属性守它）。
 */
export default function ArgusLogo({ className = '' }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      className={className}
      role="img"
      aria-label="ARGUS 徽记"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {/* 外框：圆角方形，左下角收成叶尖 */}
      <path d="M6 4.5h19a3.5 3.5 0 0 1 3.5 3.5v13a3.5 3.5 0 0 1-3.5 3.5h-13c-3.3 0-5.4-2.1-6-5.5" />
      <path d="M6 19c2.6-.3 4.4-1.6 5.4-3.9" />
      {/* 百眼矩阵 */}
      <circle cx="12.5" cy="11.5" r="3.1" />
      <circle cx="12.5" cy="11.5" r="0.7" fill="currentColor" />
      <circle cx="20.5" cy="11.5" r="3.1" />
      <circle cx="20.5" cy="11.5" r="0.7" fill="currentColor" />
      <circle cx="13.5" cy="19.5" r="2.6" />
      <circle cx="13.5" cy="19.5" r="0.6" fill="currentColor" />
      <circle cx="20.5" cy="19.5" r="2.6" />
      <circle cx="20.5" cy="19.5" r="0.6" fill="currentColor" />
    </svg>
  )
}
