# VIGIL M2「日报合成」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `items` 表里某个时间窗内的结构化条目，合成一篇给人看的一页 Markdown 日报，落 `digests` 表 + `docs/digests/YYYY-MM-DD.md`。

**Architecture:** 日报是 items 的**视图**，不是第二条抽取管线（spec §2）。程序取窗口内的 items → 脱敏后交给 LLM 做「合并同类项 + 写一句人话」→ 模型用**逐字摘录 title** 指认它引用了哪些条目 → 程序本地匹配回 item → **确定性渲染** Markdown → 落库并写文件。模型只负责措辞与合并，版式、分区、群名、截止日期全部由程序产出。

**Tech Stack:** Python 3.13 / SQLite（stdlib）/ `urllib.request`（stdlib，**不引入新依赖**）/ pytest / SiliconFlow（复用 M1 的 `vigil/llm.py`）

**Spec:** [`docs/superpowers/specs/2026-09-13-vigil-product-layer-design.md`](../specs/2026-09-13-vigil-product-layer-design.md) §2、§4.2、§4.6、§5（M2）

**Mode:** SDD **pipeline**（M1 的接力文件明确建议：M1 八个任务粒度太碎，wave 的同步开销不划算）

---

## Global Constraints

以下约束适用于**每一个**任务，不再逐任务重复。

1. **禁止引入新的运行时依赖。** `pyproject.toml` 的 `dependencies` 保持 `["sqlcipher3>=0.6.2"]`。HTTP 用 stdlib `urllib.request`，JSON 用 stdlib `json`，日期用 stdlib `datetime`。
2. **所有源码文件用 `from __future__ import annotations` 开头**（跟随 `vigil/` 现有 13 个模块）。
3. **所有文件编码 UTF-8**，注释与文档字符串一律中文。
4. **不碰 QQ 加密库。** M2 只读明文的 `data/vigil.db`；`vigil/qqdb.py` / `export.py` 一行不改。
5. **错误处理策略：配置错 → 快速失败**（抛 `RuntimeError` 子类）；**外部环境错 → 降级并报告**。⚠️ 但日报只有一次 LLM 调用，**失败时不许降级出半成品**（理由见 Task 4）。
6. **测试绝不联网、绝不碰真实 QQ 加密库、绝不碰 `data/vigil.db`**。用 `sqlite3.connect(":memory:")` 与构造样本；LLM 一律 monkeypatch。
7. **修改 `tests/test_store.py` / `tests/test_llm.py` 时必须追加而非覆盖**——它们已由 M1 建立并通过。
8. **每个任务一个独立 commit**，消息格式 `feat: ...` / `test: ...` / `chore: ...`。
9. **测试要逐条详情时用 `-vv` 而不是 `-v`**。`pyproject.toml` 里设了 `addopts = "-q"`，而 `-q` 与 `-v` 是互斥的计数器，命令行给一个 `-v` 只够抵消它。
10. **绝不把群号、uid、QQ 号发往模型**（spec §4.5）。日报路径发的是**群名**，不是群号。⚠️ 规划期间的探针第一版就是在这里翻车的（把 `group_id` 明文发了出去）——所以 Task 2 有专门的测试守着它。
11. **改了提示词必须同步 `digest.PROMPT_VERSION`**，否则库里新老产出混在一起说不清（M1 的教训）。

### 逃逸舱

计划里若出现与实现不符的断言/命令/顺序：**按实际情况修正并继续，无需请示**，但必须在 `task-N-report.md` 里写明偏差（报告是审查输入）。

若某一步**根本走不通**，同样停下报告，不要硬凑一个"看起来通过"的结果。

---

## 规划期间的探针实测（本计划的事实依据）

写计划时用真实数据跑了提示词探针（`_probe_digest.py`），得出四条**直接改变设计**的结论。执行时以这些实测为准，不要按直觉改回去。

### 发现 1：quote 契约在日报这层同样成立

| 日期 | 条数 | 结果 |
|---|---|---|
| 2026-09-13 | 10 条 items | 7.4s，**覆盖 10/10**，0 处 quote 未命中 |
| 2026-09-08 | 13 条 items | 8.6s，**覆盖 13/13**，0 处 quote 未命中 |

所以**不问模型要 item_id**，让它逐字摘录 `title`，本地匹配——与 M1 在 `refine.py` 里的选择一致（M1 实测：19 位雪花号命中 0/2、批内序号在真实管线里也错）。

### 发现 2：⚠️ 全角引号会让模型退化成无限空格循环

这是本次探针**最重要的发现**，会直接导致日报卡死：

| 变体 | 结果 |
|---|---|
| 原样发出（某条 detail 含 `“风之海310”`） | **85s 未收尾，已吐 8,896 字且仍在继续** |
| 把该处 `“ ”` 换成 `「」` | **6.2s 正常返回** |
| 全部条目的 `“ ”` 都换掉 | **5.8s 正常返回** |
| 同样的 10 条但去掉那一条 | 4.5s 正常返回 |

**实测分布**：`items` 270 条里 **4 条**命中（1.5%）；`messages` 47,719 条里 **25 条**命中。频率不高，但**第一次拿真实数据试就撞上了**。

→ 修法：发前把 `“ ”` 归一化成 `「」`（`llm.sanitize_for_llm`），另加 `max_tokens` 兜底。
→ **只修有证据的这一处**。`【】『』…` 没有实测过会退化，不要顺手加进来——加了没有依据，日后也没法追溯为什么。

### 发现 3：M1 的 LLM 客户端**没有 `max_tokens` 上限**

模型一旦退化成上面那种失控循环，唯一能拦住它的就是 180s 超时 ×3 次重试 ≈ **9 分钟空转**。加了 `max_tokens=1200` 后同样的失控请求 23s 就停（虽被截断，但**兜住了**）。

→ Task 2 给 `LLMConfig` 加 `max_tokens` 字段，**默认 `None`（不发该字段）= M1 行为完全不变**，日报显式传 `MAX_TOKENS = 2000`。

### 发现 4：短超时会误判，实验前要清残留进程

同一个请求「35s 判 FAIL」和「300s 后 2.0s 就返回」都出现过。查下去发现**我自己的僵尸后台探针进程**占着 API key 的并发，把后续请求一起拖死。

→ 结论写进流程：**别用短超时做实验**；跑对照实验前先确认没有残留的探针进程。

---

## 规划期的隔离验证跑（**本计划已被完整跑通过一遍**）

计划写完后，在**库外的 git worktree**（`git worktree add --detach D:/github/VIGIL-verify HEAD`，用库的 `.venv` 解释器、把 worktree 路径插到 `sys.path[0]`）里把本计划的全部代码与测试落地跑了一遍，然后端到端跑了四天日报。**仓库工作区全程未被污染**。

结果：**195 passed**；四天日报全部产出，覆盖率 5/5、6/6、10/10、0/0，0 孤儿行；空窗日不调模型、0 token。

### 这轮验证抓到并已修掉的三个缺陷（**不要在实施时改回去**）

| # | 缺陷 | 症状 | 修法 |
|---|---|---|---|
| **V1** | `match_lines` 照搬了 `refine._match_source` 的「摘录短于 4 字就丢」 | 8 条断言全红。title 可能只有 2-3 个字（「讲座」「体检表」），短标题**一条都匹配不上**，日报退化成全机械补行 | 改成**先按整个 title 逐字相等匹配**，再退回「子串 + ≥4 字」 |
| **V2** | `digest()` 里「空窗分支」排在 `dry_run` 检查**之前**且无条件落库 | `vigil digest --date <空窗日> --dry-run` **照样写库、落文件** | 把 `dry_run` 检查提到空窗分支前面 |
| **V3** | `test_save_digest_replaces_same_window` 的断言 | 断言「两次 digest_id 不同」以及用 `WHERE digest_id=?` 数孤儿——SQLite 的 `INTEGER PRIMARY KEY` 删空后**复用 rowid**，两条断言都失效（假红 / 测不出东西） | 改断言：只剩一篇 + 关联只剩 `[1]` + **真孤儿判据**（指向不存在日报的行数） |

**三个缺陷的共同点**：都是「测试通过不提供保障」的实例——
V1 是**把别处的规则原样搬过来而没检查适用前提**（refine 的摘录是原文片段，日报的摘录是整个 title）；
V2 是**空守卫**（测试存在，但样本走的是另一条分支，坏掉的分支没人走）；
V3 是**假红**（测试红/绿的原因与它想守的语义无关）。

### 顺带确认的一处口径（**将来别搞混**）

`day_window()` 用 Python 的 `datetime.timestamp()` 取**本地**当天 00:00，而 SQLite 的 `strftime('%s','2026-09-13')` 按 **UTC** 解释同一个字符串，两者差 8 小时：

```
day_window（本地日）     2026-09-13 的那天 → 536 条消息   ← 产品用这个
SQLite strftime（UTC 日）2026-09-13 的那天 → 527 条消息
```

日报按**本地日**划窗口是对的（「今天的日报」就该是本地 00:00–24:00）。但**写核验 SQL 时也必须用 Python 换算**，否则分母与产品口径不一致，核验自己就会报错数。Task 5 Step 3 的核验脚本已经按本地日写好了。

---

## 与 spec 的三点偏差（实施时按本计划，勿按 spec）

| # | spec 原文 | 本计划 | 依据 |
|---|---|---|---|
| 偏差 1 | §4.6「LLM 写成一页 Markdown」 | 改为 **LLM 只产出 JSON（`label` + `text` + `quotes`），Markdown 由程序确定性渲染** | 自由发挥的 Markdown 无法可靠回连 `digest_items`，而 §2.3 要求「日报里说的每一条都能在 Web 里找到」。版式交回程序还顺带让渲染可测 |
| 偏差 2 | §4.2 `digests` 表无 `prompt_ver` 列 | **加 `prompt_ver TEXT NOT NULL`** | M1 的教训：提示词一改，库里新老产出就分不清了 |
| 偏差 3 | §4.2 `digests` 表无唯一约束 | **加 `UNIQUE(window_from, window_to)`** | 否则同一天跑两次 `vigil digest` 会堆出第二篇同日日报 |

**新增的一条 spec 未规定的行为**（用户已裁定）：`items.confidence < 0.5` 的行不混进正文，单列到末尾的「🤔 拿不准的」区块。实测全库只有 1 条落在这个区间（M1 误抽的「咨询：四六级报名时间」，confidence 0.10），所以它是安全阀而非常态。

---

## 文件结构

**新建：**

| 文件 | 职责 |
|---|---|
| `vigil/digest.py` | 日报合成：载荷构造、提示词、quote 匹配、渲染、编排 |
| `tests/test_digest.py` | 日报层测试 |

**修改：**

| 文件 | 改什么 |
|---|---|
| `vigil/store.py` | 加 `digests` / `digest_items` 建表、`WindowItem`、`window_items()`、`window_stats()`、`save_digest()`、`find_digest()` |
| `vigil/llm.py` | 加 `LLMConfig.max_tokens` 字段 + `sanitize_for_llm()` |
| `vigil/cli.py` | 加 `digest` 子命令 |
| `tests/test_store.py` | 追加日报持久化测试 |
| `tests/test_llm.py` | 追加 `max_tokens` / `sanitize_for_llm` 测试 |

**不改：** `refine.py` / `redact.py` / `categories.py` / `prefilter.py` / `config.py` / `export.py` / `reader.py` / `qqdb.py` / `text.py` / `senders.py` / `media.py`。

> ⚠️ **已知未修**：M1 的 `refine.py::build_user_prompt` 同样会把含 `“ ”` 的消息发出去（全库 25 条），理论上也会触发退化循环。**M2 不动它**——改它等于改 M1 已验证的提示词输入，会牵出 `PROMPT_VERSION` 升版与「无混版」出口核验（现有 270 条全是 v2）。列为本里程碑的遗留项，见 Task 5 的收尾清单。

---

## 任务依赖

```
Task 1 (持久化) ──→ Task 3 (匹配+渲染) ──→ Task 4 (编排+CLI) ──→ Task 5 (冒烟出口)
Task 2 (LLM加固+载荷) ─┘
```

Task 1 与 Task 2 互不依赖，但按 SDD pipeline **顺序执行**。

---

### Task 1: 日报持久化层

**Files:**
- Modify: `vigil/store.py`
- Modify: `tests/test_store.py`（**追加**，不覆盖）

**Dependencies:** 无

**Touches:** `vigil/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: 无（只用 stdlib 与既有 `messages` 表）
- Produces:
  - `vigil.store.WindowItem` — frozen dataclass，字段依次为 `item_id: int`, `kind: str`, `title: str`, `detail: str | None`, `event_ts: int`, `deadline_ts: int | None`, `group_id: int`, `place: str | None`, `amount: str | None`, `confidence: float`
  - `vigil.store.window_items(conn, *, since: int, until: int) -> list[WindowItem]`
  - `vigil.store.window_stats(conn, *, since: int, until: int) -> tuple[int, int]` — 返回 `(消息数, 群数)`
  - `vigil.store.save_digest(conn, *, window_from: int, window_to: int, body_md: str, model: str, prompt_ver: str, item_ids: list[int], now: int | None = None) -> int` — 返回 `digest_id`
  - `vigil.store.find_digest(conn, *, window_from: int, window_to: int) -> tuple[int, str] | None` — `(digest_id, body_md)`
  - `vigil.store.ensure_schema(conn)` 现在**同时**建 `digests` / `digest_items`

**设计要点：**

- `digests` 上建 **唯一索引** `(window_from, window_to)`，`save_digest` 先删旧的 `digests` 与 `digest_items` 再插——保证「同一天跑两次」是替换而不是堆叠。
- `window_items` 按 `event_ts ASC, item_id ASC` 排序。**保持确定性顺序**是必要的：机械补行按这个顺序追加、发给模型的 payload 也按它排列。
  ⚠️ **但分区与署名群不依赖它**——那由 `match_lines` 自己的 `hits.sort(key=(event_ts, item_id))` 决定。
  （这条因果在规划期被我写反过，Task 1 审查实测纠正：`build_rows` 的锚点是 `picked[0]`，而 `picked` 来自 `match_lines` 的输出，与 `window_items` 的顺序无关。）
- `window_stats` 用 `COUNT(DISTINCT group_id)`。窗口由 `ts` 区间划定，1970-01-01 那批脏数据天然落在窗口外，不需要额外过滤。

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_store.py` 末尾：

```python
# ── 日报持久化（M2 Task 1）─────────────────────────────────


def _seed_items(conn: sqlite3.Connection) -> None:
    """造三条 item：两条在窗口内、一条在窗口外，含一条低置信度。"""
    store.ensure_schema(conn)
    conn.executemany(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, links, amount, confidence, model,"
        " prompt_ver, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "notice", "体检表", "10月8日前交", 3000, 4000, 100, None,
             None, "[]", None, 0.9, "m", "v2", 1),
            (2, "activity", "讲座", None, 2000, None, 200, None,
             "报告厅", "[]", None, 0.3, "m", "v2", 1),
            (3, "notice", "窗口外的", None, 9999, None, 100, None,
             None, "[]", None, 0.9, "m", "v2", 1),
        ],
    )
    conn.commit()


def test_window_items_filters_and_orders(memdb):
    _seed_messages(memdb)
    _seed_items(memdb)

    got = store.window_items(memdb, since=1000, until=5000)

    assert [it.item_id for it in got] == [2, 1]   # 按 event_ts 升序
    assert got[0].title == "讲座"
    assert got[1].deadline_ts == 4000
    assert got[1].confidence == 0.9


def test_window_items_empty_when_no_items(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)

    assert store.window_items(memdb, since=1000, until=5000) == []


def test_window_stats_counts_messages_and_groups(memdb):
    _seed_messages(memdb)   # ts=1000(群100) / 2000(群100) / 3000(群200)

    assert store.window_stats(memdb, since=1000, until=4000) == (3, 2)
    assert store.window_stats(memdb, since=1000, until=2500) == (2, 1)
    assert store.window_stats(memdb, since=5000, until=6000) == (0, 0)


def test_save_digest_returns_id_and_links_items(memdb):
    _seed_items(memdb)

    digest_id = store.save_digest(
        memdb, window_from=1000, window_to=5000, body_md="# 日报",
        model="m", prompt_ver="v1", item_ids=[1, 2], now=12345,
    )

    assert digest_id > 0
    assert store.find_digest(memdb, window_from=1000, window_to=5000) == (
        digest_id, "# 日报",
    )
    linked = memdb.execute(
        "SELECT item_id FROM digest_items WHERE digest_id=? ORDER BY item_id",
        (digest_id,),
    ).fetchall()
    assert [r[0] for r in linked] == [1, 2]


def test_save_digest_replaces_same_window(memdb):
    """同一天跑两次必须是替换，不是堆叠——否则会出两篇同日日报。"""
    _seed_items(memdb)

    store.save_digest(
        memdb, window_from=1000, window_to=5000, body_md="# 第一版",
        model="m", prompt_ver="v1", item_ids=[1, 2],
    )
    store.save_digest(
        memdb, window_from=1000, window_to=5000, body_md="# 第二版",
        model="m", prompt_ver="v1", item_ids=[1],
    )

    # ⚠️ 不要断言「两次的 digest_id 不同」——SQLite 的 INTEGER PRIMARY KEY
    # 在表被删空后会**复用 rowid**，这里两次都会拿到 1，那样断言会假红
    # （规划期实测踩到过）。要守的是「只剩一篇、旧关联行清干净、内容是新的」。
    rows = memdb.execute("SELECT COUNT(*) FROM digests").fetchone()[0]
    assert rows == 1
    # 第二次只挂了 item 1，所以 item 2 的关联必须已经被清掉。
    # ⚠️ 也不能用「digest_items WHERE digest_id=? 的条数」判孤儿：id 被复用了，
    # 那个查询会查到**新日报自己的**关联行，测不出任何东西。
    linked = [
        r[0]
        for r in memdb.execute(
            "SELECT item_id FROM digest_items ORDER BY item_id"
        ).fetchall()
    ]
    assert linked == [1]
    # 真正的孤儿判据：关联行指向一篇不存在的日报
    orphan = memdb.execute(
        "SELECT COUNT(*) FROM digest_items"
        " WHERE digest_id NOT IN (SELECT digest_id FROM digests)"
    ).fetchone()[0]
    assert orphan == 0
    assert store.find_digest(memdb, window_from=1000, window_to=5000)[1] == "# 第二版"


def test_find_digest_absent_returns_none(memdb):
    store.ensure_schema(memdb)

    assert store.find_digest(memdb, window_from=1, window_to=2) is None


def test_ensure_schema_is_idempotent_for_digests(memdb):
    """ensure_schema 每次 refine/digest 都调，必须能重复执行。"""
    store.ensure_schema(memdb)
    store.ensure_schema(memdb)

    names = {
        r[0] for r in memdb.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"digests", "digest_items"} <= names
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_store.py -vv`
Expected: FAIL —— `AttributeError: module 'vigil.store' has no attribute 'window_items'`

