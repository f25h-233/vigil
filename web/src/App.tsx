import { useState } from 'react'
import Categories from './views/Categories.tsx'
import Digests from './views/Digests.tsx'
import Feed from './views/Feed.tsx'

type Tab = 'feed' | 'cats' | 'digests'

const TABS: { key: Tab; label: string }[] = [
  { key: 'feed', label: '信息流' },
  { key: 'cats', label: '类目' },
  { key: 'digests', label: '日报' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('feed')
  // 类目筛选状态**提到 App**：这样「类目」页点一个类目跳回信息流时，
  // 筛选条件能带过去，而 Feed 卸载重挂也不会丢。
  const [kind, setKind] = useState('')

  return (
    <div className="min-h-screen bg-vigil-bg text-vigil-fg">
      <header className="sticky top-0 z-10 border-b border-white/10 bg-vigil-bg/90 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center gap-2 px-4 py-3">
          <span className="text-base font-semibold tracking-wide">🏮 VIGIL</span>
          <nav className="ml-auto flex gap-1 text-sm">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={
                  'rounded-lg px-3 py-1.5 transition-colors ' +
                  (tab === t.key
                    ? 'bg-white/10 text-white'
                    : 'text-white/55 active:bg-white/5')
                }
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-4 pb-24">
        {tab === 'feed' && <Feed kind={kind} onKind={setKind} />}
        {tab === 'cats' && (
          <Categories
            onPick={(slug) => {
              setKind(slug)
              setTab('feed')
            }}
          />
        )}
        {tab === 'digests' && <Digests />}
      </main>
    </div>
  )
}
