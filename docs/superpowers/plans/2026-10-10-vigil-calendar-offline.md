# VIGIL 日历 + 离线快照 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 VIGIL 的 PWA 加一个「日历」tab（按天可视化截止日），并让信息流/日历/日报在**断网/电脑关机**时仍能浏览最近一次同步的快照——且**如实标注**那是何时同步的。

**Architecture:** 后端新增一个只读端点 `GET /api/calendar`（只回带截止日的条目，复用既有 `item_out` 契约）；前端新增第 5 个 tab、一个 localStorage 快照模块（`snapshot.ts`）与一个在线/离线状态机（`connectivity.ts`）。视图取数失败时回落快照；离线时写操作置灰。**不引入任何新依赖。**

**Tech Stack:** Python 3 / FastAPI / SQLite(`mode=ro`) / pytest ；React 19 / TypeScript / Vite / Vitest + jsdom / Tailwind v4 (CSS-first `@theme inline`)。

**Spec:** `docs/superpowers/specs/2026-10-10-vigil-calendar-offline-design.md`（计划从 spec 论证，两者一起读）

---

## 0. 勘误区（计划期实测，逐条有命令；不读会白干）

### E1 ⚠️ 「每次在线成功取数后写快照」照字面实现会**违背 spec 的「最近 5 天全部」**

spec §3.3 写「每次在线成功取数后写一次」。若照字面让 **Feed 每次取数成功就写快照**，
写进去的是 **Feed 首屏那一页（`PAGE = 50` 条，`Feed.tsx:7`）**，而那是"最近一页"、
**不是**「最近 5 天全部」——两个说法在库密的日子会差很多。

⇒ 本计划落成**一个明确的 `syncSnapshot()`**（`snapshot.ts`）：它自己去拉
「最近 5 天的信息流（`since=today-5d`，`limit=200`= `MAX_LIMIT`）+ 全量截止日 + 最近 5 篇日报」，
由 **App 挂载时**与**网络恢复（`online` 事件）时**各触发一次。
这是 spec 意图的忠实实现，**不是偏离**；偏差在于"触发的时机由谁定"——
spec 说"每次取数后"，本计划说"挂载时 + 恢复时"，理由见下。

**为什么不用"每次取数后"**：Feed/Digests/Calendar 三个视图**各自**取数，
挂在谁身上都会漏掉另外两个（用户没打开日报页时，日报就永远不进快照）；
而且每翻一页都全量重写快照是浪费。挂载时 + 恢复时是**唯一不会漏**的两个时刻。

### E2 ⚠️ `ItemCard` 的 `onMutated` **不传就是只读态**——离线置灰应复用它，但**不能只靠它**

`ItemCard.tsx` 的改动条渲染条件是 `onMutated && (...)`；日报页正是靠**不传**
`onMutated` 得到只读卡（`Digests.tsx` 里 `<ItemCard key={it.item_id} item={it} />`）。
所以"离线 = 不传 `onMutated`"能让卡片变只读——**但那不满足用户要的"置灰 + 提示需联网"**
（控件会整个消失，用户不知道发生过什么）。

⇒ 本计划给 `ItemCard` 加一个**可选** `offline?: boolean`（默认 `false`）：
`onMutated && offline === true` 时**照常渲染改动条**，但 `<select>`/`<button>` 都 `disabled`
且旁边写一句「需要联网」。**不传 `offline` ⇒ 行为与今天一字不差**（日报页不受影响）。

### E3 ⚠️ 语义 token **不许带透明度修饰符**——"变淡"必须靠**另一个 token**，不是 `/50`

`web/src/index.css` 的 `@theme inline` 块顶部有一条**实测结论**（M7 F2）：

> ⛔ 由此：**语义 token 一律不许带透明度修饰符**（`bg-vigil-surface/50`）。

⇒ spec §3.2 的「已过期变淡」**不能用** `bg-vigil-accent/40`。本计划用
**`--v-fg-4`（最弱的前景 token）**做"已过期"的点，`--v-accent` 做"未到期"的点
——两个**不同的、各自完整的** token，值随主题走，不碰透明度修饰符。
（`noRawPalette.test.ts` 有机械检查，见 G1/G2。）

### E4 ⚠️ 裸 `rounded` 是字面量、**不可主题化**——日历格子必须用 `rounded-md/lg/xl`

`index.css` 实测：`.rounded{border-radius:.25rem}`（字面量），而
`rounded-md/lg/xl` 映射到 `var(--v-radius-*)`（值随主题走）。
粗野主义所有 radius = 0 ⇒ 用裸 `rounded` 的格子在粗野主义下**不跟随**（M7 终审 Important-1 正是这个形状）。

### E5 日期口径的地基：**本机时区**，且 `_day_start`/`_day_of` 是唯一权威

`api.py:135-171` 的 `_day_start(day, plus_days=…)` / `_day_of(ts)` 是**本地日**口径的
唯一定义处（注释写明：用 SQLite 的 `strftime('%s')` 会按 UTC 解释，差 8 小时）。
⇒ 后端新端点的 `since/until` **必须**走 `_day_start`；**不许**在 SQL 里写
`date(ts,'unixepoch','+8 hours')`（那会把时区口径抄进 SQL，且与 `_day_start` 是两份真相）。

### E6 spec §1.5：`/api/items` 的 `limit` 上限 = **200**（`api.py:51 MAX_LIMIT`）

⇒ `syncSnapshot()` 拉"最近 5 天"时用 `limit: 200` 会撞到上限——**这是有意的**：
200 是硬上限，`syncSnapshot` 就用它。若将来 5 天超过 200 条，快照会**少收**
（不是错收）；这条要写进 `snapshot.ts` 的注释，别让下一个人以为拿全了。

---

## Global Constraints

- **G1** 语义 token **不许带透明度修饰符**（`bg-vigil-surface/50` 一类）——实测结论，见 E3。
- **G2** 不许出现裸调色板类名（`bg-slate-800` / `text-white` 一类）；
  `web/src/__tests__/noRawPalette.test.ts` 会机械检查，**改前端必须让它绿**。
- **G3** 不许用裸 `rounded`（字面量）；圆角一律 `rounded-md` / `rounded-lg` / `rounded-xl` / `rounded-full`（后者已接 token）。
- **G4** 日历**不许显示时刻**（spec §1.2：36/36 截止日时刻恒为 `00:00`，精度只到「日」）。
  渲染产物里**不许出现** `00:00` 或 `HH:MM` 形态的到期时间。
- **G5** 前端改完**必须** `cd web && npm run build`（`api.py` 托管的静态目录是 `web/dist`；不构建 = 线上看不到）。
- **G6** 行尾 LF。本仓 `core.autocrlf=true`；新建文件一律 LF，改文件后用 `git ls-files --eol <path>` 核。
- **G7** **不引入新依赖**（`web/package.json` 的 dependencies 保持 3 个；不加 `idb`/date 库）。
- **G8** 后端连接**一律** `mode=ro`（`api.py` 顶部：写会被 SQLite 直接拒绝）。
- **G9** 快照**只读**：离线时写操作不可用（spec §3.3/§3.4）。
- **G10** 离线态**必须显式**：不许把"离线拿不到"渲染成"没有数据"（spec 出口标准 5）。

## Review Focus

> 以下是 spec 隐含、但**没有任何任务的测试会天然覆盖**的输入类/失败模式，最可能咬到真人。
> 每条都在**拥有该代码的任务**里配了一条测试（任务号见括号）。

1. **`navigator.onLine === true` 但后端不可达**（本机实测过的真形态：Tailscale 转发活着、后端没起 = 502）。
   ⇒ 状态机必须以**请求真的失败**为准，不能只信事件。（T3、T5）
2. **快照过期很久**（比如一周前同步的）被当成实时读。⇒ 必须显示 `synced_at`，不假装实时。（T5）
3. **`deadline_ts` 落在本地日边界**（`23:59` vs 次日 `00:00`）。⇒ 日历按**本地日**归属，
   与 `format.ts` 的本地时区口径一致（`format.ts:1-2` 已写明）。（T1、T4）
4. **快照 JSON 损坏 / 半写 / 被清空**（localStorage 手动清、写入中断）。
   ⇒ `readSnapshot()` **静默返回 null**，绝不抛。（T2）
5. **日历跨月/跨年**（12 月翻到次年 1 月、月首不是周一、31 号的月）。
   ⇒ 网格按"月首所在周的周一"起算，固定 42 格。（T4）

---

## 逃逸舱（每个 implementer 的派发词里必须原样带上）

