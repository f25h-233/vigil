import { StrictMode } from 'react'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from '../App.tsx'
import ItemCard from '../components/ItemCard.tsx'
import { _resetForTests, noteFetchResult } from '../connectivity.ts'
import { readSnapshot, writeSnapshot } from '../snapshot.ts'
import { VIEW_STORAGE_KEY } from '../uiState.ts'
import Digests from '../views/Digests.tsx'
import Feed from '../views/Feed.tsx'
import { fmtDateTime } from '../format.ts'
import type { DigestDetail, Item } from '../types.ts'

/**
 * ⭐ 出口标准 2/3/5(+G9/G10) 的守卫:离线快照回落、写操作置灰、三态分开。
 *
 * ⚠️ **三态必须分开**(spec §3.3 / G10):
 *   ① 网络通、真没有 ⇒「还没有条目。」
 *   ② 网络断、有快照 ⇒「这是 {synced_at} 的快照。」
 *   ③ 网络断、无快照 ⇒「离线，且还没有本地快照。」
 * 混起来说的后果是把「离线不知道」谎报成「真的没有」——本项目最贵的那条产品判据。
 *
 * ⚠️ `_resetForTests()` 是**必须**的(不是洁癖):`connectivity.ts` 的 `online` 是
 * **模块级**状态,`noteFetchResult(false)` 会跨用例串到下一条去
 * (`connectivity.test.ts` 顶部那条注释说的就是这个)。
 * 顺序也要紧:先撤 stub、再复位——反过来的话 `initial()` 读到的是被 stub 的 navigator。
 */

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
  localStorage.removeItem(VIEW_STORAGE_KEY)
  _resetForTests()
})

// ── 夹具 ────────────────────────────────────────────────────────────────

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
    source_count: 0,
  }
}

const SNAPSHOT_TS = Math.floor(new Date(2026, 9, 9, 8, 30).getTime() / 1000)
/** `fmtDateTime(SNAPSHOT_TS)` === '10月9日 08:30'(不硬编码时区)。 */
const SNAPSHOT_LABEL = fmtDateTime(SNAPSHOT_TS)

const DIGEST: DigestDetail = {
  digest_id: 9,
  day: '2026-10-05',
  window_from: 1_700_000_000,
  window_to: 1_700_086_400,
  created_at: 1_700_090_000,
  item_count: 1,
  body_md: '快照里的日报正文。',
  items: [item(1, '日报里引用的条目')],
}

/** 最近一次 `stubOkApi` 收到的 URL 列表(按调用顺序)。 */
let stubOkApiCalls: string[] = []

/** 一个**全部成功**的假后端。返回它收到的 URL 列表(按调用顺序)。 */
function stubOkApi(feed: Item[] = []): string[] {
  const calls: string[] = []
  stubOkApiCalls = calls
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
      if (url.startsWith('/api/categories')) {
        // 给一个类目：批量条那个下拉要**有得选**，"离线时改类目不可用"
        // 这一条才验得动（否则按钮被 `bulkKind === ''` 挡着，`!online` 那半是死支）。
        return ok({
          categories: [{ slug: 'notice', label: '通知公告', icon: '📋', count: 1, desc: 'x' }],
        })
      }
      if (url.startsWith('/api/persons')) return ok({ persons: [] })
      if (url.startsWith('/api/calendar')) return ok({ items: [], total: 0 })
      if (url.startsWith('/api/digests/')) return ok(DIGEST)
      if (url.startsWith('/api/digests')) return ok({ digests: [] })
      if (url.startsWith('/api/items/')) return ok({ ...item(1, 'x'), sources: [] })
      if (url.startsWith('/api/items')) {
        return ok({ items: feed, total: feed.length, limit: 50, offset: 0 })
      }
      return ok({})
    }),
  )
  return calls
}

