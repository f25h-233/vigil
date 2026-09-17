import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import Feed from '../views/Feed.tsx'
import Settings from '../views/Settings.tsx'
import type { CategoryDetail, Item, JobRow } from '../types.ts'

// T11：**重排界面**——把 T6 已经做好、已经测过后端机制的重排接到网页上
// （spec §4.2 ④ 的「LLM 重判 **+ 界面上多选批量改**」那两半）。
//
// ⚠️ 这里 mock 的是**全局 `fetch`**，不是 `../api.ts`（照 T8 的 `installFetch` 范式）：
// 本文件要钉的恰恰是「组件有没有真的发那次请求、请求里装了什么、有没有接着轮询」。
// mock 掉 api 层就把被测的那一层整个换掉了，用例会退化成
// 「我 mock 的函数被我调用了」——与真实行为无关。

const REORDER_KEY = 'vigil.reorder.job'

type Call = { url: string; method: string; body?: unknown }

type Fake = {
  /** `POST /api/reorder` 的回值（默认一个 running 的 job）。 */
  reorder?: JobRow
  /** 起 job 被拒时后端那句 detail（409 = 已经有一个在跑）。 */
  reorderFail?: string
  /** `finish()` 之前 `GET /api/jobs/{id}` 一直回它。 */
  running?: JobRow
  /** `finish()` 之后 `GET /api/jobs/{id}` 回它（模拟服务端那边跑完了）。 */
  finished?: JobRow
  /** `POST /api/items/kinds` 回的 actor。 */
  bulkActor?: string
  items?: Item[]
}

function jobRow(o: Partial<JobRow> = {}): JobRow {
  return {
    job_id: 'j1',
    kind: 'reorder',
    state: 'running',
    total: 0,
    done: 0,
    message: '',
    error: '',
    actor: '',
    started_at: 1_700_000_000,
    finished_at: null,
    ...o,
  }
}

function item(id: number, title: string): Item {
  return {
    item_id: id,
    kind: 'notice',
    kind_label: '通知公告',
    kind_icon: '📋',
    title,
    detail: null,
    event_ts: 1_700_000_000,
    deadline_ts: null,
    group_id: 111,
    group_name: '甲群',
    actor: null,
    actor_uin: null,
    place: null,
    amount: null,
    links: [],
    source_count: 1,
  }
}

const CATS: CategoryDetail[] = [
  { slug: 'notice', label: '通知公告', icon: '📋', desc: 'x', count: 1 },
  { slug: 'academic', label: '学业', icon: '📚', desc: 'y', count: 0 },
]

/**
 * 有状态的假 fetch（骨架照抄 T8 的 `Feed.dom.test.tsx` / T9 的 `Settings.dom.test.tsx`）。
 *
 * ⚠️ job 的推进由 `finish()` 这个**显式开关**驱动，而不是"第 n 次轮询返回第 n 个状态"：
 * 后者的进度取决于用例跑得多快（第一次挂载可能已经轮询了一两次），
 * 于是「卸载重挂之后看到的是运行中」会变成一条**看机器心情**的断言。
 */