> **① 若断言数字 / 测试顺序 / 文件名与实现不符 → 按实际修正并报告**，无需请示。
> **② 若需求自相矛盾或无法同时满足 → 停下报告，不许挑一半照做。**
> 把"驳回 + 出证据"记为**高质量行为**，不记为偏差（SDD 十九节 / M3 实测）。
> **③ 每做完一个任务，反着再问一句**：「有没有哪条约束是变异全红、但根本没被测到的？」
> **必须举例回答**，不能只写"做了变异反证"（SDD 三十节：M5 十战十中，无一次空手）。
> **④ 变异证据三件套**：改前真绿（证明洞存在）+ 改后真红 + 无变异基线绿（证明不是恒红）。
> **⑤ 跑反证时不许用 `-t`/`-k` 只选一条**，除非能说出**为什么那条用例自足**（SDD 三十七节第 8 格）。
> **⑥ 变异前后用 `cp` 备份 / `cp` 还原 + `sha256sum -c`**——⛔ **不许** `git checkout --`（它静默改行尾，E8-补）。
> **⑦ implementer 不许再派 subagent**（包括自己雇 reviewer）；审查由 controller 统一派。

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `vigil/store.py` | 查询层：新增 `deadlines_in_range`（复用既有 `_ITEM_COLS`/`_ITEM_JOINS`/`_NOT_DELETED`） | Modify |
| `vigil/api.py` | 新端点 `GET /api/calendar` | Modify |
| `tests/test_api.py` | 后端契约测试（该文件已有 `client` / `db_path` 夹具，追加在末尾） | Modify |
| `web/src/types.ts` | 新增 `CalendarPage` | Modify |
| `web/src/api.ts` | 新增 `fetchCalendar` + 让 `getJSON` 上报网络结果 | Modify |
| `web/src/snapshot.ts` | **新建**：快照读写（localStorage）+ `syncSnapshot()` | Create |
| `web/src/connectivity.ts` | **新建**：在线/离线状态机 | Create |
| `web/src/views/Calendar.tsx` | **新建**：月历视图 | Create |
| `web/src/uiState.ts` | `Tab` 加 `'calendar'`、`TABS` 加一项 | Modify |
| `web/src/App.tsx` | 渲染 `<Calendar>`、挂载/恢复时 `syncSnapshot()`、离线横幅 | Modify |
| `web/src/views/Feed.tsx` | 离线回落快照（**仅无筛选时**）+ 离线禁用批量条 | Modify |
| `web/src/views/Digests.tsx` | 离线回落快照 | Modify |
| `web/src/components/ItemCard.tsx` | 加可选 `offline` 属性（置灰 + 提示） | Modify |
| `web/src/__tests__/*.test.ts(x)` | 新增 4 个测试文件 + 追加 | Create/Modify |

---

### Task 1: 后端 —— `GET /api/calendar`

**Files:**
- Modify: `vigil/store.py`（在 `search_items` 之后追加 `deadlines_in_range`）
- Modify: `vigil/api.py`（在 `api_items` 之后追加端点）
- Test: `tests/test_api.py`（**追加**到文件末尾；复用该文件既有的 `db_path` / `client` 夹具）

**Interfaces:**
- Consumes: `store._ITEM_COLS` / `store._ITEM_JOINS` / `store._NOT_DELETED` / `store._ensure_overlay` / `store._to_api_item`（全部既有，模块内）；`api._day_start` / `api.item_out` / `api.group_names_map` / `api.category_map` / `api.connect`（全部既有，`create_app` 内闭包）。
- Produces: 
  - `store.deadlines_in_range(conn, *, since: int | None = None, until: int | None = None) -> list[store.ApiItem]`
  - 端点 `GET /api/calendar?since=YYYY-MM-DD&until=YYYY-MM-DD` → `{"items": [<item_out 形状>], "total": int}`

**Dependencies:** 无（首个任务）
**Touches:** `vigil/store.py`, `vigil/api.py`, `tests/test_api.py`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_api.py` 末尾）

```python
# ── 日历端点（第三版 spec §3.1）────────────────────────────────────────


def test_calendar_returns_only_items_with_deadline(client, db_path):
    """⚠️ 只回带截止日的条目。`deadline` 为空的那条**必须不出现**。

    变异反证：删掉 `WHERE i.deadline_ts IS NOT NULL` ⇒ 本条必红。
    """
    con = sqlite3.connect(str(db_path))
    # item 1（夹具那条）deadline 是 NULL；再加两条带截止日的
    con.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, amount, links, confidence, model, prompt_ver,"
        " created_at) VALUES (2, 'notice', '报名截止', NULL, ?, ?, 12345, NULL,"
        " NULL, NULL, '[]', 0.9, 'm', 'v1', 1)",
        (int(dt.datetime(2026, 9, 10, 9, 0).timestamp()),
         int(dt.datetime(2026, 9, 20, 0, 0).timestamp())),
    )
    con.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, amount, links, confidence, model, prompt_ver,"
        " created_at) VALUES (3, 'activity', '活动报名', NULL, ?, ?, 12345, NULL,"
        " NULL, NULL, '[]', 0.9, 'm', 'v1', 1)",
        (int(dt.datetime(2026, 9, 11, 9, 0).timestamp()),
         int(dt.datetime(2026, 9, 18, 0, 0).timestamp())),
    )
    con.commit()
    con.close()

    body = client.get("/api/calendar").json()
    ids = [it["item_id"] for it in body["items"]]
    assert 1 not in ids                    # 无截止日 ⇒ 不出现
    assert ids == [3, 2]                   # 按 deadline_ts 升序（18 号在 20 号前）
    assert body["total"] == 2


def test_calendar_item_shape_is_the_frozen_field_set(client, db_path):
    """⚠️ 日历的条目**必须**与 `/api/items` 同形——前端 `Item` 类型一字不改就靠它。

    变异反证：把 `item_out(it, names, cats)` 换成裸 `asdict(it)` ⇒ 本条必红。
    """
    con = sqlite3.connect(str(db_path))
    con.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, amount, links, confidence, model, prompt_ver,"
        " created_at) VALUES (2, 'academic', '选课截止', NULL, ?, ?, 12345, NULL,"
        " NULL, NULL, '[\"https://x.test/b\"]', 0.9, 'm', 'v1', 1)",
        (int(dt.datetime(2026, 9, 10, 9, 0).timestamp()),
         int(dt.datetime(2026, 9, 20, 0, 0).timestamp())),
    )
    con.commit()
    con.close()
    item = client.get("/api/calendar").json()["items"][0]
    assert {
        "item_id", "kind", "kind_label", "kind_icon", "title", "detail", "event_ts",
        "deadline_ts", "group_id", "group_name", "actor", "actor_uin", "place", "amount",
        "links", "source_count",
    } == set(item)
    assert item["links"] == ["https://x.test/b"]


def test_calendar_since_until_are_inclusive_of_both_ends(client, db_path):
    """⚠️ `since`/`until` 都按**包含该日**理解——与 `/api/items` 同口径。

    变异反证：把 `_day_start(until, plus_days=1)` 改成 `_day_start(until)` ⇒
    右端那条（恰好落在 until 当天 00:00）会被排除 ⇒ 本条必红。
    """
    con = sqlite3.connect(str(db_path))
    con.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, amount, links, confidence, model, prompt_ver,"
        " created_at) VALUES (2, 'notice', '18 号截止', NULL, ?, ?, 12345, NULL,"
        " NULL, NULL, '[]', 0.9, 'm', 'v1', 1)",
        (int(dt.datetime(2026, 9, 10, 9, 0).timestamp()),
         int(dt.datetime(2026, 9, 18, 0, 0).timestamp())),
    )
    con.commit()
    con.close()
    # 窗口 [9-18, 9-18]：右端那条**当天 00:00** 的必须被含进来
    got = client.get("/api/calendar", params={"since": "2026-09-18", "until": "2026-09-18"}).json()
    assert [it["item_id"] for it in got["items"]] == [2]
    # 窗口 [9-19, 9-30]：它必须被排除
    assert client.get("/api/calendar", params={"since": "2026-09-19"}).json()["items"] == []


def test_calendar_excludes_soft_deleted(client, db_path):
    """⚠️ 软删的条目**在所有读取路径上都必须消失**（D15）——日历不是例外。

    变异反证：把 `_NOT_DELETED` 从 WHERE 里删掉 ⇒ 本条必红。
    """
    con = sqlite3.connect(str(db_path))
    con.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, amount, links, confidence, model, prompt_ver,"
        " created_at) VALUES (2, 'notice', '要删掉的', NULL, ?, ?, 12345, NULL,"
        " NULL, NULL, '[]', 0.9, 'm', 'v1', 1)",
        (int(dt.datetime(2026, 9, 10, 9, 0).timestamp()),
         int(dt.datetime(2026, 9, 20, 0, 0).timestamp())),
    )
    con.commit()
    con.close()
    assert client.delete("/api/items/2").status_code == 200
    assert [it["item_id"] for it in client.get("/api/calendar").json()["items"]] == []