/** 一个**全失败**的假后端:fetch 本身抛 = 网络层没通(离线)。同时记下 URL。 */
function stubDeadApi(): string[] {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      calls.push(String(input))
      throw new TypeError('Failed to fetch')
    }),
  )
  return calls
}

/**
 * 一个**活着但每个请求都 404** 的假后端(F2 的场景:后端在线、只是这个请求有问题)。
 *
 * ⚠️ 它刻意**不是** `stubDeadApi`:后者 fetch 抛 ⇒ `noteFetchResult(false)`;
 * 而 4xx 走的是 `noteFetchResult(r.status < 500)` = `true` ⇒ **`online` 保持真**
 * (`api.ts` 的既定语义,正确)。这正是 F2 的入口:失败**不等于**离线。
 * 同时记下 URL(与另两个桩同形)。
 */
function stub404Api(detail = '订单不存在'): string[] {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      calls.push(String(input))
      // 形状与真后端同:4xx + `{detail}`(api.getJSON 会把它当错误文案)
      return { ok: false, status: 404, json: async () => ({ detail }) }
    }),
  )
  return calls
}

// ── ItemCard:可选的 `offline`(G9 / 出口标准 3)───────────────────────────

test('⚠️ offline=true ⇒ 改动控件被禁用 + 提示需要联网(G9 / 出口标准 3)', () => {
  stubOkApi()
  render(<ItemCard item={item(7, '周三停水')} onMutated={() => {}} offline />)
  const del = screen.getByRole('button', { name: '删除' }) as HTMLButtonElement
  // ⚠️ 变异反证:去掉 `|| offline === true` ⇒ 本条必红。
  expect(del.disabled).toBe(true)
  expect(screen.getByText('需要联网')).toBeTruthy()
  // 下拉框同样是写操作,同样置灰(只盯按钮会漏掉"改分类"这一半)
  const sel = document.querySelector('select') as HTMLSelectElement
  expect(sel.disabled).toBe(true)
})

test('⚠️ 不传 offline ⇒ 与今天一字不差(日报页/日历页的只读用法不受影响)', () => {
  stubOkApi()
  render(<ItemCard item={item(7, '周三停水')} onMutated={() => {}} />)
  const del = screen.getByRole('button', { name: '删除' }) as HTMLButtonElement
  expect(del.disabled).toBe(false)
  expect(screen.queryByText('需要联网')).toBeNull()
})

test('⚠️ 不传 onMutated(日报/日历的只读用法)⇒ 没有改动条', () => {
  render(<ItemCard item={item(7, '周三停水')} />)
  expect(screen.queryByRole('button', { name: '删除' })).toBeNull()
})

// ── Feed:离线回落快照 ─────────────────────────────────────────────────

const feedProps = {
  kinds: [] as string[],
  onKinds: () => {},
  persons: [] as number[],
  onPersons: () => {},
  reloadSignal: 0,
}

test('⚠️ 离线且无快照 ⇒ 说"离线，且还没有本地快照",不许说"还没有任何条目"(G10 / 出口标准 5)', async () => {
  stubDeadApi()
  render(<Feed {...feedProps} />)
  expect(await screen.findByText(/离线，且还没有本地快照/)).toBeTruthy()
  // ⚠️ 这一句是**假话**:"还没有任何条目"说的是"库里就没有",而我们只知道"读不到"。
  expect(screen.queryByText('还没有任何条目。')).toBeNull()
})

test('⚠️ 离线但有快照 ⇒ 显示快照 + 同步时刻 + 横幅(出口标准 2)', async () => {
  writeSnapshot({
    synced_at: SNAPSHOT_TS,
    feed: [item(7, '快照里的停水通知')],
    calendar: [],
    digests: [],
  })
  stubDeadApi()
  render(<Feed {...feedProps} />)
  expect(await screen.findByText('快照里的停水通知')).toBeTruthy()
  // ⚠️ 必须写清**何时**同步的,不许假装实时(G10 / 出口标准 2)。
  // ⚠️ 断言**原文**(不是 `/本地快照（/`):正则会被"日报侧那条同形的横幅"就近满足
  // (F4 的形状:一条弱断言被另一条新文案喂饱)。原文 + 时刻两个断言,改词就红。
  expect(
    screen.getByText(`离线：显示的是本地快照（${SNAPSHOT_LABEL} 同步）。`),
  ).toBeTruthy()
  expect(screen.getByText(new RegExp(SNAPSHOT_LABEL))).toBeTruthy()
})

