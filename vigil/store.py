"""抽取层的持久化：建表、取待处理消息、写 items、记账。

表建在 data/vigil.db（与 messages 同库），这样「条目 → 源消息」
可以纯 SQL JOIN，不需要跨库。

`digests` / `digest_items` 由 M2 建立——M1 建了也没有写入方。
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from collections.abc import Iterator
from dataclasses import dataclass

STATUS_OK = "ok"
STATUS_DISCARDED = "discarded"
STATUS_ERROR = "error"

# items：结构化条目，日报与 Web 都是它的视图
_ITEMS_DDL = """
CREATE TABLE IF NOT EXISTS items (
    item_id     INTEGER PRIMARY KEY,
    kind        TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    detail      TEXT,
    event_ts    INTEGER NOT NULL,
    deadline_ts INTEGER,
    group_id    INTEGER NOT NULL,
    actor_uid   TEXT,
    place       TEXT,
    links       TEXT,
    amount      TEXT,
    confidence  REAL    NOT NULL,
    model       TEXT    NOT NULL,
    prompt_ver  TEXT    NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS items_kind_ts  ON items(kind,     event_ts DESC);
CREATE INDEX IF NOT EXISTS items_group_ts ON items(group_id, event_ts DESC);
CREATE INDEX IF NOT EXISTS items_deadline ON items(deadline_ts)
    WHERE deadline_ts IS NOT NULL;
"""

# item_sources：可回溯。独立成表而非 JSON 数组，因为要双向查——
# 「这条 item 来自哪几条消息」和「这条消息产出了哪条 item」都要快。
_SOURCES_DDL = """
CREATE TABLE IF NOT EXISTS item_sources (
    item_id INTEGER NOT NULL,
    msg_id  INTEGER NOT NULL,
    PRIMARY KEY (item_id, msg_id)
);
CREATE INDEX IF NOT EXISTS item_sources_msg ON item_sources(msg_id);
"""

# refine_runs：幂等与增量的依据。一条消息一行，重跑跳过已处理的。
_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS refine_runs (
    msg_id     INTEGER PRIMARY KEY,
    refined_at INTEGER NOT NULL,
    status     TEXT    NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    prompt_ver TEXT    NOT NULL,
    err        TEXT
);
"""

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

# items_fts：搜索索引。**外部内容表**（content='items'）而不是另存一份正文——
# 正文只存 items 一处，索引只存分词位置，省空间也不会两份数据说了不一样的话。
#
# ⚠️ tokenize='trigram' 的理由：中文没有词边界，trigram 按 3 字符滑窗建索引，
# 于是「子串匹配」天然可用，不需要分词器。但它有两条实测出来的脾气：
#   1. **短于 3 字符的查询静默返回 0 条**（不报错）→ 见 search_items 的兜底分支
#   2. 裸查询串会被当 FTS5 语法解析，`NOT`/`(`/`a"b` 直接抛错 → 见 _fts_phrase
_SEARCH_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title, detail,
    content='items', content_rowid='item_id',
    tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS items_fts_ai AFTER INSERT ON items BEGIN
  INSERT INTO items_fts(rowid, title, detail)
  VALUES (new.item_id, new.title, new.detail);
END;
CREATE TRIGGER IF NOT EXISTS items_fts_ad AFTER DELETE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, title, detail)
  VALUES ('delete', old.item_id, old.title, old.detail);
END;
CREATE TRIGGER IF NOT EXISTS items_fts_au AFTER UPDATE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, title, detail)
  VALUES ('delete', old.item_id, old.title, old.detail);
  INSERT INTO items_fts(rowid, title, detail)
  VALUES (new.item_id, new.title, new.detail);
