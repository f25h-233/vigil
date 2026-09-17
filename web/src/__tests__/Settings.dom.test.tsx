import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from '../App.tsx'
import Settings from '../views/Settings.tsx'
import type { CategoriesResponse, GroupsResponse } from '../types.ts'

type Call = { url: string; method: string }

type Fake = {
  groups?: GroupsResponse
  categories?: CategoriesResponse
}

/**
 * 装一个**有状态**的假 fetch（骨架照抄 T8 的 `Feed.dom.test.tsx`）。
 *
 * ⚠️ 必须 mock 全局 `fetch` 而**不是** mock `../api.ts`：本文件要钉的缺陷
 * 恰恰是「组件有没有把后端给的东西显示出来、有没有真的发那一次请求」。
 * mock 掉 api 层就把被测的那一层换掉了，测试会退化成
 * 「我 mock 的函数被我调用了」——与真实行为无关。
 */
function installFetch(f: Fake) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, method: init?.method ?? 'GET' })
      const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })

      if (url.startsWith('/api/groups')) {
        return ok(f.groups ?? { available: true, reason: '', generated_at: 0, groups: [] })
      }
      if (url.startsWith('/api/categories')) {
        return ok(f.categories ?? { categories: [], aliases: {} })
      }
      if (url.startsWith('/api/persons')) return ok({ persons: [] })
      if (url.startsWith('/api/llm')) {
        return ok({ base_url: 'https://x/v1', model: 'm', enable_thinking: null })
      }
      if (url.startsWith('/api/config/pack')) return ok({ toml: '# pack\n' })
      if (url.startsWith('/api/items')) return ok({ items: [], total: 0, limit: 50, offset: 0 })
      if (url.startsWith('/api/digests')) return ok({ digests: [] })
      return ok({})
    }),
  )
  return calls
}

afterEach(() => vi.unstubAllGlobals())

const AVAILABLE: GroupsResponse = {
  available: true,
  reason: '',
  generated_at: 1_700_000_999,
  groups: [
    { id: 111, name: '甲群', messages: 1664, last_ts: 1_700_000_000, watched: true, known: true },
  ],
}

test('没有群快照时必须显示原因，而不是一张空表', async () => {
  /**
   * ⭐ 「一个群都没有」与「还没读过」是**两句不同的话**。
   * 空表会被读成前者——一句假话，而且是最容易让人不再信任这个页面的那种。
   *
   * ⚠️ 变异反证：让 `GroupsSection` 在 `!available` 时照样渲染
   * `<ul>`（拿到一个空 `groups` 就画空表）⇒ 本条**必红**。
   * ⚠️ 这条与后端 `groups_snapshot.load` 返回 `None` 时的行为是一对——
   * 两边都守，是因为界面**完全可能**忽略那个字段（它只是个布尔）。
   */
  installFetch({
    groups: {
      available: false,
      reason: '还没有群清单快照。请先在仓库根目录跑一次 `uv run vigil export`。',
      generated_at: null,
      groups: [],
    },
  })
  render(<Settings />)

  expect(await screen.findByText(/还没有群清单快照/)).toBeTruthy()
  // ⚠️ 第二条断言是「没画空表」的**机械**判据：不是"看着不像表"，
  // 而是页面上**根本没有列表元素**（`<ul>` 的 role 是 list）。
  expect(screen.queryByRole('list')).toBeNull()
})

test('群清单必须写出快照的生成时刻（快照会过期）', async () => {
  /**
   * ⭐ spec §4.2 ③ 的硬要求之一：快照是 CLI **预生成**的产物，会过期。
   * 不写时刻的话，用户会拿一份三天前的清单做决定。
   *
   * ⚠️ 变异反证：把「清单来自 … 的快照」那句删掉 ⇒ 本条**必红**。
   */
  installFetch({ groups: AVAILABLE })
  render(<Settings />)

  const line = await screen.findByText(/清单来自/)
  expect(line.textContent).toContain(
    new Date(AVAILABLE.generated_at! * 1000).toLocaleString('zh-CN'),
  )
  expect(await screen.findByText('甲群')).toBeTruthy()
})

