"""抽取层的持久化：建表、取待处理消息、写 items、记账。

表建在 data/vigil.db（与 messages 同库），这样「条目 → 源消息」
可以纯 SQL JOIN，不需要跨库。

`digests` / `digest_items` 由 M2 建立——M1 建了也没有写入方。
"""

from __future__ import annotations

import json
import sqlite3
import time
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

SCHEMA_DDL = (
    _ITEMS_DDL + _SOURCES_DDL + _RUNS_DDL + _DIGESTS_DDL + _DIGEST_ITEMS_DDL
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
    """建表。幂等——每次 refine 都调，不靠外部迁移工具。"""
    conn.executescript(SCHEMA_DDL)
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


def save_items(
    conn: sqlite3.Connection,
    items: list[ExtractedItem],
    *,
    model: str,
    prompt_ver: str,
    now: int | None = None,
) -> int:
    """写 items 与它们的来源，返回写入条数。"""
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
) -> None:
    """记账。用 REPLACE 保证重跑时是更新而非重复插入。"""
    if not msg_ids:
        return
    stamp = int(time.time()) if now is None else now
    conn.executemany(
        "INSERT OR REPLACE INTO refine_runs"
        " (msg_id, refined_at, status, item_count, prompt_ver, err)"
        " VALUES (?,?,?,?,?,?)",
        [(mid, stamp, status, item_count, prompt_ver, err) for mid in msg_ids],
    )
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