END;
"""

SCHEMA_DDL = (
    _ITEMS_DDL
    + _SOURCES_DDL
    + _RUNS_DDL
    + _DIGESTS_DDL
    + _DIGEST_ITEMS_DDL
    + _SEARCH_DDL
)


@dataclass(frozen=True)
class PendingMessage:
    """待抽取的一条消息，姓名已解析好。"""

    msg_id: int
    group_id: int
    ts: int
    sender_uid: str
    sender: str
    content: str


@dataclass(frozen=True)
class ExtractedItem:
    """一条结构化条目。src_msg_ids 让它可回溯到原文。"""

    kind: str
    title: str
    detail: str | None
    event_ts: int
    deadline_ts: int | None
    group_id: int
    actor_uid: str | None
    place: str | None
    links: tuple[str, ...]
    amount: str | None
    confidence: float
    src_msg_ids: tuple[int, ...]


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


def ensure_schema(conn: sqlite3.Connection) -> None:
    """建表。幂等——每次 refine 都调，不靠外部迁移工具。

    顺带重建搜索索引：触发器只管建好之后的新数据，**存量行**得靠 rebuild。
    跑在写路径上（refine / digest），代价是 O(条目数)，换来「索引不会
    长期停在过期状态」——搜索返回空结果时，那个空结果才真是「库里没有」。
    """
    conn.executescript(SCHEMA_DDL)
    rebuild_search_index(conn)
    conn.commit()


def pending_messages(
    conn: sqlite3.Connection,
    *,
    since: int | None = None,
    until: int | None = None,
    limit: int | None = None,
    redo: bool = False,
) -> list[PendingMessage]:
    """取待抽取的消息，按时间升序（时间序是上下文与切批的前提）。

    不在这里过滤 `[非文本]`——硬丢弃是预筛层的职责，
    这样 refine_runs 才能覆盖全部消息（M1 出口标准要求无遗漏）。
    """
    sql = """
        SELECT m.msg_id, m.group_id, m.ts,
               COALESCE(m.sender_uid, '') AS uid,
               COALESCE(NULLIF(s.group_nick, ''), NULLIF(s.qq_nick, ''), '') AS sender,
               m.content
        FROM messages m
        LEFT JOIN sender_names s
               ON s.group_id = m.group_id AND s.uid = m.sender_uid
    """
    where: list[str] = []
    params: list[object] = []

    if not redo:
        # ⚠️ 必须排除 error 行重试，不能把它们当成「已处理」。
        # 写成 `NOT IN (SELECT msg_id FROM refine_runs)` 的话，一次网络抖动
        # （429/超时）就会把那批消息**永久跳过**，且没有任何自动重试机制——
        # 静默的永久数据丢失。error 行是「试过但没成功」，不是「已处理」。
        where.append(
            "m.msg_id NOT IN (SELECT msg_id FROM refine_runs WHERE status != ?)"
        )
        params.append(STATUS_ERROR)
    if since is not None:
        where.append("m.ts >= ?")
        params.append(since)
    if until is not None:
        where.append("m.ts < ?")
        params.append(until)

    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY m.ts ASC, m.msg_id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    return [PendingMessage(*row) for row in conn.execute(sql, params)]


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """把一段写操作圈成一个事务：正常退出 commit，出异常 rollback 后原样抛出。

    ⚠️ 存在的唯一理由是**关掉一个窗口**：`save_items` 与 `record_run` 各自
    commit 一次，两步之间崩掉（断电/重启/任务被杀）会留下「items 落库了、
    消息没标记」的状态——下次 `pending_messages` 把同一批消息再抽一遍，
    **产出重复 items 且全程无声**（`items` 表没有任何唯一键，唯一防重复的
    机制就是 `refine_runs` 的记账跟得上）。写进一个事务后要么两件事都成、
    要么都不成，重抽是干净的。

    ⚠️ 捕 `BaseException` 而不是 `Exception`：`KeyboardInterrupt` 与
    `SystemExit` 也必须 rollback，否则 Ctrl-C 会留下半个批次。

    ⚠️ **不可重入**：不要在 `with transaction(conn)` 里面再开一层——
    sqlite3 的嵌套提交会让内层先落盘，窗口就回来了。
    """
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def save_items(
    conn: sqlite3.Connection,
    items: list[ExtractedItem],
    *,
    model: str,
    prompt_ver: str,
    now: int | None = None,
    commit: bool = True,
) -> int:
    """写 items 与它们的来源，返回写入条数。

    ⚠️ `commit=False` 用于把本函数并入外层 `transaction()` —— 调用方有责任
    用 `with transaction(conn):` 圈住，否则写的东西永远不会落盘。
    """
    stamp = int(time.time()) if now is None else now
    for item in items:
        cur = conn.execute(
            "INSERT INTO items (kind, title, detail, event_ts, deadline_ts,"
            " group_id, actor_uid, place, links, amount, confidence,"
            " model, prompt_ver, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item.kind,
                item.title,
                item.detail,
                item.event_ts,
                item.deadline_ts,
                item.group_id,
                item.actor_uid,
                item.place,
                json.dumps(list(item.links), ensure_ascii=False),
                item.amount,
                item.confidence,
                model,
                prompt_ver,
                stamp,
            ),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO item_sources (item_id, msg_id) VALUES (?, ?)",
            [(cur.lastrowid, mid) for mid in item.src_msg_ids],
        )
    if commit:
        conn.commit()
    return len(items)


def record_run(
    conn: sqlite3.Connection,
    msg_ids: list[int] | tuple[int, ...],
    *,
    status: str,
    prompt_ver: str,
    item_count: int = 0,
    err: str | None = None,
    now: int | None = None,
    commit: bool = True,
) -> None:
    """记账。用 REPLACE 保证重跑时是更新而非重复插入。

    ⚠️ `commit=False` 用于把本函数并入外层 `transaction()` —— 调用方有责任
    用 `with transaction(conn):` 圈住，否则写的东西永远不会落盘。
    """
    if not msg_ids:
        return
    stamp = int(time.time()) if now is None else now
    conn.executemany(
        "INSERT OR REPLACE INTO refine_runs"
        " (msg_id, refined_at, status, item_count, prompt_ver, err)"
        " VALUES (?,?,?,?,?,?)",
        [(mid, stamp, status, item_count, prompt_ver, err) for mid in msg_ids],
    )
    if commit:
        conn.commit()


def window_items(
    conn: sqlite3.Connection, *, since: int, until: int
) -> list[WindowItem]:
    """取时间窗内的条目，按 ``(event_ts, item_id)`` 升序。窗口是 ``[since, until)``。

    排序必须**确定**：未命中条目的机械补行按本函数返回序追加，出网 payload
    也按它排列——顺序变了，用户看到的行序就会变。

    ⚠️ 但**分区与署名群不依赖这个顺序**：``build_rows`` 的锚点是 ``picked[0]``，
    而 ``picked`` 的顺序由 ``line.item_ids`` 决定，``line.item_ids`` 来自
    ``digest.match_lines``——后者自己做了
    ``hits.sort(key=lambda it: (it.event_ts, it.item_id))``。锚点顺序由那个
    排序独立保证，与本函数的 ORDER BY 无关。

    （旧注释曾称锚点「隐式依赖」本函数顺序，那是**错的因果**：结论「顺序不能改」
    成立，但理由不是锚点，而是机械补行序与出网 payload 序。已修正。）
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


