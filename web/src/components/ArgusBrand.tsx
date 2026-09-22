import ArgusLogo from './ArgusLogo.tsx'

/** 左上角的品牌区：徽记 + 大号 ARGUS + 小字。它**整体取代**「🏮 VIGIL」（只在 ARGUS 主题下）。 */
export default function ArgusBrand() {
  return (
    <div className="flex items-center gap-2">
      <ArgusLogo className="h-9 w-9 shrink-0" />
      <div className="leading-none">
        <div className="text-lg font-bold tracking-[0.28em]">ARGUS</div>
        <div className="mt-1 text-[10px] tracking-[0.18em] text-vigil-fg-3">睡亦警觉，眼观六路</div>
      </div>
    </div>
  )
}