test('⚠️ 离线时有快照 ⇒ 卡片置灰 + 批量条不可用(G9 / 出口标准 3)', async () => {
  writeSnapshot({
    synced_at: SNAPSHOT_TS,
    feed: [item(7, '快照里的停水通知')],
    calendar: [],
    digests: [],
  })
  stubDeadApi()
  render(<Feed {...feedProps} />)
  // ⚠️ 只有**离线**的卡片才说"需要联网"——它出现在这里就同时证明了:
  // ① 列表里是快照 ② `offline` 这条路的卡片确实被传了 `offline={true}`。
  await screen.findByText('需要联网')

  expect((screen.getByRole('button', { name: '删除' }) as HTMLButtonElement).disabled).toBe(true)
})

test('⚠️ 离线 ⇒ 批量条置灰:批量改是**写**操作(G9)', async () => {
  /**
   * 这一条与上一条**故意分开**:
   * 离线读快照时 `Feed` 自己的 `/api/categories` 也拉不到 ⇒ 下拉里没有类目
   * ⇒「改类目」按钮被 `bulkKind === ''` 挡着,**那条断言恒真**
   * (与 `!online` 无关,`!online` 那半是死支)。
   * ⇒ 要让 `!online` 承重,必须先**有类目、有数据**——那只能是"先在线拿到,
   * 之后才断"(用户翻着翻着断网),这也是它在现实里的唯一形态。
   */
  stubOkApi([item(7, '实时读到的条目')])
  render(<Feed {...feedProps} />)
  await screen.findByText('实时读到的条目')

  await userEvent.click(screen.getByRole('checkbox', { name: '选择 实时读到的条目' }))
  const bulkSel = screen.getByLabelText('批量改成的类目') as HTMLSelectElement
  await waitFor(() => expect(bulkSel.options.length).toBeGreaterThan(1))
  await userEvent.selectOptions(bulkSel, 'notice')

  // 阴性对照:在线时它是可用的(否则下一条断言可能只是因为别的原因恒真)
  expect((screen.getByRole('button', { name: '改类目' }) as HTMLButtonElement).disabled).toBe(false)

  await act(async () => {
    window.dispatchEvent(new Event('offline'))
  })
  expect((screen.getByRole('button', { name: '改类目' }) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByText('批量改需要联网')).toBeTruthy()
})

test('⚠️ 带筛选时失败 ⇒ 如实报错,不许拿"不匹配的快照"冒充答案(unfiltered 守卫)', async () => {
  /**
   * ⭐ 这条钉的是 brief Step 8 变异 2(`unfiltered` 改成恒 true):
   * 快照存的是「最近 5 天的**全部**条目」,把它显示在一个**带筛选**的查询下,
   * 就是拿一张不匹配的清单回答另一个问题(「只说自己有资格说的话」,M2)。
   *
   * ⚠️ 变异反证:`const unfiltered = ...` → `const unfiltered = true` ⇒ 本条必红
   * (快照条目会出现在屏幕上、横幅也会在)。
   */
  writeSnapshot({
    synced_at: SNAPSHOT_TS,
    feed: [item(7, '快照里的停水通知')],
    calendar: [],
    digests: [],
  })
  stubDeadApi()
  render(<Feed {...feedProps} kinds={['notice']} />)
  expect(await screen.findByText(/读取失败/)).toBeTruthy()
  expect(screen.queryByText('快照里的停水通知')).toBeNull()
  expect(screen.queryByText(/本地快照（/)).toBeNull()
})

test('⚠️ 网络恢复 ⇒ 自动回到实时数据,不是卡在快照上(出口标准 4)', async () => {
  writeSnapshot({
    synced_at: SNAPSHOT_TS,
    feed: [item(7, '快照里的停水通知')],
    calendar: [],
    digests: [],
  })
  stubDeadApi()
  render(<Feed {...feedProps} />)
  await screen.findByText('快照里的停水通知')

  // 恢复:换一个活的后端,再派发浏览器的 online 事件
  stubOkApi([item(8, '实时读到的条目')])
  await act(async () => {
    window.dispatchEvent(new Event('online'))
  })

  expect(await screen.findByText('实时读到的条目')).toBeTruthy()
  expect(screen.queryByText('快照里的停水通知')).toBeNull()
  expect(screen.queryByText(/本地快照（/)).toBeNull()
})

test('⚠️ 在线首屏只取一次:订阅失败/重渲染都不许把列表重取多一次', async () => {
  /**
   * ⭐ 这一条钉的是 `onlineEpoch` 那个**从离线变在线**的判据(Feed.tsx)。
   *
   * ⚠️ 两个把守:`connectivity` 里失败请求的 `noteFetchResult(false)`
   * (它会让订阅者**在首屏请求刚落地的那一刻**被吵一次),以及任何一次
   * **无关的重渲染**(`setOnline(isOnline())` 重算成同一个 `true`)。
   * 少了那个判据,这两个把守都会白拉一次列表——而**屏幕上看不出任何区别**
   * (数据一样),只有数请求数才发现。
   *
   * ⚠️ 变异反证:把 `if (online && !wasOnline)` 写成 `if (online)` ⇒ 本条必红
   * (首屏数到 2);写成 `[]`(只在挂载时算一次) ⇒ 上面那条"网络恢复"也会红。
   */
  const calls = stubOkApi([item(8, '实时读到的条目')])
  render(<Feed {...feedProps} />)
  await screen.findByText('实时读到的条目')
  await waitFor(() => {
    expect(calls.filter((u) => u.startsWith('/api/items')).length).toBe(1)
  })
})

test('⚠️ 在线 4xx + 盘上有快照 ⇒ 如实报错,不许说"离线"、也不许拿快照冒充(F2)', async () => {
  /**
   * ⭐ F2:4xx 保持 `online===true`(`api.ts` 的 `noteFetchResult(r.status < 500)`)。
   * 「失败」**不等于**「离线」⇒ 在线 4xx 该显示**真实错误**(而不是"离线"这句话),
   * 也不该把快照冒充成本次的答案(那会同时把卡片灰掉、说"需要联网"——
   * 三句假话连成一串)。离线回落只配用在**真的离线**时。
   *
   * ⚠️ 变异反证:把 Feed 的 `!isOnline()` 守卫去掉(回落重新回到"只要失败就上")
   * 或把横幅的 `!online` 去掉 ⇒ 本条必红(屏幕上会出现快照条目 / "离线")。
   */
  writeSnapshot({
    synced_at: SNAPSHOT_TS,
    feed: [item(7, '快照里的停水通知')],
    calendar: [],
    digests: [],
  })
  stub404Api()
  render(<Feed {...feedProps} />)

  // ⭐ 快照照常回落(fallback 本身不变——它由"失败"决定,不由"离线"决定)
  expect(await screen.findByText('快照里的停水通知')).toBeTruthy()
  // ⭐ 在线 4xx **仍是错误** ⇒ 错误框在场(审查的验收要求:不许因为回落到快照
  //    就把在线错误吞掉,屏幕只剩一份来路不明的旧数据)
  expect(screen.getByText(/读取失败/)).toBeTruthy()
  expect(screen.getByText(/订单不存在/)).toBeTruthy()
  // ⭐ 屏幕上**不许**出现任何"离线"字样(快照横幅已被 `!online` 挡掉)
  expect(screen.queryByText(/离线/)).toBeNull()
})

test('⚠️ 在线 4xx 且**无**快照 ⇒ 只说错误,不许说"离线,且还没有本地快照"(F2 / G10)', async () => {
  // ③句那一处修复前无条件挂在 `err !== null` 下 ⇒ 在线 4xx 也会说"离线"。
  stub404Api()
  render(<Feed {...feedProps} />)
  expect(await screen.findByText(/读取失败/)).toBeTruthy()
  expect(screen.queryByText(/离线/)).toBeNull()
})

test('⚠️ 在线 4xx + 盘上有快照 ⇒ Digests 也如实报错、不说"离线"(F2:Digests 两处)', async () => {
  writeSnapshot({ synced_at: SNAPSHOT_TS, feed: [], calendar: [], digests: [DIGEST] })
  stub404Api()
  render(<Digests />)
  // ⭐ 快照照常回落,但**错误仍如实报出**(在线 4xx 不是"离线")
  expect(await screen.findByText('2026-10-05')).toBeTruthy()
  expect(screen.getByText(/日报读取失败/)).toBeTruthy()
  expect(screen.queryByText(/离线/)).toBeNull()
})

test('⚠️ 在线 4xx 且**无**快照 ⇒ Digests 不说"离线,且还没有本地快照"(F2:③句那一处)', async () => {
  stub404Api()
  render(<Digests />)
  expect(await screen.findByText(/日报读取失败/)).toBeTruthy()
  expect(screen.queryByText(/离线/)).toBeNull()
})

test('⚠️ 在线 4xx ⇒ App 离线横幅**不出现**(F2:横幅只认 `!online`)', async () => {
  // 阴性对照的一半:App 横幅本来就带 `!online`(审查 PROBE-D5 = 0)⇒ 在线 4xx 时不许出现。
  stub404Api()
  render(<App />)
  expect(await screen.findByText(/读取失败/)).toBeTruthy()
  expect(screen.queryByText(/写操作不可用/)).toBeNull()
})

test('⚠️ 网络通 ⇒ 用实时数据(快照只是备份,不是显示源)【上一条的阴性对照】', async () => {
  writeSnapshot({
    synced_at: SNAPSHOT_TS,
    feed: [item(7, '快照里的停水通知')],
    calendar: [],
    digests: [],
  })
  stubOkApi([item(8, '实时读到的条目')])
  render(<Feed {...feedProps} />)
  expect(await screen.findByText('实时读到的条目')).toBeTruthy()
  expect(screen.queryByText('快照里的停水通知')).toBeNull()
  expect(screen.queryByText(/本地快照（/)).toBeNull()
})

test('⚠️ 离线时只回落一次:失鲜的请求不许把快照也一起报成失败', async () => {
  // 阴性对照的一半:失败**不**回落成错误横幅——列表里是快照,不是"读取失败"。
  writeSnapshot({
    synced_at: SNAPSHOT_TS,
    feed: [item(7, '快照里的停水通知')],
    calendar: [],
    digests: [],
  })
  stubDeadApi()
  render(<Feed {...feedProps} />)
  await screen.findByText('快照里的停水通知')
  expect(screen.queryByText(/读取失败/)).toBeNull()
})

test('⚠️ StrictMode(挂→卸→挂)下订阅仍然活着:恢复在线时重取一次(不重复订阅)', async () => {
  /**
   * ⭐ 反问「`setOnline` 与 `subscribeConnectivity` 在 StrictMode 下有没有重复订阅」。
   *
   * 结构上:`useEffect(() => subscribeConnectivity(fn), [])` 的 effect **返回**
   * 退订函数 ⇒ StrictMode 的「卸」会摘掉第一个订阅、「挂」再装一个 ⇒ 净剩 1 个。
   *
   * ⚠️ 本条能钉的是**一半**(而且是一半里更危险的那一半):「卸」把订阅摘掉之后
   * **「挂」必须真的装回来**——写错成 `useEffect(() => { subscribeConnectivity(fn); return () => {} })`
   * 或 cleanup 里多摘一次,恢复在线时就**再也没有重取**。
   * 另**一半**(「装了两个」)在本层的可见面上**测不出来**:重复的监听器是同一句
   * `setOnline(isOnline())`,两次调用同值在 React 里被批处理成一个 —— 那是同值 no-op,
   * 屏幕上看不见任何差别。⇒ 如实记入报告 concerns,不假装它被守住了。
   */
  stubOkApi([item(8, '实时读到的条目')])
  render(
    <StrictMode>
      <Feed {...feedProps} />
    </StrictMode>,
  )
  await screen.findByText('实时读到的条目')

  const before = stubOkApiCalls.filter((u) => u.startsWith('/api/items')).length
  await act(async () => {
    window.dispatchEvent(new Event('offline'))
  })
  await act(async () => {
    window.dispatchEvent(new Event('online'))
  })
  await waitFor(() => {
    expect(stubOkApiCalls.filter((u) => u.startsWith('/api/items')).length).toBeGreaterThan(before)
  })
})

test('⚠️ **离线挂载** Feed ⇒ 那个"在线"合取项是**承重**的(F1):不许白发第二次首屏', async () => {
  /**
   * ⭐⭐ F1 —— 审查**证伪**了上一轮报告里那句"变异 E 不可观测、`online &&`
   * 纯防御性"。这里用**请求计数**把它钉成可观测:
   *
   * ⚠️ 关键前提是**离线挂载**(用户离线时打开 PWA —— 出口标准 2/3 的场景本身):
   * 此时 `useRef(online)` 的初值就是 `false` ⇒ 派生 effect 第一次跑时
   * `wasOnline === false`。
   *   · 根治版 `if (online && !wasOnline)`:当前也离线 ⇒ 为假 ⇒ **不**+1
   *   · E 版(只留 `!wasOnline`):`!wasOnline` 为真 ⇒ **+1** ⇒ 把首屏取数 effect
   *     **多跑一次**(一次必然失败的请求)——审查探针实测 `expected 2 to be 1`
   *
   * ⚠️ 必须**先 `noteFetchResult(false)` 再 render**:否则挂载那一刻
   * `navigator.onLine`(jsdom 默认 true)让 `online===true`,E 与根治版**同绿**
   * ——这正是上一轮报告误判"不可观测"的由来(它在**在线挂载**的输入面上试的)。
   *
   * ⚠️ 变异反证:`if (online && !wasOnline)` → `if (!wasOnline)` ⇒ 本条必红
   * (请求数 2 而非 1)。
   */
  _resetForTests()
  noteFetchResult(false) // 离线:挂载时 `online` 为 false(用户离线打开)
  const calls = stubDeadApi()
  render(<Feed {...feedProps} />)
  // 先等它能"停"下来:离线首屏失败后一定渲染出那条错误横幅
  expect(await screen.findByText(/读取失败/)).toBeTruthy()
  // 再给"派生 effect"足够时间走完(它若 +1,取数 effect 会再发一次)
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0))
  })
  // 离线挂载该**只**取一次首屏:没有任何东西能证明"此刻在线"
  expect(calls.filter((u) => u.startsWith('/api/items')).length).toBe(1)
})