def window_refine_coverage(
    conn: sqlite3.Connection, *, since: int, until: int
) -> tuple[int, int]:
    """窗口内的 (消息总数, **已抽取**的条数)。

    空窗日的日报靠它自证「**是安静，不是管线没跑**」——覆盖率不足时
    绝不能说「没有值得一提的信息」，那是句可能为假的话。

    ⚠️ ``status='error'`` 的行**不算已抽取**（修复轮次 1）：批次失败时 refine
    会写 error 行，而 ``pending_messages(redo=False)`` 的语义是「**试过但没成功
    ≠ 已处理**」——那些消息下次还会被重新取出来跑。两边若不同调，日报就会
    在「其实还有一批没抽」时说出「没有值得一提的信息」：又一个假话入口。
    （首版只查「有没有 refine_runs 行」，与 refine 的重试口径不一致。）
    """
    total = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE ts >= ? AND ts < ?", (since, until)
    ).fetchone()[0]
    refined = conn.execute(
        "SELECT COUNT(*) FROM messages m WHERE m.ts >= ? AND m.ts < ?"
        " AND m.msg_id IN (SELECT msg_id FROM refine_runs WHERE status != ?)",
        (since, until, STATUS_ERROR),
    ).fetchone()[0]
    return total, refined


def message_span(conn: sqlite3.Connection) -> tuple[int, int] | None:
    """全库消息的 ``(最早 ts, 最晚 ts)``；一条都没有时 None。

    空窗日靠它分清「**这天没数据**」与「**这天真的没人说话**」——
    两者在旧版里都渲染成「没有值得一提的信息」，而前者是句假话。

    ⚠️ **为什么要看全库的最值、而不是「窗口前面有没有消息」**：窗口落在
    跨度之外时，库里的消息一条都不可能与这天相邻；而只要窗口夹在
    ``(MIN(ts), MAX(ts))`` 之间，就必然**前后都有数据**——后者正是
    「这天真的没人说话」这句话成立的依据。只看单侧（比如「窗口之前有没有
    消息」）会在「库里的数据全在这天之后」时说不出口径相同的结论。

    ⚠️ **必须过滤 ``ts > 0``，否则「窗口早于全部数据」那一侧永远判不出来**
    （修复轮次 1）。本库有 14 条 ``ts=0`` 的脏数据（1970-01-01），它们会把
    ``MIN(ts)`` 死死按在 0：查一个**早于所有数据**的日期（如 ``2026-06-01``）时
    ``window[1] <= span[0]`` 即 ``<= 0`` → False、``window[0] > span[1]`` → False，
    于是 ``outside`` 算成 False，日报说「这天是真的没人说话」——**可那天压根
    不在数据覆盖范围内**。同一句假话，换了第三个入口。
    实测（过滤后）：``span = (1784553735, 1789308554)`` = 2026-07-20 .. 2026-09-13。

    ⚠️ **``window_stats`` 不要跟着一起改**——两处**看起来**口径不一致，实则
    不是同一类问题，强行「统一」会把对的改错：

    * ``window_stats`` 是**按窗口**统计（``WHERE ts >= ? AND ts < ?``）。脏行的
      ``ts=0`` 天然落在任何一个真实日期的窗口之外，**毒不到**它——它的口径
      本来就对，改它没有收益、只有风险（``ts > 0`` 那种过滤在窗口统计里是
      多余条件，且会让人以为「窗口统计也依赖脏数据」）。
    * ``message_span`` 是**全库 MIN/MAX**，没有任何窗口把脏行挡在外面，
      一条脏行就能把整个下界拉到 0——**它才是会被毒化的那个**。

    一句话：**窗口统计天然免疫脏行，全局最值不免疫**；所以过滤只加在这里。
    """
    row = conn.execute(
        "SELECT MIN(ts), MAX(ts) FROM messages WHERE ts > 0"
    ).fetchone()
    if not row or row[0] is None:
        return None
    return int(row[0]), int(row[1])


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
    commit: bool = True,
) -> int:
    """写一篇日报，返回 digest_id。同一个窗口**替换**而不是追加。

    ⚠️ 三步（删 digest_items → 删 digests → 插新行）**必须在同一个事务里**。
    分开提交的话，崩在中间会让当天日报凭空消失——而 `docs/digests/` 的
    文件还在，归档不变量（文件集合 == 库里的窗口日期集合）当场破掉，
    且没有任何东西会报错。

    ⚠️ `commit=False` 时**不自己开事务**，由调用方用 `transaction()` 圈住——
    这样「写库」与「落文件」能进同一个事务（见 `digest._persist`）。
    """
    stamp = int(time.time()) if now is None else now

    def _write() -> int:
        # 不删关联行的话，重跑一次就会在 digest_items 里留下指向前一版日报的孤儿行
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
        new_id = int(cur.lastrowid or 0)
        conn.executemany(
            "INSERT OR IGNORE INTO digest_items (digest_id, item_id) VALUES (?,?)",
            [(new_id, iid) for iid in item_ids],
        )
        return new_id

    if commit:
        with transaction(conn):
            return _write()
    return _write()


