import { useEffect, useState } from 'react'
import type { CategoryDetail, GroupRow, JobRow, LlmSettings } from '../types.ts'
import * as api from '../api.ts'

// 「配置」tab —— M6 的全部意义：`config/*.toml` 从「手工编辑的文件」变成
// 「网页上可增删改的配置」。
//
// ⚠️ **四节各自持有自己的数据与自己的 refresh**（`tick`），**没有一个全局 token**：
// 一个全局 token 会让「改了一个群」顺带重取另外三节的数据，而那三节的数据
// 根本没变。但**「提交 ⇒ 重取」这个模式四节必须一致**——不一致就是 M5 那两个
// 「改完界面不更新」的缺陷换个页面重演（出口判据 1 的界面形态）。

type Section = 'groups' | 'persons' | 'llm' | 'categories' | 'reorder' | 'pack'

const SECTIONS: { key: Section; label: string }[] = [
  { key: 'groups', label: '群' },
  { key: 'persons', label: '人物' },
  { key: 'llm', label: 'LLM' },
  { key: 'categories', label: '类目' },
  { key: 'reorder', label: '重排' },
  { key: 'pack', label: '导入导出' },
]

export default function Settings() {
  const [section, setSection] = useState<Section>('groups')
  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            onClick={() => setSection(s.key)}
            className={
              'rounded-full px-3 py-1 text-xs ' +
              (section === s.key ? 'bg-sky-500/20 text-sky-300' : 'bg-white/5 text-white/55')
            }
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="mt-4">
        {section === 'groups' && <GroupsSection />}
        {section === 'persons' && <PersonsSection />}
        {section === 'llm' && <LlmSection />}
        {section === 'categories' && <CategoriesSection />}
        {section === 'reorder' && <ReorderSection />}
        {section === 'pack' && <PackSection />}
      </div>
    </div>
  )
}

// ── 群 ────────────────────────────────────────────────────────────────