- [ ] **Step 3: 实现**

在 `vigil/store.py` 的 `_RUNS_DDL` 之后插入：

```python
# digests：日报成品。日报是 items 在时间窗内的叙述性渲染，不是第二套抽取管线。
# 唯一索引保证「同一天跑两次」是替换——否则会在库里堆出两篇同日日报。
_DIGESTS_DDL = """
CREATE TABLE IF NOT EXISTS digests (
    digest_id   INTEGER PRIMARY KEY,
    window_from INTEGER NOT NULL,
    window_to   INTEGER NOT NULL,
    body_md     TEXT    NOT NULL,
    model       TEXT    NOT NULL,
    prompt_ver  TEXT    NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS digests_window ON digests(window_from, window_to);
"""

# digest_items：日报 ↔ 条目的互跳。M3 的「点回原文」靠它，
# 也是「日报里说的每一条都能在 Web 里找到」这句承诺的落地。
_DIGEST_ITEMS_DDL = """
CREATE TABLE IF NOT EXISTS digest_items (
    digest_id INTEGER NOT NULL,
    item_id   INTEGER NOT NULL,
    PRIMARY KEY (digest_id, item_id)
);
CREATE INDEX IF NOT EXISTS digest_items_item ON digest_items(item_id);
"""
```

把 `SCHEMA_DDL` 一行改成：

```python
SCHEMA_DDL = (
    _ITEMS_DDL + _SOURCES_DDL + _RUNS_DDL + _DIGESTS_DDL + _DIGEST_ITEMS_DDL
)
```

把模块 docstring 里那句 `digests / digest_items 属于 M2，本模块不建` 删掉，换成：

```python
`digests` / `digest_items` 由 M2 建立——M1 建了也没有写入方。
```

在 `ExtractedItem` 定义之后追加：

```python
@dataclass(frozen=True)
class WindowItem:
    """日报要用到的一条条目。只含渲染与匹配需要的列。"""

    item_id: int
    kind: str
    title: str
    detail: str | None
    event_ts: int
    deadline_ts: int | None
    group_id: int
    place: str | None
    amount: str | None
    confidence: float
```

在文件末尾追加：

```python
def window_items(
    conn: sqlite3.Connection, *, since: int, until: int
) -> list[WindowItem]:
    """取时间窗内的条目，按事件时间升序。

    ⚠️ **排序必须确定**：机械补行按这个顺序追加、发给模型的 payload 也按它排列。
    但**分区与署名群不依赖它**——那由 ``digest.match_lines`` 自己的
    ``hits.sort(key=(event_ts, item_id))`` 决定，与本函数的顺序无关。
    """
    rows = conn.execute(
        "SELECT item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, place, amount, confidence"
        " FROM items WHERE event_ts >= ? AND event_ts < ?"
        " ORDER BY event_ts ASC, item_id ASC",
        (since, until),
    ).fetchall()
    return [WindowItem(*row) for row in rows]


def window_stats(
    conn: sqlite3.Connection, *, since: int, until: int
) -> tuple[int, int]:
    """窗口内的 (消息数, 群数)。日报开头那句「N 个群 M 条消息」用它。

    按 ts 区间取，1970-01-01 那批脏数据天然落在窗口外——不需要额外过滤，
    也就不会误把它们算进消息数。
    """
    return conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT group_id) FROM messages"
        " WHERE ts >= ? AND ts < ?",
        (since, until),
    ).fetchone()


def save_digest(
    conn: sqlite3.Connection,
    *,
    window_from: int,
    window_to: int,
    body_md: str,
    model: str,
    prompt_ver: str,
    item_ids: list[int],
    now: int | None = None,
) -> int:
    """写一篇日报，返回 digest_id。同一个窗口**替换**而不是追加。

    先删旧的 digest_items 再删 digests：不删关联行的话，重跑一次就会在
    digest_items 里留下指向前一版日报的孤儿行。
    """
    stamp = int(time.time()) if now is None else now
    conn.execute(
        "DELETE FROM digest_items WHERE digest_id IN"
        " (SELECT digest_id FROM digests WHERE window_from=? AND window_to=?)",
        (window_from, window_to),
    )
    conn.execute(
        "DELETE FROM digests WHERE window_from=? AND window_to=?",
        (window_from, window_to),
    )
    cur = conn.execute(
        "INSERT INTO digests (window_from, window_to, body_md, model,"
        " prompt_ver, created_at) VALUES (?,?,?,?,?,?)",
        (window_from, window_to, body_md, model, prompt_ver, stamp),
    )
    digest_id = int(cur.lastrowid or 0)
    conn.executemany(
        "INSERT OR IGNORE INTO digest_items (digest_id, item_id) VALUES (?,?)",
        [(digest_id, iid) for iid in item_ids],
    )
    conn.commit()
    return digest_id


def find_digest(
    conn: sqlite3.Connection, *, window_from: int, window_to: int
) -> tuple[int, str] | None:
    """按窗口找已存的日报，返回 ``(digest_id, body_md)``。没有就是 None。"""
    row = conn.execute(
        "SELECT digest_id, body_md FROM digests WHERE window_from=? AND window_to=?",
        (window_from, window_to),
    ).fetchone()
    return (row[0], row[1]) if row else None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_store.py -vv`
Expected: 全部 PASS（M1 原有的 + 新增 7 条）

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 138 + 7 = **145 passed**（M1 基线 138 条不许掉）

- [ ] **Step 5: Commit**

```bash
git add vigil/store.py tests/test_store.py
git commit -m "feat(store): 加日报持久化（digests/digest_items 表 + 窗口查询与幂等写入）"
```

---

### Task 2: LLM 客户端加固 + 日报载荷构造

**Files:**
- Modify: `vigil/llm.py`
- Create: `vigil/digest.py`（本任务只放常量、载荷与提示词）
- Modify: `tests/test_llm.py`（**追加**）
- Create: `tests/test_digest.py`

**Dependencies:** [Task 1]

**Touches:** `vigil/llm.py`, `vigil/digest.py`, `tests/test_llm.py`, `tests/test_digest.py`

**Interfaces:**
- Consumes: `vigil.store.WindowItem`（Task 1）；`vigil.redact.Redactor`（M1 已有）
- Produces:
  - `vigil.llm.sanitize_for_llm(text: str) -> str`
  - `vigil.llm.LLMConfig.max_tokens: int | None = None`（字段；`None` = 不发该字段）
  - `vigil.digest.PROMPT_VERSION: str = "v1"`
  - `vigil.digest.LOW_CONFIDENCE: float = 0.5`
  - `vigil.digest.MAX_TOKENS: int = 2000`
  - `vigil.digest.build_system_prompt() -> str`
  - `vigil.digest.build_items_payload(items: list[store.WindowItem], names: dict[int, str], redactor: Redactor) -> list[dict]`
  - `vigil.digest.build_user_prompt(payload: list[dict], *, day: str) -> str`

**三条硬规则**（每条都有探针实测支撑，见「规划期间的探针实测」节）：

1. `build_items_payload` **只发群名，不发群号**（spec §4.5）
2. 每个文本字段都过 **`Redactor.text()`** 再出网（纵深防御：item 是模型抽的，它会「补出原文没有的实体」）
3. 每个文本字段都过 **`sanitize_for_llm()`**（全角引号会让模型退化成无限空格循环）

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_llm.py` 末尾：

```python
# ── max_tokens 与字符归一化（M2 Task 2）────────────────────