def item_sources_text(
    conn: sqlite3.Connection, item_ids: list[int]
) -> dict[int, str]:
    """把每条 item 的**源消息正文**按 item_id 拼起来。

    用途：核验「截止日是不是源文里真有的」（``digest.deadline_supported``）。

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


def items_with_deadline(conn: sqlite3.Connection) -> list[tuple[int, int]]:
    """所有**带截止日**的 ``(item_id, deadline_ts)``。回填核验用。"""
    return [
        (int(a), int(b))
        for a, b in conn.execute(
            "SELECT item_id, deadline_ts FROM items"
            " WHERE deadline_ts IS NOT NULL ORDER BY item_id"
        )
    ]


def clear_deadlines(conn: sqlite3.Connection, item_ids: list[int]) -> int:
    """把给定条目的 ``deadline_ts`` 置 NULL，返回实际改动行数。

    只动这一列：条目的标题、正文、来源一概不碰——**降级的是那一个字段，
    不是整条信息**。用户仍然看得到这条，只是不再被告知一个编出来的日期。
    """
    if not item_ids:
        return 0
    marks = ",".join("?" * len(item_ids))
    cur = conn.execute(
        f"UPDATE items SET deadline_ts = NULL WHERE item_id IN ({marks})",
        list(item_ids),
    )
    conn.commit()
    return int(cur.rowcount)


# ── 只读查询层：Web 的读侧（M3 Task 2）────────────────────────
#
# 全是只读的 SELECT（`rebuild_search_index` 是唯一例外，它写索引）。
# 列名与 API 契约逐字对应，`:mod:`vigil.api`（T3）直接把它序列化出去。

# FTS5 trigram 的最小可查长度。短于它的查询**不会报错，只会返回空**。
MIN_TRIGRAM = 3


def rebuild_search_index(conn: sqlite3.Connection) -> None:
    """把搜索索引与 items 重建一致。

    触发器建好之后新数据会自动同步；这个函数管的是**存量行**与
    「索引曾经与 items 脱节」的情况。
    """
    conn.execute("INSERT INTO items_fts(items_fts) VALUES ('rebuild')")
    conn.commit()


def _fts_phrase(q: str) -> str:
    """把用户输入包成 FTS5 **短语**查询。

    ⚠️ 不包就会炸（实测）：`NOT`、`a"b`、`(`、`补退选 -卡` 全都让 MATCH 抛
    ``OperationalError``——用户在搜索框里打个引号就是 500。包成短语后，
    这些输入退化成「按字面找这个短语」，语义仍然正确。
    """
    return '"' + q.replace('"', '""') + '"'


def _escape_like(q: str) -> str:
    """LIKE 的通配符转义。不转义的话用户输入的 % 会变成「匹配一切」。"""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# C0 控制字符（U+0000–U+001F），含 NUL。它们不承担任何搜索语义。
_CONTROL_TRANS = str.maketrans("", "", "".join(chr(c) for c in range(0x20)))


def _strip_controls(q: str) -> str:
    """剥掉 C0 控制字符（含 NUL）。**必须在 trigram / LIKE 分岔之前调用。**

    ⚠️ 一个 NUL 能让**两条路径各出一个假结果**，而且都能从 HTTP 触发
    （``q`` 是用户直接给的查询串）。实测（内存库 2 行）：

    - ``len(q) >= 3`` → FTS5 解析器在 NUL 处**截断**，``_fts_phrase`` 包出来的
      引号因此不闭合 → 未捕获的 ``OperationalError: unterminated string``
      → T3 上线后就是一个 **500**。
      实测：``q='\\x00选课通知'`` / ``q='选\\x00课'`` 都抛这个错。
    - ``len(q) <= 2`` → SQLite 的 LIKE 把 pattern 在 NUL 处**截断成 ``%``**
      → **返回全表**。实测：``q='\\x00课'`` 在 2 行的库里返回 ``total=2``，
      而正确答案是 1（只有「选课通知」含「课」）。
      这比报错危险得多——它是个**假数字**：页面会说「共 2 条」，
      用户以为搜到了，其实一行都没筛。本项目最忌的就是这类错。

    控制字符本来就不承担搜索语义，剥掉不会让哪个正常查询失去结果。
    剥完为空串时按「不筛选」处理——与既有的「空 ``q`` 等于不筛选」契约一致。
    """
    return q.translate(_CONTROL_TRANS)


@dataclass(frozen=True)
class ApiItem:
    """喂给 Web 的一条条目。列名与 API 契约逐字对应。

    ``actor`` 已在 SQL 里解析成姓名（同 ``pending_messages`` 的口径）；
    ``group_name`` 不在这里解析——群名来自 ``config/groups.toml`` 而不是库，
    由 API 层补上。库返回 id、配置层补名字，这个分工与既有代码一致。
    """

    item_id: int
    kind: str
    title: str
    detail: str | None
    event_ts: int
    deadline_ts: int | None
    group_id: int
    actor: str | None
    place: str | None
    amount: str | None
    links: tuple[str, ...]
    source_count: int


@dataclass(frozen=True)
class SourceRow:
    """一条源消息的原文。Web 的「点回原文」靠它。"""

    msg_id: int
    ts: int
    sender: str
    group_id: int
    content: str


@dataclass(frozen=True)
class DigestSummaryRow:
    digest_id: int
    window_from: int
    window_to: int
    created_at: int
    item_count: int


@dataclass(frozen=True)
class DigestRow:
    digest_id: int
    window_from: int
    window_to: int
    body_md: str
    created_at: int
    item_count: int


_ITEM_COLS = (
    "i.item_id, i.kind, i.title, i.detail, i.event_ts, i.deadline_ts, i.group_id,"
    " COALESCE(NULLIF(sn.group_nick, ''), NULLIF(sn.qq_nick, ''), '') AS actor,"
    " i.place, i.amount, i.links,"
    " (SELECT COUNT(*) FROM item_sources src WHERE src.item_id = i.item_id)"
    "   AS source_count"
)

_ITEM_JOINS = (
    " FROM items i"
    " LEFT JOIN sender_names sn ON sn.group_id = i.group_id AND sn.uid = i.actor_uid"
)


def _parse_links(raw: object) -> tuple[str, ...]:
    """``items.links`` 存的是 JSON 数组文本。

    ⚠️ 解析失败**不抛异常**：这一列是 M1 写的，坏一条不该让整页 500。
    解析不出来就当没有链接（视图少一栏，不是白屏）。
    """
    if not raw:
        return ()
    try:
        data = json.loads(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ()
    if not isinstance(data, list):
        return ()
    return tuple(str(x) for x in data)


def _to_api_item(row: tuple) -> ApiItem:
    (item_id, kind, title, detail, event_ts, deadline_ts, group_id,
     actor, place, amount, links, source_count) = row
    return ApiItem(
        item_id=item_id,
        kind=kind,
        title=title,
        detail=detail,
        event_ts=event_ts,
        deadline_ts=deadline_ts,
        group_id=group_id,
        actor=actor or None,
        place=place,
        amount=amount,
        links=_parse_links(links),
        source_count=int(source_count),
    )


def _item_filters(
    *,
    kind: str | None,
    since: int | None,
    until: int | None,
    group: int | None,
    q: str | None,
) -> tuple[list[str], list[object]]:
    """拼 WHERE 片段。**关键词的两条路径在这里分岔**（trigram / LIKE）。"""
    where: list[str] = []
    params: list[object] = []
    if kind:
        where.append("i.kind = ?")
        params.append(kind)
    if since is not None:
        where.append("i.event_ts >= ?")
        params.append(since)
    if until is not None:
        where.append("i.event_ts < ?")
        params.append(until)
    if group is not None:
        where.append("i.group_id = ?")
        params.append(group)
    if q is not None:
        # ⚠️ 净化必须在这里、**分岔之前**——两条路径各有各的坏法（见 _strip_controls）。
        # 剥完为空串就与「没传 q」同义：沿用「空 q 等于不筛选」的既有契约。
        q = _strip_controls(q)
    if q:
        if len(q) >= MIN_TRIGRAM:
            where.append(
                "i.item_id IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)"
            )
            params.append(_fts_phrase(q))
        else:
            # ⚠️ trigram tokenizer **对短于 3 字符的查询静默返回 0 条**（实测，
            # 不报错）——而中文双字词（「选课」「讲座」）恰恰是最常见的查询。
            # 没有这一支的话，「搜不到」会被读成「库里没有」，是句假话。
            # items 目前 270 行、年增约两千行，LIKE 全表扫的代价可以忽略。
            like = f"%{_escape_like(q)}%"
            where.append(
                "(i.title LIKE ? ESCAPE '\\'"
                " OR IFNULL(i.detail, '') LIKE ? ESCAPE '\\')"
            )
            params += [like, like]
    return where, params


def search_items(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    since: int | None = None,
    until: int | None = None,
    group: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ApiItem], int]:
    """查条目，返回 ``(当页, 符合条件的总数)``。

    排序是 ``event_ts DESC, item_id DESC``（新的在前）——信息流的默认读法。
    ⚠️ 与 ``window_items`` 的 ASC 不同是**故意的**：日报按时间顺着读，
    信息流按时间倒着看。两处都不许「顺手改成一致」。
    """
    where, params = _item_filters(
        kind=kind, since=since, until=until, group=group, q=q
    )
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = int(
        conn.execute(f"SELECT COUNT(*) FROM items i{clause}", params).fetchone()[0]
    )
    rows = conn.execute(
        f"SELECT {_ITEM_COLS}{_ITEM_JOINS}{clause}"
        " ORDER BY i.event_ts DESC, i.item_id DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return [_to_api_item(r) for r in rows], total


def get_item(conn: sqlite3.Connection, item_id: int) -> ApiItem | None:
    """单条条目；不存在返回 None（由调用方决定 404 的形状）。"""
    row = conn.execute(
        f"SELECT {_ITEM_COLS}{_ITEM_JOINS} WHERE i.item_id = ?", (item_id,)
    ).fetchone()
    return _to_api_item(row) if row else None


def source_messages(conn: sqlite3.Connection, item_id: int) -> list[SourceRow]:
    """这条 item 来源消息的**原文**，按 ``(ts, msg_id)`` 升序。

    顺序是当初喂给模型的顺序——回溯时读起来才顺。

    名字不叫 ``item_sources``——那会与**表名**撞车，读代码时分不清
    说的是表还是函数（这里返回的是「消息」，不是「来源行」）。
    """
    rows = conn.execute(
        "SELECT m.msg_id, m.ts,"
        " COALESCE(NULLIF(sn.group_nick, ''), NULLIF(sn.qq_nick, ''), '') AS sender,"
        " m.group_id, IFNULL(m.content, '')"
        " FROM item_sources src"
        " JOIN messages m ON m.msg_id = src.msg_id"
        " LEFT JOIN sender_names sn"
        "        ON sn.group_id = m.group_id AND sn.uid = m.sender_uid"
        " WHERE src.item_id = ?"
        " ORDER BY m.ts ASC, m.msg_id ASC",
        (item_id,),
    ).fetchall()
    return [SourceRow(*r) for r in rows]


def kind_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """每个类目有多少条。类目视图的角标用它。"""
    return {
        str(k): int(n)
        for k, n in conn.execute("SELECT kind, COUNT(*) FROM items GROUP BY kind")
    }


def list_digests(
    conn: sqlite3.Connection, *, limit: int = 30
) -> list[DigestSummaryRow]:
    """日报列表，最近的窗口在前。**不带正文**——列表页用不上，白白撑大响应。"""
    rows = conn.execute(
        "SELECT d.digest_id, d.window_from, d.window_to, d.created_at,"
        " (SELECT COUNT(*) FROM digest_items di WHERE di.digest_id = d.digest_id)"
        " FROM digests d ORDER BY d.window_from DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [DigestSummaryRow(*r) for r in rows]


def get_digest(conn: sqlite3.Connection, digest_id: int) -> DigestRow | None:
    row = conn.execute(
        "SELECT d.digest_id, d.window_from, d.window_to, d.body_md, d.created_at,"
        " (SELECT COUNT(*) FROM digest_items di WHERE di.digest_id = d.digest_id)"
        " FROM digests d WHERE d.digest_id = ?",
        (digest_id,),
    ).fetchone()
    return DigestRow(*row) if row else None


def digest_items(conn: sqlite3.Connection, digest_id: int) -> list[ApiItem]:
    """一篇日报引用的条目，按 ``(event_ts, item_id)`` 升序——与日报正文同序。"""
    rows = conn.execute(
        f"SELECT {_ITEM_COLS}{_ITEM_JOINS}"
        " JOIN digest_items di ON di.item_id = i.item_id"
        " WHERE di.digest_id = ?"
        " ORDER BY i.event_ts ASC, i.item_id ASC",
        (digest_id,),
    ).fetchall()
    return [_to_api_item(r) for r in rows]
