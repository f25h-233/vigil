"""人工干预层：对**数据**的人工修改，不写 `data/vigil.db`。

为什么要单独一层（D14）：用户要「手动改分类 / 删除条目 / 撤销」，这三件事都要写数据，
而 M3 起 `data/vigil.db` 的只读是**机械保证**（`mode=ro`）。把它们写进主库，
那道保证就没了；而**一张 append-only 的事件表同时给出这三件事**——
撤销天然就有（事件可回溯），删除变成 tombstone，重排变成 `set_kind` 事件
（从而 `item_id` 永不翻新，见 D16）。

⚠️ **overlay 是视图层修正，不是"数据被改真了"**。直接 `sqlite3 data/vigil.db` 查，
被删的条目仍然在。这个性质是有意的，写在这里免得将来有人当成缺陷。

⚠️ **两张表的分工**：
* `item_edits` 是**唯一真相**（append-only，撤销就是对它做删除）
* `item_state` 是**物化的折叠结果**，由写入路径维护。
  读取路径 JOIN 它即可，不需要窗口函数——SQL 保持简单是刻意的。
  它可以在任何时候由 `rebuild_state()` 从 `item_edits` 完整重算。
"""

from __future__ import annotations

import pathlib
import sqlite3
import time

from .config import REPO_ROOT

OVERRIDES_DB = REPO_ROOT / "data" / "overrides.db"

ACTION_SET_KIND = "set_kind"
ACTION_SET_FIELD = "set_field"
ACTION_DELETE = "delete"