def test_max_tokens_omitted_by_default(monkeypatch, cfg):
    """默认不发 max_tokens——M1 的 refine 行为必须一字不变。"""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse(_envelope("{}"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    chat_json(cfg, system="s", user="u", sleep=lambda _: None)

    assert "max_tokens" not in captured["body"]


def test_max_tokens_sent_when_set(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse(_envelope("{}"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    chat_json(
        LLMConfig(api_key="k", max_tokens=2000),
        system="s", user="u", sleep=lambda _: None,
    )

    assert captured["body"]["max_tokens"] == 2000


def test_sanitize_replaces_fullwidth_quotes():
    """实测：全角引号会让模型退化成无限空格循环（85s 未收尾）。"""
    assert sanitize_for_llm("昵称“风之海310”") == "昵称「风之海310」"


def test_sanitize_leaves_other_text_alone():
    """只修有证据的那一处，别的标点不许顺手改。"""
    assert sanitize_for_llm("【通知】9月14日…") == "【通知】9月14日…"
```

把 `tests/test_llm.py` 顶部的 import 改成：

```python
from vigil.llm import LLMConfig, LLMError, chat_json, sanitize_for_llm
```

创建 `tests/test_digest.py`：

```python
"""日报合成的测试。**全部用构造样本，不联网、不碰 data/vigil.db。**"""

from __future__ import annotations

import sqlite3

import pytest

from vigil import digest
from vigil.redact import Redactor
from vigil.store import WindowItem


def _item(
    item_id: int = 1,
    *,
    kind: str = "notice",
    title: str = "体检表",
    detail: str | None = "10月8日前交到辅导员处",
    event_ts: int = 1000,
    deadline_ts: int | None = None,
    group_id: int = 100,
    place: str | None = None,
    amount: str | None = None,
    confidence: float = 0.9,
) -> WindowItem:
    return WindowItem(
        item_id=item_id, kind=kind, title=title, detail=detail,
        event_ts=event_ts, deadline_ts=deadline_ts, group_id=group_id,
        place=place, amount=amount, confidence=confidence,
    )


# ── 载荷构造 ────────────────────────────────────────────────


def test_payload_sends_group_name_not_id():
    """⚠️ 探针第一版就是把 group_id 明文发了出去——这条测试守着它。"""
    payload = digest.build_items_payload(
        [_item(group_id=643375490)], {643375490: "新生群"}, Redactor()
    )

    assert payload[0]["group"] == "新生群"
    assert "643375490" not in json.dumps(payload, ensure_ascii=False)


def test_payload_sanitizes_fullwidth_quotes():
    payload = digest.build_items_payload(
        [_item(title="卖笔记", detail="昵称“风之海310”")], {}, Redactor()
    )

    assert "“" not in payload[0]["detail"]
    assert "「风之海310」" in payload[0]["detail"]


def test_payload_redacts_phone_numbers():
    """item 是模型从脱敏文本里抽的，但它会补出原文没有的实体——出网前再抹一遍。"""
    payload = digest.build_items_payload(
        [_item(detail="联系 13812345678 报名")], {}, Redactor()
    )

    assert "13812345678" not in payload[0]["detail"]


def test_payload_formats_time_and_deadline():
    import datetime as dt

    ts = int(dt.datetime(2026, 9, 13, 14, 20).timestamp())
    dl = int(dt.datetime(2026, 10, 8).timestamp())
    payload = digest.build_items_payload([_item(event_ts=ts, deadline_ts=dl)], {}, Redactor())

    assert payload[0]["time"] == "14:20"
    assert payload[0]["deadline"] == "2026-10-08"


def test_payload_null_dashes_stay_null():
    payload = digest.build_items_payload(
        [_item(detail=None, place=None, amount=None, deadline_ts=None)], {}, Redactor()
    )

    assert payload[0]["detail"] is None
    assert payload[0]["deadline"] is None


def test_system_prompt_states_the_three_contracts():
    prompt = digest.build_system_prompt()

    assert "quotes" in prompt      # 逐字摘录
    assert "label" in prompt       # 短标签
    assert "不要编造" in prompt     # 不许补原文没有的实体


def test_user_prompt_carries_the_day():
    prompt = digest.build_user_prompt([], day="2026-09-13")

    assert "2026-09-13" in prompt
```

`tests/test_digest.py` 顶部补上 `import json`（`test_payload_sends_group_name_not_id` 用到）：

```python
import json
import sqlite3

import pytest
```

> `sqlite3` / `pytest` 本任务还用不到，但 Task 3、Task 4 会用到，先按最终形态导入。若 lint 报未使用，保留即可——**不要删**，删了 Task 3 会再改一次这个文件的头部。

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm.py tests/test_digest.py -vv`
Expected: FAIL —— `ImportError: cannot import name 'sanitize_for_llm'` 与 `ModuleNotFoundError: No module named 'vigil.digest'`

- [ ] **Step 3: 实现 —— 先改 `vigil/llm.py`**

模块 docstring 的「三处易错点」后面追加第四条：

```
  4. **全角引号会让模型退化成无限空格循环。** 2026-09-15 实测：同一份 10 条
     item 的日报请求，某条 detail 含 ``“ ”`` 时 85s 未收尾、已吐 8,896 字且
     仍在继续；把该处换成 ``「」`` 后 6.2s 正常返回。发往模型前请过
     ``sanitize_for_llm``。
```

在 `_FENCE` 之前插入：

```python
# 模型在 chat 模板里遇到全角引号会退化成**无限空格循环**——2026-09-15 实测：
#
#   原样发出（detail 含 “风之海310”）  → 85s 未收尾，已吐 8,896 字且仍在继续
#   把该处 “ ” 换成 「」              → 6.2s 正常返回
#   全部条目的 “ ” 都换掉            → 5.8s 正常返回
#
# 实测分布：items 270 条里 4 条命中（1.5%）、messages 47,719 条里 25 条命中。
# 频率不高，但第一次拿真实数据试就撞上了。
#
# ⚠️ **只修有证据的这一处。** 【】『』… 没有实测过会退化，不要顺手加进来——
# 加了没有依据，日后也没法追溯为什么这么写。真要加，先做实验。
_LLM_UNSAFE = str.maketrans({"“": "「", "”": "」"})


def sanitize_for_llm(text: str) -> str:
    """把会让模型退化的字符换成安全等价物。发往模型的文本都要过这一道。"""
    return text.translate(_LLM_UNSAFE)
```

在 `LLMConfig` 里、`enable_thinking` 之后追加字段：

```python
    # 输出 token 上限。None = **不发这个字段**（老模型不一定认）。
    # 默认 None 是为了让 M1 的 refine 行为一字不变；日报显式传 2000。
    # 为什么必须有：模型一旦退化成上面的空格循环，唯一能拦住它的就是超时
    # ——180s × 3 次重试 ≈ 9 分钟空转。实测加 max_tokens=1200 后同样的失控
    # 请求 23s 就停（虽被截断，但兜住了）。
    max_tokens: int | None = None
```

在 `chat_json` 里、`if cfg.enable_thinking is not None:` 那两行之后追加：

```python
    if cfg.max_tokens is not None:
        request_body["max_tokens"] = cfg.max_tokens
```

- [ ] **Step 4: 实现 —— 再建 `vigil/digest.py`**

```python
"""日报合成：把某个时间窗内的 items 写成给同学看的一页 Markdown。

三条设计判断，每条都有实测或 spec 支撑：

1. **输入是 items，不是原始消息**（spec §2.4）。筛选在 M1 已经做完，
   日报**不再筛第二遍**——窗口内每条 item 都必须出现在日报里，
   否则就是又一个静默过滤器，而「静默漏掉」正是这个工具最不能犯的错。
2. **不问模型要 item_id**。M1 实测：19 位雪花号命中 0/2、批内序号在真实
   管线里也错。改成让模型**逐字摘录 title**，由 ``match_lines`` 本地定位。
3. **模型只负责措辞与合并，版式由程序确定性渲染**（与 spec §4.6 的偏差 1）。
   自由发挥的 Markdown 无法可靠回连 ``digest_items``，而 spec §2.3 要求
   「日报里说的每一条，必然能在 Web 里找到」。

模型输出契约（``{"lines": [{"quotes": [...], "label": "...", "text": "..."}]}``）
的措辞经真实数据探针验证：9/13 的 10 条并成 8 行、9/8 的 13 条并成 7 行，
两天都是 100% 覆盖、0 处 quote 未命中。
"""

from __future__ import annotations

import datetime as dt

from . import store
from .llm import sanitize_for_llm
from .redact import Redactor

# 日报有自己的提示词版本，与 refine.PROMPT_VERSION 各记各的。
# 改了 build_system_prompt 就要升这里，否则 digests 表里新老产出分不清。
PROMPT_VERSION = "v1"

# 低于这个置信度的行不混进正文，单列到末尾的「🤔 拿不准的」区块。
# 实测全库只有 1 条落在这个区间（M1 误抽的「咨询：四六级报名时间」，0.10），
# 所以它是安全阀而非常态。
LOW_CONFIDENCE = 0.5

# 输出上限。正常一天 20 条 item 的日报约 550 输出 token，2000 有充足余量；
# 但要小到能在模型退化时及时掐断（见 vigil/llm.py 的退化说明）。
MAX_TOKENS = 2000


def build_system_prompt() -> str:
    """系统提示词。

    ⚠️ 第 6 条（不要写群名）是实测逼出来的：不写这条时模型会把群名当主语
    写进 text（「常大二手咸鱼⑤群发布兼职招聘」），而群名是程序在行尾另外
    追加的，读起来就重复了。但群名**又必须发**——它是模型判断「哪些条目
    属于同一件事」的信号，去掉后 9/13 的合并从 8 行退化回 10 行。
    所以：**发群名，但明令禁止写进输出。**

    ⚠️ 第 2 条（合并）要写在 rules 前部：合并是 spec §4.6 明确要求的
    「合并同类项」，漏掉它日报就退化成 items 的流水账。
    """
    return """你是校园信息日报的编辑。把当天从各个 QQ 群里提炼出的条目，写成一份给同学看的一页日报。

读者的诉求是：**一眼看完，不漏事**。

规则：

1. **每一条 item 都必须出现在日报里**——不能因为"这条不重要"就省略。
2. **讲同一件事的多条 item 合并成一行**：同一个活动、同一个部门、同一件事的
   多条动态，合成一行讲清楚。合并时 quotes 要把涉及的每一条都列上。
3. quotes：逐字摘录你引用的那几条 item 的 title 原文片段。程序拿它回连条目，
   **匹配不上的行会被丢弃**，所以必须逐字照抄，不要改写。
4. label：**不超过 12 个字**的短标签，说明这一行讲的是什么。它会加粗显示在行首，
   要能一眼扫到，**不要写成完整句子**。
5. text：一句话说清细节，让人不看原文就知道该怎么办；没有额外信息时给空串。
6. 输入里的 group 字段只用来帮你判断哪些条目属于同一件事，
   **不要把它写进 label 或 text**——程序会在行尾自动标注来源群。
7. **不要编造 item 里没有的信息**——时间、地点、部门、人名，宁可不写也不能补。

输出必须是 JSON 对象，形如 {"lines": [{"quotes": ["..."], "label": "...", "text": "..."}]}。"""


def build_items_payload(
    items: list[store.WindowItem],
    names: dict[int, str],
    redactor: Redactor,
) -> list[dict]:
    """把窗口内的 items 整理成发给模型的 JSON。

    ⚠️ 三条硬规则，每条都有实测支撑，少一条都出过事：

    * **只发群名，不发群号**（spec §4.5）。规划期间的探针第一版就是把
      ``group_id`` 明文发了出去——全库 15 个群号本来就不该出网。
    * **过 Redactor**：item 是模型从已脱敏文本里抽的，但它会「补出原文
      没有的实体」，所以出网前再抹一遍号码。
    * **过 sanitize_for_llm**：全角引号会让模型退化成无限空格循环。
    """

    def clean(value: str | None) -> str | None:
        if not value:
            return None
        return sanitize_for_llm(redactor.text(value)) or None

    payload = []
    for item in items:
        payload.append(
            {
                "title": clean(item.title) or "",
                "detail": clean(item.detail),
                "kind": item.kind,
                "time": dt.datetime.fromtimestamp(item.event_ts).strftime("%H:%M"),
                "place": clean(item.place),
                "amount": clean(item.amount),
                "deadline": (
                    dt.datetime.fromtimestamp(item.deadline_ts).strftime("%Y-%m-%d")
                    if item.deadline_ts
                    else None
                ),
                "group": sanitize_for_llm(names.get(item.group_id, "")),
            }
        )
    return payload


def build_user_prompt(payload: list[dict], *, day: str) -> str:
    """用户提示词。载荷已经是脱敏过的，这里只负责拼装与注入日期。

    注入「今天是哪天」是必须的——M1 实测：不告诉模型今天，它会把
    「9月7号」猜成过去的年份。
    """
    import json

    body = json.dumps({"items": payload}, ensure_ascii=False, indent=1)
    return f"今天的日期是 {day}。\n\n以下是 {day} 这一天提炼出的条目：\n{body}"
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm.py tests/test_digest.py -vv`
Expected: 全部 PASS

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: **156 passed**（Task 1 的 145 + 本任务 11 条：test_llm 4 条 + test_digest 7 条）
（这个数字是规划期**实测**出来的，不是估算。逐文件：test_store 18 / test_llm 17 / test_digest 45。）

- [ ] **Step 6: 真实连通性冒烟（本任务唯一一次联网）**

用真实数据验证载荷与提示词端到端能跑通（不入库、不写文件）：

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
sys.argv=['x']
from _probe_digest import fetch, build_items          # 规划期的探针，见仓库根
from vigil import digest
from vigil.config import load_config, load_llm_key
from vigil.llm import LLMConfig, chat_json
from vigil.redact import Redactor
cfg = load_config(); names = {g.id: g.name for g in cfg.groups}
items = [build_items([r], names, Redactor())[0] for r in []]
"
```

> ⚠️ **本步骤改用更直接的形式**——上面那段是占位说明，实际执行下面这条：

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import sys, time; sys.path.insert(0,'.'); sys.argv=['x']
import sqlite3, datetime as dt
from vigil import digest, store
from vigil.config import load_config, load_llm_key
from vigil.llm import LLMConfig, chat_json
from vigil.redact import Redactor
cfg = load_config(); names = {g.id: g.name for g in cfg.groups}
conn = sqlite3.connect('data/vigil.db')
since, until = digest.day_window('2026-09-13')
items = store.window_items(conn, since=since, until=until)
payload = digest.build_items_payload(items, names, Redactor())
sys_p, usr_p = digest.build_system_prompt(), digest.build_user_prompt(payload, day='2026-09-13')
t = time.time()
r = chat_json(LLMConfig(api_key=load_llm_key(), max_tokens=digest.MAX_TOKENS,
                        enable_thinking=False), system=sys_p, user=usr_p)
print(f'{time.time()-t:.1f}s  {r.input_tokens}/{r.output_tokens} tok')
print('lines:', len(r.payload.get('lines') or []))
for l in (r.payload.get('lines') or [])[:3]:
    print(' ', l.get('label'), '|', (l.get('quotes') or [''])[0])
"
```

Expected: 打印耗时、token 用量与至少一行 `label`，**10 秒内返回**。
⚠️ 若超过 60 秒仍未返回，**不要直接判失败**——先看是不是有残留的探针进程占着并发（见「探针实测发现 4」），再重试一次。

- [ ] **Step 7: Commit**

```bash
git add vigil/llm.py vigil/digest.py tests/test_llm.py tests/test_digest.py
git commit -m "feat: 加日报载荷与提示词；给 LLM 客户端补 max_tokens 与全角引号归一化"
```

---

### Task 3: quote 匹配与确定性渲染

**Files:**
- Modify: `vigil/digest.py`（追加）
- Modify: `tests/test_digest.py`（追加）

**Dependencies:** [Task 1, Task 2]

**Touches:** `vigil/digest.py`, `tests/test_digest.py`

**Interfaces:**
- Consumes: `vigil.store.WindowItem`（Task 1）、`vigil.categories.Category`（M1）
- Produces:
  - `vigil.digest.DigestLine` — frozen dataclass，字段 `label: str`, `text: str`, `item_ids: tuple[int, ...]`
  - `vigil.digest.Row` — frozen dataclass，字段 `label: str`, `text: str`, `kind: str`, `group_id: int`, `deadline_ts: int | None`, `low_confidence: bool`, `mechanical: bool = False`
  - `vigil.digest.match_lines(raw_lines: object, items: list[store.WindowItem]) -> tuple[list[DigestLine], list[str]]`
  - `vigil.digest.build_rows(lines: list[DigestLine], items: list[store.WindowItem], *, low_confidence: float = LOW_CONFIDENCE) -> list[Row]`
  - `vigil.digest.stat_line(*, groups: int, messages: int, items: int) -> str`
  - `vigil.digest.render_markdown(*, day: str, stat_line: str, rows: list[Row], cats: tuple[Category, ...], names: dict[int, str], window_from: int = 0) -> str`
  - `vigil.digest.yesterday(today: dt.date | None = None) -> str`
  - `vigil.digest.day_window(date_str: str) -> tuple[int, int]`

**设计要点：**

- **未被任何一行引用的 item 会被机械补一行**（`mechanical=True`）。日报的价值在「不漏」，宁可读起来生硬也不能因为模型漏写就丢条目。
- **「别忘」区块 = 有 `deadline_ts` 且 `deadline_ts >= window_from` 的行**。加这个下界是真实数据逼出来的：全库有 1 条 item 的 deadline 早于事件日（8/5 的条目挂着 5/6 的截止），不过滤的话会在八月日报里冒出「别忘 5 月 6 日」。
- **「别忘」里的行不再出现在类目区块**，避免同一件事读两遍。
- 行的锚点 = `match_lines` 排好序后的**第一个** item（由它自己的 `hits.sort` 决定，**不是** `window_items` 的顺序），它决定类目与署名群。

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_digest.py` 末尾：

```python
# ── quote 匹配 ──────────────────────────────────────────────


def test_match_lines_finds_item_by_quote():
    items = [_item(1, title="体检表"), _item(2, title="讲座", event_ts=2000)]

    lines, unmatched = digest.match_lines(
        [{"quotes": ["讲座"], "label": "学术讲座", "text": "周五晚 7 点"}], items
    )

    assert unmatched == []
    assert len(lines) == 1
    assert lines[0].label == "学术讲座"
    assert lines[0].item_ids == (2,)


def test_match_lines_tolerates_inserted_spaces():
    """⚠️ 实测：模型会在数字两侧插空格（原文「风之海310」它写成「风之海 310」）。

    直接子串匹配会漏掉这种**格式**差异，但归一化后两侧都无空格、仍逐字对应。
    """
    items = [_item(1, detail="百度网盘搜索昵称“风之海310”")]

    lines, unmatched = digest.match_lines(
        [{"quotes": ["风之海 310"], "label": "卖笔记", "text": ""}], items
    )

    assert unmatched == []
    assert lines[0].item_ids == (1,)


def test_match_lines_merges_multiple_quotes():
    items = [_item(1, title="面试地点变更"), _item(2, title="录取名单公布", event_ts=2000)]

    lines, _ = digest.match_lines(
        [{"quotes": ["面试地点变更", "录取名单公布"], "label": "新媒体", "text": "…"}],
        items,
    )

    assert lines[0].item_ids == (1, 2)


def test_match_lines_reports_unmatched_quotes():
    items = [_item(1, title="体检表")]

    lines, unmatched = digest.match_lines(
        [{"quotes": ["根本不存在的标题"], "label": "x", "text": ""}], items
    )

    assert lines == []
    assert unmatched == ["根本不存在的标题"]


def test_match_lines_drops_too_short_quote():
    """太短的摘录容易误命中，宁可丢——沿用 refine._match_source 的判断。"""
    items = [_item(1, title="体检表")]

    lines, unmatched = digest.match_lines(
        [{"quotes": ["表"], "label": "x", "text": ""}], items
    )

    assert lines == []
    assert unmatched == ["表"]


def test_match_lines_ignores_malformed_entries():
    """模型偶尔会返回字符串或 null 元素，不能让它们崩掉整轮。"""
    lines, unmatched = digest.match_lines(
        ["不是字典", None, {"quotes": "不是数组"}, {"quotes": ["体检表"], "label": "a"}],
        [_item(1, title="体检表")],
    )

    assert len(lines) == 1
    assert lines[0].label == "a"


def test_match_lines_falls_back_to_title_when_label_missing():
    lines, _ = digest.match_lines(
        [{"quotes": ["体检表"], "text": ""}], [_item(1, title="体检表")]
    )

    assert lines[0].label == "体检表"


def test_match_lines_one_quote_matching_two_items_marks_both():
    """标题重复的两条（实测全库有，如「校园卡办理」系列）必须都算覆盖。"""
    items = [_item(1, title="校园卡办理"), _item(2, title="校园卡办理", event_ts=2000)]

    lines, _ = digest.match_lines(
        [{"quotes": ["校园卡办理"], "label": "校园卡", "text": ""}], items
    )

    assert lines[0].item_ids == (1, 2)


# ── 机械补行 ────────────────────────────────────────────────


def test_build_rows_appends_mechanical_row_for_uncovered_item():
    items = [_item(1, title="体检表"), _item(2, title="讲座", event_ts=2000)]
    lines, _ = digest.match_lines(
        [{"quotes": ["体检表"], "label": "体检", "text": "10月8日前交"}], items
    )

    rows = digest.build_rows(lines, items)

    assert [r.mechanical for r in rows] == [False, True]
    assert rows[1].label == "讲座"


def test_build_rows_marks_low_confidence_only_when_all_items_low():
    items = [
        _item(1, title="存疑", confidence=0.1),
        _item(2, title="确定的", confidence=0.9, event_ts=2000),
    ]
    lines, _ = digest.match_lines(
        [
            {"quotes": ["存疑"], "label": "a", "text": ""},
            {"quotes": ["确定的"], "label": "b", "text": ""},
        ],
        items,
    )

    rows = digest.build_rows(lines, items)

    assert rows[0].low_confidence is True
    assert rows[1].low_confidence is False


def test_build_rows_merged_row_is_confident_when_any_item_is():
    items = [_item(1, title="存疑", confidence=0.1), _item(2, title="确定的", confidence=0.9, event_ts=2000)]
    lines, _ = digest.match_lines(
        [{"quotes": ["存疑", "确定的"], "label": "a", "text": ""}], items
    )

    rows = digest.build_rows(lines, items)

    assert rows[0].low_confidence is False
    assert rows[0].deadline_ts is None


def test_build_rows_takes_earliest_deadline_of_merged_items():
    items = [
        _item(1, title="甲", deadline_ts=5000),
        _item(2, title="乙", deadline_ts=4000, event_ts=2000),
    ]
    lines, _ = digest.match_lines(
        [{"quotes": ["甲", "乙"], "label": "合并", "text": ""}], items
    )

    assert digest.build_rows(lines, items)[0].deadline_ts == 4000


def test_build_rows_mechanical_row_keeps_own_confidence():
    items = [_item(1, title="存疑的", confidence=0.1)]

    rows = digest.build_rows([], items)

    assert rows[0].mechanical is True
    assert rows[0].low_confidence is True


# ── 渲染 ────────────────────────────────────────────────────


@pytest.fixture
def cats():
    from vigil.categories import Category

    return (
        Category("notice", "通知公告", "正式通知", "📋"),
        Category("activity", "活动", "讲座与社团", "🎤"),
        Category("academic", "学业", "作业与考试", "📚"),
    )


def _render(rows, cats, *, window_from=0, names=None, groups=3, messages=412):
    return digest.render_markdown(
        day="2026-09-13",
        stat_line=digest.stat_line(groups=groups, messages=messages,
                                   items=sum(1 for _ in rows) or 0),
        rows=rows, cats=cats, names=names or {}, window_from=window_from,
    )


def test_render_header_and_stat_line(cats):
    out = _render([digest.Row("体检表", "10月8日前交", "notice", 100, None, False)], cats)

    assert out.startswith("# 守夜人日报 · 2026-09-13")
    assert "3 个群 412 条消息" in out
    assert "## 📋 通知公告" in out
    assert "- **体检表** 10月8日前交" in out


def test_render_appends_group_name(cats):
    out = _render(
        [digest.Row("体检表", "", "notice", 100, None, False)],
        cats, names={100: "储运263班级群"},
    )

    assert out.rstrip().endswith("· 储运263班级群")


def test_render_omits_tail_when_group_unknown(cats):
    """群名查不到时不要退回群号——那是本不该出现在成品里的数字。"""
    out = _render([digest.Row("体检表", "", "notice", 999, None, False)], cats)

    assert "999" not in out


def test_render_alerts_section_for_future_deadline(cats):
    rows = [digest.Row("体检表", "交到辅导员处", "notice", 100, 5000, False)]

    out = _render(rows, cats, window_from=1000)

    assert "## ⏰ 别忘" in out
    assert "截止 " in out
    # 进了「别忘」就不该在类目区块里再出现一次
    assert out.count("**体检表**") == 1


def test_render_excludes_already_past_deadline_from_alerts(cats):
    """⚠️ 实测数据里有 deadline 早于事件日的条目（8/5 的条目挂 5/6 的截止）。

    不过滤的话，八月日报里会冒出「别忘 5 月 6 日」这种不可能执行的事。
    """
    rows = [digest.Row("档案袋封口", "", "notice", 100, 500, False)]

    out = _render(rows, cats, window_from=1000)

    assert "## ⏰ 别忘" not in out
    assert "- **档案袋封口**" in out        # 仍然要出现在类目区块里，不丢


def test_render_sections_follow_category_order(cats):
    rows = [
        digest.Row("a", "", "academic", 100, None, False),
        digest.Row("b", "", "activity", 100, None, False),
        digest.Row("c", "", "notice", 100, None, False),
    ]

    out = _render(rows, cats)

    assert out.index("## 📋 通知公告") < out.index("## 🎤 活动") < out.index("## 📚 学业")


def test_render_unknown_kind_is_kept_not_dropped(cats):
    """类目表里没有的 kind（理论上不该有）排到最后，但**不能静默丢**。"""
    out = _render([digest.Row("x", "", "没见过的类目", 100, None, False)], cats)

    assert "- **x**" in out


def test_render_unsure_section_comes_last(cats):
    rows = [
        digest.Row("确定", "", "notice", 100, None, False),
        digest.Row("存疑", "", "academic", 100, None, True),
    ]

    out = _render(rows, cats)

    assert "## 🤔 拿不准的" in out
    assert out.index("## 🤔 拿不准的") > out.index("## 📋 通知公告")
    assert out.index("**存疑**") > out.index("## 🤔 拿不准的")


def test_render_low_confidence_beats_deadline(cats):
    """既低置信度又有截止日的行归「拿不准」——存疑的信息不该催人去办。"""
    rows = [digest.Row("存疑", "", "notice", 100, 5000, True)]

    out = _render(rows, cats, window_from=1000)

    assert "## ⏰ 别忘" not in out
    assert "## 🤔 拿不准的" in out


def test_render_empty_window_says_no_news(cats):
    out = digest.render_markdown(
        day="2026-08-08", stat_line=digest.stat_line(groups=2, messages=12, items=0),
        rows=[], cats=cats, names={},
    )

    assert "没有值得一提的信息" in out
    assert "# 守夜人日报 · 2026-08-08" in out


def test_stat_line_mentions_items_when_present(cats):
    assert "提炼出 7 条" in digest.stat_line(groups=3, messages=412, items=7)


def test_stat_line_omits_items_when_zero():
    line = digest.stat_line(groups=2, messages=12, items=0)

    assert "提炼出" not in line
    assert "12" in line


# ── 窗口换算 ────────────────────────────────────────────────


def test_day_window_covers_exactly_one_day():
    since, until = digest.day_window("2026-09-13")

    assert until - since == 86400
    import datetime as dt

    assert dt.datetime.fromtimestamp(since).strftime("%H:%M") == "00:00"


def test_day_window_rejects_garbage():
    with pytest.raises(ValueError):
        digest.day_window("昨天")


def test_yesterday_defaults_to_the_day_before_today():
    import datetime as dt

    assert digest.yesterday(dt.date(2026, 9, 15)) == "2026-09-14"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_digest.py -vv`
Expected: FAIL —— `AttributeError: module 'vigil.digest' has no attribute 'match_lines'`

- [ ] **Step 3: 实现**

在 `vigil/digest.py` 末尾追加（`import re` 与 `from dataclasses import dataclass, field` 加到文件头部 import 区）：

```python
# 归一化时剥掉的字符：空白与常见中英文标点。与 refine.py 同款取值。
# 目的是容忍「（640）」vs「(640)」这类**格式**差异，不是容忍改写。
_PUNCT = re.compile(r"[\s，。！？、：；「」『』【】（）()\[\]…~～\-—]+")


def _norm(text: str) -> str:
    """归一化。**只动标点与空白，不动汉字与数字。**

    ⚠️ 为什么必须归一化而不是直接 `in`：实测模型会在数字两侧插空格
    （原文「风之海310」它写成「风之海 310」）。直接子串匹配会漏掉这种
    纯格式差异，而归一化后两侧都无空格、仍逐字对应。
    """
    return _PUNCT.sub("", text)


@dataclass(frozen=True)
class DigestLine:
    """模型返回的一行，已匹配回具体的 items。"""

    label: str
    text: str
    item_ids: tuple[int, ...]


@dataclass(frozen=True)
class Row:
    """日报里最终要渲染的一行。渲染只认它，不认模型返回的原始结构。"""

    label: str
    text: str
    kind: str
    group_id: int
    deadline_ts: int | None
    low_confidence: bool
    mechanical: bool = False


def match_lines(
    raw_lines: object, items: list[store.WindowItem]
) -> tuple[list[DigestLine], list[str]]:
    """把模型返回的行匹配回 items，返回 ``(命中行, 未命中的 quotes)``。

    **匹配不上就丢掉那一行，由 build_rows 用机械补行兜住**——宁可读起来
    生硬，也不能把条目静默丢了。未命中的 quotes 会返回给调用方计数上报。

    一个 quote 可能命中**多条** item（实测全库有重复标题，如「校园卡办理」
    系列 5 条）——全都要算覆盖，否则那些条目会被误判成「模型漏了」而
    补出重复的机械行。
    """
    if not isinstance(raw_lines, list):
        return [], []

    normed = [
        (it, _norm(it.title), _norm(f"{it.title} {it.detail or ''}")) for it in items
    ]
    lines: list[DigestLine] = []
    unmatched: list[str] = []

    for raw in raw_lines:
        if not isinstance(raw, dict):
            continue
        quotes = raw.get("quotes")
        if not isinstance(quotes, list):
            continue
        hits: list[store.WindowItem] = []
        for quote in quotes:
            raw_quote = str(quote).strip()
            needle = _norm(raw_quote)
            if not needle:
                continue
            # ⚠️ 先按「整个 title 逐字相等」找。**这一步不能省**：title 本身
            # 可能只有两三个字（「讲座」「体检表」），下面那条子串规则有长度
            # 下限，短标题只能靠这条路命中。
            #
            # 这是规划期实测抓到的缺陷：初版把 refine._match_source 的
            # 「摘录短于 4 字就丢」原样照搬了过来，结果 8 条断言全红
            # ——短标题一条都匹配不上，日报会退化成全机械补行。**那条例外的
            # 适用前提不同**：refine 的摘录是 10-30 字的原文片段，这里的摘录
            # 是整个 title。
            found = [it for it, title, _ in normed if title == needle]
            if not found and len(needle) >= 4:
                # 再按子串找。**下限 4 个字**：摘录太短容易误命中别的条目。
                # ⚠️ 多认领**不只**是「归到某一行、不会丢」这么轻。
                # 规划期审查实测：锚点取的是 `picked[0]`，所以子串多认领一个
                # event_ts 更早的无关条目，会把整行的**分区与署名群**换掉
                # ——实测能把 activity/群200 的事渲染成「· 群100」并归进通知公告。
                # 条目确实没丢，但署错了群、归错了分区。
                # （「锚点优先取整 title 精确命中」的改进已记为延迟项。）
                # 下限取 4 是保守取值，不是硬约束。
                found = [it for it, _, blob in normed if needle in blob]
            if not found:
                unmatched.append(raw_quote)
            for it in found:
                if it not in hits:
                    hits.append(it)
        if not hits:
            continue
        hits.sort(key=lambda it: (it.event_ts, it.item_id))
        label = str(raw.get("label") or "").strip() or hits[0].title
        text = str(raw.get("text") or "").strip()
        lines.append(
            DigestLine(
                label=label,
                text=text,
                item_ids=tuple(it.item_id for it in hits),
            )
        )
    return lines, unmatched


def build_rows(
    lines: list[DigestLine],
    items: list[store.WindowItem],
    *,
    low_confidence: float = LOW_CONFIDENCE,
) -> list[Row]:
    """命中行 + 机械补行 → 最终的渲染行清单。

    **没被任何一行引用的 item 会被机械补一行**（label 用 title、text 用 detail）。
    日报的价值在「不漏事」，所以宁可读起来生硬，也不能因为模型漏写就丢条目
    ——那正是 spec §2.3 要避免的「日报有、列表没有」的反面：列表有、日报没有。
    """
    by_id = {it.item_id: it for it in items}
    used: set[int] = set()
    rows: list[Row] = []

    for line in lines:
        picked = [by_id[iid] for iid in line.item_ids if iid in by_id]
        if not picked:
            continue
        used.update(it.item_id for it in picked)
        deadlines = [it.deadline_ts for it in picked if it.deadline_ts]
        rows.append(
            Row(
                label=line.label,
                text=line.text,
                kind=picked[0].kind,
                group_id=picked[0].group_id,
                deadline_ts=min(deadlines) if deadlines else None,
                low_confidence=all(it.confidence < low_confidence for it in picked),
            )
        )

    for item in items:
        if item.item_id in used:
            continue
        rows.append(
            Row(
                label=item.title,
                text=item.detail or "",
                kind=item.kind,
                group_id=item.group_id,
                deadline_ts=item.deadline_ts,
                low_confidence=item.confidence < low_confidence,
                mechanical=True,
            )
        )
    return rows


def stat_line(*, groups: int, messages: int, items: int) -> str:
    """日报开头那句话。数字全部由程序算，不问模型——它编过。"""
    base = f"当天 {groups} 个群 {messages:,} 条消息"
    return f"{base}，提炼出 {items} 条。" if items else f"{base}。"


def _render_row(row: Row, names: dict[int, str], *, with_deadline: bool) -> str:
    parts = [f"- **{row.label}**"]
    if row.text:
        parts.append(row.text)
    line = " ".join(parts)
    tail = names.get(row.group_id, "")
    if with_deadline and row.deadline_ts:
        stamp = dt.datetime.fromtimestamp(row.deadline_ts).strftime("%m-%d")
        tail = f"截止 {stamp} · {tail}" if tail else f"截止 {stamp}"
    # 群名查不到就什么都不缀——**不要退回群号**，那是本不该出现在成品里的数字
    return f"{line} · {tail}" if tail else line


def render_markdown(
    *,
    day: str,
    stat_line: str,
    rows: list[Row],
    cats: tuple,
    names: dict[int, str],
    window_from: int = 0,
) -> str:
    """确定性渲染。模型只提供 label 与 text，版式全在这里。

    分区顺序：**别忘 → 各类目 → 拿不准的**。

    * 「别忘」= 有 deadline 且 **deadline 不早于窗口起点** 的行。加下界是真实
      数据逼出来的：全库有 1 条 item 的截止日早于事件日（8/5 的条目挂 5/6），
      不过滤就会在八月日报里冒出「别忘 5 月 6 日」。
    * 进了「别忘」的行**不再出现在类目区块**——同一件事读两遍是负担。
    * 低置信度的行只进「拿不准的」，即使它有截止日：存疑的信息不该催人去办。
    """
    head = f"# 守夜人日报 · {day}\n\n{stat_line}\n"
    if not rows:
        return head + "\n没有值得一提的信息。\n"

    alert_idx = {
        i for i, r in enumerate(rows)
        if r.deadline_ts and r.deadline_ts >= window_from and not r.low_confidence
    }
    unsure_idx = {i for i, r in enumerate(rows) if r.low_confidence}

    icons = {c.slug: (c.icon, c.label) for c in cats}
    order = [c.slug for c in cats]

    buckets: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        if i in alert_idx or i in unsure_idx:
            continue
        buckets.setdefault(row.kind, []).append(i)
    # 类目表里没有的 kind 排到最后——**不静默丢**
    for kind in buckets:
        if kind not in icons:
            order.append(kind)

    out = [head]
    if alert_idx:
        out.append("## ⏰ 别忘\n")
        out += [_render_row(rows[i], names, with_deadline=True)
                for i in sorted(alert_idx)]
        out.append("")
    for slug in order:
        idx = buckets.get(slug)
        if not idx:
            continue
        icon, label = icons.get(slug, ("", slug))
        title = f"{icon} {label}".strip() if icon else label
        out.append(f"## {title}\n")
        out += [_render_row(rows[i], names, with_deadline=False) for i in idx]
        out.append("")
    if unsure_idx:
        out.append("## 🤔 拿不准的\n")
        out += [_render_row(rows[i], names, with_deadline=False)
                for i in sorted(unsure_idx)]
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def yesterday(today: dt.date | None = None) -> str:
    """默认日报日期 = 昨天。日报是「回看昨天」，不是「看今天」。"""
    base = today or dt.date.today()
    return (base - dt.timedelta(days=1)).isoformat()


def day_window(date_str: str) -> tuple[int, int]:
    """把 ``YYYY-MM-DD`` 变成 ``[当天 00:00, 次日 00:00)`` 的 unix 秒区间。

    ⚠️ 用 datetime + timedelta 而不是 ``since + 86400``：后者在有夏令时的
    时区会差一小时。国内用不着，但这是免费的正确答案。
    """
    try:
        start = dt.datetime.strptime(date_str, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"日期格式应为 YYYY-MM-DD，实际是 {date_str!r}"
        ) from exc
    return int(start.timestamp()), int((start + dt.timedelta(days=1)).timestamp())
```

把文件头部的 import 区补成：

```python
import datetime as dt
import json
import re
from dataclasses import dataclass, field

from . import store
from .llm import sanitize_for_llm
from .redact import Redactor
```

并把 `build_user_prompt` 里那句函数内的 `import json` 删掉（已提到文件头）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_digest.py -vv`
Expected: 全部 PASS

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: **184 passed**（Task 2 的 156 + 本任务 28 条）

- [ ] **Step 5: 变异反证（**必做**，M1 实测「测试有效性三陷阱」四次重现）**

测试通过**几乎不提供保障**——写测试的和写实现的是同一批人。挑两条守着关键语义的测试，临时删掉被守的代码，确认它们**变红**：

```bash
bash -c '
set -e
cp vigil/digest.py /tmp/digest.bak
trap "cp /tmp/digest.bak vigil/digest.py" EXIT
# 变异 1：机械补行整段删掉（应让 test_build_rows_appends_mechanical_row_for_uncovered_item 变红）
python - "$@" <<EOF
import re, pathlib
p = pathlib.Path("vigil/digest.py")
s = p.read_text(encoding="utf-8")
s2 = s.replace("    for item in items:\n        if item.item_id in used:\n            continue\n", "    for item in []:\n        if item.item_id in used:\n            continue\n")
assert s2 != s, "变异 1 没生效——锚点变了，先更新这一行"
p.write_text(s2, encoding="utf-8")
EOF
.venv/Scripts/python.exe -m pytest tests/test_digest.py -q -k mechanical 2>&1 | tail -3
cp /tmp/digest.bak vigil/digest.py
EOF
```

> ⚠️ **`trap ... EXIT` 不能省，也不要用 `cp A /tmp/x || cp` 的写法**——M1 踩过：git bash 下 `/tmp` 存在，`||` 不走，源码会被留在变异状态。
> ⚠️ **必须看红的原因**：红的必须是「少了机械补行」这件事本身，不能是 `NameError`/`IndentationError` 一类机械层面的失败——那种红不构成有效反证。

- [ ] **Step 6: Commit**

```bash
git add vigil/digest.py tests/test_digest.py
git commit -m "feat(digest): 加 quote 匹配与确定性渲染（含机械补行、别忘/拿不准分区）"
```

---

### Task 4: 编排 + CLI

**Files:**
- Modify: `vigil/digest.py`（追加编排入口）
- Modify: `vigil/cli.py`
- Modify: `tests/test_digest.py`（追加）

**Dependencies:** [Task 1, Task 2, Task 3]

**Touches:** `vigil/digest.py`, `vigil/cli.py`, `tests/test_digest.py`

**Interfaces:**
- Consumes: Task 1 的 `store.*`、Task 2/3 的 `digest.*`、M1 的 `config.Config` / `categories.load_categories` / `llm.chat_json`
- Produces:
  - `vigil.digest.DigestStats` — dataclass，字段 `day: str`, `window_from: int`, `window_to: int`, `items: int`, `lines: int`, `mechanical: int`, `unmatched_quotes: int`, `messages: int`, `groups: int`, `input_tokens: int`, `output_tokens: int`, `digest_id: int | None`, `output_path: str`, `errors: list[str]`
  - `vigil.digest.digest(config, *, api_key, db_path=None, conn=None, since, until, day_label, model=DEFAULT_MODEL, enable_thinking=False, output_dir=None, write_file=True, dry_run=False, prompt_ver=PROMPT_VERSION, on_progress=print) -> DigestStats`
  - `vigil.cli.cmd_digest(args) -> int`

**为什么 LLM 失败时不写「降级日报」：**

日报只有一次 LLM 调用，没有「其他批次成功了」这一说。失败时若照样把机械补行拼成一篇写进 `docs/digests/YYYY-MM-DD.md`，那篇文件看起来和正常日报一模一样——**这就是 M1 反复抓到的「假绿」**：产物存在，质量已经塌了，事后一眼看不出来。所以：**报错、不写文件、不入库、返回非零**，让失败可见。M4 的自动化会靠这个非零退出码报警。

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_digest.py` 末尾：

```python
# ── 编排 ────────────────────────────────────────────────────


class _FakeLLM:
    """假 LLM：记录调用次数，返回预设载荷。绝不联网。"""

    def __init__(self, lines):
        self.lines = lines
        self.calls = 0
        self.configs = []

    def __call__(self, cfg, *, system, user, sleep=None):
        from vigil.llm import LLMResult

        self.calls += 1
        self.configs.append(cfg)
        return LLMResult(payload={"lines": self.lines}, input_tokens=100,
                         output_tokens=50)


@pytest.fixture
def seeded(memdb):
    """两条 item + 一条窗口外 + 完整 messages。"""
    from vigil import store

    memdb.executescript(
        """
        CREATE TABLE messages (
            msg_id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL,
            ts INTEGER NOT NULL, sender_uid TEXT, content TEXT NOT NULL
        );
        """
    )
    since, until = digest.day_window("2026-09-13")
    memdb.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        [
            (1, 100, since + 60, "u_a", "通知：明天交体检表"),
            (2, 100, since + 120, "u_b", "收到"),
            (3, 200, since + 180, "u_c", "有讲座"),
        ],
    )
    store.ensure_schema(memdb)
    memdb.executemany(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, links, amount, confidence, model,"
        " prompt_ver, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "notice", "体检表", "10月8日前交", since + 60, None, 100, None,
             None, "[]", None, 0.9, "m", "v2", 1),
            (2, "activity", "讲座", None, since + 180, None, 200, None,
             None, "[]", None, 0.9, "m", "v2", 1),
        ],
    )
    memdb.commit()
    return memdb, since, until


class _Config:
    """最小 Config 替身——只用到 groups。"""

    def __init__(self, groups):
        from vigil.config import Group

        self.groups = tuple(Group(id=g, name=n) for g, n in groups.items())


def test_digest_writes_body_and_links_every_item(seeded, monkeypatch, tmp_path):
    from vigil import store

    conn, since, until = seeded
    fake = _FakeLLM([
        {"quotes": ["体检表"], "label": "体检", "text": "10月8日前交"},
        {"quotes": ["讲座"], "label": "讲座", "text": "周五晚"},
    ])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(
        _Config({100: "班级群", 200: "新生群"}), api_key="k", conn=conn,
        since=since, until=until, day_label="2026-09-13", output_dir=tmp_path,
    )

    assert fake.calls == 1
    assert stats.items == 2
    assert stats.mechanical == 0
    assert stats.errors == []
    body = (tmp_path / "2026-09-13.md").read_text(encoding="utf-8")
    assert "- **体检** 10月8日前交 · 班级群" in body
    # 窗口内**每条** item 都必须挂上——这是「日报里的每一条都能在 Web 找到」的前提
    linked = conn.execute(
        "SELECT item_id FROM digest_items WHERE digest_id=? ORDER BY item_id",
        (stats.digest_id,),
    ).fetchall()
    assert [r[0] for r in linked] == [1, 2]


def test_digest_sends_max_tokens_and_thinking_off(seeded, monkeypatch, tmp_path):
    conn, since, until = seeded
    fake = _FakeLLM([{"quotes": ["体检表"], "label": "a", "text": ""}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn, since=since,
                  until=until, day_label="2026-09-13", output_dir=tmp_path)

    assert fake.configs[0].max_tokens == digest.MAX_TOKENS
    assert fake.configs[0].enable_thinking is False


def test_digest_never_sends_group_ids(seeded, monkeypatch, tmp_path):
    """⚠️ 守着「群号不出网」这条硬约束——探针第一版就是在这里翻车的。"""
    conn, since, until = seeded
    seen = {}

    def spy(cfg, *, system, user, sleep=None):
        from vigil.llm import LLMResult

        seen["user"] = user
        seen["system"] = system
        return LLMResult(payload={"lines": []}, input_tokens=1, output_tokens=1)

    monkeypatch.setattr("vigil.digest.chat_json", spy)

    digest.digest(_Config({100: "班级群", 200: "新生群"}), api_key="k", conn=conn,
                  since=since, until=until, day_label="2026-09-13", output_dir=tmp_path)

    assert "班级群" in seen["user"]
    assert "100" not in seen["user"].replace("2026-09-13", "").replace("10月8日", "")


def test_digest_uncovered_item_gets_mechanical_row(seeded, monkeypatch, tmp_path):
    conn, since, until = seeded
    fake = _FakeLLM([{"quotes": ["体检表"], "label": "体检", "text": ""}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(_Config({100: "班级群", 200: "新生群"}), api_key="k",
                          conn=conn, since=since, until=until,
                          day_label="2026-09-13", output_dir=tmp_path)

    assert stats.mechanical == 1
    body = (tmp_path / "2026-09-13.md").read_text(encoding="utf-8")
    assert "- **讲座**" in body


def test_digest_empty_window_does_not_call_model(seeded, monkeypatch, tmp_path):
    """空窗日：不花 token、不留空白文件，但**明确说没有信息**（spec §4.6）。"""
    conn, since, until = seeded
    conn.execute("DELETE FROM items")
    conn.commit()
    fake = _FakeLLM([])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                          since=since, until=until, day_label="2026-09-13",
                          output_dir=tmp_path)

    assert fake.calls == 0
    assert stats.items == 0
    body = (tmp_path / "2026-09-13.md").read_text(encoding="utf-8")
    assert "没有值得一提的信息" in body


def test_digest_llm_failure_writes_nothing_and_reports(seeded, monkeypatch, tmp_path):
    """失败不许降级成「机械拼盘」——那种文件看起来和正常日报一样。"""
    from vigil.llm import LLMError

    conn, since, until = seeded

    def boom(cfg, *, system, user, sleep=None):
        raise LLMError("HTTP 503")

    monkeypatch.setattr("vigil.digest.chat_json", boom)

    stats = digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                          since=since, until=until, day_label="2026-09-13",
                          output_dir=tmp_path)

    assert stats.errors and "503" in stats.errors[0]
    assert stats.digest_id is None
    assert not (tmp_path / "2026-09-13.md").exists()
    assert conn.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 0


def test_digest_rerun_replaces_instead_of_stacking(seeded, monkeypatch, tmp_path):
    conn, since, until = seeded
    fake = _FakeLLM([{"quotes": ["体检表", "讲座"], "label": "全部", "text": ""}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)
    cfg = _Config({100: "班级群", 200: "新生群"})

    digest.digest(cfg, api_key="k", conn=conn, since=since, until=until,
                  day_label="2026-09-13", output_dir=tmp_path)
    digest.digest(cfg, api_key="k", conn=conn, since=since, until=until,
                  day_label="2026-09-13", output_dir=tmp_path)

    assert conn.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 1
    assert fake.calls == 2


def test_digest_dry_run_does_not_call_model_or_write(seeded, monkeypatch, tmp_path):
    conn, since, until = seeded
    fake = _FakeLLM([])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                          since=since, until=until, day_label="2026-09-13",
                          output_dir=tmp_path, dry_run=True)

    assert fake.calls == 0
    assert stats.items == 2
    assert not (tmp_path / "2026-09-13.md").exists()


def test_digest_dry_run_on_empty_window_still_writes_nothing(seeded, monkeypatch, tmp_path):
    """⚠️ 空窗 + dry-run 的组合——端到端实测抓到过：当时空窗分支排在 dry_run
    检查前面且无条件落库，于是 `--dry-run` 照样写了库、落了文件。
    单测原本用的样本有 item，走的是另一条分支，所以没守住这个组合。"""
    conn, since, until = seeded
    conn.execute("DELETE FROM items")
    conn.commit()
    fake = _FakeLLM([])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                          since=since, until=until, day_label="2026-09-13",
                          output_dir=tmp_path, dry_run=True)

    assert fake.calls == 0
    assert stats.digest_id is None
    assert not (tmp_path / "2026-09-13.md").exists()
    assert conn.execute("SELECT COUNT(*) FROM digests").fetchone()[0] == 0


def test_digest_no_write_skips_file_but_still_saves(seeded, monkeypatch, tmp_path):
    conn, since, until = seeded
    fake = _FakeLLM([{"quotes": ["体检表", "讲座"], "label": "全部", "text": ""}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(_Config({100: "班级群", 200: "新生群"}), api_key="k",
                          conn=conn, since=since, until=until,
                          day_label="2026-09-13", output_dir=tmp_path,
                          write_file=False)

    assert stats.digest_id is not None
    assert stats.output_path == ""
    assert not (tmp_path / "2026-09-13.md").exists()


def test_digest_rejects_reversed_window(seeded):
    conn, _, _ = seeded

    with pytest.raises(ValueError):
        digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                      since=5000, until=1000, day_label="2026-09-13")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_digest.py -vv`
Expected: FAIL —— `AttributeError: module 'vigil.digest' has no attribute 'digest'`

- [ ] **Step 3: 实现 —— `vigil/digest.py` 追加编排**

头部 import 区补上：

```python
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .categories import load_categories
from .config import Config, REPO_ROOT
from .llm import DEFAULT_MODEL, LLMConfig, LLMError, chat_json, sanitize_for_llm
```

文件末尾追加：

```python
# 日报落盘目录。相对仓库根，与 spec §4.6 的约定一致。
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "digests"


@dataclass
class DigestStats:
    """如实报告——模型漏写的、匹配失败的、程序补的，都要看得见。"""

    day: str = ""
    window_from: int = 0
    window_to: int = 0
    items: int = 0
    lines: int = 0          # 模型返回且匹配成功的行数
    mechanical: int = 0     # 程序补的行数——**不为 0 就说明模型漏写了**
    unmatched_quotes: int = 0
    messages: int = 0
    groups: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    digest_id: int | None = None
    output_path: str = ""
    errors: list[str] = field(default_factory=list)


def digest(
    config: Config,
    *,
    api_key: str,
    db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
    since: int,
    until: int,
    day_label: str,
    model: str = DEFAULT_MODEL,
    enable_thinking: bool | None = False,
    output_dir: Path | None = None,
    write_file: bool = True,
    dry_run: bool = False,
    prompt_ver: str = PROMPT_VERSION,
    on_progress=print,
) -> DigestStats:
    """合成一天的日报并落库（可选落文件）。

    连接由调用方持有：CLI 传 db_path，测试传内存 conn（与 refine 同款约定）。
    """
    if until <= since:
        raise ValueError(f"结束时间必须晚于开始时间：{since} → {until}")

    stats = DigestStats(
        day=day_label, window_from=since, window_to=until,
    )
    names = {g.id: g.name for g in config.groups}
    cats = load_categories()
    out_dir = output_dir or DEFAULT_OUTPUT_DIR

    owns_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(str(db_path or config.output_db))
    try:
        store.ensure_schema(conn)
        items = store.window_items(conn, since=since, until=until)
        messages, groups = store.window_stats(conn, since=since, until=until)
        stats.items = len(items)
        stats.messages = messages
        stats.groups = groups

        summary = stat_line(groups=groups, messages=messages, items=len(items))

        # ⚠️ --dry-run 必须排在「空窗」分支**前面**。
        #
        # 规划期的端到端实测抓到过这个顺序错误：原本空窗分支在前且无条件
        # ``_persist``，于是 `vigil digest --date <空窗日> --dry-run` **照样写库
        # 落文件**。单元测试没抓到，是因为它用的样本有 item、走的是另一条分支
        # ——空窗 + dry-run 这个组合当时根本没被测过（「空守卫」那一类）。
        if dry_run:
            if items:
                on_progress(
                    f"[digest] --dry-run：窗口内 {len(items)} 条 item，"
                    f"将调用 1 次模型，不写库、不落文件"
                )
            else:
                on_progress(
                    f"[digest] --dry-run：{day_label} 窗口内没有条目，"
                    f"将写一篇「没有值得一提的信息」的日报，不调用模型、不写库"
                )
            return stats

        # 空窗日**不调模型**：既不该花钱，也不该给模型机会编出点什么。
        # 但照样出文件——spec §4.6 要求「明确输出没有值得一提的信息，不假装有事」。
        if not items:
            body = render_markdown(
                day=day_label, stat_line=summary, rows=[], cats=cats, names=names,
            )
            on_progress(f"[digest] {day_label}：窗口内没有条目")
            return _persist(stats, conn, body, model, prompt_ver, [], write_file,
                            out_dir, day_label)

        payload = build_items_payload(items, names, Redactor())
        try:
            result = chat_json(
                LLMConfig(
                    api_key=api_key, model=model,
                    enable_thinking=enable_thinking, max_tokens=MAX_TOKENS,
                ),
                system=build_system_prompt(),
                user=build_user_prompt(payload, day=day_label),
            )
        except LLMError as exc:
            # ⚠️ 不降级。拼一篇只有机械行的「日报」写进 docs/digests/ 的话，
            # 那篇文件与正常日报长得一模一样——正是不许出现的假绿。
            stats.errors.append(f"模型调用失败: {exc}")
            on_progress(f"[digest] {stats.errors[-1]}")
            return stats

        stats.input_tokens = result.input_tokens
        stats.output_tokens = result.output_tokens

        lines, unmatched = match_lines(result.payload.get("lines"), items)
        rows = build_rows(lines, items)
        stats.lines = len(lines)
        stats.unmatched_quotes = len(unmatched)
        stats.mechanical = sum(1 for r in rows if r.mechanical)

        body = render_markdown(
            day=day_label, stat_line=summary, rows=rows, cats=cats, names=names,
            window_from=since,
        )
        # 窗口内**每条** item 都挂上——行里有的是模型写的，有的是机械补的，
        # 但两种都对应真实条目，所以覆盖率必然是 100%。
        return _persist(
            stats, conn, body, model, prompt_ver,
            [it.item_id for it in items], write_file, out_dir, day_label,
        )
    finally:
        if owns_conn and conn is not None:
            conn.close()


def _persist(
    stats: DigestStats,
    conn: sqlite3.Connection,
    body: str,
    model: str,
    prompt_ver: str,
    item_ids: list[int],
    write_file: bool,
    out_dir: Path,
    day_label: str,
) -> DigestStats:
    """落库 + 落文件。两件都做，或（write_file=False）只落库。"""
    stats.digest_id = store.save_digest(
        conn,
        window_from=stats.window_from,
        window_to=stats.window_to,
        body_md=body,
        model=model,
        prompt_ver=prompt_ver,
        item_ids=item_ids,
    )
    if write_file:
        path = out_dir / f"{day_label}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        stats.output_path = str(path)
    return stats
```

- [ ] **Step 4: 实现 —— `vigil/cli.py` 加 `digest` 子命令**

在 `cmd_refine` 之后追加：

```python
def cmd_digest(args) -> int:
    """日报：把 items 写成一天一页 Markdown。"""
    from . import digest as digest_mod
    from .config import load_llm_key

    config = _load_config_only()
    db = _require_export_db(config)

    api_key = load_llm_key()
    if not api_key and not args.dry_run:
        sys.exit(
            "[配置错误] 没有 LLM 密钥。\n"
            "  请在仓库根目录的 .env 里写入：SILICONFLOW_API_KEY=sk-...\n"
            "  （--dry-run 不需要密钥）"
        )

    day = args.date or digest_mod.yesterday()
    try:
        since, until = digest_mod.day_window(day)
    except ValueError as exc:
        sys.exit(f"[参数错误] {exc}")

    stats = digest_mod.digest(
        config,
        api_key=api_key,
        db_path=db,
        since=since,
        until=until,
        day_label=day,
        # --model 不给时是 None，而 None 会绕过 digest() 的默认值，所以这里兜底
        model=args.model or digest_mod.DEFAULT_MODEL,
        enable_thinking=args.think,
        write_file=not args.no_write,
        dry_run=args.dry_run,
    )

    print("-" * 60)
    if stats.errors:
        # 非零退出码是 M4 自动化的报警信号——别吞掉
        for err in stats.errors:
            print(f"[失败] {err}")
        return 1

    print(
        f"完成：{stats.day} 窗口内 {stats.groups} 个群 {stats.messages:,} 条消息"
        f" → {stats.items} 条 item → 日报 {stats.lines} 行"
    )
    if stats.mechanical:
        # 不为 0 就说明模型漏写了条目，是提示词该改的信号——必须显眼
        print(
            f"[注意] 其中 {stats.mechanical} 行是程序补的（模型没写到），"
            f"读起来会生硬——这通常意味着提示词该调了"
        )
    if stats.unmatched_quotes:
        print(f"[注意] 有 {stats.unmatched_quotes} 处摘录没匹配上条目，已丢弃")
    if args.dry_run:
        print("（--dry-run：未调用模型、未写库、未落文件）")
        return 0

    print(f"token 用量：输入 {stats.input_tokens:,} / 输出 {stats.output_tokens:,}")
    if stats.output_path:
        print(f"日报文件：{stats.output_path}")
    else:
        print("（--no-write：只入库，未落文件）")
    return 0
```

在 `main()` 里、`p_refine.set_defaults(...)` 之后追加：

```python
    p_digest = sub.add_parser("digest", help="日报：把 items 合成一天一页 Markdown")
    p_digest.add_argument("--date", help="日报日期 YYYY-MM-DD（默认昨天）")
    p_digest.add_argument("--model", default=None, help="覆盖默认模型")
    p_digest.add_argument(
        "--think",
        action="store_true",
        help="打开模型的思考模式（默认关闭，与 refine 一致）",
    )
    p_digest.add_argument(
        "--no-write", action="store_true", help="只入库，不写 docs/digests/ 文件"
    )
    p_digest.add_argument("--dry-run", action="store_true", help="只报告不调用模型")
    p_digest.set_defaults(func=cmd_digest)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: **195 passed**（Task 3 的 184 + 本任务 11 条）

- [ ] **Step 6: 真实数据干跑（不花钱、不写库）**

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/vigil.exe digest --date 2026-09-13 --dry-run
```

Expected: 打印 `窗口内 10 个群 527 条消息 → 10 条 item`，无异常退出。

- [ ] **Step 7: Commit**

```bash
git add vigil/digest.py vigil/cli.py tests/test_digest.py
git commit -m "feat(cli): 加 vigil digest 命令（编排 + 落库 + 落文件 + 失败可见）"
```

---

### Task 5: 冒烟验收（M2 出口）

**Files:**
- 不改代码。本任务是**出口证据**的生产。
- 产出：`M2-验收日报/`（三篇日报 + 一篇空窗日）+ `M2-验收材料.md`

**Dependencies:** [Task 1–4]

**Touches:** 无源码改动。若冒烟抓到 bug → **停下报告 controller**，不要在本任务里顺手修。

**M2 出口标准（spec §5）：** 连续 3 天真实日报，用户读完判定「有用」；含一次空窗日（无 items）的正确表现。

**用户已裁定**：验收用 **2026-09-11 / 09-12 / 09-13**（最近三天，也是开学季信息最密的一段：5 / 6 / 10 条 item），空窗日取 **2026-08-08**（0 条 item）。

- [ ] **Step 1: 确认 API 并发干净**

⚠️ 别跳过这步。规划期间就因为残留的探针进程占着 key 的并发，把整轮实验拖成「同一请求一次 2s、一次 85s」的幻觉。

```bash
PYTHONIOENCODING=utf-8 powershell.exe -NoProfile -Command "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -like '*probe*' -or \$_.CommandLine -like '*sys.argv*' }).Count"
```

Expected: `0`。不为 0 就先按 PID 精确清掉（**绝不用 `taskkill //F //IM node.exe`**，那会杀掉 claude-mem 的 hook 进程）。

- [ ] **Step 2: 跑四天（**捕获完整输出**）**

```bash
mkdir -p _smoke
for d in 2026-09-11 2026-09-12 2026-09-13 2026-08-08; do
  PYTHONIOENCODING=utf-8 .venv/Scripts/vigil.exe digest --date "$d" 2>&1 | tee "_smoke/$d.log"
  echo "  ^^^ $d 退出码 ${PIPESTATUS[0]}"
done
```

Expected: 四次都退出码 0；`docs/digests/` 下出现四个文件；每天的输出日志落在 `_smoke/`。
⚠️ 若某天超过 60 秒无返回：先复查 Step 1 的进程数，再重试一次；**连续两次超时才记为失败**。

- [ ] **Step 3: 机械核验（**真正的质量闸门**）**

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import pathlib, re, sqlite3, datetime as dt
c = sqlite3.connect('data/vigil.db')
print(f'{\"日期\":<12}{\"item\":>5}{\"链表\":>5}{\"行数\":>5}{\"补行\":>5}{\"未匹配\":>7}  判定')
ok = True
for day in ['2026-09-11','2026-09-12','2026-09-13','2026-08-08']:
    log = pathlib.Path(f'_smoke/{day}.log').read_text(encoding='utf-8')
    m = re.search(r'其中 (\d+) 行是程序补的', log)
    u = re.search(r'有 (\d+) 处摘录没匹配上', log)
    mech, un = int(m.group(1)) if m else 0, int(u.group(1)) if u else 0
    s = int(dt.datetime.strptime(day, '%Y-%m-%d').timestamp()); e = s + 86400
    n = c.execute('SELECT COUNT(*) FROM items WHERE event_ts>=? AND event_ts<?', (s,e)).fetchone()[0]
    row = c.execute('SELECT digest_id, body_md FROM digests WHERE window_from=? AND window_to=?', (s,e)).fetchone()
    if row is None:
        print(f'{day:<12}{n:>5}{\"缺!\":>5}'); ok = False; continue
    linked = c.execute('SELECT COUNT(*) FROM digest_items WHERE digest_id=?', (row[0],)).fetchone()[0]
    # ⚠️ 质量闸门是「补行」而不是「覆盖率」：覆盖率恒为 100%（见下方说明），
    #    只有补行数才反映模型到底写没写出东西。
    good = (linked == n) and (mech == 0)
    ok &= good
    print(f'{day:<12}{n:>5}{linked:>5}{len(row[1].splitlines()):>5}{mech:>5}{un:>7}  '
          + ('✓' if good else '✗'))
print('---')
total = c.execute('SELECT COUNT(*) FROM digests').fetchone()[0]
print('篇数:', total, '（应为 4）'); ok &= (total == 4)
orphan = c.execute('SELECT COUNT(*) FROM digest_items WHERE digest_id NOT IN (SELECT digest_id FROM digests)').fetchone()[0]
print('孤儿行:', orphan, '（应为 0）'); ok &= (orphan == 0)
print('总体:', '✅ 通过' if ok else '❌ 不通过')
"
```

Expected: 三天 `补行 = 0`、空窗日 0 行；共 4 篇；孤儿行 0；末行 `✅ 通过`。

⚠️ **为什么这条核验被重写过（规划期最终 review 抓到的假绿）**：

初版只查「`digest_items` 是否挂满了窗口内全部 items」。但 `digest()` **无条件**把全部 item_id 交给 `_persist`，所以那个等式**恒真——没有任何可达状态能让它失败**。实测：让模型返回**空 lines**，10 条 item 全变成机械补行，初版脚本照样打印 `10/10 ✓ 总体: ✅ 通过`（`mechanical=10/10` 却毫无提示）。

也就是说：**模型返回垃圾、日报退化成秃列表，出口核验仍判通过。** 这正是 M1 反复抓到的「假绿」，而且出现在出口闸门上。

**所以真正的闸门是「补行数」**：
- `补行 > 0` = 模型漏写了条目，日报里有读起来生硬的机械行 → **不通过**，回头调提示词
- 覆盖率那两列**保留但仅作结构性检查**（它守的是 `item_ids` 的接线，不是日报质量），不要拿它当质量证据

⚠️ **分母口径**：用窗口内全部 items（Python 本地时间换算），**不要**用 SQLite 的 `strftime('%s', …)`——后者按 UTC 解释，与产品的本地日窗口差 8 小时。

- [ ] **Step 4: 空窗日的正确表现**

```bash
PYTHONIOENCODING=utf-8 cat docs/digests/2026-08-08.md
```

Expected: 含「没有值得一提的信息」，且**不出现任何条目行**、不含「## ⏰ 别忘」等区块标题。

- [ ] **Step 5: 幂等复跑**

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/vigil.exe digest --date 2026-09-13
```

Expected: 退出码 0，`digests` 表**仍然是 4 篇**（不是 5 篇），`docs/digests/2026-09-13.md` 被覆盖而不是追加。

- [ ] **Step 6: 整理验收材料**

创建 `M2-验收材料.md`：

```markdown
# VIGIL M2 验收材料 —— 日报合成

> 生成于 2026-09-15 ｜ 模型 `Qwen/Qwen3.5-35B-A3B`（关思考）｜ 提示词 `v1`

## 机械核验（自动）

（粘贴 Step 3 的完整输出）

## 待你判定的三篇日报

按 spec §5，M2 的出口标准是：**连续 3 天真实日报，你读完判定「有用」**。

请逐篇读下面的日报，然后回答一个问题：**如果这是你每天收到的，你会觉得有用吗？**

### 2026-09-11

（粘贴 `docs/digests/2026-09-11.md` 全文）

### 2026-09-12

（粘贴全文）

### 2026-09-13

（粘贴全文）

## 空窗日

（粘贴 `docs/digests/2026-08-08.md` 全文）

## 已知缺陷（不必重复报告，已知）

1. **M1 的「会补出原文没有的实体」会原样传下来**——日报读的是 items，items 错它就错。
   实测样本：`## 📚 学业` 里那条「咨询：四六级报名时间」是 M1 误抽的
   （detail 自己写着「无具体信息，仅为提问」，confidence 0.10），
   它会被归到「🤔 拿不准的」区块而不混进正文。
2. **模型偶尔会在正文里重复群名**（如「高数（一）储运群要求…」），
   而行尾本来就有程序标注的来源群。属已知的轻微冗余。
3. **`vigil refine` 仍有全角引号退化的隐患**（全库 25 条消息含 `“ ”`），
   M2 未修：改它等于改 M1 已验证的提示词输入，会牵出 prompt_ver 升版与
   出口核验重跑。**遗留到下一个里程碑。**
```

- [ ] **Step 7: 呈现给用户**

把 `M2-验收材料.md` 给用户，**等判定**。这一步不能用自动检查替代（spec §5 明文要求）。

- [ ] **Step 8: Commit**

```bash
git add docs/digests M2-验收材料.md
git commit -m "chore: M2 冒烟验收材料（9/11–9/13 三篇日报 + 空窗日 8/8）"
```

---

## 自审记录（写完后按 writing-plans 要求做的三件套）

### 1. spec 覆盖对照

| spec 要求 | 落在哪个任务 |
|---|---|
| §4.2 `digests` 表 | Task 1（+ 偏差 2 的 `prompt_ver`、偏差 3 的唯一索引） |
| §4.2 `digest_items` 表 | Task 1 |
| §4.6「输入是 items，不是原始消息」 | Task 4（`window_items`） |
| §4.6「取窗口内的 items，按类目分组、按 event_ts 排序」 | Task 1（排序）+ Task 3（分区渲染） |
| §4.6「合并同类项」 | Task 2（提示词规则 2）、Task 3（`match_lines` 一行挂多条） |
| §4.6「LLM 写成一页 Markdown」 | Task 2 + Task 3（按偏差 1 改为 JSON + 程序渲染） |
| §4.6「先给需要行动的（有 deadline_ts），再给知道就好的」 | Task 3（「⏰ 别忘」区块 + 过期截止日过滤） |
| §4.6「落 digests 表 + 写 docs/digests/YYYY-MM-DD.md」 | Task 4（`_persist`） |
| §4.6「空窗日明确输出'没有值得一提的信息'」 | Task 3（`render_markdown` 早返回）+ Task 4（空窗不调模型）+ Task 5 Step 4 |
| §4.5 脱敏（群号不出网） | Task 2（`build_items_payload`）+ Task 4 有一条专门的测试守着 |
| §5 M2 出口「连续 3 天真实日报，用户判定有用」 | Task 5 |
| §5 M2 出口「含一次空窗日」 | Task 5 Step 4 |
| §2.3「日报里说的每一条都能在 Web 里找到」 | Task 4（`digest_items` 挂窗口内**全部** items）+ Task 5 Step 3 的覆盖率核验 |

**无遗漏**。

### 2. 占位符扫描

已扫：计划里没有 `TBD` / `TODO` / 「类似 Task N」/ 「加适当的错误处理」。每个 Step 都带可直接照抄的完整代码或可直接执行的完整命令。

⚠️ 一处需要说明：Task 2 Step 6 的冒烟命令**保留了一段被划掉的写法**（第一段 `python -c` 是规划期写错后废弃的草稿）。执行时**用第二段**。这不是占位符，是明确标注的历史痕迹——但实施者只需照抄「实际执行下面这条」之后的那段。

### 3. 跨任务类型/签名一致性

逐条核对过：

| 名字 | 定义处 | 使用处 | 一致？ |
|---|---|---|---|
| `store.WindowItem` 的 10 个字段 | Task 1 | Task 2 `build_items_payload`、Task 3 `_norm`/`build_rows` | ✅ |
| `store.window_items(conn, *, since, until)` | Task 1 | Task 4 | ✅ |
| `store.window_stats` 返回 `(int, int)` | Task 1 | Task 4 解包成 `messages, groups` | ✅ |
| `store.save_digest(... item_ids: list[int])` | Task 1 | Task 4 `_persist` | ✅ |
| `digest.DigestLine(label, text, item_ids)` | Task 3 | Task 4 `build_rows` | ✅ |
| `digest.Row(..., mechanical=False)` | Task 3 | Task 4 统计 `r.mechanical` | ✅ |
| `digest.render_markdown(..., window_from=0)` | Task 3 | Task 4 传 `window_from=since` | ✅ |
| `digest.stat_line(*, groups, messages, items)` | Task 3 | Task 4 | ✅ |
| `digest.day_window` / `digest.yesterday` | Task 3 | Task 4 CLI | ✅ |
| `llm.sanitize_for_llm` | Task 2 | Task 2 `build_items_payload` | ✅ |
| `LLMConfig.max_tokens` | Task 2 | Task 4 传 `MAX_TOKENS` | ✅ |
| 测试累计条数 138 → 145 → 156 → 184 → 195 | — | 每任务 Step 末尾 | ✅ 逐级递增（**实测值**，不是估算） |

❌ **发现并已修正的一处**：Task 2 Step 6 最初写成了「用 `_probe_digest.build_items` 拼一个空列表」——那是无意义的草稿。已改为直接走 `store.window_items` + `digest.build_items_payload` 的真实路径，并明确标注哪一段才是要执行的。

---

## Task 6：截止日核验（**冒烟后追加**，用户 2026-09-15 裁定）

### 为什么有这一条

**首次冒烟抓到的不是代码 bug，是真实数据破坏。** 机械闸门全过（三天补行全 0），但用户逐篇读时发现「⏰ 别忘」区块在骗人。对照窗口内 4 条 deadline 与它们的**源消息原文**：

| item | 程序标的截止 | 源消息原文 | 有依据？ |
|---|---|---|---|
| 235 | **09-15** | 「各位小班：按学校最新要求，**明早**7:20 在宿舍楼下集合完毕」 | ❌ |
| 249 | **09-19** | 「**周六下午**4.00-8.00」 | ❌ |
| 250 | **09-15** | 「**明天**下午5点到6点有补录的机会」 | ❌ |
| 177 | 09-16 | 教务处通知链接（09-09 发布） | ✅ |

**3/4 无依据，且方向一致地往后飘**，把已经发生的事说成「别忘了」。更糟的是 item 249：它标 9-19，而 9/13 那篇日报里的另外三条恰好佐证那场面试 **9/12 就面完了**。

**责任划分要说清楚**：日期是 **M1 抽取时编的**（`refine` 的已知缺陷「会补出原文没有的实体」），不是 M2 造的。**但 M2 把它放大了**——本计划的设计裁决是「截止日由程序机械打出，不信任模型的措辞」，本意是可靠，**实际效果是把模型幻觉洗成了机器权威**，而「⏰ 别忘」恰恰是用户拿去办事的地方。

**用户裁定**：正文可用，只卡「别忘」→ 加机械核验后再判。

### 判据

**截止日必须能在该条自己的源消息里逐字找到**，否则：
- **不进「⏰ 别忘」**
- **不被打「截止 MM-DD」戳**（本来就只在别忘区块打，所以是自动的）
- **条目本身照常出现**在它的类目区块里（**不漏事**）——只是不再以权威口吻催办

判据刻意做成**机械可判的**（不是再叫一个模型去判）：源文里找得到就是找得到，找不到就是没有依据。

### 被降级的截止日必须**可见**

静默丢弃截止日是另一种失败。所以：`DigestStats` 记录被降级的条数，CLI **打印出来**。

**Files:**
- Modify: `vigil/store.py`（加 `item_sources_text`）
- Modify: `vigil/digest.py`（加核验函数、`Row.deadline_trusted`、`build_rows` 参数、`digest()` 接线、`DigestStats` 两个计数）
- Modify: `vigil/cli.py`（打印降级计数）
- Modify: `tests/test_store.py`、`tests/test_digest.py`（追加）

**Dependencies:** [Task 1, Task 3, Task 4, Task 5]

**Touches:** `vigil/store.py`, `vigil/digest.py`, `vigil/cli.py`, `tests/test_store.py`, `tests/test_digest.py`

**Interfaces:**
- Consumes: `store.WindowItem`、`digest.Row`、`digest.build_rows`、`digest.render_markdown`、`digest.digest`
- Produces:
  - `vigil.store.item_sources_text(conn, item_ids: list[int]) -> dict[int, str]`
  - `vigil.digest.deadline_supported(deadline_ts: int | None, sources: str) -> bool`
  - `vigil.digest.verified_deadlines(items: list[store.WindowItem], sources: dict[int, str]) -> set[int]`
  - `vigil.digest.Row.deadline_trusted: bool = False`（新字段）
  - `vigil.digest.build_rows(..., trusted: set[int] | None = None)`（新关键字参数，默认 `None` → 空集 → **全部截止日都不进别忘**）
  - `vigil.digest.DigestStats.deadlines_kept: int`、`deadlines_dropped: int`

> ⚠️ `build_rows` 的 `trusted` **默认必须是 `None` 而非全集**——默认值为「全信任」的话，任何忘记传参的调用方都会静默退回危险行为。

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_store.py` 末尾：

```python
def test_item_sources_text_joins_all_messages(memdb):
    _seed_messages(memdb)          # msg 1/2/3
    store.ensure_schema(memdb)
    conn = memdb
    conn.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, links, amount, confidence, model,"
        " prompt_ver, created_at) VALUES (1,'notice','t',NULL,1000,NULL,100,"
        " NULL,NULL,'[]',NULL,0.9,'m','v2',1)"
    )
    conn.executemany(
        "INSERT INTO item_sources (item_id, msg_id) VALUES (?,?)", [(1, 1), (1, 3)]
    )
    conn.commit()

    got = store.item_sources_text(conn, [1])

    assert set(got) == {1}
    assert "明天有讲座" in got[1] and "二手自行车出" in got[1]


def test_item_sources_text_skips_items_without_sources(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)

    assert store.item_sources_text(memdb, [999]) == {}


def test_item_sources_text_empty_input(memdb):
    store.ensure_schema(memdb)

    assert store.item_sources_text(memdb, []) == {}
```

追加到 `tests/test_digest.py` 末尾：

```python
# ── 截止日核验（Task 6，冒烟抓到的真实数据破坏）────────────────


def test_deadline_supported_finds_chinese_date():
    import datetime as dt

    ts = int(dt.datetime(2026, 9, 16, 12, 0).timestamp())

    assert digest.deadline_supported(ts, "9月16日12:00开始报名缴费")
    assert digest.deadline_supported(ts, "9月16日截止")
    assert digest.deadline_supported(ts, "9月16号截止")


def test_deadline_supported_requires_a_month():
    """⚠️ **裸日不算依据** —— 只有「16日」没有月份时判为不支持。

    这条守卫是审查轮在**真实库**上抓出来的：初版为了满足一个自相矛盾的测试
    加了裸日回退，结果它在真实数据上精度 **0/2**，放行的两条全是假的：

    * item 88（事件日 08-06）源文「31号也不算早了，我有一个朋友**26号**就开学」
      → 被判成「截止 09-26」。那句「26号」说的是别人学校开学，不是 9-26 的截止。
    * item 109（事件日 08-17）源文「**30号**就得到学校」→ 被判成「截止 09-30」。

    两个反例的错**方向一致地往后飘**，正是本任务要消灭的那类错。
    """
    import datetime as dt

    ts = int(dt.datetime(2026, 9, 16, 12, 0).timestamp())

    assert not digest.deadline_supported(ts, "16日12:00开始报名缴费")


def test_deadline_supported_rejects_short_form_inside_longer_number():
    """数字边界：短日期不能匹配进更长的数字里。"""
    import datetime as dt

    ts = int(dt.datetime(2026, 9, 3).timestamp())

    assert not digest.deadline_supported(ts, "119-16")


def test_deadline_supported_accepts_dot_form():
    """点号写法（实测真实语料里有：「9.6上午」「9.11左右截止」）。"""
    import datetime as dt

    assert digest.deadline_supported(int(dt.datetime(2026, 9, 6).timestamp()), "9.6上午")
    assert digest.deadline_supported(
        int(dt.datetime(2026, 9, 11).timestamp()), "9.11左右截止"
    )


def test_deadline_supported_tolerates_spaces_in_source():
    """实测源文里有「9 月 16 日」这种带空格的写法。"""
    import datetime as dt

    ts = int(dt.datetime(2026, 9, 16).timestamp())

    assert digest.deadline_supported(ts, "9 月 16 日 截 止")


def test_deadline_supported_rejects_relative_time_words():
    """⚠️ 冒烟实测：源文只写「明早」「明天」「周六下午」时，M1 却把 deadline 填成了具体日期。

    这类**没有字面依据**的日期必须判为不支持——否则「别忘」会把已经发生的事
    说成「别忘了」。
    """
    import datetime as dt

    ts = int(dt.datetime(2026, 9, 15).timestamp())

    assert not digest.deadline_supported(ts, "各位小班：明早7:20在宿舍楼下集合")
    assert not digest.deadline_supported(ts, "周六下午4.00-8.00")
    assert not digest.deadline_supported(ts, "明天下午5点到6点有补录的机会")


def test_deadline_supported_false_when_no_deadline():
    assert not digest.deadline_supported(None, "随便什么 9月16日")


def test_verified_deadlines_returns_only_supported_ids():
    import datetime as dt

    ts = int(dt.datetime(2026, 9, 16).timestamp())
    items = [
        _item(1, title="有依据", deadline_ts=ts),
        _item(2, title="没依据", deadline_ts=ts, event_ts=2000),
    ]
    sources = {1: "16日12:00开始报名", 2: "周六下午4.00-8.00"}

    assert digest.verified_deadlines(items, sources) == {1}


def test_build_rows_defaults_to_not_trusting_any_deadline():
    """⚠️ 默认必须是「全不信任」——默认全信任的话，忘记传参的调用方会静默退回危险行为。"""
    items = [_item(1, title="甲", deadline_ts=5000)]

    rows = digest.build_rows([], items)

    assert rows[0].deadline_trusted is False


def test_build_rows_marks_trusted_deadline():
    items = [_item(1, title="甲", deadline_ts=5000)]

    rows = digest.build_rows([], items, trusted={1})

    assert rows[0].deadline_trusted is True


def test_build_rows_untrusted_when_any_merged_deadline_is_untrusted():
    """合并行里只要有一条截止日没依据，整行就不进「别忘」。"""
    items = [
        _item(1, title="甲", deadline_ts=5000),
        _item(2, title="乙", deadline_ts=6000, event_ts=2000),
    ]
    lines, _ = digest.match_lines(
        [{"quotes": ["甲", "乙"], "label": "合并", "text": ""}], items
    )

    rows = digest.build_rows(lines, items, trusted={1})

    assert rows[0].deadline_trusted is False


def test_render_excludes_untrusted_deadline_from_alerts(cats):
    """没依据的截止日不许进「别忘」，也不许被打上「截止 MM-DD」戳。"""
    rows = [digest.Row("存疑日期", "明天下午", "notice", 100, 5000, False)]

    out = _render(rows, cats, window_from=1000)

    assert "## ⏰ 别忘" not in out
    assert "截止" not in out
    assert "- **存疑日期**" in out        # 条目本身照常出现，不漏事


def test_render_includes_trusted_deadline_in_alerts(cats):
    rows = [
        digest.Row("有依据", "16日12:00开始", "notice", 100, 5000, False,
                   deadline_trusted=True)
    ]

    out = _render(rows, cats, window_from=1000)

    assert "## ⏰ 别忘" in out
    assert "截止 " in out
```

并给 `_render` 旁边补一个构造 `Row` 的辅助（避免每处都写 6 个位置参数）：

```python
def _row(label, text="", kind="notice", group_id=100, deadline_ts=None,
         low_confidence=False, mechanical=False, deadline_trusted=False):
    return digest.Row(label, text, kind, group_id, deadline_ts, low_confidence,
                      mechanical, deadline_trusted)
```

追加到编排测试区：

```python
def test_digest_wires_deadline_verification(seeded, monkeypatch, tmp_path):
    """接线的端到端：源文有字面日期的进「别忘」，没有的不进，且计数如实上报。"""
    import datetime as dt
    from vigil import store

    conn, since, until = seeded
    conn.execute("DELETE FROM items")
    conn.execute("DELETE FROM messages")
    ts_ok = int(dt.datetime(2026, 9, 16, 12, 0).timestamp())
    conn.execute(
        "INSERT INTO messages VALUES (1, 100, ?, 'u_a', '9月16日12:00开始报名缴费')",
        (since + 60,),
    )
    conn.execute(
        "INSERT INTO messages VALUES (2, 100, ?, 'u_b', '明天下午5点有补录机会')",
        (since + 120,),
    )
    conn.executemany(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, links, amount, confidence, model,"
        " prompt_ver, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (1, "academic", "四六级报名", None, since + 60, ts_ok, 100, None,
             None, "[]", None, 0.9, "m", "v2", 1),
            (2, "activity", "补录面试", None, since + 120, ts_ok, 100, None,
             None, "[]", None, 0.9, "m", "v2", 1),
        ],
    )
    conn.executemany(
        "INSERT INTO item_sources (item_id, msg_id) VALUES (?,?)", [(1, 1), (2, 2)]
    )
    conn.commit()
    fake = _FakeLLM([{"quotes": ["四六级报名", "补录面试"], "label": "两件事", "text": ""}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    stats = digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                          since=since, until=until, day_label="2026-09-13",
                          output_dir=tmp_path)

    assert stats.deadlines_kept == 1
    assert stats.deadlines_dropped == 1
    body = (tmp_path / "2026-09-13.md").read_text(encoding="utf-8")
    # 合并行的截止日不可信 → 不该进「别忘」
    assert "## ⏰ 别忘" not in body
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_store.py tests/test_digest.py`
Expected: FAIL —— `AttributeError: module 'vigil.store' has no attribute 'item_sources_text'` 等

- [ ] **Step 3: 实现 —— `vigil/store.py` 追加**

```python
def item_sources_text(
    conn: sqlite3.Connection, item_ids: list[int]
) -> dict[int, str]:
    """把每条 item 的**源消息正文**按 item_id 拼起来。

    用途：核验「截止日是不是源文里真有的」。

    ⚠️ 为什么需要这么做：M1 的抽取**会补出原文没有的实体**，截止日是重灾区。
    首次冒烟实测：窗口内 4 条 deadline 有 3 条在源文里毫无依据，且方向一致
    地往后飘（源文「明早7:20集合」被填成 9-15、「周六下午4.00-8.00」被填成
    9-19，而那场面试 9/12 就面完了）。

    没有来源行的 item 不出现在返回里——调用方按「无依据」处理。
    """
    if not item_ids:
        return {}
    marks = ",".join("?" * len(item_ids))
    rows = conn.execute(
        f"SELECT s.item_id, m.content FROM item_sources s"
        f" JOIN messages m ON m.msg_id = s.msg_id"
        f" WHERE s.item_id IN ({marks})",
        list(item_ids),
    ).fetchall()
    grouped: dict[int, list[str]] = {}
    for item_id, content in rows:
        grouped.setdefault(item_id, []).append(content or "")
    return {k: "\n".join(v) for k, v in grouped.items()}
```

- [ ] **Step 4: 实现 —— `vigil/digest.py`**

在 `Row` 上加字段（放在 `mechanical` 之后）：

```python
    deadline_trusted: bool = False
```

在 `_norm` 之后插入核验函数（完整代码见上文的「判据」节，函数为
`_WS` / `_date_forms` / `deadline_supported` / `verified_deadlines`）：

```python
# 归一化空白：实测源文里有「9 月 16 日」这种带空格写法。
_WS = re.compile(r"\s+")


def _date_forms(ts: int) -> tuple[str, ...]:
    """同一个日期在中文语料里的常见写法。全部**去空白**后比较。

    ⚠️ **每一项都必须带月份**——理由见下面那条守卫测试
    （`test_deadline_supported_requires_a_month`）。初版曾补过「裸日」回退
    （只写「16日」不带月份），真实库实测精度 **0/2**，放行的两条全是假的。

    ⚠️ 短写法（`M-D` / `M/D` / `M.D`）要**加数字边界**，否则
    `deadline_supported(9-3, "119-16")` 会为真（"9-16" 落在 "119-16" 里）。
    """
    d = dt.datetime.fromtimestamp(ts)
    return (
        f"{d.year}-{d.month:02d}-{d.day:02d}",
        f"{d.year}/{d.month:02d}/{d.day:02d}",
        f"{d.month}月{d.day}日",
        f"{d.month}月{d.day}号",
        f"{d.month:02d}-{d.day:02d}",
        f"{d.month}-{d.day}",
        f"{d.month}/{d.day}",
        f"{d.month:02d}/{d.day:02d}",
        f"{d.month}.{d.day}",
        f"{d.month:02d}.{d.day:02d}",
    )


def deadline_supported(deadline_ts: int | None, sources: str) -> bool:
    """源文里能不能逐字找到这个日期。**找不到就是没有依据。**

    ⚠️ 判据刻意做成机械可判的（不是再叫一个模型去判）：
    源文里找得到就是找得到，找不到就是没有依据。这样它可以被测试守卫，
    也不会引入第二个模型的判断。
    """
    if not deadline_ts:
        return False
    haystack = _WS.sub("", sources)
    return any(form in haystack for form in _date_forms(deadline_ts))


def verified_deadlines(
    items: list[store.WindowItem], sources: dict[int, str]
) -> set[int]:
    """哪些 item 的截止日在源文里有字面依据。"""
    return {
        it.item_id
        for it in items
        if deadline_supported(it.deadline_ts, sources.get(it.item_id, ""))
    }
```

`build_rows` 签名与实现改成：

```python
def build_rows(
    lines: list[DigestLine],
    items: list[store.WindowItem],
    *,
    low_confidence: float = LOW_CONFIDENCE,
    trusted: set[int] | None = None,
) -> list[Row]:
    """命中行 + 机械补行 → 最终的渲染行清单。

    ``trusted`` 是**截止日在源文里有字面依据**的 item_id 集合。

    ⚠️ 默认必须是 ``None`` → 空集 → **全部截止日都不进「别忘」**。
    若默认成全信任，任何忘记传参的调用方都会静默退回危险行为
    （把模型编的日期用机器口吻打出来）。
    """
    trusted = set() if trusted is None else trusted
    ...
```

命中行那支的 `Row(...)` 加：

```python
                deadline_trusted=bool(deadlines)
                and all(it.item_id in trusted for it in picked if it.deadline_ts),
```

机械补行那支加：

```python
                deadline_trusted=item.item_id in trusted,
```

`render_markdown` 的 `alert_idx` 改成：

```python
    alert_idx = {
        i
        for i, r in enumerate(rows)
        if r.deadline_trusted
        and r.deadline_ts
        and r.deadline_ts >= window_from
        and not r.low_confidence
    }
```

`DigestStats` 加两个字段：

```python
    deadlines_kept: int = 0
    deadlines_dropped: int = 0
```

`digest()` 里接线（`items = store.window_items(...)` 之后）：

```python
        sources = store.item_sources_text(conn, [it.item_id for it in items])
        trusted = verified_deadlines(items, sources)
        stats.deadlines_kept = len(trusted)
        stats.deadlines_dropped = sum(
            1 for it in items if it.deadline_ts and it.item_id not in trusted
        )
```

并把 `build_rows(lines, items)` 改成 `build_rows(lines, items, trusted=trusted)`。

- [ ] **Step 5: 实现 —— `vigil/cli.py` 打印降级计数**

在 `stats.mechanical` 那段之后插入：

```python
    if stats.deadlines_dropped:
        # 静默丢弃截止日是另一种失败——降级必须看得见
        print(
            f"[注意] {stats.deadlines_dropped} 条截止日在源消息里找不到字面依据，"
            f"未进「别忘」（条目本身仍照常出现）——已保留 {stats.deadlines_kept} 条"
        )
```

- [ ] **Step 6: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 214 + 新增约 13 条

- [ ] **Step 7: 变异反证（**必做**）**

⚠️ 隔离副本 + 自检 `vigil.__file__` + 清 `__pycache__` + `PYTHONDONTWRITEBYTECODE=1` +
阳性对照 + **锚点命中次数 ≥1 的断言**（锚点不要走命令行传，本仓库实测非 ASCII 参数会被 Git Bash 静默打空）。
详见 ledger 的「方法论新发现」。

至少验证：去掉 `deadline_supported` 的字面核验 → 测试红；`build_rows` 的 `trusted`
默认改成「全信任」→ 测试红；`render_markdown` 的 `alert_idx` 去掉 `r.deadline_trusted` → 测试红。

- [ ] **Step 8: Commit**

```bash
git add vigil/store.py vigil/digest.py vigil/cli.py tests/test_store.py tests/test_digest.py
git commit -m "feat(digest): 截止日须在源文里有字面依据才进「别忘」（冒烟抓到的真实数据破坏）"
```

---

## Task 9：空窗日的筛除分布（**用户验收后追加**）

### 为什么有这一条

用户读完四篇材料后判定：**三天全部「有用」——M2 的出口标准（spec §5）达成**。
但空窗日的表现被判为「**信息不够**」，并选定「**再加筛除分布**」。

现状是：

```markdown
# 守夜人日报 · 2026-08-08
当天 1 个群 1,059 条消息。
没有值得一提的信息。
```

**问题不在于话少，在于它和「这天压根还没抽取过」长得一模一样。**
8/8 实测 `refine_runs` 记账 1,059 条（全 `discarded`）——那天确实跑过、确实没事；
可如果哪天 refine 没跑，日报会照样说「没有值得一提的信息」，**这是句假话**。

用户选定的形态：

```markdown
# 守夜人日报 · 2026-08-08

当天 1 个群 1,059 条消息。

其中 812 条被本地规则筛掉（纯应答 / 过短 / 刷屏广告），
247 条送模型后判为无价值。

没有值得一提的信息。
```

### ⚠️ 一条必须写进代码的已知边界

**`refine_runs` 只记 `discarded` / `ok`，分不出「本地规则筛掉」与「送模型后判无价值」**
——两者都记 `discarded`。所以这个分布只能**把本地预筛重跑一遍**来拆分
（纯本地、零 API 成本）。

**代价**：口径前提是 `config/groups.toml` 的 `tier` 与 `prefilter` 的规则
**与 refine 当时一致**。改了规则就会漂移——这是这条统计的**已知边界，写进 docstring**。

### 判据（两条，缺一不可）

1. 窗口内**消息全部有 `refine_runs` 记账** → 出筛除分布 +「没有值得一提的信息」
2. 覆盖不全 → **不许说「没有值得一提的信息」**，改说「本窗口尚未抽取（N/M）」并提示先跑 `vigil refine`

**第 2 条是这条需求真正的价值所在**：它把一句可能为假的话，换成一句一定为真的话。

**Files:**
- Modify: `vigil/store.py`（加 `window_refine_coverage`）
- Modify: `vigil/digest.py`（加 `screening_breakdown` / `render_empty_day`，`digest()` 接线）
- Modify: `tests/test_store.py`、`tests/test_digest.py`

**Dependencies:** [Task 1, Task 3, Task 4, Task 6, Task 8]

**Touches:** `vigil/store.py`, `vigil/digest.py`, `tests/test_store.py`, `tests/test_digest.py`

**Interfaces:**
- `vigil.store.window_refine_coverage(conn, *, since: int, until: int) -> tuple[int, int]` — `(消息总数, 有 refine_runs 记账的条数)`
- `vigil.digest.screening_breakdown(conn, config, *, since, until) -> tuple[int, int, int]` — `(消息总数, 本地筛掉, 送模型后无产出)`
- `vigil.digest.render_empty_day(*, day: str, groups: int, messages: int, refined: int, local_dropped: int, sent: int) -> str`

> ⚠️ **只改空窗日路径**。非空日的日报**一字不动**——它们已通过用户验收，
    没有理由重新验证。

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_store.py`：

```python
def test_window_refine_coverage_counts_recorded_messages(memdb):
    _seed_messages(memdb)          # 3 条消息
    store.ensure_schema(memdb)
    store.record_run(memdb, [1, 2], status=store.STATUS_DISCARDED, prompt_ver="v2")

    assert store.window_refine_coverage(memdb, since=1000, until=4000) == (3, 2)


def test_window_refine_coverage_empty_window(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)

    assert store.window_refine_coverage(memdb, since=9000, until=9999) == (0, 0)
```

追加到 `tests/test_digest.py`：

```python
# ── 空窗日的自证与筛除分布（Task 9，用户验收后追加）────────────


def test_render_empty_day_not_yet_refined_does_not_claim_nothing_happened():
    """⚠️ 覆盖不全时**不许**说「没有值得一提的信息」——那是句可能为假的话。

    这条是 Task 9 真正的价值：把一句可能为假的话换成一句一定为真的话。
    """
    out = digest.render_empty_day(
        day="2026-08-08", groups=1, messages=1059, refined=0,
        local_dropped=0, sent=0,
    )

    assert "没有值得一提的信息" not in out
    assert "尚未抽取" in out
    assert "vigil refine" in out
    assert "0/1,059" in out


def test_render_empty_day_shows_screening_breakdown():
    out = digest.render_empty_day(
        day="2026-08-08", groups=1, messages=1059, refined=1059,
        local_dropped=812, sent=247,
    )

    assert "没有值得一提的信息" in out
    assert "812" in out and "247" in out
    assert "1,059" in out


def test_render_empty_day_partial_coverage_is_treated_as_not_refined():
    out = digest.render_empty_day(
        day="2026-08-08", groups=1, messages=1059, refined=1058,
        local_dropped=812, sent=246,
    )

    assert "尚未抽取" in out
    assert "1,058/1,059" in out


def test_screening_breakdown_splits_local_from_model(seeded):
    """本地筛掉与送模型后无产出必须分得开（refine_runs 分不开，只能重算）。"""
    from vigil import store

    conn, since, until = seeded
    conn.execute("DELETE FROM messages")
    conn.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        [
            (1, 100, since + 10, "u_a", "收到"),                       # 纯应答 → 本地丢
            (2, 100, since + 20, "u_b", "dd"),                         # 过短 → 本地丢
            (3, 100, since + 30, "u_c", "明天记得带体检表到辅导员处"),   # 送模型
        ],
    )
    conn.commit()

    total, local, sent = digest.screening_breakdown(
        conn, _Config({100: "班级群"}), since=since, until=until
    )

    assert (total, local, sent) == (3, 2, 1)


def test_digest_empty_window_reports_not_refined(seeded, monkeypatch, tmp_path):
    """端到端：窗口没抽取过时，日报里必须是「尚未抽取」而不是「没事」。"""
    conn, since, until = seeded
    conn.execute("DELETE FROM items")
    conn.commit()
    fake = _FakeLLM([])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                  since=since, until=until, day_label="2026-09-13",
                  output_dir=tmp_path)

    body = (tmp_path / "2026-09-13.md").read_text(encoding="utf-8")
    assert "尚未抽取" in body
    assert "没有值得一提的信息" not in body


def test_digest_empty_window_breakdown_end_to_end(seeded, monkeypatch, tmp_path):
    """端到端：抽取过且确实没事时，报出筛除分布。"""
    from vigil import store

    conn, since, until = seeded
    conn.execute("DELETE FROM items")
    conn.execute("DELETE FROM messages")
    conn.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        [(1, 100, since + 10, "u_a", "收到"), (2, 100, since + 20, "u_b", "dd"),
         (3, 100, since + 30, "u_c", "随便聊聊天气不错啊今天挺热的")],
    )
    store.record_run(conn, [1, 2, 3], status=store.STATUS_DISCARDED, prompt_ver="v2")
    conn.commit()
    fake = _FakeLLM([])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                  since=since, until=until, day_label="2026-09-13",
                  output_dir=tmp_path)

    body = (tmp_path / "2026-09-13.md").read_text(encoding="utf-8")
    assert "没有值得一提的信息" in body
    assert "被本地规则筛掉" in body
    assert "3/3" not in body          # 覆盖信息只在未抽取分支里出现
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_store.py tests/test_digest.py`
Expected: FAIL —— `AttributeError: module 'vigil.store' has no attribute 'window_refine_coverage'` 等

- [ ] **Step 3: 实现 —— `vigil/store.py` 追加**

```python
def window_refine_coverage(
    conn: sqlite3.Connection, *, since: int, until: int
) -> tuple[int, int]:
    """窗口内的 (消息总数, 有 refine_runs 记账的条数)。

    空窗日的日报靠它自证「**是安静，不是管线没跑**」——覆盖率不足时
    绝不能说「没有值得一提的信息」，那是句可能为假的话。
    """
    total = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE ts >= ? AND ts < ?", (since, until)
    ).fetchone()[0]
    refined = conn.execute(
        "SELECT COUNT(*) FROM messages m WHERE m.ts >= ? AND m.ts < ?"
        " AND m.msg_id IN (SELECT msg_id FROM refine_runs)",
        (since, until),
    ).fetchone()[0]
    return total, refined