// ── Digests:离线回落快照 ──────────────────────────────────────────────

test('⚠️ 离线但有快照 ⇒ 日报列表与正文都从快照来,并写明同步时刻', async () => {
  /**
   * 快照里的日报是 `DigestDetail[]`(带正文),而列表要的是 `DigestSummary`
   * ——后者本就是前者的子集,显式挑字段而不是硬转类型。
   *
   * ⚠️ 打开正文**不该再发请求**:快照里就有正文,离线下那个请求必然失败,
   * 失败了再把用户刚点开的那一篇报成"读取失败"是自找的。
   */
  writeSnapshot({ synced_at: SNAPSHOT_TS, feed: [], calendar: [], digests: [DIGEST] })
  stubDeadApi()
  render(<Digests />)

  expect(await screen.findByText('2026-10-05')).toBeTruthy()
  expect(screen.getByText(new RegExp(SNAPSHOT_LABEL))).toBeTruthy()
  // ⚠️ 原文(不是 `/本地快照（/`):F2 的变异必须能让这里红 ⇒ 也用原文钉住。
  expect(
    screen.getByText(`离线：显示的是本地快照（${SNAPSHOT_LABEL} 同步）。`),
  ).toBeTruthy()

  await userEvent.click(screen.getByRole('button', { name: /2026-10-05/ }))
  expect(await screen.findByText('快照里的日报正文。')).toBeTruthy()
})