def test_calendar_rejects_bad_date(client):
    """坏日期串 ⇒ 400（与 `/api/items` 同形，走 `_day_start`）。"""
    assert client.get("/api/calendar", params={"since": "2026/09/18"}).status_code == 400
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_api.py -k calendar -v`
Expected: FAIL —— `404`（端点不存在），断言 `503`/`404` 形态

- [ ] **Step 3: 实现 `store.deadlines_in_range`**（追加到 `vigil/store.py` 的 `search_items` 之后）

```python
def deadlines_in_range(
    conn: sqlite3.Connection,
    *,
    since: int | None = None,
    until: int | None = None,
) -> list[ApiItem]:
    """带截止日的条目，按 ``(deadline_ts, event_ts, item_id)`` **升序**。

    日历用：从早到晚读，与信息流的 `event_ts DESC` 相反。

    ⚠️ 三处复用既有常量（`_ITEM_COLS` / `_ITEM_JOINS` / `_NOT_DELETED`），
    理由与 `search_items` 逐字相同：软删必须在这里也生效、类目别名也必须在这里
    也解析——漏任何一处的后果是「日历与信息流对同一个条目的说法不同」（R13）。

    ⚠️ 排序的第三键是 `item_id`：`deadline_ts` 与 `event_ts` 都可能相同，只有
    加它才是**确定**序（同 `window_items` 对确定序的要求）。

    ⚠️ **不许**在这里写 `date(deadline_ts,'unixepoch','+8 hours')`：本地日口径的
    唯一定义处是 `api._day_start` / `api._day_of`（E5）。这里只比原始 epoch 秒。
    """
    _ensure_overlay(conn)
    where = ["i.deadline_ts IS NOT NULL", _NOT_DELETED]
    params: list[int] = []
    if since is not None:
        where.append("i.deadline_ts >= ?")
        params.append(since)
    if until is not None:
        where.append("i.deadline_ts < ?")
        params.append(until)
    clause = " WHERE " + " AND ".join(where)
    rows = conn.execute(
        f"SELECT {_ITEM_COLS}{_ITEM_JOINS}{clause}"
        " ORDER BY i.deadline_ts ASC, i.event_ts ASC, i.item_id ASC",
        params,
    ).fetchall()
    return [_to_api_item(r) for r in rows]
```

- [ ] **Step 4: 实现端点**（追加到 `vigil/api.py` 的 `api_items` 之后，`api_item` 之前）

```python
    @app.get("/api/calendar")
    def api_calendar(
        since: str | None = None,
        until: str | None = None,
    ) -> dict:
        """带截止日的条目。**默认全量**（不带 since/until）。

        ⚠️ 自成一端，不走 `/api/items`：后者的 `limit` 上限是 `MAX_LIMIT = 200`，
        而日历要**全量**（用户 2026-10-10 裁定）——200 这条线迟早会咬；
        且前端硬筛要先把整个窗口的条目拉回来（第三版 spec §1.4/§3.1）。

        ⚠️ 不分页：截止日是全库最稀疏的一类数据（spec §1.1 实测 36/592）。
        真要涨到需要分页时，这个响应的 `total` 就是触发器。

        ⚠️ `since`/`until` 都按**包含该日**理解（右端取次日 00:00），与
        `/api/items` 同口径——两处必须都走 `_day_start`（E5）。
        """
        names = group_names_map()
        cats = category_map()
        con = connect()
        try:
            items = store.deadlines_in_range(
                con,
                since=_day_start(since) if since else None,
                until=_day_start(until, plus_days=1) if until else None,
            )
        finally:
            con.close()
        return {
            "items": [item_out(it, names, cats) for it in items],
            "total": len(items),
        }
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_api.py -k calendar -v`
Expected: PASS（5 passed）

- [ ] **Step 6: 跑全量后端回归**

Run: `uv run pytest`
Expected: `850 passed`（基线 845 + 5）

- [ ] **Step 7: 变异反证（三件套：改前真绿 → 改后真红 → 无变异基线绿）**

在 `vigil/store.py` 的 `deadlines_in_range` 里做**三处**变异，每处单独做、做完即还原
（用 `cp` 备份 + `cp` 还原 + `sha256sum -c`；⛔ **不用** `git checkout --`，它会静默改行尾，勘误 E8-补）：

1. 删 `"i.deadline_ts IS NOT NULL"` → `test_calendar_returns_only_items_with_deadline` 必红
2. 删 `_NOT_DELETED` → `test_calendar_excludes_soft_deleted` 必红
3. 把 `api_calendar` 的 `until=_day_start(until, plus_days=1)` 改成 `until=_day_start(until)` → `test_calendar_since_until_are_inclusive_of_both_ends` 必红

每处都要**贴原始输出**（红的条数 + 红的是哪条断言）。
**⚠️ 反着再问一句（SDD 三十/三十七节，必答）**：有没有哪条约束是变异全红、但**根本没被测到**的？
逐条举例回答。至少考虑：`item_id` 第三排序键、`item_out` 的 `names`/`cats` 现读、空结果 `total == 0`。

- [ ] **Step 8: Commit**

```bash
git add vigil/store.py vigil/api.py tests/test_api.py
git commit -m "feat(api): GET /api/calendar —— 带截止日的条目（日历端点）

store.deadlines_in_range 复用 _ITEM_COLS/_ITEM_JOINS/_NOT_DELETED，
只回 deadline_ts IS NOT NULL 且未软删的条目，按 deadline_ts 升序。
since/until 走 _day_start（本地日口径唯一权威），默认全量。
自成一端因为 /api/items 的 limit 上限是 200。"
```

---

### Task 2: 前端数据层 —— `CalendarPage` + `fetchCalendar` + `snapshot.ts`

**Files:**
- Modify: `web/src/types.ts`（追加 `CalendarPage`）
- Modify: `web/src/api.ts`（追加 `fetchCalendar`；`getJSON` 上报网络结果）
- Create: `web/src/snapshot.ts`
- Test: Create `web/src/__tests__/snapshot.test.ts`

**Interfaces:**
- Consumes: `getJSON`（`api.ts` 内既有）、`fetchItems`/`fetchCalendar`/`fetchDigests`/`fetchDigest`（本文件/self）、`noteFetchResult`（T3 产出 —— ⚠️ **本任务先 import 一个 stub**，T3 落地前用局部空实现，见 Step 3 注）。
- Produces:
  - `type CalendarPage = { items: Item[]; total: number }`
  - `fetchCalendar(range?: { since?: string; until?: string }): Promise<CalendarPage>`
  - `type Snapshot = { synced_at: number; feed: Item[]; calendar: Item[]; digests: DigestDetail[] }`
  - `SNAPSHOT_STORAGE_KEY = 'vigil.snapshot'`
  - `readSnapshot(): Snapshot | null` ／ `writeSnapshot(s: Snapshot): void` ／ `clearSnapshot(): void`
  - `syncSnapshot(): Promise<void>`

**Dependencies:** [Task 1]（`fetchCalendar` 指向 T1 的端点契约）
**Touches:** `web/src/types.ts`, `web/src/api.ts`, `web/src/snapshot.ts`, `web/src/__tests__/snapshot.test.ts`

- [ ] **Step 1: 写失败测试** `web/src/__tests__/snapshot.test.ts`

```ts
import { afterEach, expect, test, vi } from 'vitest'
import type { DigestDetail, Item } from '../types.ts'
import {
  SNAPSHOT_STORAGE_KEY,
  clearSnapshot,
  readSnapshot,
  writeSnapshot,
} from '../snapshot.ts'

afterEach(() => localStorage.clear())