```

- [ ] **Step 4: 实现 —— `vigil/digest.py`**

头部 import 补 `from . import prefilter`。

在 `_persist` 之前插入：

```python
def screening_breakdown(
    conn: sqlite3.Connection, config: Config, *, since: int, until: int
) -> tuple[int, int, int]:
    """窗口内的 (消息总数, 本地规则筛掉的, 送模型后判无价值的)。

    ⚠️ **为什么要重算而不是查 `refine_runs`**：那张表只记
    ``discarded`` / ``ok``，而「本地规则筛掉」与「送模型后判无价值」
    **都记 ``discarded``**——查不出来。所以把本地预筛再跑一遍（纯本地、零 API）。

    ⚠️ **已知边界**：口径前提是 `config/groups.toml` 的 ``tier`` 与
    ``prefilter`` 的规则**与 refine 当时一致**。改了任一者，这里的拆分就会
    与当时的实际不一致。这是这条统计的固有代价，不是 bug。
    """
    msgs = store.pending_messages(conn, since=since, until=until, redo=True)
    _, screen_stats = prefilter.screen(msgs, tier_of=config.tier_of)
    local = screen_stats.dropped
    return len(msgs), local, len(msgs) - local


def render_empty_day(
    *,
    day: str,
    groups: int,
    messages: int,
    refined: int,
    local_dropped: int,
    sent: int,
) -> str:
    """空窗日的日报正文。

    **两条判据，缺一不可**：

    1. 窗口内消息**全部有 refine_runs 记账** → 出筛除分布 +「没有值得一提的信息」
    2. 覆盖不全 → **不许说「没有值得一提的信息」**，改说「尚未抽取」并提示先跑 refine

    第 2 条是这条需求的真正价值：把一句**可能为假**的话，换成一句**一定为真**的话。
    在此之前，「这天确实没事」与「这天压根没抽取过」在日报里长得一模一样。
    """
    head = f"# 守夜人日报 · {day}\n\n当天 {groups} 个群 {messages:,} 条消息。\n"
    if refined < messages:
        return (
            f"# 守夜人日报 · {day}\n\n"
            f"当天 {groups} 个群 {messages:,} 条消息，"
            f"**本窗口尚未抽取**（{refined:,}/{messages:,}）。\n\n"
            f"先跑 `vigil refine` 再生成日报。\n"
        )
    return (
        head
        + f"\n其中 {local_dropped:,} 条被本地规则筛掉（纯应答 / 过短 / 刷屏广告），"
        + f"\n{sent:,} 条送模型后判为无价值。\n"
        + "\n没有值得一提的信息。\n"
    )
