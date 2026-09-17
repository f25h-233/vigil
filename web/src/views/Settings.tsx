import { useEffect, useState } from 'react'
import type { CategoryDetail, GroupRow, LlmSettings } from '../types.ts'
import * as api from '../api.ts'

// 「配置」tab —— M6 的全部意义：`config/*.toml` 从「手工编辑的文件」变成
// 「网页上可增删改的配置」。
//
// ⚠️ **四节各自持有自己的数据与自己的 refresh**（`tick`），**没有一个全局 token**：
// 一个全局 token 会让「改了一个群」顺带重取另外三节的数据，而那三节的数据
// 根本没变。但**「提交 ⇒ 重取」这个模式四节必须一致**——不一致就是 M5 那两个
// 「改完界面不更新」的缺陷换个页面重演（出口判据 1 的界面形态）。

type Section = 'groups' | 'persons' | 'llm' | 'categories' | 'pack'

const SECTIONS: { key: Section; label: string }[] = [
  { key: 'groups', label: '群' },
  { key: 'persons', label: '人物' },
  { key: 'llm', label: 'LLM' },
  { key: 'categories', label: '类目' },
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
    try {
      await api.addGroup(n, name.trim(), 'normal')
      setMsg(`已加入 ${n}。⚠️ 下次 vigil export 会拉它的**全部历史**——首轮实测大群约 1,664 条 / 21 批 / 6.3 分钟。`)
      setId(''); setName('')
      setTick((t) => t + 1)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
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
        <button onClick={submit} className="rounded-lg bg-sky-500/20 px-3 py-1.5 text-sm text-sky-200">
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
      // ⚠️ 显示的是**服务端回给的那个值**，不是本地的输入框状态：
      // 后端将来若做了归一化（比如补全 URL），界面上必须看得见差别。
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
      <button onClick={() => api.undoCategorieChange().then(() => setTick((t) => t + 1))}
              className="mt-3 rounded-lg bg-white/5 px-3 py-1.5 text-xs text-white/60">
        ↶ 撤销上一次类目改动
      </button>
      {msg !== null && <p className="mt-2 text-xs text-white/60">{msg}</p>}
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
        <input type="file" accept=".toml,text/plain"
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