function installFetch(f: Fake) {
  const calls: Call[] = []
  let finished = false

  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      const body = init?.body === undefined ? undefined : JSON.parse(String(init.body))
      calls.push({ url, method, body })
      const ok = (b: unknown, status = 200) => ({
        ok: status < 400,
        status,
        json: async () => b,
      })
      const fail = (status: number, detail: string) => ({
        ok: false,
        status,
        json: async () => ({ detail }),
      })

      if (method === 'POST' && url === '/api/reorder') {
        if (f.reorderFail) return fail(409, f.reorderFail)
        return ok(f.reorder ?? jobRow(), 202)
      }
      if (method === 'POST' && url.endsWith('/cancel')) {
        return ok({ cancelled: true, state: 'running' })
      }
      if (method === 'POST' && url.endsWith('/undo')) return ok({ undone: true, count: 3 })
      if (url.startsWith('/api/jobs/')) {
        return ok(finished ? (f.finished ?? jobRow()) : (f.running ?? jobRow()))
      }
      // ⚠️ 顺序：`/api/items/kinds` 必须排在 `/api/items/` 与 `/api/items` **前面**，
      // 否则它会被更宽的前缀吃掉（那样这条用例测的就不是它自己那条请求了）。
      if (method === 'POST' && url === '/api/items/kinds') {
        const ids = (body as { item_ids: number[] }).item_ids ?? []
        return ok({ actor: f.bulkActor ?? 'bulk:fake', count: ids.length })
      }
      if (method === 'POST' && url === '/api/bulk-undo') return ok({ undone: true, count: 2 })
      if (url.startsWith('/api/categories')) return ok({ categories: CATS, aliases: {} })
      if (url.startsWith('/api/persons')) return ok({ persons: [] })
      if (url.startsWith('/api/groups')) {
        return ok({ available: true, reason: '', generated_at: 0, groups: [] })
      }
      if (url.startsWith('/api/items/')) return ok({ ...(f.items ?? [])[0], sources: [] })
      if (url.startsWith('/api/items')) {
        const items = f.items ?? []
        return ok({ items, total: items.length, limit: 50, offset: 0 })
      }
      return ok({})
    }),
  )

  return {
    calls,
    /** 服务端那边这一刻跑完了（下一次轮询就会看到终态）。 */
    finish: () => {
      finished = true
    },
    jobPolls: () =>
      calls.filter((c) => c.method === 'GET' && c.url.startsWith('/api/jobs/')),
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  // ⚠️ jsdom 的 localStorage 在**同一个文件的所有用例之间是共享的**：
  // 不清的话，上一个用例留下的 job_id 会让下一个用例一上来就"恢复"出一个任务，
  // 而那条失败与被测行为毫无关系（本项目在 `data/vigil.lock` 上吃过同一形状的亏）。
  window.localStorage.clear()
})

/** 进入某一节（`Settings` 自己渲染在 `App` 之外时不会与导航撞车）。 */
async function openSection(name: string) {
  await userEvent.click(screen.getByRole('button', { name }))
}

// ── 重排（job）────────────────────────────────────────────────────────

test('起 job → 轮询到 done：进度照实显示 done/total，终态之后停止轮询', async () => {
  /**
   * ⭐ spec §4.2 ④ 的 job 那一半：一件跑 1–2 分钟的活儿必须**看得见**，
   * 而不是一个转圈的请求。
   *
   * ⚠️ 三条断言缺一不可：
   *   ① `job_id` 落进 `localStorage`——不落的话刷新一次就再也看不到结果了，
   *      而它**还在服务端跑着**、还占着唯一的 `JobBusy` 名额；
   *   ② 进度是 `done/total` 的**照实**显示（`done` 是"最后成功批次的序号"，
   *      不是完成批次数）——手滑写成 `done + 1` 就是另一句假话；
   *   ③ 终态之后**不再轮询**：轮询的依赖列表里少了 `job?.state` 的话，
   *      interval 会一直活着（`job_id` 没变 ⇒ effect 不重跑 ⇒ 清理不掉）。
   */
  const { calls, finish, jobPolls } = installFetch({
    reorder: jobRow({ job_id: 'j1' }),
    running: jobRow({ job_id: 'j1', done: 2, total: 5, message: '第 2 批判完' }),
    finished: jobRow({
      job_id: 'j1',
      state: 'done',
      done: 5,
      total: 5,
      actor: 'reorder:1:ab12cd34',
      message: '12 条改了类目，3 条没判成（它们没被动）',
      finished_at: 1_700_000_120,
    }),
  })
  render(<Settings />)
  await openSection('重排')
  await userEvent.click(screen.getByRole('button', { name: '开始重排' }))

  expect(await screen.findByText(/已开始/)).toBeTruthy()
  expect(
    window.localStorage.getItem(REORDER_KEY),
    'job_id 没落 localStorage ⇒ 刷新一次就再也看不到这个任务了（而它还在服务端跑着）',
  ).toBe('j1')

  // ② 进度：`2/5`（不是 `3/5`——`done` 不加一）
  expect(await screen.findByText(/2\/5/, undefined, { timeout: 3000 })).toBeTruthy()

  finish()
  expect(
    await screen.findByText(/12 条改了类目/, undefined, { timeout: 5000 }),
  ).toBeTruthy()

  // ③ 停了：终态之后再等一轮，轮询次数不许涨
  const n = jobPolls().length
  await new Promise((r) => setTimeout(r, 1300))
  expect(jobPolls().length, '终态之后还在轮询：interval 没被清理掉').toBe(n)
  // 终态之后「取消重排」不该还在（它只对 running 有意义）
  expect(screen.queryByRole('button', { name: '取消重排' })).toBeNull()
  // 终态之后 localStorage 也该清掉：再刷新时不必去问一个已经结束的 job
  expect(window.localStorage.getItem(REORDER_KEY)).toBeNull()
  expect(calls.some((c) => c.method === 'POST' && c.url === '/api/reorder')).toBe(true)
})