function item(id: number, deadline: number | null): Item {
  return {
    item_id: id,
    kind: 'notice',
    kind_label: '通知公告',
    kind_icon: '📋',
    title: `条目 ${id}`,
    detail: null,
    event_ts: 1_700_000_000,
    deadline_ts: deadline,
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

const DIGEST: DigestDetail = {
  digest_id: 9,
  day: '2026-10-05',
  window_from: 1_700_000_000,
  window_to: 1_700_086_400,
  created_at: 1_700_090_000,
  item_count: 1,
  body_md: '# 守夜人日报',
  items: [item(1, null)],
}

// ⚠️ 期望值**逐字写死**，不许用 `toEqual(某个常量)` —— 那是自指的
// （见 `uiState.test.ts` 顶部那条 T5 review Low-1 的教训）。
test('没存过 ⇒ null', () => {
  expect(readSnapshot()).toBeNull()
})

test('存了再读 ⇒ 逐字相同', () => {
  writeSnapshot({
    synced_at: 1_700_000_000,
    feed: [item(1, null)],
    calendar: [item(2, 1_700_100_000)],
    digests: [DIGEST],
  })
  expect(readSnapshot()).toEqual({
    synced_at: 1_700_000_000,
    feed: [item(1, null)],
    calendar: [item(2, 1_700_100_000)],
    digests: [DIGEST],
  })
})

test('⚠️ 垃圾 JSON / 非对象 ⇒ null，且不抛', () => {
  localStorage.setItem(SNAPSHOT_STORAGE_KEY, '{not json')
  expect(readSnapshot()).toBeNull()
  localStorage.setItem(SNAPSHOT_STORAGE_KEY, '42')
  expect(readSnapshot()).toBeNull()
})

test('⚠️ 形状不对（缺 synced_at / 数组字段不是数组）⇒ null，不抛', () => {
  // 半写 / 被外力改过的快照必须被当成"没有快照"，而不是渲染出半个页面
  localStorage.setItem(SNAPSHOT_STORAGE_KEY, JSON.stringify({ feed: [] }))
  expect(readSnapshot()).toBeNull()
  localStorage.setItem(
    SNAPSHOT_STORAGE_KEY,
    JSON.stringify({ synced_at: 1, feed: 'nope', calendar: [], digests: [] }),
  )
  expect(readSnapshot()).toBeNull()
})

test('clearSnapshot 之后 ⇒ null', () => {
  writeSnapshot({ synced_at: 1, feed: [], calendar: [], digests: [] })
  clearSnapshot()
  expect(readSnapshot()).toBeNull()
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/__tests__/snapshot.test.ts`
Expected: FAIL —— `Failed to resolve import "../snapshot.ts"`

- [ ] **Step 3: 写 `web/src/snapshot.ts`**

```ts
/**
 * 离线快照：把「最近一次在线同步到的数据」留在 localStorage，断网时读它。
 *
 * ⚠️ **为什么是 localStorage 不是 IndexedDB**（第三版 spec §1.6 实测）：
 * 快照体量 ≈ 47 KB（最近 5 天信息流 + 全量 36 条截止日 + 5 篇日报），
 * 而 localStorage 上限 ≈ 5 MB —— 用了不到 1%。为此引一个 `idb` 依赖 + 异步事务
 * 是**过度设计**；本仓现有的两个持久化（`theme.ts` / `uiState.ts`）也都在这里。
 *
 * ⚠️ **为什么不用 Service Worker 缓存 API**：`vite.config.ts` 的
 * `workbox.navigateFallbackDenylist = [/^\/api\//]` 明确把 `/api/` 排除在兜底之外
 * ⇒ SW **不会**缓存 API 响应，离线数据只能由应用层自己持有。
 *
 * ⚠️ 快照是**只读**的：离线时写操作不可用（spec §3.3/§3.4）。本模块只负责存/取。
 */

import { fetchCalendar, fetchDigest, fetchDigests, fetchItems } from './api.ts'
import type { DigestDetail, Item } from './types.ts'

export const SNAPSHOT_STORAGE_KEY = 'vigil.snapshot'

/** 信息流/日报各留最近几天。用户 2026-10-10 裁定（spec §6 Q1）。 */
const SNAPSHOT_DAYS = 5

/** 最近 5 篇日报。条数少是因为 `body_md` 已经很小（实测 99–431 B/篇，spec §1.6）。 */
const SNAPSHOT_DIGESTS = 5

/**
 * ⚠️ 拉"最近 5 天"时用 200 —— 它就是 `api.py` 的 `MAX_LIMIT`（勘误 E6）。
 * **若 5 天真的超过 200 条，快照会少收，而不是错收**。别以为拿全了。
 */
const SNAPSHOT_FEED_LIMIT = 200

export type Snapshot = {
  /** 快照生成时刻（Unix 秒）。**展示时必须用它**，不许假装数据是实时的。 */
  synced_at: number
  /** 最近 N 天的信息流条目。 */
  feed: Item[]
  /** **全量**带截止日的条目（日历用）。 */
  calendar: Item[]
  /** 最近 N 篇日报，含 `body_md`。 */
  digests: DigestDetail[]
}

/** 本地日 `YYYY-MM-DD`（与 `format.ts` 的本地时区口径一致）。 */
function localDay(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/**
 * 读快照。**任何异常/形状不对一律返回 `null`，绝不抛**（Review Focus #4：半写、
 * 被外力改过、localStorage 被清空）。
 *
 * ⚠️ 返回 `null` 的语义是「**没有快照**」，与「快照里是空的」是两件事——
 * 调用方必须分开说（G10）。
 */
export function readSnapshot(): Snapshot | null {
  let raw: string | null = null
  try {
    raw = localStorage.getItem(SNAPSHOT_STORAGE_KEY)
  } catch {
    return null
  }
  if (raw === null) return null
  let o: unknown
  try {
    o = JSON.parse(raw)
  } catch {
    return null
  }
  if (typeof o !== 'object' || o === null) return null
  const s = o as Record<string, unknown>
  // ⚠️ 只校验**形状**（四个字段存在且类型对），不逐条校验 Item ——
  // 它们来自本程序自己的 API；逐字段深校验的收益不抵复杂度。
  if (typeof s.synced_at !== 'number') return null
  if (!Array.isArray(s.feed) || !Array.isArray(s.calendar) || !Array.isArray(s.digests)) {
    return null
  }
  return {
    synced_at: s.synced_at,
    feed: s.feed as Item[],
    calendar: s.calendar as Item[],
    digests: s.digests as DigestDetail[],
  }
}

/** 写快照。**存不下只影响「下次离线还能不能看」**，不该让当前这次同步失败。 */
export function writeSnapshot(s: Snapshot): void {
  try {
    localStorage.setItem(SNAPSHOT_STORAGE_KEY, JSON.stringify(s))
  } catch {
    // 配额满 / 无痕模式：静默失败。这不是当前交互的前提。
  }
}

export function clearSnapshot(): void {
  try {
    localStorage.removeItem(SNAPSHOT_STORAGE_KEY)
  } catch {
    /* 同上 */
  }
}

/**
 * 拉一次快照并落盘。**由 App 在挂载时与网络恢复时各调一次**（勘误 E1）——
 * 不挂在各视图的取数上，因为那样会漏掉用户没打开的视图。
 *
 * ⚠️ 任一请求失败 ⇒ **整个 `syncSnapshot` 失败，不写半份快照**：半份快照
 * （比如有信息流、没日报）会让离线时"日报不见了"，看起来像那些日报被删了。
 * 宁可没有快照（调用方说"离线，且还没有本地快照"），也不要一份残缺的快照。
 */
export async function syncSnapshot(): Promise<void> {
  const since = localDay(new Date(Date.now() - SNAPSHOT_DAYS * 86_400_000))
  const [feed, calendar, digestList] = await Promise.all([
    fetchItems({ since, limit: SNAPSHOT_FEED_LIMIT }),
    fetchCalendar(),
    fetchDigests(),
  ])
  const digests = await Promise.all(
    digestList.digests.slice(0, SNAPSHOT_DIGESTS).map((d) => fetchDigest(d.digest_id)),
  )
  writeSnapshot({
    synced_at: Math.floor(Date.now() / 1000),
    feed: feed.items,
    calendar: calendar.items,
    digests,
  })
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npx vitest run src/__tests__/snapshot.test.ts`
Expected: PASS（5 passed）

- [ ] **Step 5: 加 `CalendarPage` 与 `fetchCalendar`**

`web/src/types.ts` 追加：

```ts
/**
 * 日历端点的响应。**与 `/api/items` 同形**（items 是同一套 `item_out`），
 * 只是**不分页**、只含带截止日的条目。
 */
export type CalendarPage = {
  items: Item[]
  total: number
}
```

`web/src/api.ts`：在 `import type {...}` 里加 `CalendarPage`，并在 `fetchItems` 之后追加：

```ts
/**
 * 日历数据：**只**含带截止日的条目，默认全量（第三版 spec §3.1）。
 *
 * ⚠️ 它**不走** `/api/items`：后者的 `limit` 上限是 200，而日历要全量。
 */
export const fetchCalendar = (range?: { since?: string; until?: string }) => {
  const p = new URLSearchParams()
  if (range?.since) p.set('since', range.since)
  if (range?.until) p.set('until', range.until)
  const qs = p.toString()
  return getJSON<CalendarPage>(`/api/calendar${qs ? `?${qs}` : ''}`)
}
```

- [ ] **Step 6: 让 `getJSON` 上报网络结果**（`web/src/api.ts`）

把 `getJSON` 改成下面这样（**只改这一处**，`sendJSON` 不动）：

```ts
/**
 * ⚠️ `noteFetchResult` 由 `connectivity.ts`（T3）提供。**这里先写死 import**——
 * T3 未落地时它会编译失败，所以 T2 与 T3 必须**同批**合入或按序（T3 先）。
 * 计划按 **T2 先、T3 紧随** 排；落地时若 T3 还没做完，把下面两处调用临时注释掉，
 * **但必须在 T3 里补回来**（否则状态机失去了"请求真的失败"这一路信号，
 * Review Focus #1 就没人守）。
 */
async function getJSON<T>(url: string): Promise<T> {
  let r: Response
  try {
    r = await fetch(url)
  } catch (e) {
    // fetch **本身抛** = 网络层没通（离线、DNS、连接被拒）。
    // ⚠️ 这与"服务器返回 500"是两回事：后者 fetch 不抛。
    noteFetchResult(false)
    throw e
  }
  // ⚠️ 只有 **5xx** 才算"后端不可达"：4xx 是"服务器活着、这个请求有问题"
  // （bad date、404），把它算成离线会让用户看到一个假的"离线"横幅。
  // ⚠️ 这正是"设置对了 ≠ 行为对了"（M4 二十五节）的落点：`navigator.onLine`
  // 是**设置**，"请求真的失败"是**行为**——两个都要看（spec §3.4）。
  noteFetchResult(r.status < 500)
  if (!r.ok) {
    let msg = `HTTP ${r.status}`
    try {
      const body = (await r.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') msg = body.detail
    } catch {
      /* 响应不是 JSON（比如前端未构建时的 503 HTML），就用状态码 */
    }
    throw new Error(msg)
  }
  return (await r.json()) as T
}
```

并在 `api.ts` 顶部 import 区加：

```ts
import { noteFetchResult } from './connectivity.ts'
```

- [ ] **Step 7: 跑前端全量 + 构建**

Run: `cd web && npx vitest run && npm run build`
Expected: 测试全绿（基线 159 + 5 = 164）；build `EXIT=0`

- [ ] **Step 8: 变异反证**

对 `snapshot.ts` 的 `readSnapshot`：
1. 删掉 `typeof s.synced_at !== 'number'` 那一行 → `形状不对 ⇒ null` 必红
2. 把 `catch { return null }` 改成 `catch { return { synced_at: 0, feed: [], calendar: [], digests: [] } }` → `垃圾 JSON ⇒ null` 必红

**⚠️ 反着再问一句（必答）**：有没有约束是变异全红但没被测到？至少考虑：
`writeSnapshot` 的 try/catch 配额分支、`syncSnapshot` 的"任一失败不写半份"、
`SNAPSHOT_FEED_LIMIT = 200` 这个值本身。

- [ ] **Step 9: Commit**

```bash
git add web/src/types.ts web/src/api.ts web/src/snapshot.ts web/src/__tests__/snapshot.test.ts
git commit -m "feat(web): 快照数据层 —— CalendarPage + fetchCalendar + snapshot.ts

快照存 localStorage（实测 ≈47KB vs 5MB 上限），不引 IndexedDB。
readSnapshot 形状不对一律返回 null（半写/坏 JSON 不抛）。
syncSnapshot 由 App 在挂载与网络恢复时调用，不做"每次取数后写"。"
```

---

### Task 3: 前端 —— 在线/离线状态机 `connectivity.ts`

**Files:**
- Create: `web/src/connectivity.ts`
- Test: Create `web/src/__tests__/connectivity.test.ts`

**Interfaces:**
- Consumes: 无（叶子模块）。
- Produces:
  - `isOnline(): boolean`
  - `subscribeConnectivity(fn: () => void): () => void`
  - `noteFetchResult(ok: boolean): void`（供 `api.ts` 调用）
  - `_resetForTests(): void`

**Dependencies:** 无
**Touches:** `web/src/connectivity.ts`, `web/src/__tests__/connectivity.test.ts`

> ⚠️ **本任务必须在 T2 落地前后紧随合入**——`api.ts` 的 `getJSON` 已经 import 它。

- [ ] **Step 1: 写失败测试** `web/src/__tests__/connectivity.test.ts`

```ts
import { afterEach, expect, test, vi } from 'vitest'
import {
  _resetForTests,
  isOnline,
  noteFetchResult,
  subscribeConnectivity,
} from '../connectivity.ts'

afterEach(() => {
  _resetForTests()
  vi.unstubAllGlobals()
})

test('初值取自 navigator.onLine', () => {
  _resetForTests()
  // jsdom 里 navigator.onLine 默认为 true
  expect(isOnline()).toBe(true)
})

test('⚠️ 请求失败 ⇒ 判定为不可用（不能只信 navigator.onLine）', () => {
  // 这是 Review Focus #1 的落点：本机实测过"Tailscale 转发活着、后端没起 = 502"，
  // 而 navigator.onLine 那一刻**是 true**。只看事件的实现会在本条上红。
  // ⚠️ 变异反证：把 noteFetchResult 改成空函数 ⇒ 本条必红。
  noteFetchResult(false)
  expect(isOnline()).toBe(false)
})

test('请求成功 ⇒ 回到可用', () => {
  noteFetchResult(false)
  noteFetchResult(true)
  expect(isOnline()).toBe(true)
})

test('订阅：状态变化时被通知，且只通知一次', () => {
  const fn = vi.fn()
  const off = subscribeConnectivity(fn)
  noteFetchResult(false)
  expect(fn).toHaveBeenCalledTimes(1)
  noteFetchResult(false) // 同值不变 ⇒ 不再通知
  expect(fn).toHaveBeenCalledTimes(1)
  off()
  noteFetchResult(true)
  expect(fn).toHaveBeenCalledTimes(1) // 已退订
})

test('浏览器 offline 事件 ⇒ 不可用；online 事件 ⇒ 可用', () => {
  window.dispatchEvent(new Event('offline'))
  expect(isOnline()).toBe(false)
  window.dispatchEvent(new Event('online'))
  expect(isOnline()).toBe(true)
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/__tests__/connectivity.test.ts`
Expected: FAIL —— `Failed to resolve import "../connectivity.ts"`

- [ ] **Step 3: 写 `web/src/connectivity.ts`**

```ts
/**
 * 在线/离线状态机 —— 应用层的**单一真相源**。
 *
 * ⚠️ **为什么不能只信 `navigator.onLine`**（spec §3.4 + 本仓实测）：
 * 它只说"有没有网络链路"，不说"后端可达"。本机实测过的真形态：
 * Tailscale 转发活着、后端没起 ⇒ 浏览器认为在线（onLine === true），
 * 而每个 `/api/` 请求都 502。只看事件的实现会在那一刻显示"在线"，
 * 然后每个页面都报错——用户看到的是一堆莫名其妙的失败。
 *
 * ⇒ 本模块收**两路**信号：
 *   ① 浏览器的 `online` / `offline` 事件（**提前量**：立刻、但可能不准）；
 *   ② `noteFetchResult()`（**事实**：由 `api.getJSON` 按每个请求的真实结局上报）。
 * 后者赢：它描述的是"刚刚真的发生了什么"。
 *
 * ⚠️ 这不是"设置对了 ≠ 行为对了"（M4 二十五节）的复现，而是**它的解法**：
 * 设置（onLine）与行为（请求成败）**都要看**，且以行为为准。
 */

type Listener = () => void

function initial(): boolean {
  // SSR / 测试环境没有 navigator 时，按"在线"起步（宁可先试一次网络）
  return typeof navigator === 'undefined' ? true : navigator.onLine
}

let online = initial()
const listeners = new Set<Listener>()

function set(next: boolean): void {
  if (next === online) return
  online = next
  // ⚠️ 复制一份再遍历：监听器里退订会让 Set 在迭代中变化
  for (const l of [...listeners]) l()
}

export function isOnline(): boolean {
  return online
}

export function subscribeConnectivity(fn: Listener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

/** 由 `api.getJSON` 在每个请求结束后上报（`ok` = 没抛且 status < 500）。 */
export function noteFetchResult(ok: boolean): void {
  set(ok)
}

if (typeof window !== 'undefined') {
  window.addEventListener('online', () => set(true))
  window.addEventListener('offline', () => set(false))
}

/** 只有测试用：模块级状态会跨用例串。 */
export function _resetForTests(): void {
  online = initial()
  listeners.clear()
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd web && npx vitest run src/__tests__/connectivity.test.ts`
Expected: PASS（5 passed）

- [ ] **Step 5: 变异反证**

1. 把 `noteFetchResult` 改成空函数体 → `请求失败 ⇒ 判定为不可用` 必红
2. 删掉 `if (next === online) return` → `只通知一次` 必红
3. 删掉 `if (typeof window !== 'undefined')` 那两个监听器 → `浏览器 offline 事件` 必红

**⚠️ 反着再问一句（必答）**：至少考虑 —— 两个监听器重复注册怎么办？
`_resetForTests` 清了 `listeners` 但**没有**摘掉 window 上的监听器，
这对测试隔离有什么影响？

- [ ] **Step 6: Commit**

```bash
git add web/src/connectivity.ts web/src/__tests__/connectivity.test.ts
git commit -m "feat(web): 在线/离线状态机 —— 事件 + 请求结局双路信号

不以 navigator.onLine 为准（它只是设置）：api.getJSON 按每个请求的
真实结局上报，5xx/网络抛错才算不可用，4xx 不算。"
```

---

### Task 4: 前端 —— 日历视图 + 第 5 个 tab

**Files:**
- Modify: `web/src/uiState.ts`（`Tab` + `TABS`）
- Create: `web/src/views/Calendar.tsx`
- Modify: `web/src/App.tsx`（渲染 `<Calendar>`）
- Test: Create `web/src/__tests__/Calendar.dom.test.tsx`

**Interfaces:**
- Consumes: `fetchCalendar`（T2）、`readSnapshot`（T2）、`ItemCard`（既有，只读用法）、既有语义 token（G1/G2/G3）。
- Produces: `export default function Calendar(): JSX.Element`（无 props）。

**Dependencies:** [Task 2]（`fetchCalendar` / `readSnapshot`）; [Task 1]（端点）
**Touches:** `web/src/uiState.ts`, `web/src/views/Calendar.tsx`, `web/src/App.tsx`, `web/src/__tests__/Calendar.dom.test.tsx`

- [ ] **Step 1: 写失败测试** `web/src/__tests__/Calendar.dom.test.tsx`

```tsx
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import Calendar from '../views/Calendar.tsx'
import { SNAPSHOT_STORAGE_KEY } from '../snapshot.ts'
import type { Item } from '../types.ts'

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

function item(id: number, deadline: number | null): Item {
  return {
    item_id: id,
    kind: 'notice',
    kind_label: '通知公告',
    kind_icon: '📋',
    title: `条目${id}`,
    detail: null,
    event_ts: 1_700_000_000,
    deadline_ts: deadline,
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

function installFetch(items: Item[]) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      calls.push(url)
      const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
      if (url.startsWith('/api/calendar')) return ok({ items, total: items.length })
      if (url.startsWith('/api/categories')) return ok({ categories: [] })
      return ok({})
    }),
  )
  return calls
}

/** 本机时区下某天的 epoch 秒。写测试时**不要硬编码时区**。 */
function at(y: number, mo: number, d: number): number {
  return Math.floor(new Date(y, mo - 1, d, 0, 0, 0).getTime() / 1000)
}

test('⚠️ 只标截止日、不显示时刻（spec §1.2 + G4）', async () => {
  // 固定"今天"到 2026-10，让 2026-10-20 是未来、2026-10-05 已过
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 9, 10, 12, 0, 0))
  installFetch([item(1, at(2026, 10, 20)), item(2, at(2026, 10, 5))])
  render(<Calendar />)
  await screen.findByText('2026年10月')
  const html = document.body.innerHTML
  // ⚠️ 变异反证：把 fmtDateTime 用进格子 ⇒ 本条必红
  expect(html).not.toContain('00:00')
})

test('点某天 ⇒ 列当天到期的条目', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 9, 10, 12, 0, 0))
  installFetch([item(1, at(2026, 10, 20)), item(2, at(2026, 10, 21))])
  render(<Calendar />)
  await screen.findByText('2026年10月')
  await userEvent.click(screen.getByRole('button', { name: /10 月 20 日/ }))
  expect(screen.getByText('条目1')).toBeTruthy()
  expect(screen.queryByText('条目2')).toBeNull()
})

test('⚠️ 跨月翻页（12 月 → 次年 1 月）', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.setSystemTime(new Date(2026, 11, 15, 12, 0, 0)) // 2026-12
  installFetch([])
  render(<Calendar />)
  await screen.findByText('2026年12月')
  await userEvent.click(screen.getByRole('button', { name: '下个月' }))
  // ⚠️ 变异反证：把 `new Date(y, m + 1, 1)` 写成 `new Date(y + 1, m + 1, 1)` ⇒ 红
  expect(screen.getByText('2027年1月')).toBeTruthy()
  await userEvent.click(screen.getByRole('button', { name: '上个月' }))
  expect(screen.getByText('2026年12月')).toBeTruthy()
})

test('⚠️ 网络失败且无快照 ⇒ 说"离线"而不是"没有条目"（G10）', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }),
  )
  render(<Calendar />)
  const msg = await screen.findByText(/离线/)
  expect(msg.textContent).toContain('还没有本地快照')
})