```

`digest()` 里的空窗分支改成：

```python
        if not items:
            total, refined = store.window_refine_coverage(
                conn, since=since, until=until
            )
            if refined < total:
                body = render_empty_day(
                    day=day_label, groups=groups, messages=messages,
                    refined=refined, local_dropped=0, sent=0,
                )
                on_progress(
                    f"[digest] {day_label}：窗口内 {refined:,}/{total:,} 条已抽取，"
                    f"**尚未抽取完**——日报只说明这个，不下「没事」的结论"
                )
            else:
                _, local, sent = screening_breakdown(
                    conn, config, since=since, until=until
                )
                body = render_empty_day(
                    day=day_label, groups=groups, messages=messages,
                    refined=refined, local_dropped=local, sent=sent,
                )
                on_progress(f"[digest] {day_label}：窗口内没有条目")
            return _persist(
                stats, conn, body, model, prompt_ver, [], write_file, out_dir, day_label
            )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest`
Expected: 236 + 新增 8 条 = **244 passed**

- [ ] **Step 6: 变异反证（**必做**）**

至少验证：把「覆盖不全」的分支去掉（一律说「没有值得一提的信息」）→ 测试红；
`screening_breakdown` 的 `sent` 恒等于 `total` → 测试红；
`window_refine_coverage` 的 `refined` 恒等于 `total` → 测试红。

隔离副本 + 自检 `vigil.__file__` + 清 `__pycache__` + `PYTHONDONTWRITEBYTECODE=1` +
阳性对照 + **锚点命中 ≥1 且不走命令行传**（详见 ledger 的方法论节）。

- [ ] **Step 7: 真实数据复核（**必读**）**

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/vigil.exe digest --date 2026-08-08
```