test('刷新（卸载重挂）之后：从 localStorage 恢复同一个 job，并**继续轮询**到 done', async () => {
  /**
   * ⭐ 钉的正是"刷新即丢"那个坏法：重排要跑 1–2 分钟，用户很可能刷新页面去看别的。
   * 不恢复的话，刷新一次就再也看不到那个 job 的结果了——而它**还在服务端跑着**，
   * 再点「开始重排」只会拿到一个 409 而不知道为什么。
   *
   * ⚠️ 两条断言各钉一半：
   *   ① 挂载时读回 `localStorage` 并**接着显示同一个任务**（不恢复 ⇒ 这里只有一句"还没有跑过重排"）；
   *   ② 恢复之后**轮询还在跑**（只恢复不轮询 ⇒ 它永远停在「运行中」）。
   */
  const { finish, jobPolls } = installFetch({
    reorder: jobRow({ job_id: 'j-refresh' }),
    running: jobRow({ job_id: 'j-refresh', done: 1, total: 4 }),
    finished: jobRow({
      job_id: 'j-refresh',
      state: 'done',
      done: 4,
      total: 4,
      message: '9 条改了类目，1 条没判成（它们没被动）',
    }),
  })
  const first = render(<Settings />)
  await openSection('重排')
  await userEvent.click(screen.getByRole('button', { name: '开始重排' }))
  expect(await screen.findByText(/运行中/)).toBeTruthy()
  expect(window.localStorage.getItem(REORDER_KEY)).toBe('j-refresh')

  // 刷新 = 组件全丢、只剩 localStorage
  first.unmount()

  render(<Settings />)
  await openSection('重排')
  expect(await screen.findByText(/运行中/)).toBeTruthy() // ① 恢复
  finish()
  expect(
    await screen.findByText(/9 条改了类目/, undefined, { timeout: 5000 }),
  ).toBeTruthy() // ② 继续轮询
  expect(jobPolls().length).toBeGreaterThanOrEqual(2)
})

test('取消 ⇒ 调 /api/jobs/{id}/cancel，且说清"正在飞的那一批会跑完"', async () => {
  /**
   * ⭐ 取消是**协作式**的（后端把这件事写在 docstring 里）：点了之后
   * 正在飞的那一批会跑完，真正结束看轮询到的 `state`。界面必须这么说，
   * 否则用户点完看到"还在跑"会以为按钮坏了——而它会以为第二次点击才有用。
   *
   * ⚠️ 变异反证：把 `api.cancelJob(...)` 那行删掉 ⇒ 本条**必红**。
   */
  const { calls } = installFetch({
    reorder: jobRow({ job_id: 'j-cancel' }),
    running: jobRow({ job_id: 'j-cancel', done: 1, total: 9 }),
    finished: jobRow({ job_id: 'j-cancel', state: 'cancelled', done: 1, total: 9 }),
  })
  render(<Settings />)
  await openSection('重排')
  await userEvent.click(screen.getByRole('button', { name: '开始重排' }))

  await userEvent.click(await screen.findByRole('button', { name: '取消重排' }))

  expect(await screen.findByText(/停在下一批/)).toBeTruthy()
  expect(
    calls.some((c) => c.method === 'POST' && c.url === '/api/jobs/j-cancel/cancel'),
    '点了取消，却没有把请求发出去',
  ).toBe(true)
})