test('⚠️ 网络失败但有快照 ⇒ 显示快照 + 同步时刻', async () => {
  localStorage.setItem(
    SNAPSHOT_STORAGE_KEY,
    JSON.stringify({
      synced_at: Math.floor(new Date(2026, 9, 9, 8, 30).getTime() / 1000),
      feed: [],
      calendar: [item(7, at(2026, 10, 20))],
      digests: [],
    }),
  )
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }),
  )
  render(<Calendar />)
  expect(await screen.findByText(/快照/)).toBeTruthy()
  expect(screen.getByText(/条目7|10 月 20 日/)).toBeTruthy()
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/__tests__/Calendar.dom.test.tsx`
Expected: FAIL —— `Failed to resolve import "../views/Calendar.tsx"`

- [ ] **Step 3: `uiState.ts` 加 tab**

```ts
export type Tab = 'feed' | 'cats' | 'digests' | 'calendar' | 'settings'

export const TABS: { key: Tab; label: string }[] = [
  { key: 'feed', label: '信息流' },
  { key: 'cats', label: '类目' },
  { key: 'digests', label: '日报' },
  { key: 'calendar', label: '日历' },
  { key: 'settings', label: '配置' },
]
```

（⚠️ `readView` 的 `VALID_TABS` 由 `TABS` 派生，自动跟上——`uiState.ts:21`。）

- [ ] **Step 4: 写 `web/src/views/Calendar.tsx`**

```tsx
import { useEffect, useMemo, useState } from 'react'
import { fetchCalendar } from '../api.ts'
import ItemCard from '../components/ItemCard.tsx'
import { readSnapshot } from '../snapshot.ts'
import type { Item } from '../types.ts'