test('加群之后必须说清代价：下次 export 会拉全量历史', async () => {
  /**
   * ⭐ spec §4.2 ③ 的又一条硬要求：**不给数字的提示等于没提示**。
   * 首轮实测 1,664 条 / 21 批 / 6.3 分钟——不说的后果是用户加了个万人大群，
   * 然后以为程序卡死了。
   *
   * ⚠️ 变异反证：把 `submit()` 里那句 `setMsg(...)` 换成一句「已加入」
   * （或删掉）⇒ 本条**必红**。
   */
  const calls = installFetch({ groups: AVAILABLE })
  render(<Settings />)

  await screen.findByText('甲群')
  await userEvent.type(screen.getByPlaceholderText('群号'), '444')
  await userEvent.type(screen.getByPlaceholderText('群名'), '丁群')
  await userEvent.click(screen.getByRole('button', { name: '加入监视' }))

  const msg = await screen.findByText(/全部历史/)
  expect(msg.textContent).toContain('1,664')
  expect(msg.textContent).toContain('6.3 分钟')
  // ⚠️ 机制也要断言：提示写了却没有真的发出 POST，那是一句谎话。
  expect(calls.some((c) => c.method === 'POST' && c.url === '/api/groups')).toBe(true)
})

test('删类目时未知条目数就必须要求选择迁移目标', async () => {
  /**
   * ⭐ 出口判据 6 的界面形态：「不允许静默留下指向不存在 slug 的条目」。
   *
   * ⚠️ 变异反证：把「确认删除」按钮的
   * `disabled={pending.count > 0 && !migrateTo}` 去掉 ⇒ 本条**必红**。
   *
   * ⚠️ 三条断言缺一不可（否则是一条空守卫）：
   *   ① 先说清「还有 N 条」——只说"要选目标"而不给 N，用户不知道这事多大；
   *   ② N > 0 时按钮**点不动**（这才是判据 6 的机械形式）；
   *   ③ **选了目标之后按钮要点得动**——只有 ② 的话，一个把按钮永久禁用的
   *      实现照样绿，而那等于这个类目永远删不掉。
   */
  installFetch({
    categories: {
      categories: [
        { slug: 'notice', label: '通知公告', icon: '📋', desc: 'x', count: 5 },
        { slug: 'academic', label: '学业', icon: '📚', desc: 'y', count: 0 },
      ],
      aliases: {},
    },
  })
  render(<Settings />)

  await userEvent.click(screen.getByRole('button', { name: '类目' }))
  await screen.findByText(/通知公告/)
  await userEvent.click(screen.getAllByRole('button', { name: '删除' })[0])

  const prompt = await screen.findByText(/还有/)
  expect(prompt.textContent).toContain('5')
  const confirm = screen.getByRole('button', { name: '确认删除' }) as HTMLButtonElement
  expect(confirm.disabled).toBe(true)

  await userEvent.selectOptions(screen.getByRole('combobox'), 'academic')
  expect(
    (screen.getByRole('button', { name: '确认删除' }) as HTMLButtonElement).disabled,
  ).toBe(false)
})

test('「配置」tab 在 App 里挂得上，且真的去读了群清单', async () => {
  /**
   * ⚠️ 变异反证：把 `App.tsx` 的 `{tab === 'settings' && <Settings />}`
   * 删掉 ⇒ 本条**必红**（点完「配置」页面上什么都没有）。
   */
  const calls = installFetch({ groups: AVAILABLE })
  render(<App />)

  await userEvent.click(await screen.findByRole('button', { name: '配置' }))
  expect(await screen.findByRole('button', { name: '导入导出' })).toBeTruthy()
  expect(calls.some((c) => c.url.startsWith('/api/groups'))).toBe(true)
})