test('起 job 撞 409：原样显示后端那句"等它结束"，不吞掉', async () => {
  /**
   * ⭐ 409 = **已有 job 在跑**（唯一的 `JobBusy` 名额）。这不是"出错了"，
   * 而是"等一下"——后端那句 detail 已经把话说清楚了，界面照原样显示即可
   * （和 `/api/undo` 的 409 同形）。吞掉它的话，用户看到的是一个
   * 没有任何解释的失败。
   *
   * ⚠️ 变异反证：把 `start()` 的 `catch` 里那句 `setErr(...)` 删掉 ⇒ 本条**必红**。
   */
  installFetch({ reorderFail: '已经有一个后台任务在跑了，等它结束再试' })
  render(<Settings />)
  await openSection('重排')
  await userEvent.click(screen.getByRole('button', { name: '开始重排' }))

  expect(await screen.findByText(/等它结束再试/)).toBeTruthy()
})

// ── 信息流里的多选批量改 ───────────────────────────────────────────────

test('多选批量改：撤销用的是 bulkSetKind 返回的那个 actor，且改完重取第一页', async () => {
  /**
   * ⭐ D16 的「界面上多选批量改」那一半（spec §4.2 ④）。
   *
   * ⚠️ 三条断言各钉一件事：
   *   ① 请求体是 `{item_ids, kind}`——**一次提交一个 actor**，所以那几条能被一次撤销；
   *   ② 撤销发出去的 `actor` **就是** `bulkSetKind` 返回的那个（存错/丢掉 ⇒
   *      "改了 5 条、发现改错了"只能一条条改回去）；
   *   ③ 改完**重取第一页**（不带 `offset`）——照 `reload()` 的既有做法。
   *      复用 `retry()` 的话它走 `loadMore()`，那是**往后追加**，
   *      屏幕上那条已经变了的条目不会被刷新（M5 A-Minor-7 的原形）。
   */
  const { calls } = installFetch({
    items: [item(7, '周三停水'), item(8, '奖学金评定')],
    bulkActor: 'bulk:abc123',
  })
  render(
    <Feed kinds={[]} onKinds={() => {}} persons={[]} onPersons={() => {}} reloadSignal={0} />,
  )

  await screen.findByText('周三停水')
  await userEvent.click(screen.getByLabelText('选择 周三停水'))
  await userEvent.click(screen.getByLabelText('选择 奖学金评定'))
  await userEvent.selectOptions(screen.getByLabelText('批量改成的类目'), 'academic')
  await userEvent.click(screen.getByRole('button', { name: '改类目' }))

  const post = calls.find((c) => c.method === 'POST' && c.url === '/api/items/kinds')
  expect(post?.body).toEqual({ item_ids: [7, 8], kind: 'academic' })

  // ③ 重取第一页（不是追加）
  await waitFor(() => {
    expect(calls.filter((c) => c.url.startsWith('/api/items?')).length).toBeGreaterThan(1)
  })
  const pages = calls.filter((c) => c.url.startsWith('/api/items?'))
  expect(
    pages[pages.length - 1].url,
    '批量改之后的这次重取带了 offset——那是 loadMore 的追加语义，' +
      '它不会刷新屏幕上那条已经变了的条目（M5 A-Minor-7）',
  ).not.toContain('offset')

  // 改完清空选中：还留着的话用户会以为那几条还选着、再点一次就改重了
  await waitFor(() => {
    expect((screen.getByLabelText('选择 周三停水') as HTMLInputElement).checked).toBe(false)
  })
  expect(screen.queryByLabelText('批量改成的类目')).toBeNull()

  // ① 撤销：用的必须是**存下来的那个** actor
  await userEvent.click(await screen.findByRole('button', { name: /撤销这次批量改/ }))
  const undoPost = calls.find((c) => c.method === 'POST' && c.url === '/api/bulk-undo')
  expect(
    undoPost?.body,
    '撤销用的不是 bulkSetKind 回给的那个 actor ⇒ 撤不回刚改的那一批',
  ).toEqual({ actor: 'bulk:abc123' })
})