/** 周一为首列（中文规划类应用的常见约定）。 */
const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']

const pad = (n: number) => String(n).padStart(2, '0')

/** 本机时区的 `YYYY-MM-DD`。字符串比较即日期比较（同位数）。 */
function dayKey(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/**
 * 6×7 = 42 格的月历网格，从「含当月 1 号的那一周的周一」起算。
 * 固定 42 格 ⇒ 布局不随月份跳变（跨月/跨年由 `new Date(y, m, d)` 自己进位）。
 */
function monthGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1)
  const offset = (first.getDay() + 6) % 7 // 周一 = 0
  return Array.from({ length: 42 }, (_, i) => new Date(year, month, 1 - offset + i))
}

export default function Calendar() {
  // null = 还没读到（请求在飞）；与「读到了、0 条」分开（G10 的同一条判据）
  const [items, setItems] = useState<Item[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  /** 数据来自快照时的同步时刻；实时数据时为 null。 */
  const [snapshotAt, setSnapshotAt] = useState<number | null>(null)
  const [reloadTick, setReloadTick] = useState(0)

  const today = dayKey(new Date())
  const [cursor, setCursor] = useState(() => {
    const now = new Date()
    return { y: now.getFullYear(), m: now.getMonth() }
  })
  const [picked, setPicked] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    setErr(null)
    fetchCalendar()
      .then((r) => {
        if (!alive) return
        setItems(r.items)
        setSnapshotAt(null)
      })
      .catch((e: unknown) => {
        if (!alive) return
        // ⚠️ 失败了才回落快照。**三态必须分开**（spec 出口标准 5）：
        // 网络通没数据 / 断网有快照 / 断网无快照
        const snap = readSnapshot()
        if (snap !== null) {
          setItems(snap.calendar)
          setSnapshotAt(snap.synced_at)
          setErr(null)
        } else {
          setItems(null)
          setErr(e instanceof Error ? e.message : String(e))
        }
      })
    return () => {
      alive = false
    }
  }, [reloadTick])

  // 按本地日分桶（⚠️ 与后端 `_day_start`/`_day_of` 同一个口径：本机时区）
  const byDay = useMemo(() => {
    const m = new Map<string, Item[]>()
    for (const it of items ?? []) {
      if (it.deadline_ts === null) continue
      const k = dayKey(new Date(it.deadline_ts * 1000))
      const arr = m.get(k)
      if (arr) arr.push(it)
      else m.set(k, [it])
    }
    return m
  }, [items])

  const grid = useMemo(() => monthGrid(cursor.y, cursor.m), [cursor])
  const dayItems = picked !== null ? (byDay.get(picked) ?? []) : []

  return (
    <div>
      {/* ⚠️ 快照横幅：**必须**说清这是何时同步的，不许假装实时（G10 / 出口标准 5） */}
      {snapshotAt !== null && (
        <div className="mb-3 rounded-lg bg-vigil-warn-soft p-3 text-sm text-vigil-warn">
          离线：下面是 <SnapshotTime ts={snapshotAt} /> 同步的快照。
        </div>
      )}

      {err !== null && (
        <div className="mb-3 rounded-lg bg-vigil-danger-soft p-3 text-sm text-vigil-danger">
          <p>日历读取失败：{err}</p>
          <p className="mt-1 text-xs">离线，且还没有本地快照。</p>
          <button
            onClick={() => setReloadTick((t) => t + 1)}
            className="mt-2 rounded-lg bg-vigil-danger-btn px-3 py-1.5 text-xs text-vigil-danger-text active:bg-vigil-danger-btn-active"
          >
            重试
          </button>
        </div>
      )}

      <div className="mb-2 flex items-center justify-between">
        <button
          onClick={() => setCursor((c) => shiftMonth(c, -1))}
          aria-label="上个月"
          className="rounded-md px-2 py-1 text-sm text-vigil-fg-3 active:bg-vigil-surface"
        >
          ‹
        </button>
        <span className="text-sm font-medium">
          {cursor.y}年{cursor.m + 1}月
        </span>
        <button
          onClick={() => setCursor((c) => shiftMonth(c, 1))}
          aria-label="下个月"
          className="rounded-md px-2 py-1 text-sm text-vigil-fg-3 active:bg-vigil-surface"
        >
          ›
        </button>
      </div>

      <div className="grid grid-cols-7 gap-1 text-center text-xs text-vigil-fg-4">
        {WEEKDAYS.map((w) => (
          <div key={w} className="py-1">
            {w}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7 gap-1">
        {grid.map((d) => {
          const k = dayKey(d)
          const n = byDay.get(k)?.length ?? 0
          const inMonth = d.getMonth() === cursor.m
          const isToday = k === today
          // ⚠️ "已过期" 用 **--v-fg-4**（最弱的前景 token）而不是 `bg-vigil-accent/40`
          // ——语义 token 不许带透明度修饰符（G1 / 勘误 E3）。
          const overdue = k < today
          return (
            <button
              key={k}
              onClick={() => setPicked(k)}
              aria-label={`${d.getMonth() + 1} 月 ${d.getDate} 日`}
              className={
                'flex flex-col items-center gap-1 rounded-md py-2 text-xs ' +
                (inMonth ? 'text-vigil-fg-2' : 'text-vigil-fg-4') +
                (picked === k ? ' bg-vigil-surface-2' : ' active:bg-vigil-surface') +
                (isToday ? ' outline outline-1 outline-vigil-accent' : '')
              }
            >
              <span>{d.getDate()}</span>
              {/* ⭐ 有截止日才打点；到期的实心亮、已过期的变淡（用户 Q2） */}
              {n > 0 && (
                <span
                  aria-label={`${n} 条到期`}
                  className={
                    'h-1.5 w-1.5 rounded-full ' +
                    (overdue ? 'bg-vigil-fg-4' : 'bg-vigil-accent')
                  }
                />
              )}
            </button>
          )
        })}
      </div>

      {picked !== null && (
        <div className="mt-4">
          <p className="mb-2 text-xs text-vigil-fg-4">{picked} 到期</p>
          {dayItems.length === 0 ? (
            <p className="text-sm text-vigil-fg-4">这一天没有到期的条目。</p>
          ) : (
            <ul className="space-y-2">
              {dayItems.map((it) => (
                // ⚠️ 不传 onMutated ⇒ 只读卡（与日报页同一个用法，勘误 E2）
                <ItemCard key={it.item_id} item={it} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function shiftMonth(c: { y: number; m: number }, delta: number): { y: number; m: number } {
  // `new Date(y, m + delta, 1)` 自己处理跨年进位，不手动算
  const d = new Date(c.y, c.m + delta, 1)
  return { y: d.getFullYear(), m: d.getMonth() }
}

/** 快照时刻，精确到分钟。**只用于横幅**，不进日历格。 */
function SnapshotTime({ ts }: { ts: number }) {
  const d = new Date(ts * 1000)
  return (
    <span>
      {d.getMonth() + 1}月{d.getDate()}日 {pad(d.getHours())}:{pad(d.getMinutes())}
    </span>
  )
}
```

- [ ] **Step 5: `App.tsx` 渲染第 5 个 tab**

在 `App.tsx` 的 import 区加 `import Calendar from './views/Calendar.tsx'`，
并在 `<main>` 里（`digests` 那一行之后）加：

```tsx
        {tab === 'calendar' && <Calendar />}
```

- [ ] **Step 6: 跑测试 + 构建**

Run: `cd web && npx vitest run src/__tests__/Calendar.dom.test.tsx && npx vitest run && npm run build`
Expected: Calendar 5 passed；全量 164 + 5 = 169 passed；build `EXIT=0`

- [ ] **Step 7: 变异反证**

1. `monthGrid` 的 `(first.getDay() + 6) % 7` 改成 `first.getDay()`（丢了周一为首列）
2. `shiftMonth` 改成手算 `{ y: c.y, m: c.m + delta }`
3. 把 overdue 的判断 `k < today` 改成 `false`（永不判过期）
4. 把 `bg-vigil-fg-4`（过期点）改成 `bg-vigil-accent`

每条都要说明**哪条测试红了**；没红的，按 Important 记（"这一处删掉/改坏之后，什么都没有红"）。

**⚠️ 反着再问一句（必答）**：至少考虑 —— `aria-label` 里的 `${d.getMonth()+1} 月 ${d.getDate} 日`
有没有在别处冲突？`picked` 指向的日期被翻月后还在不在（跨月选中的日期残留）？

- [ ] **Step 8: Commit**

```bash
git add web/src/uiState.ts web/src/views/Calendar.tsx web/src/App.tsx web/src/__tests__/Calendar.dom.test.tsx
git commit -m "feat(web): 日历视图 + 第 5 个 tab

月历固定 42 格（周一为首列，跨年靠 Date 进位）；有截止日才打点，
到期用 --v-accent、已过期用 --v-fg-4（不碰透明度修饰符，E3）。
失败才回落快照并显示同步时刻，三态分开。"
```

---

### Task 5: 前端 —— 离线接入（快照回落 + 置灰 + 横幅）

**Files:**
- Modify: `web/src/components/ItemCard.tsx`（可选 `offline` 属性）
- Modify: `web/src/views/Feed.tsx`（离线回落快照 + 禁用批量条）
- Modify: `web/src/views/Digests.tsx`（离线回落快照）
- Modify: `web/src/App.tsx`（`syncSnapshot()` 触发 + 离线横幅 + 撤销置灰）
- Test: Create `web/src/__tests__/Offline.dom.test.tsx`

**Interfaces:**
- Consumes: `isOnline`/`subscribeConnectivity`（T3）、`syncSnapshot`/`readSnapshot`（T2）、`ItemCard`（本任务改）。
- Produces: `ItemCard` 新增 **可选** prop `offline?: boolean`（默认 `false` ⇒ 行为与今天一字不差）。

**Dependencies:** [Task 2, Task 3, Task 4]
**Touches:** `web/src/components/ItemCard.tsx`, `web/src/views/Feed.tsx`, `web/src/views/Digests.tsx`, `web/src/App.tsx`, `web/src/__tests__/Offline.dom.test.tsx`

- [ ] **Step 1: 写失败测试** `web/src/__tests__/Offline.dom.test.tsx`

```tsx
import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import ItemCard from '../components/ItemCard.tsx'
import type { Item } from '../types.ts'

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

const ITEM: Item = {
  item_id: 7,
  kind: 'notice',
  kind_label: '通知公告',
  kind_icon: '📋',
  title: '周三停水',
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

test('⚠️ offline=true ⇒ 改动控件被禁用 + 提示需要联网（G9 / 出口标准 3）', () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ categories: [] }) })),
  )
  render(<ItemCard item={ITEM} onMutated={() => {}} offline />)
  const del = screen.getByRole('button', { name: '删除' }) as HTMLButtonElement
  expect(del.disabled).toBe(true)               // ⚠️ 变异反证：去掉 disabled ⇒ 红
  expect(screen.getByText('需要联网')).toBeTruthy()
})

test('⚠️ 不传 offline ⇒ 与今天一字不差（日报页的只读用法不受影响）', () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ categories: [] }) })),
  )
  render(<ItemCard item={ITEM} onMutated={() => {}} />)
  const del = screen.getByRole('button', { name: '删除' }) as HTMLButtonElement
  expect(del.disabled).toBe(false)
  expect(screen.queryByText('需要联网')).toBeNull()
})