test('⚠️ 离线且无快照 ⇒ 说"离线，且还没有本地快照",不许说"还没有日报"(G10)', async () => {
  stubDeadApi()
  render(<Digests />)
  expect(await screen.findByText(/离线，且还没有本地快照/)).toBeTruthy()
  expect(screen.queryByText(/还没有日报/)).toBeNull()
})

// ── App:同步时机 + 离线横幅 + 撤销置灰 ────────────────────────────────

test('⚠️ 在线挂载 ⇒ 同步一次快照(离线才有的那份数据)', async () => {
  const calls = stubOkApi([])
  stubOkApiCalls = calls
  render(<App />)
  await waitFor(() => expect(readSnapshot()).not.toBeNull())
  expect(calls.some((u) => u.startsWith('/api/calendar'))).toBe(true)
})

test('⚠️ 离线挂载 ⇒ 不同步快照(`if (!online) return` 的守卫,变异 3)', async () => {
  /**
   * ⚠️ 变异反证:把 `App.tsx` 的 `if (!online) return` 删掉 ⇒ 本条必红
   * (离线也去发三组快照请求,`/api/calendar` 会出现)。
   */
  _resetForTests()
  noteFetchResult(false)
  const calls = stubDeadApi()
  render(<App />)
  await screen.findByText(/离线/)
  expect(calls.some((u) => u.startsWith('/api/calendar'))).toBe(false)
})

