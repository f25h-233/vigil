import { useState } from 'react'
import { undoLast } from './api.ts'
import ThemePicker from './components/ThemePicker.tsx'
import { applyTheme, readTheme, type ThemeId } from './theme.ts'
import Categories from './views/Categories.tsx'
import Digests from './views/Digests.tsx'
import Feed from './views/Feed.tsx'
import Settings from './views/Settings.tsx'

type Tab = 'feed' | 'cats' | 'digests' | 'settings'

const TABS: { key: Tab; label: string }[] = [
  { key: 'feed', label: '信息流' },
  { key: 'cats', label: '类目' },
  { key: 'digests', label: '日报' },
  { key: 'settings', label: '配置' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('feed')
  // 类目筛选状态**提到 App**：这样「类目」页点一个类目跳回信息流时，
  // 筛选条件能带过去，而 Feed 卸载重挂也不会丢。
  //
  // ⚠️ 多选：维度**内**是并集（选中多个类目 = 它们的合集），
  // 维度**间**是交集（类目 ∧ 人物）——spec §四 #4。
  const [kinds, setKinds] = useState<string[]>([])
  const [persons, setPersons] = useState<number[]>([])
  // 撤销的可见反馈：点完要说一句，否则不知道到底生效没有
  const [undoMsg, setUndoMsg] = useState<string | null>(null)
  // 撤销改的是库的**有效状态**，而 Feed 手里那份列表是旧快照——不给它发个
  // 信号，条目不会回到屏幕上（实测：撤销成功了，界面却毫无变化，
  // 用户会以为撤销没生效，于是再点一次，把上一步也撤掉）。
  const [dataTick, setDataTick] = useState(0)

  // 主题：值放在 App（应用级状态），ThemePicker 只是它的一个**视图**
  // （两处各持一份就会出现「菜单说材质、页面是蒸汽波」）。
  // ⚠️ `readTheme` 传的是**函数引用** ⇒ React 当惰性初始化用，挂载时读一次盘。
  const [theme, setTheme] = useState<ThemeId>(readTheme)
  function pickTheme(id: ThemeId) {
    setTheme(id)
    applyTheme(id) // 落盘 + 挂属性 + 同步 theme-color，一处做完
  }

  async function undo() {
    setUndoMsg(null)
    try {
      const r = await undoLast()
      setUndoMsg(r.undone ? '已撤销上一步' : '没有可撤销的操作')
      // 没撤成（空栈）就不用重取：什么都没变
      if (r.undone) setDataTick((t) => t + 1)
    } catch (e: unknown) {
      setUndoMsg(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="min-h-screen text-vigil-fg">
      {/* ⚠️ 头部**两行**（品牌+动作 / tab）不是审美选择：375×667 下仪器实测
          （计划 §0 E8）——单行时顶栏 77px、tab 被 flex 挤到 48px 宽、标签折成**两行**，
          而**没有任何元素被裁**（右侧余 16px）⇒ 这不是「修溢出」，是「别把标签挤扁」；
          再加一个 🎨 只会更扁。第二行留 `overflow-x-auto`：宁可横向滚，也别再压扁。 */}
      <header className="sticky top-0 z-10 border-b border-vigil-border bg-vigil-header backdrop-blur-vigil-header">
        <div className="mx-auto flex max-w-3xl items-center gap-1.5 px-4 pt-2">
          <span className="text-base font-semibold tracking-wide">🏮 VIGIL</span>
          {/* ⚠️ `ml-auto` 原来挂在 `nav` 上；撤销按钮插到它前面之后必须**挪过来**
              （同一行里只有一个 `ml-auto` 起作用，两个都在会变成两段式布局）。 */}
          <button
            onClick={undo}
            className="ml-auto rounded-lg px-2 py-1 text-xs text-vigil-fg-3 active:bg-vigil-surface"
          >
            ↶ 撤销
          </button>
          {undoMsg !== null && (
            <span className="max-w-[9rem] truncate text-xs text-vigil-fg-4">{undoMsg}</span>
          )}
          <ThemePicker value={theme} onChange={pickTheme} />
        </div>
        <nav className="mx-auto flex max-w-3xl gap-1 overflow-x-auto px-4 pb-2 pt-1 text-sm">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={
                'shrink-0 rounded-lg px-3 py-1.5 transition-colors ' +
                (tab === t.key
                  ? 'bg-vigil-surface-2 text-vigil-fg'
                  : 'text-vigil-fg-3 active:bg-vigil-surface')
              }
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-4 pb-24">
        {tab === 'feed' && (
          <Feed
            kinds={kinds}
            onKinds={setKinds}
            persons={persons}
            onPersons={setPersons}
            reloadSignal={dataTick}
          />
        )}
        {tab === 'cats' && (
          <Categories
            onPick={(slug) => {
              // ⚠️ 用 `setKinds([slug])`（**替换**而不是追加）：从类目页点进来
              // 是"我要看这一类"，追加会得到「上一次的筛选 ∧ 这一次的」这种
              // 没人要的结果。
              setKinds([slug])
              setTab('feed')
            }}
          />
        )}
        {tab === 'digests' && <Digests />}
        {tab === 'settings' && <Settings />}
      </main>
    </div>
  )
}