test('⚠️ 不传 onMutated（日报/日历的只读用法）⇒ 没有改动条', () => {
  render(<ItemCard item={ITEM} />)
  expect(screen.queryByRole('button', { name: '删除' })).toBeNull()
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npx vitest run src/__tests__/Offline.dom.test.tsx`
Expected: FAIL —— `offline` 不是已知属性（TS）/ `需要联网` 找不到

- [ ] **Step 3: `ItemCard` 加 `offline`**

props 类型里加 `offline?: boolean`，并把改动条改成：

```tsx
      {onMutated && (
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-vigil-border-soft pt-2 text-xs">
          <select
            value={item.kind}
            disabled={busy || offline === true}
            onChange={(e) => changeKind(e.target.value)}
            className="rounded-lg bg-vigil-inset px-2 py-1 text-xs text-vigil-fg-2 outline-none disabled:opacity-40"
          >
            {cats.map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.icon} {c.label}
              </option>
            ))}
          </select>
          <button
            onClick={remove}
            disabled={busy || offline === true}
            className="rounded-lg bg-vigil-danger-soft px-2 py-1 text-vigil-danger disabled:opacity-40"
          >
            删除
          </button>
          {offline === true && <span className="text-vigil-fg-4">需要联网</span>}
          {actErr !== null && <span className="text-vigil-danger">{actErr}</span>}
        </div>
      )}