_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS item_edits (
    edit_id    INTEGER PRIMARY KEY,
    item_id    INTEGER NOT NULL,
    msg_id     INTEGER,
    action     TEXT    NOT NULL,
    field      TEXT,
    old_value  TEXT,
    new_value  TEXT,
    actor      TEXT    NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS item_edits_item ON item_edits(item_id);

CREATE TABLE IF NOT EXISTS item_state (
    item_id INTEGER PRIMARY KEY,
    kind    TEXT,
    deleted INTEGER NOT NULL DEFAULT 0
);
"""


class OverlayError(RuntimeError):
    """人工干预层的使用错误——快速失败。"""


def ensure_tables(conn: sqlite3.Connection) -> None:
    """建表。幂等。**不 commit**——调用方决定事务边界。"""
    conn.executescript(_TABLES_DDL)


def ensure_schema(path: pathlib.Path | None = None) -> None:
    """确保 overlay 文件存在且表齐全。幂等，供服务启动与写路径调用。

    ⚠️ 读取路径（`api.py`）**不能**在这里建库——它们是只读的。所以服务启动时
    先调这个函数（D11 允许 Web 写 overlay），之后每个请求才敢无条件 ATTACH。
    """
    target = path or OVERRIDES_DB
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    try:
        # ⚠️ WAL **必须在这里设**（裁定 R6）：T5 之后 `api.py` 的 `mode=ro` 只读连接
        # 会与 `refine` / T8 的写端点**并发**访问同一个库。rollback-journal 下写者持
        # EXCLUSIVE 锁 ⇒ 读请求撞 `database is locked`；而 `mode=ro` 的连接**不能**
        # 把库转成 WAL（它连库头都写不了）⇒ 只能在建库时设。
        # 实测：WAL 不影响 `mode=ro` 的 ATTACH（`-shm`/`-wal` 由 SQLite 按需重建）。
        conn.execute("PRAGMA journal_mode=WAL")
        ensure_tables(conn)
        conn.commit()
    finally:
        conn.close()


def connect(path: pathlib.Path | None = None) -> sqlite3.Connection:
    """**可写**连接（写端点专用）。"""
    conn = sqlite3.connect(str(path or OVERRIDES_DB))
    conn.row_factory = sqlite3.Row
    return conn


def attach_readonly(conn: sqlite3.Connection, path: pathlib.Path | None = None) -> None:
    """把 overlay 挂成 `ov`（只读）。读取路径专用。

    ⚠️ 用 `mode=ro` 挂——读取路径不该有写能力，哪怕只是"顺手"。
    ⚠️ 幂等：已挂过就什么都不做（`sqlite3` 重复 ATTACH 同名会报错）。

    ⚠️ **Task 4 实测的平台事实（brief 的写法在本机对部分调用方不可用）**：
    `file:...?mode=ro` 这个 URI 形式**只有连接带 `SQLITE_OPEN_URI` 时才被解析**，
    也就是必须由 `sqlite3.connect(..., uri=True)` 打开。本仓库里
    `api.py:110` **是**（`mode=ro` 的读路径），而 `cli.py:502`
    （`deadline-audit`，spec §3.3 列的 5 条读路径之一）**不是**。
    连接没带这个标志时，SQLite 把整串当**普通文件名**去开，于是报出极难定位的
    `OperationalError: unable to open database: file:C:/...?mode=ro`
    （三种 URI 写法全试过，无一可用；见 task-4-report.md）。

    ⚠️ **为什么不"兜底挂一次可写的再 PRAGMA 冻住"**：`PRAGMA ov.query_only=1`
    实测是**连接级**的（主库也一起写不了），而 `digest.py:577` / `refine.py:399`
    的连接**既要读** `window_items`**又要写**自己的表——兜底会把它们写坏。
    所以这里**只**给出「挂不上就报错」，绝不退化成可写挂载。
    """
    if any(r[1] == "ov" for r in conn.execute("PRAGMA database_list")):
        return
    target = (path or OVERRIDES_DB).as_posix()
    try:
        conn.execute(f"ATTACH DATABASE 'file:{target}?mode=ro' AS ov")
    except sqlite3.OperationalError as exc:
        # 把「怎么修」写进异常里：T5/T6 迟早会踩（cli.py:502 的连接没开 uri=True）。
        raise OverlayError(
            "overlay 只读挂载失败：连接需由 sqlite3.connect(..., uri=True) 打开"
            f"（api.py:110 是，cli.py:502 不是）。原始错误：{exc}"
        ) from exc


def _append(
    conn: sqlite3.Connection,
    *,
    item_id: int,
    msg_id: int | None,
    action: str,
    field: str | None,
    old_value: str | None,
    new_value: str | None,
    actor: str,
    now: int | None,
) -> int:
    stamp = int(time.time()) if now is None else now
    cur = conn.execute(
        "INSERT INTO item_edits"
        " (item_id, msg_id, action, field, old_value, new_value, actor, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (item_id, msg_id, action, field, old_value, new_value, actor, stamp),
    )
    _apply_to_state(
        conn, item_id=item_id, action=action, new_value=new_value, edit_id=cur.lastrowid
    )
    conn.commit()
    return int(cur.lastrowid)


def set_kind(
    conn: sqlite3.Connection, *, item_id: int, kind: str, actor: str = "web",
    now: int | None = None,
) -> int:
    """把某条 item 的类目改掉（写一条事件，不改 `items` 表）。"""
    if not kind:
        raise OverlayError("kind 不能为空")
    return _append(
        conn, item_id=item_id, msg_id=None, action=ACTION_SET_KIND, field="kind",
        old_value=None, new_value=kind, actor=actor, now=now,
    )


def delete_item(
    conn: sqlite3.Connection, *, item_id: int, msg_id: int | None, actor: str = "web",
    now: int | None = None,
) -> int:
    """软删（D15）。`msg_id` 是「永不被重抽复活」的键——**能不传就一定要传**。

    ⚠️ 不知道 `msg_id` 时传 None 是允许的（界面仍然会隐藏它），
    但那条源消息将来 `--redo` 时**就会复活**。调用方有责任尽量带上。
    """
    return _append(
        conn, item_id=item_id, msg_id=msg_id, action=ACTION_DELETE, field=None,
        old_value=None, new_value=None, actor=actor, now=now,
    )


def undo(conn: sqlite3.Connection, *, edit_id: int) -> bool:
    """撤掉一条事件，然后重建状态。事件不存在返回 False。

    ⚠️ 这里是全模块**唯一**一处 DELETE——append-only 的例外。
    它的安全性来自「事件表的尾部没有外部引用」：没有任何东西按 edit_id 持有指针。
    """
    cur = conn.execute("DELETE FROM item_edits WHERE edit_id = ?", (edit_id,))
    if cur.rowcount == 0:
        # ⚠️ **不许** rollback（reviewer 实测的 FIX 2）：调用方可能正开着一段事务
        # （T8 的"批量写 + 末尾校验"），回滚会把**它**写进去还没 commit 的东西一起丢掉
        # （实测 1→0）。失败分支本身什么都没改，不需要任何补偿动作。
        return False
    rebuild_state(conn)
    conn.commit()
    return True


def last_edit(conn: sqlite3.Connection) -> tuple[int, int, str] | None:
    row = conn.execute(
        "SELECT edit_id, item_id, action FROM item_edits ORDER BY edit_id DESC LIMIT 1"
    ).fetchone()
    return (int(row[0]), int(row[1]), str(row[2])) if row else None


def deleted_msg_ids(conn: sqlite3.Connection) -> frozenset[int]:
    """被软删条目对应的源消息 id——`refine` 靠它跳过重抽（D15）。

    ⚠️ **与 `item_state` 是同一次折叠**（裁定 R5）：墓碑化的是「**最终态**
    `deleted=1` 的 item 所引用的源消息」，不是"历史上有过 `delete` 事件"。
    `delete(i, msg=10)` 之后再 `set_kind(i)` ⇒ i 可见 ⇒ 10 **不**再被墓碑化
    （`test_delete_then_set_kind_last_wins` 早就裁定了这条语义；两次独立折叠会让
    两个视图对同一份日志给出**相反**答案——R13 同族）。

    ⚠️ **一条消息产出多条 item 时取 exists 语义**：该 msg 只要有**任意**一条
    最终态为 deleted 的 item 就墓碑化它。不这么做，重抽会把用户删掉的那条
    **复活**（直接违反 D15）；代价（同源的兄弟条目也会被冻结）见报告「疑虑」。
    """
    return frozenset(
        int(r[0])
        for r in conn.execute(
            "SELECT DISTINCT e.msg_id FROM item_edits e"
            " JOIN item_state s ON s.item_id = e.item_id"
            " WHERE s.deleted = 1 AND e.msg_id IS NOT NULL"
        )
    )


def rebuild_state(conn: sqlite3.Connection) -> None:
    """从事件日志**完整重算** `item_state`。幂等，任何时刻调都得到同一结果。"""
    conn.execute("DELETE FROM item_state")
    rows = conn.execute(
        "SELECT item_id, action, new_value FROM item_edits ORDER BY edit_id ASC"
    ).fetchall()
    for item_id, action, new_value in rows:
        if action == ACTION_DELETE:
            conn.execute(
                "INSERT INTO item_state (item_id, kind, deleted) VALUES (?, NULL, 1)"
                " ON CONFLICT(item_id) DO UPDATE SET deleted = 1",
                (item_id,),
            )
        elif action == ACTION_SET_KIND:
            conn.execute(
                "INSERT INTO item_state (item_id, kind, deleted) VALUES (?, ?, 0)"
                " ON CONFLICT(item_id) DO UPDATE SET kind = excluded.kind, deleted = 0",
                (item_id, new_value),
            )


def _apply_to_state(
    conn: sqlite3.Connection, *, item_id: int, action: str, new_value: str | None,
    edit_id: int,
) -> None:
    """把一条新事件折叠进 `item_state`（增量，不重算全表）。

    ⚠️ 必须与 `rebuild_state` 的结果**恒等**——这是两者唯一的契约。
    `test_rebuild_state_matches_incremental` 守着它。
    """
    if action == ACTION_DELETE:
        conn.execute(
            "INSERT INTO item_state (item_id, kind, deleted) VALUES (?, NULL, 1)"
            " ON CONFLICT(item_id) DO UPDATE SET deleted = 1",
            (item_id,),
        )
    elif action == ACTION_SET_KIND:
        conn.execute(
            "INSERT INTO item_state (item_id, kind, deleted) VALUES (?, ?, 0)"
            " ON CONFLICT(item_id) DO UPDATE SET kind = excluded.kind, deleted = 0",
            (item_id, new_value),
        )