Expected：`docs/digests/2026-08-08.md` 出现筛除分布，且两个数字之和 == 1,059。
**把该文件全文抄进报告。**

⚠️ 只需真跑 8/8 一天（另三篇是非空日，本轮不改它们的行为，**不要重跑**）。

- [ ] **Step 8: Commit**

```bash
git add vigil/store.py vigil/digest.py tests/test_store.py tests/test_digest.py docs/digests/2026-08-08.md
git commit -m "feat(digest): 空窗日自证抽取状态并报筛除分布（验收反馈）"
```

---

## Task 10：刷新验收材料（Task 9 之后）

把新的 8/8 正文与用户已填的判定一起刷进 `M2-验收材料.md`（**保留用户写的判定原文，不要改写**），提交。

---

## Task 11：空窗日的两个退化输入（**Task 9 审查后追加**）

### 为什么有这一条

Task 9 审查（Approved）抓到 **F1（Important）**：**Task 9 要消灭的那句假话还有第三个变体。**

> `vigil digest` 不带 `--date` 时默认查「**昨天**」。若那天**压根没导出过**，
> `messages = 0` → 「已覆盖」判据 `refined < total` 即 `0 < 0` **为假** →
> 仍走「已覆盖」分支，说「没有值得一提的信息」，还多出「其中 0 条被本地规则筛掉…
> 0 条送到模型…」两行。审查者在副本上真跑 `--date 2026-09-14` 复现，**无任何测试覆盖 `messages = 0`**。