test('⚠️ 在线事件连发 ⇒ 每次"离线→在线"只同步一次(不风暴)', async () => {
  /**
   * ⭐ 反问「`syncSnapshot` 在离线事件连发时会不会风暴」的守卫。
   * 机制:`connectivity.set()` 对**同值**短路 ⇒ 连发同一事件只通知一次;
   * 而 App 的同步 effect 挂在 `[online]` 上 ⇒ 每次真实的「断→通」边沿同步一次,
   * 不随事件条数增长。三次边沿 ⇒ 恰好三次同步(不是 3N 次)。
   */
  const calls = stubOkApi([])
  stubOkApiCalls = calls
  render(<App />)
  await waitFor(() => expect(readSnapshot()).not.toBeNull())
  const base = calls.filter((u) => u.startsWith('/api/calendar')).length

  for (let i = 0; i < 3; i++) {
    await act(async () => {
      window.dispatchEvent(new Event('offline'))
      window.dispatchEvent(new Event('offline'))
      window.dispatchEvent(new Event('offline'))
    })
    await act(async () => {
      window.dispatchEvent(new Event('online'))
      window.dispatchEvent(new Event('online'))
      window.dispatchEvent(new Event('online'))
    })
  }

  await waitFor(() => {
    expect(calls.filter((u) => u.startsWith('/api/calendar')).length).toBe(base + 3)
  })
})