function GroupsSection() {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.fetchGroups>> | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const [id, setId] = useState('')
  const [name, setName] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  // ⚠️ **提交中必须禁掉按钮**（Fix loop 1 / m5）：一次请求在飞的时候再点一下，
  // 第二次多半撞 409「群已经在配置里了」——而那句红字会盖掉第一句成功提示，
  // 用户看到的是"我刚加的那个群报错了"（与 `ItemCard` 的 `busy` 同形）。
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    setErr(null)
    api.fetchGroups().then(setData).catch((e) => {
      setErr(e instanceof Error ? e.message : String(e))
      setData(null)
    })
  }, [tick])

  async function submit() {
    setMsg(null)
    const n = Number(id.trim())
    if (!Number.isInteger(n) || n <= 0) {
      setMsg('群号必须是正整数')
      return
    }
    setBusy(true)
    try {
      await api.addGroup(n, name.trim(), 'normal')
      setMsg(`已加入 ${n}。⚠️ 下次 vigil export 会拉它的**全部历史**——首轮实测大群约 1,664 条 / 21 批 / 6.3 分钟。`)
      setId(''); setName('')
      setTick((t) => t + 1)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (err !== null) return <p className="text-sm text-red-400">读取失败：{err}</p>
  if (data === null) return <p className="text-sm text-white/40">读取中…</p>

  // ⚠️ **没有快照时明说**，绝不画一张空表：空表会被读成
  // 「你的 QQ 库里一个群都没有」——一句假话（与后端 `available:false` 同一条判据）。
  if (!data.available) {
    return (
      <div className="rounded-lg bg-amber-500/10 p-3 text-sm text-amber-200">
        <p>{data.reason}</p>
      </div>
    )
  }

  return (
    <div>
      <p className="text-xs text-white/40">
        清单来自 {new Date(data.generated_at! * 1000).toLocaleString('zh-CN')} 的快照
        （由 vigil export 生成）。刚加进 QQ 的群要等下次 export 才看得见。
      </p>
      <ul className="mt-3 space-y-1">
        {data.groups.map((g) => (
          <GroupRowView key={g.id} g={g} onChanged={() => setTick((t) => t + 1)} />
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap gap-2">
        <input value={id} onChange={(e) => setId(e.target.value)} placeholder="群号"
               className="w-32 rounded-lg bg-white/5 px-2 py-1.5 text-sm" />
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="群名"
               className="flex-1 rounded-lg bg-white/5 px-2 py-1.5 text-sm" />
        <button onClick={submit} disabled={busy}
                className="rounded-lg bg-sky-500/20 px-3 py-1.5 text-sm text-sky-200 disabled:opacity-40">
          加入监视
        </button>
      </div>
      {msg !== null && <p className="mt-2 text-xs text-white/60">{msg}</p>}
    </div>
  )
}

function GroupRowView({ g, onChanged }: { g: GroupRow; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setErr(null)
    try { await fn(); onChanged() }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }

  return (
    <li className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2 text-sm">
      <span className="flex-1 truncate">
        {g.name || '(无名)'} <span className="text-white/40">{g.id}</span>
        <span className="ml-2 text-xs text-white/40">{g.messages.toLocaleString()} 条</span>
      </span>
      {g.watched ? (
        <>
          <button disabled={busy}
                  onClick={() => act(() => api.patchGroup(g.id, { enabled: false }))}
                  className="rounded px-2 py-1 text-xs text-white/50">
            停用
          </button>
          <button disabled={busy} onClick={() => act(() => api.removeGroup(g.id))}
                  className="rounded px-2 py-1 text-xs text-red-300">
            移除
          </button>
        </>
      ) : (
        <button disabled={busy} onClick={() => act(() => api.addGroup(g.id, g.name, 'normal'))}
                className="rounded px-2 py-1 text-xs text-sky-300">
          加入监视
        </button>
      )}
      {err !== null && <span className="text-xs text-red-400">{err}</span>}
    </li>
  )
}

// ── 人物 ──────────────────────────────────────────────────────────────
//
// ⚠️ 这一节与 `components/PersonPicker.tsx` 的**请求与表单是同源的**，
// 但没有抽公共组件，理由两条（brief 允许「抽不动就照抄 + 说明为什么」）：
//
//   ① 两者的**展示形态**不同：`PersonPicker` 是一个可折叠的**筛选器**
//      （选中的 uin 要回传给 Feed，删除时还要把它从当前筛选里摘掉），
//      而这里是配置页的一个**管理列表**（没有选中态、不需要折叠）。
//      抽出来的共享件必须同时服务两种交互，它的 props 会长出
//      「有没有选中态」「删完要不要回调筛选」这类分支——**抽象的成本
//      比省下的那 30 行高**。
//   ② `PersonPicker` 挂在信息流页上，有 DOM 用例经过它。为一个纯展示差异
//      去改一个正在工作的组件，收益是"少 30 行"，代价是**把 Feed 页拖进
//      这次改动的影响面**。
//
// ⚠️ 但**两条验证必须与它一致**（照抄的是行为）：QQ 号必须是正整数、
// 名字不能空——那两句提示是同一个用户问题的同一个答案，不许漂移。

function PersonsSection() {
  const [people, setPeople] = useState<Awaited<ReturnType<typeof api.fetchPersons>>['persons'] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [uin, setUin] = useState('')
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    setErr(null)
    api.fetchPersons().then((r) => setPeople(r.persons)).catch((e) => {
      setErr(e instanceof Error ? e.message : String(e))
      setPeople(null)
    })
  }, [tick])

  async function add() {
    const n = Number(uin.trim())
    if (!Number.isInteger(n) || n <= 0) {
      setErr('QQ 号必须是正整数（0 不是有效账号）')
      return
    }
    if (!label.trim()) {
      setErr('给它起个名字——群昵称会变，这个名字不会')
      return
    }
    setBusy(true)
    setErr(null)
    setMsg(null)
    try {
      await api.addPerson(n, label.trim())
      setUin('')
      setLabel('')
      setMsg(`已监视 ${n}。`)
      setTick((t) => t + 1)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function drop(n: number) {
    setBusy(true)
    setErr(null)
    setMsg(null)
    try {
      await api.removePerson(n)
      setTick((t) => t + 1)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      {err !== null && <p className="mb-2 text-xs text-red-400">{err}</p>}
      {people === null && err === null && <p className="text-sm text-white/40">读取中…</p>}
      {people !== null && people.length === 0 && (
        <p className="text-sm text-white/40">还没有监视任何人。在下面加一个 QQ 号。</p>
      )}
      <ul className="space-y-1">
        {(people ?? []).map((p) => (
          <li key={p.uin} className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2 text-sm">
            <span className="flex-1 truncate">
              {p.label} <span className="text-white/40">{p.uin}</span>
              <span className="ml-2 text-xs text-white/40">{p.count} 条</span>
            </span>
            <button disabled={busy} onClick={() => drop(p.uin)}
                    className="rounded px-2 py-1 text-xs text-red-300">
              移除
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap gap-2">
        <input value={uin} onChange={(e) => setUin(e.target.value)} inputMode="numeric"
               placeholder="QQ 号"
               className="w-32 rounded-lg bg-white/5 px-2 py-1.5 text-sm" />
        <input value={label} onChange={(e) => setLabel(e.target.value)}
               placeholder="名字（辅导员某辅导员）"
               className="flex-1 rounded-lg bg-white/5 px-2 py-1.5 text-sm" />
        <button onClick={add} disabled={busy}
                className="rounded-lg bg-sky-500/20 px-3 py-1.5 text-sm text-sky-200 disabled:opacity-40">
          新增
        </button>
      </div>
      {msg !== null && <p className="mt-2 text-xs text-white/60">{msg}</p>}
    </div>
  )
}

// ── LLM ───────────────────────────────────────────────────────────────

const THINKING_CHOICES = [
  { value: 'omit', label: '不发这个字段（通用 OpenAI 端点用这个）' },
  { value: 'false', label: '发 false（硅基流动 / Qwen 用这个）' },
  { value: 'true', label: '发 true' },
] as const

type ThinkingChoice = (typeof THINKING_CHOICES)[number]['value']

function choiceOf(v: boolean | null): ThinkingChoice {
  return v === null ? 'omit' : v ? 'true' : 'false'
}

function describeThinking(v: boolean | null): string {
  return v === null ? '不发这个字段' : `发 ${v}`
}

function LlmSection() {
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [thinking, setThinking] = useState<ThinkingChoice>('omit')
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.fetchLlmSettings()
      .then((s) => {
        setBaseUrl(s.base_url)
        setModel(s.model)
        setThinking(choiceOf(s.enable_thinking))
      })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
  }, [])

  async function save() {
    setBusy(true)
    setMsg(null)
    setErr(null)
    try {
      const s: LlmSettings = {
        base_url: baseUrl.trim(),
        model: model.trim(),
        // ⚠️ 'omit' 必须发 **null**（= 不发这个字段），**不是 `false`**：
        // 两者在界面上看不出区别，报文里却是两个不同的东西——`false` 发给
        // 通用 OpenAI 端点会 400，而"不发"对 Qwen3 混合思考模型意味着慢 40 倍。
        enable_thinking: thinking === 'omit' ? null : thinking === 'true',
      }
      const back = await api.saveLlmSettings(s)
      // ⚠️ 三个字段都按**服务端回给的那个值**回填，不是留着本地的输入框状态
      // （Fix loop 1 / m3）。
      //
      // ⚠️ 这句注释原来只说了半句真话（reviewer 抓到的）：那时只有 `thinking`
      // 真的回填了，`base_url`/`model` 还是本地 state——而**本地 state 与服务端
      // 存下去的值是可以不同的**：`save()` 发出去的是 `trim()` 过的，输入的
      // 首尾空白会被后端丢掉。于是"所见即所存"这句话在界面上不成立，
      // 用户看到的还是他自己那串带空白的输入。
      // 两处一起改（注释 + 行为）：`trim()` 是**写侧的归一化**，
      // 界面上必须看得见它的结果——不然下一次 `GET` 回来会"变样"。
      setBaseUrl(back.base_url)
      setModel(back.model)
      setThinking(choiceOf(back.enable_thinking))
      setMsg(`已保存：${back.base_url} · ${back.model} · ${describeThinking(back.enable_thinking)}`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <label className="block">
        <span className="text-xs text-white/55">端点（base_url）</span>
        <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)}
               placeholder="https://api.siliconflow.cn/v1/chat/completions"
               className="mt-1 w-full rounded-lg bg-white/5 px-2 py-1.5 text-sm" />
      </label>
      <label className="block">
        <span className="text-xs text-white/55">模型</span>
        <input value={model} onChange={(e) => setModel(e.target.value)}
               placeholder="Qwen/Qwen3.5-35B-A3B"
               className="mt-1 w-full rounded-lg bg-white/5 px-2 py-1.5 text-sm" />
      </label>
      <label className="block">
        <span className="text-xs text-white/55">enable_thinking</span>
        <select value={thinking} onChange={(e) => setThinking(e.target.value as ThinkingChoice)}
                className="mt-1 w-full rounded-lg bg-white/5 px-2 py-1.5 text-sm">
          {THINKING_CHOICES.map((c) => (
            <option key={c.value} value={c.value}>{c.label}</option>
          ))}
        </select>
      </label>
      <p className="text-xs text-white/40">
        ⚠️ 密钥**不在**这份配置里（它走仓库根的 <code>.env</code>），所以这里也没有它的输入框。
      </p>
      <button onClick={save} disabled={busy}
              className="rounded-lg bg-sky-500/20 px-3 py-1.5 text-sm text-sky-200 disabled:opacity-40">
        保存
      </button>
      {err !== null && <p className="text-xs text-red-400">{err}</p>}
      {msg !== null && <p className="text-xs text-white/60">{msg}</p>}
    </div>
  )
}

// ── 类目 ──────────────────────────────────────────────────────────────

function CategoriesSection() {
  const [cats, setCats] = useState<CategoryDetail[]>([])
  const [aliases, setAliases] = useState<Record<string, string>>({})
  const [tick, setTick] = useState(0)
  const [msg, setMsg] = useState<string | null>(null)
  // ⚠️ 「有 N 条属于它，迁移到哪个？」——**必须是一个真的选择**，
  // 不是一个 `window.confirm`（那没法让用户挑目标类目）。
  const [pending, setPending] = useState<CategoryDetail | null>(null)
  const [migrateTo, setMigrateTo] = useState('')
  // ⚠️ **新增与编辑都必须在这里**：`desc` 是**逐字进 LLM 提示词的判据**
  // （见 `types.ts` 的 `CategoryDetail`），只读的列表等于把那个字段锁死在
  // 手编 `categories.toml` 里——那正是本里程碑要消灭的东西。
  const [draft, setDraft] = useState({ slug: '', label: '', desc: '', icon: '' })
  const [editing, setEditing] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState({ slug: '', label: '', desc: '', icon: '' })

  useEffect(() => {
    api.fetchCategoriesDetailed()
      .then((r) => { setCats(r.categories); setAliases(r.aliases) })
      .catch((e) => setMsg(e instanceof Error ? e.message : String(e)))
  }, [tick])

  async function doDelete() {
    if (pending === null) return
    try {
      await api.removeCategory(pending.slug, migrateTo || undefined)
      setMsg(`已删除「${pending.label}」` + (migrateTo ? `，${pending.count} 条已并入「${migrateTo}」` : ''))
      setPending(null); setMigrateTo('')
      setTick((t) => t + 1)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    }
  }

  async function doAdd() {
    try {
      await api.addCategory(
        draft.slug.trim(), draft.label.trim(), draft.desc, draft.icon.trim(),
      )
      setMsg(`已新增「${draft.label.trim()}」。它在信息流的类目筛选里**立刻**可见。`)
      setDraft({ slug: '', label: '', desc: '', icon: '' })
      setTick((t) => t + 1)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    }
  }

  async function doEdit(slug: string) {
    try {
      await api.updateCategory(slug, {
        slug: editDraft.slug.trim(),
        label: editDraft.label.trim(),
        desc: editDraft.desc,
        icon: editDraft.icon.trim(),
      })
      // ⚠️ 改名走的是**别名**（旧 slug 的条目不改 `item_id`，spec D16）：
      // 所以这里必须说清"改了名之后旧名字留下了什么"，否则用户会以为
      // 条目丢了（它们只是从此按新名字显示）。
      setMsg(
        editDraft.slug.trim() !== slug
          ? `已把「${slug}」改名为「${editDraft.slug.trim()}」——旧名字下的条目现在按新名字显示。`
          : `已保存「${editDraft.label.trim()}」。`,
      )
      setEditing(null)
      setTick((t) => t + 1)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div>
      <ul className="space-y-1">
        {cats.map((c) => (
          <li key={c.slug} className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2 text-sm">
            <span>{c.icon} {c.label}</span>
            <span className="text-xs text-white/40">{c.slug} · {c.count} 条</span>
            <button className="ml-auto rounded px-2 py-1 text-xs text-white/50"
                    onClick={() => {
                      setEditing(c.slug)
                      setEditDraft({ slug: c.slug, label: c.label, desc: c.desc, icon: c.icon })
                    }}>
              编辑
            </button>
            <button className="rounded px-2 py-1 text-xs text-white/50"
                    onClick={() => { setPending(c); setMigrateTo('') }}>
              删除
            </button>
          </li>
        ))}
      </ul>

      {editing !== null && (
        <div className="mt-3 rounded-lg bg-white/5 p-3">
          <p className="text-xs text-white/55">
            编辑「{editing}」——改 slug 等于**改名**：旧名字下的条目不改 id，
            从此按新名字显示（这条映射会留在下面的「改过名的类目」里）。
          </p>
          <div className="mt-2 grid gap-1.5">
            <input value={editDraft.icon} onChange={(e) => setEditDraft({ ...editDraft, icon: e.target.value })}
                   placeholder="图标（emoji）" className="rounded-lg bg-black/30 px-2 py-1 text-xs" />
            <input value={editDraft.label} onChange={(e) => setEditDraft({ ...editDraft, label: e.target.value })}
                   placeholder="中文名" className="rounded-lg bg-black/30 px-2 py-1 text-xs" />
            <input value={editDraft.slug} onChange={(e) => setEditDraft({ ...editDraft, slug: e.target.value })}
                   placeholder="slug（英文/数字/-）" className="rounded-lg bg-black/30 px-2 py-1 text-xs" />
            <textarea value={editDraft.desc} onChange={(e) => setEditDraft({ ...editDraft, desc: e.target.value })}
                      rows={2} placeholder="判据（会逐字进 LLM 提示词）"
                      className="rounded-lg bg-black/30 px-2 py-1 text-xs" />
          </div>
          <div className="mt-2 flex gap-2">
            <button onClick={() => doEdit(editing)}
                    className="rounded-lg bg-sky-500/20 px-3 py-1 text-xs text-sky-200">
              保存
            </button>
            <button onClick={() => setEditing(null)}
                    className="rounded-lg bg-white/5 px-3 py-1 text-xs text-white/60">
              取消
            </button>
          </div>
        </div>
      )}

      <div className="mt-4 border-t border-white/10 pt-3">
        <p className="text-xs text-white/55">新增类目</p>
        <div className="mt-1 flex flex-wrap gap-1.5">
          <input value={draft.icon} onChange={(e) => setDraft({ ...draft, icon: e.target.value })}
                 placeholder="图标" className="w-16 rounded-lg bg-white/5 px-2 py-1 text-xs" />
          <input value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })}
                 placeholder="中文名" className="w-28 rounded-lg bg-white/5 px-2 py-1 text-xs" />
          <input value={draft.slug} onChange={(e) => setDraft({ ...draft, slug: e.target.value })}
                 placeholder="slug" className="w-28 rounded-lg bg-white/5 px-2 py-1 text-xs" />
          <input value={draft.desc} onChange={(e) => setDraft({ ...draft, desc: e.target.value })}
                 placeholder="判据（会逐字进 LLM 提示词）"
                 className="flex-1 rounded-lg bg-white/5 px-2 py-1 text-xs" />
          <button onClick={doAdd} disabled={!draft.slug.trim() || !draft.label.trim()}
                  className="rounded-lg bg-sky-500/20 px-3 py-1 text-xs text-sky-200 disabled:opacity-40">
            新增
          </button>
        </div>
      </div>

      {pending !== null && (
        <div className="mt-3 rounded-lg bg-amber-500/10 p-3 text-sm text-amber-100">
          {pending.count > 0 ? (
            <>
              <p>⚠️ 「{pending.label}」还有 **{pending.count} 条**条目指着它。删之前必须选一个迁移目标——否则那些条目会指向一个不存在的类目。</p>
              <select value={migrateTo} onChange={(e) => setMigrateTo(e.target.value)}
                      className="mt-2 rounded-lg bg-black/30 px-2 py-1 text-sm">
                <option value="">— 选一个 —</option>
                {cats.filter((c) => c.slug !== pending.slug).map((c) => (
                  <option key={c.slug} value={c.slug}>{c.icon} {c.label}</option>
                ))}
              </select>
            </>
          ) : (
            <p>「{pending.label}」下没有任何条目，可以直接删除。</p>
          )}
          <div className="mt-2 flex gap-2">
            <button onClick={doDelete} disabled={pending.count > 0 && !migrateTo}
                    className="rounded-lg bg-red-500/20 px-3 py-1 text-xs text-red-200 disabled:opacity-40">
              确认删除
            </button>
            <button onClick={() => setPending(null)}
                    className="rounded-lg bg-white/5 px-3 py-1 text-xs text-white/60">
              取消
            </button>
          </div>
        </div>
      )}

      {Object.keys(aliases).length > 0 && (
        <p className="mt-3 text-xs text-white/40">
          改过名的类目：{Object.entries(aliases).map(([o, n]) => `${o} → ${n}`).join('、')}
        </p>
      )}
      {/* ⚠️ **必须有 `.catch()`**（Fix loop 1 / m1）：没有它的话，撤销失败
          （空栈时后端 409、overlay 锁住时 5xx）会变成一条**未处理的 rejection**
          ——控制台里一行红字，而**界面上一个字都没有**：用户点了撤销、
          什么都没发生、也没有任何话说。与同文件其它失败分支同形处理。 */}
      <button
        onClick={() =>
          api
            .undoCategorieChange()
            .then(() => setTick((t) => t + 1))
            .catch((e) => setMsg(e instanceof Error ? e.message : String(e)))
        }
        className="mt-3 rounded-lg bg-white/5 px-3 py-1.5 text-xs text-white/60"
      >
        ↶ 撤销上一次类目改动
      </button>
      {msg !== null && <p className="mt-2 text-xs text-white/60">{msg}</p>}
    </div>
  )
}

// ── 重排（job）────────────────────────────────────────────────────────
//
// ⚠️ 这一节是 **M6 的计划补遗**：原计划的 T9 只写了「四节 + 导入导出」，
// 漏了 spec §4.2 ④ 的「重排 = LLM 重判 + **界面上多选批量改**」。
// 后果是具体的：出口判据 7（撤销能回到重排前）在 **API 层成立**（5 条用例全绿），
// 而 `/api/jobs/{id}/cancel`、`/api/items/kinds`、`/api/bulk-undo` 在 `web/` 里
// **零引用** ⇒ 用户够不到 ⇒ **那个特性事实上不存在**。
//
// 三条刻意的形状，每一件都有一个具体的坏法：
//   ① `job_id` 落 `localStorage`：重排要跑 1–2 分钟，用户很可能刷新页面。
//      不存的话刷新一次就再也看不到那个 job 的结果了，而它**还在服务端跑着**、
//      还占着唯一的 `JobBusy` 名额（再点「开始重排」拿到 409，却不知道为什么）。
//   ② 轮询的依赖列表里 `job?.job_id` 与 `job?.state` **两个都要**：放整个 `job`
//      对象会每 1 秒重建一次 interval（对象每次渲染都是新的引用），
//      只放 `job_id` 又会漏掉"状态变了要停"（interval 到终态还活着，白问一辈子）。
//   ③ 「取消重排」只在 `running` 时出现；「撤销这次重排」只在**非 running 且
//      `actor` 非空**时出现——`actor` 是那一批改动的键，空的话撤无可撤。

// ⚠️ 模块级常量取名带前缀（而不是 brief 里的裸 `KEY`）：它和别的 section 在
// 同一个模块作用域里，一个叫 `KEY` 的常量在这里是一颗随时会被撞上的雷。
const REORDER_JOB_KEY = 'vigil.reorder.job'

const JOB_STATE_LABEL: Record<JobRow['state'], string> = {
  running: '运行中',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

function ReorderSection() {
  const [job, setJob] = useState<JobRow | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  // ⚠️ 提交中必须禁掉按钮（与 `GroupsSection` 的 `busy` 同形）：一次请求在飞的
  // 时候再点一下，第二次多半撞 409「已经有一个后台任务在跑了」，而那句红字会
  // 盖掉第一句成功提示——用户看到的是"我刚点的重排报错了"。
  const [busy, setBusy] = useState(false)
  // 撤过一次（无论撤没撤动）之后按钮就消失：留着一个只会说「没有可撤销的改动」
  // 的按钮，等于在诱导用户再点一次——而它第二次**必然**是同样那句话。
  const [undoable, setUndoable] = useState(true)

  // ① 挂载时把上次那个 job 读回来继续看（刷新恢复）。
  // ⚠️ 读不到（服务重启过、job 早被 LRU 挤掉）就把钥匙清掉：留着一个问不到的
  // job_id 会让每次刷新都白问一次，而界面上永远是"没有任务"。
  useEffect(() => {
    const saved = window.localStorage.getItem(REORDER_JOB_KEY)
    if (!saved) return
    api
      .fetchJob(saved)
      .then(setJob)
      .catch(() => window.localStorage.removeItem(REORDER_JOB_KEY))
  }, [])

  // ② 轮询：只在 running 时开。
  useEffect(() => {
    if (job === null || job.state !== 'running') return
    const t = setInterval(() => {
      api
        .fetchJob(job.job_id)
        .then((j) => {
          setJob(j)
          if (j.state !== 'running') window.localStorage.removeItem(REORDER_JOB_KEY)
        })
        .catch((e: unknown) => setErr(e instanceof Error ? e.message : String(e)))
    }, 1000)
    return () => clearInterval(t)
  }, [job?.job_id, job?.state])

  async function start() {
    setErr(null)
    setMsg(null)
    setBusy(true)
    try {
      const j = await api.startReorder()
      setJob(j)
      setUndoable(true)
      window.localStorage.setItem(REORDER_JOB_KEY, j.job_id)
      setMsg('已开始。重排要跑 1–2 分钟，可以离开这个页面（刷新也不会丢）。')
    } catch (e: unknown) {
      // ⚠️ 409 = **已有 job 在跑**（唯一的 `JobBusy` 名额）。这不是"出错了"，
      // 而是"等一下"——后端那句 detail 已经把话说清楚了，原样显示即可
      // （与 `/api/undo` 的 409 同形）。吞掉它的话，用户看到的是一次
      // 没有任何解释的失败。400 则是"没有 LLM 密钥"，同样照原样说。
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function cancel() {
    if (job === null) return
    setErr(null)
    setMsg(null)
    try {
      const r = await api.cancelJob(job.job_id)
      // ⚠️ 取消是**协作式**的：`cancelled: true` 只说"请求已受理"，正在飞的那一批
      // 会跑完。不这么说的话，用户点完看到还在跑会以为按钮坏了（然后去点第二次）。
      setMsg(
        r.cancelled
          ? '已请求取消——正在飞的那一批会跑完，它停在下一批（轮询到「已取消」才算真停）。'
          : '它已经结束了，这一步没赶上（取消只对正在跑的任务有意义）。',
      )
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  async function undo() {
    if (job === null) return
    setErr(null)
    setMsg(null)
    try {
      const r = await api.undoJob(job.job_id)
      setMsg(
        r.undone
          ? `已撤销这一批：${r.count} 条回到重排前的类目。`
          : '这一批没有可撤销的改动（可能已经撤过了，或它一条都没改）。',
      )
      setUndoable(false)
    } catch (e: unknown) {
      // 409 = 它还在跑（先取消再撤销）；404 = job 早没了；500 = overlay 锁住。
      // 三句都是不同的话，`sendJSON` 已经把后端的 detail 抛上来了，原样显示。
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-white/40">
        重排 = 让 LLM 按**当前类目定义**重判已有条目。它只写 overlay，条目的{' '}
        <code>item_id</code> 前后不变（D16），所以一整批改错了可以一次退回。
      </p>

      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={start}
          disabled={busy}
          className="rounded-lg bg-sky-500/20 px-3 py-1.5 text-sm text-sky-200 disabled:opacity-40"
        >
          开始重排
        </button>
        {job !== null && job.state === 'running' && (
          <button
            onClick={cancel}
            className="rounded-lg bg-white/5 px-3 py-1.5 text-sm text-white/60"
          >
            取消重排
          </button>
        )}
        {job !== null && job.state !== 'running' && job.actor !== '' && undoable && (
          <button
            onClick={undo}
            className="rounded-lg bg-white/5 px-3 py-1.5 text-sm text-white/60"
          >
            ↶ 撤销这次重排
          </button>
        )}
      </div>

      {job !== null && (
        <div className="rounded-lg bg-white/5 p-3">
          <p className="text-xs text-white/55">
            任务 {job.job_id} · {JOB_STATE_LABEL[job.state]}
            {/* ⚠️ `done` 是「**最后一条成功批次**的序号」，不是"已完成批次数"
                （后端 docstring 原话）。照实显示，**别自己加一**——那会变成
                另一句假话：第 1 批就抛异常时用户会看到 2/N，像"全成了"。 */}
            {job.state === 'running' &&
              (job.total > 0
                ? ` · ${job.done}/${job.total}`
                : ' · 等待第一批进度…')}
          </p>
          {job.message !== '' && (
            <p className="mt-1 text-xs text-white/70">{job.message}</p>
          )}
          {job.error !== '' && (
            <p className="mt-1 text-xs text-red-400">{job.error}</p>
          )}
        </div>
      )}

      {err !== null && <p className="text-xs text-red-400">{err}</p>}
      {msg !== null && <p className="text-xs text-white/60">{msg}</p>}
    </div>
  )
}

// ── 导入导出（配置包）──────────────────────────────────────────────────
//
// ⚠️ 走的是 **JSON body 里的字符串**，不是 multipart 上传
// （后端只为这件事引一个 `python-multipart` 不划算，见 `api_import_pack`）。
// 所以前端这边：导出用 `Blob` + `URL.createObjectURL` 下载，
// 导入用 `FileReader.readAsText` 读成文本再 POST。

function summarise(r: Record<string, unknown>): string {
  const n = (k: string) => String(r[k] ?? 0)
  return `群 ${n('groups')} / 类目 ${n('categories')} / 人物 ${n('persons')} / 别名 ${n('aliases')}`
}

function linesOf(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => String(x)) : []
}

function PackSection() {
  const [toml, setToml] = useState<string | null>(null)
  const [importText, setImportText] = useState('')
  const [keepSettings, setKeepSettings] = useState(true)
  const [msg, setMsg] = useState<string | null>(null)
  const [notes, setNotes] = useState<string[]>([])
  const [warnings, setWarnings] = useState<string[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function refresh() {
    setErr(null)
    api.exportPack()
      .then((r) => setToml(r.toml))
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
  }

  useEffect(refresh, [])

  function download() {
    if (toml === null) return
    // ⚠️ `URL.createObjectURL` 用完必须 `revoke`：不撤的话每点一次下载
    // 都在页面里留下一个指向同一份 Blob 的句柄（自用单页站点无所谓，
    // 但这条是一行的事，而"泄漏了看不见"正是本项目最讨厌的形状）。
    const url = URL.createObjectURL(new Blob([toml], { type: 'application/toml' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'vigil-config.toml'
    a.click()
    URL.revokeObjectURL(url)
  }

  function readFile(f: File) {
    const reader = new FileReader()
    reader.onload = () => {
      setImportText(String(reader.result ?? ''))
      setErr(null)
      setMsg(`已读入 ${f.name}——点「先校验不写入」看它能不能用`)
    }
    reader.onerror = () => setErr(`读不了这个文件：${f.name}`)
    reader.readAsText(f)
  }

  async function run(apply: boolean) {
    setBusy(true)
    setMsg(null)
    setErr(null)
    setNotes([])
    setWarnings([])
    try {
      const r = await api.importPack(importText, apply, keepSettings)
      setNotes(linesOf(r.notes))
      setWarnings(linesOf(r.warnings))
      setMsg(apply ? `已应用：${summarise(r)}` : `校验通过：${summarise(r)}（一个字节都没写）`)
      // ⚠️ 应用之后**导出区必须重取**：群/类目/人物可能都变了，
      // 不重取的话 textarea 里还留着导入前那一份，用户会以为没生效。
      if (apply) refresh()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs text-white/55">
          导出（**不含密钥**——密钥走 <code>.env</code>，不在这三份配置里）
        </p>
        <textarea readOnly value={toml ?? ''} rows={10}
                  className="mt-1 w-full rounded-lg bg-black/30 p-2 font-mono text-xs text-white/70" />
        <div className="mt-2 flex gap-2">
          <button onClick={refresh}
                  className="rounded-lg bg-white/5 px-3 py-1.5 text-xs text-white/60">
            重新生成
          </button>
          <button onClick={download} disabled={toml === null}
                  className="rounded-lg bg-sky-500/20 px-3 py-1.5 text-xs text-sky-200 disabled:opacity-40">
            下载 .toml
          </button>
        </div>
      </div>

      <div className="border-t border-white/10 pt-3">
        <p className="text-xs text-white/55">导入</p>
        {/* ⚠️ `aria-label` 不是装饰：`<input type="file">` **没有隐式 ARIA role**，
            没有它就只能靠 `querySelector('input[type=file]')` 去抓——那种抓法
            在用例里长得像"内部实现细节"，也让屏幕阅读器只能念出一句"按钮"。 */}
        <input type="file" accept=".toml,text/plain" aria-label="选择配置包文件"
               onChange={(e) => { const f = e.target.files?.[0]; if (f) readFile(f) }}
               className="mt-1 block w-full text-xs text-white/60" />
        <textarea value={importText} onChange={(e) => setImportText(e.target.value)} rows={8}
                  placeholder="选一个 .toml，或直接把它粘在这里"
                  className="mt-2 w-full rounded-lg bg-black/30 p-2 font-mono text-xs text-white/70" />
        <label className="mt-2 flex items-center gap-2 text-xs text-white/60">
          <input type="checkbox" checked={keepSettings}
                 onChange={(e) => setKeepSettings(e.target.checked)} />
          保留本机路径（[settings] 用本机这份，不采用包里的）
        </label>
        <div className="mt-2 flex gap-2">
          <button onClick={() => run(false)} disabled={busy || !importText.trim()}
                  className="rounded-lg bg-white/5 px-3 py-1.5 text-xs text-white/60 disabled:opacity-40">
            先校验不写入
          </button>
          <button onClick={() => run(true)} disabled={busy || !importText.trim()}
                  className="rounded-lg bg-amber-500/20 px-3 py-1.5 text-xs text-amber-200 disabled:opacity-40">
            导入并覆盖本机配置
          </button>
        </div>
      </div>

      {err !== null && <p className="text-xs text-red-400">{err}</p>}
      {msg !== null && <p className="text-xs text-white/60">{msg}</p>}
      {notes.length > 0 && (
        <ul className="space-y-1 text-xs text-white/60">
          {notes.map((n, i) => <li key={i}>· {n}</li>)}
        </ul>
      )}
      {warnings.length > 0 && (
        <ul className="space-y-1 text-xs text-amber-200">
          {warnings.map((w, i) => <li key={i}>⚠️ {w}</li>)}
        </ul>
      )}
    </div>
  )
}