```

（解构 props 处同步加 `offline`；`offline` 缺省为 `undefined` ⇒ `offline === true` 为假 ⇒ 行为不变。）

- [ ] **Step 4: `Feed` 离线回落 + 禁用批量条**

在 `Feed.tsx` 顶部 import：`import { isOnline, subscribeConnectivity } from '../connectivity.ts'`、
`import { readSnapshot } from '../snapshot.ts'`。加 state 与订阅：

```tsx
  const [online, setOnline] = useState(isOnline)
  useEffect(() => subscribeConnectivity(() => setOnline(isOnline())), [])
```

把首屏取数的 `.catch` 改成：

```tsx
      .catch((e: unknown) => {
        if (mine !== seq.current) return
        // ⚠️ 只在**无筛选**时回落快照：快照存的是"最近 N 天的全部条目"，
        // 把它显示在一个**带筛选**的查询下，就是拿一张不匹配的清单回答
        // 另一个问题（"只说自己有资格说的话"，M2）。带筛选时如实报错。
        const unfiltered = kinds.length === 0 && persons.length === 0 && q === ''
        const snap = unfiltered ? readSnapshot() : null
        if (snap !== null && snap.feed.length > 0) {
          setShown({ items: snap.feed, total: snap.feed.length, kindsKey, personsKey, q })
        } else {
          setErr(e instanceof Error ? e.message : String(e))
          setShown(null)
        }
      })
```

并把批量条与卡片传参改成离线感知（把 `selected.size > 0 &&` 那块里的按钮加 `disabled={bulkBusy || !online}`，
给 `<ItemCard>` 传 `offline={!online}`）。**同时**在计数行上方加一行快照提示：

```tsx
      {!online && (
        <p className="mt-3 rounded-lg bg-vigil-warn-soft p-2 text-xs text-vigil-warn">
          离线：显示的是本地快照。
        </p>
      )}
```

- [ ] **Step 5: `Digests` 离线回落**

在 `Digests.tsx` 的列表 `.catch` 里：失败且 `readSnapshot() !== null` 时，
用 `snap.digests` 填列表（把 `DigestDetail[]` 映射成列表要用的 `DigestSummary` 字段——
它们本就是子集），并显示同一句快照横幅；打开某篇时若在快照里，直接用快照的 `detail`。

- [ ] **Step 6: `App` 触发 `syncSnapshot` + 离线横幅 + 撤销置灰**

`App.tsx`：
- import `syncSnapshot`（`./snapshot.ts`）、`isOnline`/`subscribeConnectivity`（`./connectivity.ts`）。
- 挂载时与回到在线时各同步一次：

```tsx
  const [online, setOnline] = useState(isOnline)
  useEffect(() => subscribeConnectivity(() => setOnline(isOnline())), [])
  useEffect(() => {
    if (!online) return
    // ⚠️ 失败不打扰用户：快照是"锦上添花"，同步失败只意味着离线时少一份数据。
    void syncSnapshot().catch(() => {})
  }, [online])
```

- 撤销按钮加 `disabled={!online}`，并在头部下方加一条离线横幅（`bg-vigil-warn-soft text-vigil-warn`）。

- [ ] **Step 7: 跑测试 + 构建 + 全量**

Run: `cd web && npx vitest run && npm run build`
Expected: 169 + 3 = 172 passed；build `EXIT=0`

- [ ] **Step 8: 变异反证**

1. 去掉 `ItemCard` 的 `disabled={busy || offline === true}` 里的 `|| offline === true` → Offline 用例①必红
2. 把 `Feed` 的 `unfiltered` 判断改成恒 `true` → 需要一条"带筛选时失败 ⇒ 报错而非显示快照"的测试；
   **若这条测试不存在，本变异不会红** ⇒ 补一条测试（这是 Review Focus 里"带筛选"那一格）
3. 去掉 `App` 的 `if (!online) return`（离线也同步）→ 无测试盯 ⇒ 按 Important 记录并补测试

**⚠️ 反着再问一句（必答）**：至少考虑 —— `syncSnapshot` 在**离线事件连发**时会不会风暴？
`setOnline` 与 `subscribeConnectivity` 在 `StrictMode` 下（挂→卸→挂）有没有重复订阅？

- [ ] **Step 9: Commit**

```bash
git add web/src/components/ItemCard.tsx web/src/views/Feed.tsx web/src/views/Digests.tsx web/src/App.tsx web/src/__tests__/Offline.dom.test.tsx
git commit -m "feat(web): 离线接入 —— 快照回落 + 写操作置灰 + 快照横幅

ItemCard 加可选 offline（不传=行为不变）；Feed 仅在无筛选时回落快照
（带筛选时如实报错，不拿不匹配的清单冒充答案）；App 在挂载与恢复时
同步快照，离线时撤销置灰并显示横幅。"
```

---

## 收尾（阶段⑤⑥）

- 阶段③ **最终全分支 opus review**：`review-package <计划> <BASE> <HEAD>`，BASE = 本计划提交时的 HEAD。
- 阶段④ **冒烟（出口证据）**：真进程 + 真数据跑 spec §5 的六条判据，
  **判据 1（五套主题 + ARGUS 下日历正常）必须留人眼验收**（对齐 M1/M7）。
  ⚠️ 冒烟前 `cd web && npm run build`（G5）——`web/dist` 就是线上。
- 阶段⑤ `superpowers:finishing-a-development-branch`。
- 阶段⑥ 记忆埋点：更新 `vigil-progress.md` + 本版 spec 的落地状态。

---

## Self-Review（写完自检）

**1. Spec 覆盖：**
| spec 节 | 任务 |
|---|---|
| §3.1 端点 | T1 |
| §3.2 日历 tab | T4（TABS）+ T4（视图）|
| §3.3 快照 | T2（模块）+ T5（回落）|
| §3.4 状态机 | T3 |
| §5 判据 1–6 | T4/T5 的测试 + 冒烟 |
| §4 不做清单 | 无任务（正确）|

**2. 占位符扫描：** 无 TBD/TODO；每个代码步都有完整代码。

**3. 类型一致性：** `Snapshot` 的四个字段在 T2 定义、T5 消费一致；
`fetchCalendar` 返回 `CalendarPage`，T4 用 `r.items`；`noteFetchResult`（T3）在 T2 被 import。

**4. Review Focus 落实：** 五条各配了测试（T1/T2/T3/T4/T5，见该节括注）。