**这不是本轮引入的**，但落在本轮刚重写的分支里，**且 M4 自动化真的会撞上**：
自动跑 `vigil digest` 时若 `vigil export` 失败，日报会说「今天很安静」，
而不是「今天没数据」——**同一个假话，换了个入口**。

### 判据（两条）

1. **`total == 0`** → 要分清两种（**controller 修正**：初版写成「一律不许说『没有值得一提的信息』」，措辞太宽——范围**之内**时那句话是**真话**，不该禁）：
   - 窗口落在数据库时间范围**之外** → **不许说「没有值得一提的信息」**，改说「这一天没有数据，先跑 `vigil export`」
   - 窗口落在范围**之内** → 「前后都有数据，这天是真的没人说话」+「没有值得一提的信息」（**这是真话，保留**）

   ⚠️ **`message_span` 必须过滤 `ts > 0` 的脏行**：本库有 14 条 `ts=0` 的占位行，不过滤的话
   `MIN(ts)` **恒为 0**，「窗口早于全部数据」那侧**永远判不出来**——查一个早于所有数据的日期
   会得到「这天真的没人说话」，**又是同一类假话**。（`window_stats` 不需要这么改：它按窗口
   统计，脏行天然落在窗口外；而 `message_span` 取的是全局 MIN/MAX，会被脏行毒化。）