test('⚠️ 离线 ⇒ 头部有横幅、撤销置灰(出口标准 3)', async () => {
  _resetForTests()
  noteFetchResult(false)
  stubDeadApi()
  render(<App />)
  expect(await screen.findByText(/离线/)).toBeTruthy()
  expect((screen.getByRole('button', { name: /撤销/ }) as HTMLButtonElement).disabled).toBe(true)
})

test('⚠️ 在线 ⇒ 撤销可用(上一条的阴性对照)', async () => {
  stubOkApi([])
  render(<App />)
  await screen.findByText('还没有任何条目。')
  expect((screen.getByRole('button', { name: /撤销/ }) as HTMLButtonElement).disabled).toBe(false)
})

test('⚠️ ARGUS 主题 + 离线 ⇒ 头部那个 ↶undo 也置灰(F3:G9 的同一条要求)', async () => {
  /**
   * ⭐ F3 —— 上一轮**变异全绿**:把 `App.tsx` ARGUS 头部那个 `↶undo` 的
   * `disabled={!online}` 删掉,205 全绿 ⇒ 该分支的置灰**没有任何判据**。
   * brief Step 6 要求"撤销按钮加 `disabled={!online}`",ARGUS 分支属同一条要求。
   *
   * ⚠️ 起渲染的方式照 `argusBrand.dom.test.tsx`:`localStorage.setItem('vigil.theme','argus')`
   * —— `App` 的 `useState(readTheme)` 是惰性初始化 ⇒ 挂载时读盘。
   * ⚠️ ARGUS 那个按钮的名字是 `↶undo`(**不是**默认主题的 `↶ 撤销`),
   * 所以 `queryByRole('button', {name:/撤销/})` 在 ARGUS 下恒为 null —— 必须按它自己的名字找。
   */
  localStorage.setItem('vigil.theme', 'argus')
  _resetForTests()
  noteFetchResult(false)
  stubDeadApi()
  render(<App />)
  await screen.findByText(/离线/)
  const undo = screen.getByRole('button', { name: /undo/ }) as HTMLButtonElement
  expect(undo.disabled).toBe(true)
  // ⚠️ 同时钉住"这确实是 ARGUS 那套头部":默认主题的按钮叫"↶ 撤销",不叫"↶undo"。
  // 这是"判据够到了 ARGUS 分支"的证据(否则 find 到的可能是另一套头部的按钮)。
  expect(screen.queryByRole('button', { name: /^↶ 撤销$/ })).toBeNull()
})

