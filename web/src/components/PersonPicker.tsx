import { useEffect, useState } from 'react'
import { addPerson, fetchPersons, removePerson } from '../api.ts'
import type { Person } from '../types.ts'

/**
 * 「按人物筛选」——一个**与类目体系并列的第二维度**。
 *
 * ⚠️ 与类目的关系是：**维度内并集、维度间交集**（spec §四 #4）。
 * 这个组件只管"选了哪些人"，拼 WHERE 是后端的事——前端不要试图
 * 把两个维度揉成一个 `q` 或一个 `kind`，那会让交集变成并集。
 *
 * ⚠️ 三态必须分开（与 Feed 同一条规矩）：还没读到 / 读到了 0 个人 / 读取失败。
 * 把「读失败」画成「一个人都没有」会让用户以为名单被清空了。
 */
export default function PersonPicker({
  selected,
  onChange,
}: {
  selected: number[]
  onChange: (uins: number[]) => void
}) {
  const [people, setPeople] = useState<Person[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [uin, setUin] = useState('')
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)

  function reload() {
    setErr(null)
    fetchPersons()
      .then((r) => setPeople(r.persons))
      .catch((e: unknown) => {
        setErr(e instanceof Error ? e.message : String(e))
        setPeople(null)
      })
  }

  useEffect(reload, [])

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
    try {
      await addPerson(n, label.trim())
      setUin('')
      setLabel('')
      reload()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  async function drop(n: number) {
    setBusy(true)
    setErr(null)
    try {
      await removePerson(n)
      // 从当前筛选里也摘掉——否则筛选项还留着一个已经不存在的人，
      // 列表会一直空着，而用户不知道是为什么
      onChange(selected.filter((u) => u !== n))
      reload()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="rounded-full bg-white/5 px-3 py-1 text-xs text-white/55"
      >
        👤 按人物筛选
        {selected.length > 0 ? `（已选 ${selected.length}）` : ''}
      </button>

      {open && (
        <div className="mt-2 rounded-xl bg-white/5 p-3">
          {err !== null && (
            <p className="mb-2 text-xs text-red-400">{err}</p>
          )}
          {people === null && err === null && (
            <p className="text-xs text-white/40">读取中…</p>
          )}
          {people !== null && people.length === 0 && (
            <p className="text-xs text-white/40">
              还没有监视任何人。在下面加一个 QQ 号。
            </p>
          )}
          {people !== null && people.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {people.map((p) => {
                const on = selected.includes(p.uin)
                return (
                  <span key={p.uin} className="inline-flex items-center">
                    <button
                      onClick={() =>
                        onChange(
                          on
                            ? selected.filter((u) => u !== p.uin)
                            : [...selected, p.uin],
                        )
                      }
                      className={
                        'rounded-l-full px-3 py-1 text-xs ' +
                        (on
                          ? 'bg-sky-500/20 text-sky-300'
                          : 'bg-white/5 text-white/55')
                      }
                    >
                      {p.label}（{p.count}）
                    </button>
                    <button
                      onClick={() => drop(p.uin)}
                      disabled={busy}
                      title={`不再监视 ${p.uin}`}
                      className="rounded-r-full bg-white/5 px-2 py-1 text-xs text-white/35 active:bg-white/10"
                    >
                      ×
                    </button>
                  </span>
                )
              })}
            </div>
          )}

          <div className="mt-3 flex flex-wrap gap-1.5">
            <input
              value={uin}
              onChange={(e) => setUin(e.target.value)}
              inputMode="numeric"
              placeholder="QQ 号"
              className="w-28 rounded-lg bg-black/30 px-2 py-1 text-xs outline-none placeholder:text-white/30"
            />
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="名字（辅导员张老师）"
              className="flex-1 rounded-lg bg-black/30 px-2 py-1 text-xs outline-none placeholder:text-white/30"
            />
            <button
              onClick={add}
              disabled={busy}
              className="rounded-lg bg-sky-500/20 px-3 py-1 text-xs text-sky-300 disabled:opacity-40"
            >
              新增
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