2. **`sent == 0`（但 `total > 0`）** → 不说「0 条送到模型后判为无价值」，
   改说「**没有送模型**」

**Files:** Modify `vigil/store.py`、`vigil/digest.py`、`tests/test_store.py`、`tests/test_digest.py`

**Interfaces:**
- `vigil.store.message_span(conn) -> tuple[int, int] | None` — 全库消息的 `(最早 ts, 最晚 ts)`；无消息时 `None`
- `vigil.digest.render_empty_day(...)` 增加 `span: tuple[int, int] | None = None` 参数

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_store.py`：

```python
def test_message_span_returns_min_and_max(memdb):
    _seed_messages(memdb)          # ts = 1000 / 2000 / 3000

    assert store.message_span(memdb) == (1000, 3000)


def test_message_span_none_when_no_messages(memdb):
    _seed_messages(memdb)
    memdb.execute("DELETE FROM messages")

    assert store.message_span(memdb) is None
```

追加到 `tests/test_digest.py`：

```python
def test_render_empty_day_no_messages_at_all_outside_span():
    """⚠️ F1：窗口落在数据库时间范围之外时，说「没事」是假话——那是**没数据**。"""
    out = digest.render_empty_day(
        day="2026-09-14", groups=0, messages=0, refined=0,
        local_dropped=0, sent=0, span=(1000, 3000),
    )

    assert "没有值得一提的信息" not in out
    assert "vigil export" in out
    assert "0 条被本地规则筛掉" not in out        # 退化句子不许出现


def test_render_empty_day_no_messages_but_inside_span():
    """窗口落在范围之内却 0 条 → 是真的没人说话。"""
    out = digest.render_empty_day(
        day="2026-09-14", groups=0, messages=0, refined=0,
        local_dropped=0, sent=0, span=(1000, 3000),
        window=(2000, 2999),
    )

    assert "没有值得一提的信息" in out
    assert "真的没人说话" in out


def test_render_empty_day_zero_sent_does_not_say_zero():
    """⚠️ sent == 0 时不许渲染「0 条送到模型后判为无价值」。"""
    out = digest.render_empty_day(
        day="2026-08-08", groups=1, messages=20, refined=20,
        local_dropped=20, sent=0, span=(1, 10**12),
    )

    assert "0 条送到模型" not in out
    assert "没有送模型" in out
    assert "没有值得一提的信息" in out
```

- [ ] **Step 2: 实现 —— `vigil/store.py`**

```python
def message_span(conn: sqlite3.Connection) -> tuple[int, int] | None:
    """全库消息的 ``(最早 ts, 最晚 ts)``；一条都没有时 None。

    空窗日靠它分清「**这天没数据**」与「**这天真的没人说话**」——
    两者在旧版里都渲染成「没有值得一提的信息」，而前者是句假话。
    """
    row = conn.execute("SELECT MIN(ts), MAX(ts) FROM messages").fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0]), int(row[1])
```

- [ ] **Step 3: 实现 —— `vigil/digest.py` 的 `render_empty_day`**

签名加 `span: tuple[int, int] | None = None` 与 `window: tuple[int, int] | None = None`，
并按下面三条返回：

```python
    # ① 窗口内一条消息都没有
    if messages == 0:
        outside = span is None or window is None or window[1] <= span[0] or window[0] > span[1]
        if outside:
            return (
                f"# 守夜人日报 · {day}\n\n"
                f"当天没有任何消息记录——数据库里也没有覆盖这一天的数据。\n\n"
                f"先跑 `vigil export`。\n"
            )
        return (
            f"# 守夜人日报 · {day}\n\n"
            f"当天没有任何消息记录。\n\n"
            f"数据库里前后都有数据，所以这天是真的没人说话。\n"
        )
    # ② 覆盖不全（原判据，不变）
    if refined < messages:
        ...
    # ③ 已覆盖：出筛除分布
    tail = (
        f"其中 {local_dropped:,} 条被本地规则筛掉（纯应答 / 过短 / 刷屏广告一类），"
        f"没有送模型。\n"
        if sent == 0
        else f"其中 {local_dropped:,} 条被本地规则筛掉（纯应答 / 过短 / 刷屏广告一类），"
             f"\n{sent:,} 条送到模型后判为无价值。\n"
    )
```

（其余文案不变。）

`digest()` 里调用处传 `span=store.message_span(conn)` 与 `window=(since, until)`。

- [ ] **Step 4: 跑测试确认通过**　Expected: 246 + 新增约 5 条

- [ ] **Step 5: 变异反证**
至少：去掉 `messages == 0` 分支 → 红；`outside` 恒 False → 红；`sent == 0` 分支去掉 → 红。

- [ ] **Step 6: 真实数据复核**
```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/vigil.exe digest --date 2026-09-14   # 无数据的那天
PYTHONIOENCODING=utf-8 .venv/Scripts/vigil.exe digest --date 2026-08-08   # 空窗日（应不变）
```
两者全文抄进报告。**另三篇仍不要重跑。**

- [ ] **Step 7: Commit**
```bash
git add vigil/store.py vigil/digest.py tests/test_store.py tests/test_digest.py docs/digests/
git commit -m "fix(digest): 空窗日补两个退化输入（窗口无数据 / 零送模型），不再说「没事」"
```
⚠️ 会把 `docs/digests/2026-09-14.md` 一并提交（无数据日的日报，是预期产物）。

---

## Task 12：覆盖率可见（**用户 2026-09-15 裁定追加**）

### 为什么有这一条

这是同一句「可能的假话」的**第四个变体**，也是**最容易撞上**的一个：

覆盖率检查**只存在于空窗分支**。非空日若只抽取了一部分——`vigil refine` 撞预算护栏
（`--budget`）会**中途停**——日报会照常写「当天 9 个群 514 条消息，提炼出 6 条」，
**读起来像读遍了 514 条，实际只看了一部分**。

M4 的自动化就是跑 `refine → digest`，护栏一响就中招。

### 判据

**只在覆盖不全时**加限定，覆盖完整时**一字不变**：

```
覆盖完整：  当天 9 个群 514 条消息，提炼出 6 条。
覆盖不全：  当天 9 个群 514 条消息（仅抽取了 300/514），提炼出 4 条。
```

⚠️ **用户已验收的 9/11、9/12、9/13 三篇覆盖率实测都是 100%**，所以这条改动
**不会改动任何已验收的产物**——这是它可以进本轮的前提。

**Files:** Modify `vigil/digest.py`、`tests/test_digest.py`

**Interfaces:**
- `vigil.digest.stat_line(*, groups: int, messages: int, items: int, refined: int | None = None) -> str`
  — `refined` 为 `None` 或 `>= messages` 时不加限定（**默认 `None` = 不加限定**，与既有调用点兼容）

- [ ] **Step 1: 写失败的测试**

追加到 `tests/test_digest.py`：

```python
def test_stat_line_unchanged_when_fully_refined():
    """覆盖完整时一字不变——用户已验收的三篇走的正是这条。"""
    assert (
        digest.stat_line(groups=9, messages=514, items=6, refined=514)
        == "当天 9 个群 514 条消息，提炼出 6 条。"
    )


def test_stat_line_defaults_to_no_qualifier():
    """默认不加限定，既有调用点行为不变。"""
    assert "仅抽取" not in digest.stat_line(groups=9, messages=514, items=6)


def test_stat_line_shows_partial_coverage():
    """⚠️ 覆盖不全时必须说清楚，否则日报读起来像读遍了全部消息。"""
    line = digest.stat_line(groups=9, messages=514, items=4, refined=300)

    assert "仅抽取了 300/514" in line
    assert "提炼出 4 条" in line


def test_digest_nonempty_window_flags_partial_coverage(seeded, monkeypatch, tmp_path):
    """端到端：非空日只抽取了一部分时，正文必须带限定。"""
    from vigil import store

    conn, since, until = seeded
    conn.execute("DELETE FROM messages")
    conn.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        [(1, 100, since + 10, "u_a", "通知：明天交体检表"),
         (2, 100, since + 20, "u_b", "收到"),
         (3, 100, since + 30, "u_c", "有讲座")],
    )
    # 只记账前两条 → 覆盖 2/3
    store.record_run(conn, [1, 2], status=store.STATUS_DISCARDED, prompt_ver="v2")
    conn.commit()
    fake = _FakeLLM([{"quotes": ["体检表"], "label": "体检", "text": ""}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)

    digest.digest(_Config({100: "班级群"}), api_key="k", conn=conn,
                  since=since, until=until, day_label="2026-09-13",
                  output_dir=tmp_path)

    body = (tmp_path / "2026-09-13.md").read_text(encoding="utf-8")
    assert "仅抽取了 2/3" in body
```

- [ ] **Step 2: 实现 —— `vigil/digest.py`**

`stat_line` 改成：

```python
def stat_line(
    *, groups: int, messages: int, items: int, refined: int | None = None
) -> str:
    """日报开头那句话。数字全部由程序算，不问模型——它编过。

    ⚠️ **覆盖不全时必须加限定**：非空日若只抽取了一部分（如 `vigil refine` 撞了
    预算护栏中途停），不加限定的话「当天 N 条消息，提炼出 M 条」**读起来像读遍了
    全部 N 条**。默认 ``refined=None`` 表示「不加限定」，与既有调用点兼容；
    覆盖完整时输出一字不变（用户已验收的三篇走的正是这条）。
    """
    base = f"当天 {groups} 个群 {messages:,} 条消息"
    if refined is not None and refined < messages:
        base += f"（仅抽取了 {refined:,}/{messages:,}）"
    return f"{base}，提炼出 {items} 条。" if items else f"{base}。"
```

`digest()` 的非空路径：在算 `summary` 之前拿一次覆盖率并传进去

```python
        _, refined = store.window_refine_coverage(conn, since=since, until=until)
        summary = stat_line(
            groups=groups, messages=messages, items=len(items), refined=refined
        )
```

- [ ] **Step 3: 跑测试确认通过**

- [ ] **Step 4: 变异反证**
至少：`refined` 不传（限定永远不出现）→ 红；把 `refined < messages` 改成 `<=` → 红（完整时也会加限定）。

- [ ] **Step 5: 真实数据复核（**关键**）**

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/vigil.exe digest --date 2026-09-12
```

⚠️ **只跑 9/12 一天**，它的覆盖率是 100%。

❌ **初版判据写错了，已作废**：原写「改前改后 `git hash-object` 必须相同」。
**这条判据在本项目里根本不成立**——**重跑必然改变 hash**，因为 LLM 输出天生非确定性
（本里程碑早已记过：「**不能用 sha256 证明 LLM 产物没被改动**」）。
实测：`0c078dc6…` → `31cefdcc…`，差异全在模型措辞，而 `stat_line`（本改动唯一能触及的输出）一字未变。

✅ **正确的验收方式是受控 A/B（同一冻结模型、同一输入、新旧两版代码各跑一次）**：
```
旧码 body_sha256 = 035cd715e2c07030
新码 body_sha256 = 035cd715e2c07030   ← 相同，证明本改动没动到已验收的产物
partial 模式（300/514）：旧码「提炼出 6 条」／新码「（仅抽取了 300/514）」← 证明改动确实生效
```
跑完 A/B 后**必须把产物还原到验收态**（`git hash-object` 回到 HEAD 的值）。

- [ ] **Step 6: Commit**
```bash
git add vigil/digest.py tests/test_digest.py
git commit -m "feat(digest): 非空日在覆盖不全时写明限定（避免读起来像读遍了全部消息）"
```

---

## Task 7：重跑冒烟（**Task 6 之后**）

按 Task 5 的 Step 1–8 原样重跑一遍。判据加一条：

- **9/11 与 9/12 的「别忘」应只剩下有字面依据的那些**。按上面那张表，窗口内应当
  **只剩 1 条**（item 177 的四六级 09-16）。
- 三次机械闸门（补行 = 0）仍须成立。
- CLI 的降级计数要出现在输出里，且与预期相符。

---