test('⚠️ ARGUS 主题 + 在线 ⇒ ↶undo 可用(上一条的阴性对照:F3 不是"恒置灰")', async () => {
  localStorage.setItem('vigil.theme', 'argus')
  stubOkApi([])
  render(<App />)
  await screen.findByText('还没有任何条目。')
  const undo = screen.getByRole('button', { name: /undo/ }) as HTMLButtonElement
  expect(undo.disabled).toBe(false)
})

test('⚠️ 快照同步失败不该影响页面(它是"锦上添花")', async () => {
  /**
   * ⚠️ `void syncSnapshot().catch(() => {})` 里那个 `.catch` 的守卫:
   * 快照拉不到只意味着"离线时少一份数据",不该把页面弄崩或弹一堆错误。
   */
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
      if (url.startsWith('/api/categories')) return ok({ categories: [] })
      if (url.startsWith('/api/persons')) return ok({ persons: [] })
      // 快照那一组全 500 ⇒ syncSnapshot 抛
      if (url.startsWith('/api/calendar')) return { ok: false, status: 500, json: async () => ({ detail: '内部错误' }) }
      if (url.startsWith('/api/digests')) return { ok: false, status: 500, json: async () => ({ detail: '内部错误' }) }
      if (url.startsWith('/api/items')) return ok({ items: [item(9, '页面照常渲染')], total: 1, limit: 50, offset: 0 })
      return ok({})
    }),
  )
  render(<App />)
  expect(await screen.findByText('页面照常渲染')).toBeTruthy()
  expect(readSnapshot()).toBeNull() // 失败不写半份
})
