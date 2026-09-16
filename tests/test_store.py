"""持久化层的测试。全部用内存库，不碰 data/vigil.db。"""

from __future__ import annotations

import sqlite3

import pytest

from vigil import store
from vigil.store import ExtractedItem, PendingMessage


# messages + sender_names 的形状，与 export.py 产出的完全一致。
# 这两张表**不由 store.ensure_schema 建**（它们是 export.py 的产物、真库里一直在），
# 但查询层会 JOIN 它们——所以测试里凡是要跑查询层的插桩，都得先把它们立起来。
# ⚠️ 用 IF NOT EXISTS：M3 Task 2 的 `_insert_item` 会在 `_seed_messages` 之前
# 先立一次表，两者叠加时不能炸。
_MESSAGE_TABLES_DDL = """
CREATE TABLE IF NOT EXISTS messages (
    msg_id     INTEGER PRIMARY KEY,
    group_id   INTEGER NOT NULL,
    ts         INTEGER NOT NULL,
    sender_uid TEXT,
    content    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sender_names (
    group_id   INTEGER NOT NULL,
    uid        TEXT    NOT NULL,
    group_nick TEXT,
    qq_nick    TEXT,
    uin        INTEGER,
    in_group   INTEGER,
    PRIMARY KEY (group_id, uid)
);
"""


def _ensure_message_tables(conn: sqlite3.Connection) -> None:
    """让查询层 JOIN 得起来。幂等。"""
    conn.executescript(_MESSAGE_TABLES_DDL)


def _seed_messages(conn: sqlite3.Connection) -> None:
    """造一张最小的 messages + sender_names，形状与 export.py 产出的完全一致。"""
    _ensure_message_tables(conn)
    conn.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        [
            (1, 100, 1000, "u_a", "明天有讲座"),
            (2, 100, 2000, "u_b", "收到"),
            (3, 200, 3000, "u_a", "二手自行车出"),
        ],
    )
    conn.executemany(
        "INSERT INTO sender_names VALUES (?,?,?,?,?,?)",
        [
            (100, "u_a", "张三", "三三", 111, 0),
            (100, "u_b", None, "李四", 222, 0),
            (200, "u_a", "张三", "三三", 111, 0),
        ],
    )
    conn.commit()


def test_ensure_schema_is_idempotent(memdb):
    store.ensure_schema(memdb)
    store.ensure_schema(memdb)
    names = {
        r[0]
        for r in memdb.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"items", "item_sources", "refine_runs"} <= names


def test_pending_messages_resolves_sender_name(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    pending = store.pending_messages(memdb)
    assert len(pending) == 3
    # 群昵称优先于 QQ 昵称
    assert pending[0].sender == "张三"
    # 群昵称为空时退回 QQ 昵称
    assert pending[1].sender == "李四"


def test_pending_messages_orders_by_time(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    assert [m.msg_id for m in store.pending_messages(memdb)] == [1, 2, 3]


def test_pending_messages_skips_already_run(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    store.record_run(memdb, [1], status=store.STATUS_OK, prompt_ver="v1")
    assert [m.msg_id for m in store.pending_messages(memdb)] == [2, 3]


def test_pending_messages_retries_error_rows(memdb):
    """⚠️ error 行必须被重试，不能当成「已处理」（Task 7 审查实测抓出）。

    写成 `NOT IN (SELECT msg_id FROM refine_runs)` 的话，一次网络抖动
    （429/超时）就会把那批消息**永久跳过**，且没有任何自动重试机制——
    静默的永久数据丢失。error 的语义是「试过但没成功」，不是「已处理」。
    """
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    store.record_run(memdb, [1], status=store.STATUS_OK, prompt_ver="v1")
    store.record_run(memdb, [2], status=store.STATUS_ERROR, prompt_ver="v1", err="429")
    store.record_run(memdb, [3], status=store.STATUS_DISCARDED, prompt_ver="v1")

    # 只有 error 那条会被重新取出——ok 与 discarded 都算真处理过了
    assert [m.msg_id for m in store.pending_messages(memdb)] == [2]


def test_redo_returns_everything(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    store.record_run(memdb, [1, 2, 3], status=store.STATUS_OK, prompt_ver="v1")
    assert len(store.pending_messages(memdb, redo=True)) == 3


def test_pending_messages_respects_window_and_limit(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    assert [m.msg_id for m in store.pending_messages(memdb, since=2000)] == [2, 3]
    assert [m.msg_id for m in store.pending_messages(memdb, until=2000)] == [1]
    assert len(store.pending_messages(memdb, limit=2)) == 2


def test_save_items_writes_sources(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    item = ExtractedItem(
        kind="activity",
        title="西太湖报告厅有讲座",
        detail=None,
        event_ts=1000,
        deadline_ts=None,
        group_id=100,
        actor_uid="u_a",
        place="西太湖报告厅",
        links=(),
        amount=None,
        confidence=0.9,
        src_msg_ids=(1,),
    )
    assert store.save_items(memdb, [item], model="m", prompt_ver="v1", now=42) == 1

    row = memdb.execute(
        "SELECT kind, title, deadline_ts, actor_uid, created_at FROM items"
    ).fetchone()
    assert row == ("activity", "西太湖报告厅有讲座", None, "u_a", 42)
    assert memdb.execute("SELECT item_id, msg_id FROM item_sources").fetchall() == [(1, 1)]


def test_save_items_roundtrips_links(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    item = ExtractedItem(
        kind="notice", title="报名", detail=None, event_ts=1000, deadline_ts=None,
        group_id=100, actor_uid=None, place=None,
        links=("https://example.com/a", "https://example.com/b"),
        amount=None, confidence=0.5, src_msg_ids=(1,),
    )
    store.save_items(memdb, [item], model="m", prompt_ver="v1")
    raw = memdb.execute("SELECT links FROM items").fetchone()[0]
    assert "example.com/a" in raw and "example.com/b" in raw


def test_record_run_is_idempotent(memdb):
    store.ensure_schema(memdb)
    store.record_run(memdb, [7], status=store.STATUS_OK, prompt_ver="v1", item_count=2)
    store.record_run(memdb, [7], status=store.STATUS_DISCARDED, prompt_ver="v2")
    rows = memdb.execute("SELECT msg_id, status, prompt_ver FROM refine_runs").fetchall()
    assert rows == [(7, "discarded", "v2")]


def test_item_sources_supports_reverse_lookup(memdb):
    """『这条消息产出了哪条 item』必须可查——避免重复抽取靠它。"""
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    item = ExtractedItem(
        kind="notice", title="t", detail=None, event_ts=1000, deadline_ts=None,
        group_id=100, actor_uid=None, place=None, links=(), amount=None,
        confidence=0.5, src_msg_ids=(1, 2),
    )
    store.save_items(memdb, [item], model="m", prompt_ver="v1")
    by_msg = memdb.execute(
        "SELECT item_id FROM item_sources WHERE msg_id = ?", (2,)
    ).fetchall()
    assert by_msg == [(1,)]


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
    # find_digest 已按审查裁决删除（零生产调用方，见修复轮次 1）——直接查表。
    assert memdb.execute(
        "SELECT digest_id, body_md FROM digests WHERE window_from=? AND window_to=?",
        (1000, 5000),
    ).fetchone() == (digest_id, "# 日报")
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
    assert memdb.execute(
        "SELECT body_md FROM digests WHERE window_from=? AND window_to=?",
        (1000, 5000),
    ).fetchone()[0] == "# 第二版"


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


# ── 修复轮次 1：补守卫（F1/F2/F4/F5）─────────────────────────


def _insert_items(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    """按 (item_id, kind, title, detail, event_ts, deadline_ts, group_id,
    place, amount, confidence) 造条目。只给边界/映射用例用。"""
    conn.executemany(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, links, amount, confidence, model,"
        " prompt_ver, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (iid, kind, title, detail, ts, dl, gid, None, place, "[]", amount,
             conf, "m", "v1", 1)
            for (iid, kind, title, detail, ts, dl, gid, place, amount, conf)
            in rows
        ],
    )
    conn.commit()


def test_window_items_bounds_are_half_open(memdb):
    """窗口是半开区间 [since, until)：下界**含**、上界**不含**。

    ⚠️ 这条守的是「跨日不重复计数」。``day_window`` 是 ``[今日00:00, 明日00:00)``，
    今天的 ``until`` 正好是明天的 ``since``——上界一旦写成闭区间，边界那条
    条目会在昨天和今天的日报里**各出现一次**：数字对不上、条目重复，
    而且是静默的，没有任何报错。
    """
    store.ensure_schema(memdb)
    _insert_items(memdb, [
        (11, "notice", "下界外", None, 999, None, 100, None, None, 0.9),
        (12, "notice", "恰在下界", None, 1000, None, 100, None, None, 0.9),
        (13, "notice", "窗口内", None, 4999, None, 100, None, None, 0.9),
        (14, "notice", "恰在上界", None, 5000, None, 100, None, None, 0.9),
        (15, "notice", "上界外", None, 5001, None, 100, None, None, 0.9),
    ])

    got = store.window_items(memdb, since=1000, until=5000)

    # 边界两条的决定性：12 含（>= 不是 >）、14 不含（< 不是 <=）
    assert [it.item_id for it in got] == [12, 13]


def test_window_stats_bounds_are_half_open(memdb):
    """``window_stats`` 的窗口同样必须半开——否则当日消息数会跨日重复计。

    种子故意放在 ts=9999..20001，与 ``_seed_messages`` 的 1000/2000/3000
    完全错开，所以不需要删任何既有行。
    """
    _seed_messages(memdb)
    memdb.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        [
            (901, 100, 9999, "u_a", "下界外"),
            (902, 100, 10000, "u_a", "恰在下界"),
            (903, 100, 19999, "u_a", "窗口内"),
            (904, 200, 20000, "u_a", "恰在上界"),
            (905, 200, 20001, "u_a", "上界外"),
        ],
    )
    memdb.commit()

    # 2 条消息、同属群 100 → (2, 1)：上界闭区间会变 (3, 2)、下界开区间会变 (1, 1)
    assert store.window_stats(memdb, since=10000, until=20000) == (2, 1)


def test_window_items_orders_by_event_ts_ascending(memdb):
    """按 ``event_ts`` 升序——即使 ``item_id`` 顺序与之相同也不能退化成 id 序。

    ⚠️ brief 原来的种子（id 1→ts 3000、id 2→ts 2000）里 **id 序与 ts 序恰好相反**，
    于是 ``ORDER BY item_id DESC`` 与正确实现返回同一个 ``[2, 1]``，变异抓不住。
    本条刻意让 **id 序与 ts 序相同**，把这条路堵上。
    """
    store.ensure_schema(memdb)
    _insert_items(memdb, [
        (21, "notice", "最早", None, 1000, None, 100, None, None, 0.9),
        (22, "notice", "居中", None, 2000, None, 100, None, None, 0.9),
        (23, "notice", "最晚", None, 3000, None, 100, None, None, 0.9),
    ])

    got = store.window_items(memdb, since=0, until=9999)

    assert [it.item_id for it in got] == [21, 22, 23]


def test_window_items_tie_break_is_item_id(memdb):
    """并列 ``event_ts`` 的条目按 ``item_id`` 升序——守 ``(event_ts, item_id)`` 契约。

    种子两条 ``event_ts`` 相同、``group_id`` 不同、``item_id`` 与群号顺序相反，
    对齐真实库的形状（审查实测：53 个有 item 的本地日里约 8 天存在 ``event_ts`` 撞车）。

    ⚠️ **诚实标注（实测，非推断）：只删掉 ORDER BY 里 ``item_id ASC`` 这一个子句，
    本测试抓不住，而且没有任何种子能抓住。**

    原因是 ``item_id`` 就是 rowid，而本函数的 SELECT 取全部 10 列、用不上覆盖索引
    （实测 plan = ``SCAN items`` + ``USE TEMP B-TREE``），并列键在临时 B 树里保持
    rowid 序，结果与显式 tie-break 完全相同。
    反例才是陷阱：若把 SELECT 收窄成只取 ``item_id``，plan 变成
    ``SCAN items USING COVERING INDEX items_group_ts``，并列序改由群号决定，
    此时两者才会分道扬镳（实测 ``[9, 3]`` vs ``[3, 9]``）——但那是另一种查询形状，
    不是 ``window_items``。

    所以保留 ``item_id ASC`` 是**纵深防御**：一旦将来 SELECT 收窄到能被
    ``items_group_ts`` 覆盖，或 SQLite 的排序稳定性假设变化，它就是决定性的一行。
    本测试真正守住的，是「排序键是 ``event_ts`` 而不是别的」这一层。
    """
    store.ensure_schema(memdb)
    _insert_items(memdb, [
        (9, "notice", "群 100 的", None, 2000, None, 100, None, None, 0.9),
        (3, "notice", "群 300 的", None, 2000, None, 300, None, None, 0.9),
    ])

    got = store.window_items(memdb, since=0, until=9999)

    assert [it.item_id for it in got] == [3, 9]
    # 契约形式：返回序必须已按 (event_ts, item_id) 排好
    assert got == sorted(got, key=lambda it: (it.event_ts, it.item_id))


def test_window_items_maps_every_field(memdb):
    """逐字段核对 ``WindowItem(*row)`` 的 10 个位置映射。

    ⚠️ 这是本模块**真正会静默错配**的那条路：``kind`` 与 ``group_id`` 是
    ``build_rows`` 锚点（分区与署名群）的来源，``place`` / ``amount`` 直接进渲染。
    原来只断言了 4/10 个字段（item_id/title/deadline_ts/confidence），
    所以把 SELECT 里的 ``place, amount`` 对调、或将来 ``items`` 加列后顺序没对齐，
    测试会全绿，而日报的分区、群名、地点、金额会静默错乱。

    种子的每个字段都取**互不相同**的值，任何两列对调都会撞红。
    """
    store.ensure_schema(memdb)
    _insert_items(memdb, [
        (7, "activity", "讲座", "10月8日前交", 2000, 4000, 200, "报告厅",
         "免费", 0.75),
    ])

    got = store.window_items(memdb, since=0, until=9999)

    assert len(got) == 1
    it = got[0]
    assert it.item_id == 7
    assert it.kind == "activity"
    assert it.title == "讲座"
    assert it.detail == "10月8日前交"
    assert it.event_ts == 2000
    assert it.deadline_ts == 4000
    assert it.group_id == 200
    assert it.place == "报告厅"
    assert it.amount == "免费"
    assert it.confidence == 0.75


def test_save_digest_records_provenance_columns(memdb):
    """``model`` / ``prompt_ver`` / ``created_at`` 必须真的按位写进去。

    ⚠️ 顶到 Global Constraint 11：改了提示词要能说清哪批产出是哪一版。
    原来 ``now=12345`` 传了却**从没断言过**，且三列无一被读回——
    ``model`` 与 ``prompt_ver`` 对调、``created_at`` 写死成 0，全都不会报警，
    溯源能力形同虚设。

    model 与 prompt_ver 取**类型不同、值不相似**的字符串，对调必撞红。
    """
    _seed_items(memdb)

    digest_id = store.save_digest(
        memdb, window_from=1000, window_to=5000, body_md="# 日报",
        model="qwen3.5-test", prompt_ver="digest-v9", item_ids=[1], now=12345,
    )

    row = memdb.execute(
        "SELECT model, prompt_ver, created_at FROM digests WHERE digest_id=?",
        (digest_id,),
    ).fetchone()
    assert row == ("qwen3.5-test", "digest-v9", 12345)


# ── 源消息正文（M2 Task 6：截止日核验）─────────────────────


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


# ── 空窗日的抽取覆盖自证（Task 9，用户验收后追加）──────────────


def test_window_refine_coverage_counts_recorded_messages(memdb):
    _seed_messages(memdb)          # 3 条消息
    store.ensure_schema(memdb)
    store.record_run(memdb, [1, 2], status=store.STATUS_DISCARDED, prompt_ver="v2")

    assert store.window_refine_coverage(memdb, since=1000, until=4000) == (3, 2)


def test_window_refine_coverage_empty_window(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)

    assert store.window_refine_coverage(memdb, since=9000, until=9999) == (0, 0)


def test_window_refine_coverage_ignores_error_rows(memdb):
    """⚠️ ``status='error'`` 不算「已抽取」——与 refine 的重试口径对齐。

    ``pending_messages(redo=False)`` 的语义是「试过但没成功 ≠ 已处理」，那批消息
    下次还会被重新取出来跑。首版只查「有没有 refine_runs 行」，于是「一批失败了」
    会被日报当成「抽取完了、确实没事」——又一个假话入口。

    变异反证：把 `WHERE status != ?` 去掉 → 本条红（(3, 3) 而不是 (3, 2)）。
    """
    _seed_messages(memdb)          # 3 条消息
    store.ensure_schema(memdb)
    store.record_run(memdb, [1, 2], status=store.STATUS_DISCARDED, prompt_ver="v2")
    store.record_run(memdb, [3], status=store.STATUS_ERROR, prompt_ver="v2",
                     err="429")

    assert store.window_refine_coverage(memdb, since=1000, until=4000) == (3, 2)


# ── 全库时间跨度：分清「这天没数据」与「这天没人说话」（Task 11）──────


def test_message_span_returns_min_and_max(memdb):
    _seed_messages(memdb)          # ts = 1000 / 2000 / 3000

    assert store.message_span(memdb) == (1000, 3000)


def test_message_span_none_when_no_messages(memdb):
    _seed_messages(memdb)
    memdb.execute("DELETE FROM messages")

    assert store.message_span(memdb) is None


def test_message_span_ignores_zero_ts_rows(memdb):
    """⚠️ ``ts=0`` 的脏行不许把 ``MIN(ts)`` 拉走（修复轮次 1）。

    真库里有 14 条 1970 的脏数据。它们把 ``MIN(ts)`` 按在 0 时，
    「窗口早于全部数据」那一侧就永远判不出来（``window[1] <= 0`` 为假）——
    于是查一个**根本没数据**的日期，日报会说「这天真的没人说话」。
    """
    _seed_messages(memdb)                      # ts = 1000 / 2000 / 3000
    memdb.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?)", (4, 100, 0, "u_x", "1970 脏行")
    )

    span = store.message_span(memdb)

    assert span == (1000, 3000)                # 不是 (0, 3000)
    assert span[0] != 0


def test_message_span_ignores_negative_ts_rows(memdb):
    """负数 ts 同样不该被当成「最早」——同一类脏数据、同一个过滤器管住。"""
    _seed_messages(memdb)
    memdb.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?)", (4, 100, -1, "u_x", "脏行")
    )

    assert store.message_span(memdb) == (1000, 3000)


def test_message_span_none_when_only_dirty_rows(memdb):
    """全是脏行 = 一条可用数据也没有 → None（说「没数据」而不是「没人说话」）。"""
    _seed_messages(memdb)
    memdb.execute("DELETE FROM messages")
    memdb.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?)", (4, 100, 0, "u_x", "1970 脏行")
    )

    assert store.message_span(memdb) is None


# ── 截止日回填：读哪些 / 清哪些（M3 Task 1）────────────────────


def _insert_item(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    kind: str = "notice",
    title: str | None = None,
    event_ts: int = 1000,
    deadline_ts: int | None = None,
) -> None:
    """造一条最小 item（只为截止日回填用例服务）。

    ⚠️ 本文件既有的插桩是 `_seed_items`（固定三行）与 `_insert_items(conn, rows)`
    （元组列表），**没有** brief 里写的 `_insert_item`。这里按 `_seed_items` 的
    列清单照补一个单行版本——**列名一个不差**，不自己发明形状。

    M3 Task 2 扩展：加了 `kind` / `title` / `event_ts` 三个关键字参数，供搜索用例
    构造不同类目与时间的行。三个默认值与 T1 原版**逐字相同**（`"notice"` /
    `f"条目{item_id}"` / `1000`），所以 T1 既有的三处调用产出的行一个字节都没变。

    顺带立起 messages / sender_names：查询层（`search_items` / `get_item` /
    `digest_items`）LEFT JOIN 后者取署名，而 `store.ensure_schema` 不建它们
    （真库里由 export.py 产出）。不立的话测试会炸 `no such table: sender_names`。
    """
    _ensure_message_tables(conn)
    conn.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, links, amount, confidence, model,"
        " prompt_ver, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (item_id, kind, title if title is not None else f"条目{item_id}", None,
         event_ts, deadline_ts, 100, None, None, "[]", None, 0.9, "m", "v1", 1),
    )
    conn.commit()


def _insert_message(
    conn: sqlite3.Connection,
    msg_id: int,
    *,
    content: str = "",
    ts: int = 1000,
    group_id: int = 100,
    sender_uid: str | None = None,
) -> None:
    """造一条源消息（`source_messages` 的「点回原文」用例服务）。

    形状照 `_seed_messages` 的列清单，只是单行、可指定内容。
    """
    _ensure_message_tables(conn)
    conn.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        (msg_id, group_id, ts, sender_uid, content),
    )
    conn.commit()


def test_items_with_deadline_only_returns_rows_that_have_one():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, deadline_ts=1000)
    _insert_item(conn, 2, deadline_ts=None)
    assert store.items_with_deadline(conn) == [(1, 1000)]


def test_clear_deadlines_only_touches_that_column():
    """两个性质一起守：**只动那一列**，且**只动传入的那些行**。

    ⚠️ 第二个性质是审查退回后补的（Task 1 修复轮次 1）。初版只插了**一条** item，
    于是「把全表 deadline_ts 都置 NULL」（= 完全忽略 `item_ids` 参数）这种实现
    照样全绿——**它守了列，没守行**。这不是假想：`clear_deadlines` 是本里程碑
    唯一一处对真库的不可逆写操作（`vigil deadline-audit --apply` 直接改
    `data/vigil.db`），忽略参数就等于**静默清掉全库的截止日**。
    """
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, deadline_ts=1000)
    _insert_item(conn, 2, deadline_ts=2000)
    # item 1 的 deadline_ts 会变；item 2 **一列都不许变**（除主键外全列快照）
    other_cols = (
        "kind, title, detail, event_ts, group_id, actor_uid, place, links,"
        " amount, confidence, model, prompt_ver, created_at"
    )
    before2 = conn.execute(
        f"SELECT {other_cols} FROM items WHERE item_id = 2"
    ).fetchone()

    assert store.clear_deadlines(conn, [1]) == 1

    assert conn.execute(
        "SELECT deadline_ts FROM items WHERE item_id = 1"
    ).fetchone()[0] is None
    # ⚠️ 关键守卫：item 2 不在传入列表里，它的截止日必须**原样留着**。
    # 变异反证：把 `WHERE item_id IN (...)` 改成恒真，这一行立刻变红。
    assert conn.execute(
        "SELECT deadline_ts FROM items WHERE item_id = 2"
    ).fetchone()[0] == 2000
    assert conn.execute(
        f"SELECT {other_cols} FROM items WHERE item_id = 2"
    ).fetchone() == before2
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2, "不许删行"


def test_clear_deadlines_with_empty_list_is_a_noop():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    assert store.clear_deadlines(conn, []) == 0


# ── FTS5 搜索索引 + 只读查询层（M3 Task 2）──────────────────────


def test_search_finds_two_chinese_chars_via_like_fallback():
    """⭐ 双字词必须搜得到——这是本任务的头号陷阱。

    FTS5 trigram 对**短于 3 字符**的查询静默返回 0 条（不报错），
    而中文双字词（「选课」「讲座」）恰恰是最常见的查询。
    没有 LIKE 兜底的话，「搜不到」会被读成「库里没有」。
    """
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, title="选课通知", kind="academic")
    _insert_item(conn, 2, title="失物招领", kind="lostfound")
    items, total = store.search_items(conn, q="选课")
    assert total == 1 and items[0].item_id == 1


def test_search_finds_three_chinese_chars_via_trigram():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, title="校园卡补办", kind="life")
    items, total = store.search_items(conn, q="校园卡")
    assert total == 1 and items[0].item_id == 1


def test_search_survives_fts5_syntax_characters():
    """用户输入直接喂 MATCH 会抛 OperationalError——必须被包成短语。

    ⚠️ **必须带断言 + 阳性对照**。「调用一下不抛异常」是空守卫：
    搜索整个坏掉（永远返回 0）时，它照样绿。
    """
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, title="选课通知", kind="academic")
    for q in ["NOT", 'a"b', "(", "补退选 -卡", "a OR b"]:
        _, total = store.search_items(conn, q=q)
        assert total == 0, f"{q!r} 应 0 条，实际 {total}"
    # 阳性对照：这些字符**确实能被搜到**——否则上面那组 0 分不清
    # 「搜索坏了」与「确实没有」。
    _insert_item(conn, 2, title="通知（补）", kind="notice")
    _, total = store.search_items(conn, q="（补）")
    assert total == 1


def test_search_escapes_like_wildcards():
    """`%` 不转义就会匹配一切——那是个假数字。"""
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, title="选课通知", kind="academic")
    _, total = store.search_items(conn, q="%")
    assert total == 0


def _seed_two_items_for_search(conn: sqlite3.Connection) -> None:
    """两行，且**第二行让「返回全表」区分得出来**（全表 = 2 ≠ 任何正确答案 1）。"""
    store.ensure_schema(conn)
    _insert_item(conn, 1, title="选课通知", kind="academic")
    _insert_item(conn, 2, title="失物招领", kind="lostfound")


def test_search_strips_nul_before_the_trigram_branch():
    """⚠️ 分支一（`len(q) >= 3` → FTS5）：NUL 会让**引号不闭合**。

    FTS5 解析器在 NUL 处截断，`_fts_phrase` 包出来的短语因此缺右引号
    → 未捕获的 `OperationalError: unterminated string` → T3 上线后就是一个 **500**。

    ⚠️ 阳性对照不是可选项：只断言「NUL 查询不抛异常」的话，
    「搜索整个坏掉、永远返 0」也照样绿。所以紧跟一个**不带 NUL 的同义查询**。
    """
    conn = sqlite3.connect(":memory:")
    _seed_two_items_for_search(conn)

    assert store.search_items(conn, q="\x00选课通知")[1] == 1
    assert store.search_items(conn, q="选\x00课\x00通\x00知")[1] == 1
    # 阳性对照：剥掉 NUL 就是同一个查询，结果必须一致
    assert store.search_items(conn, q="选课通知")[1] == 1
    # 阴性对照：确实没有的词仍旧返回 0（守「不是永远返 1」）
    assert store.search_items(conn, q="\x00不存在的词条")[1] == 0


def test_search_strips_nul_before_the_like_branch():
    """⚠️ 分支二（`len(q) <= 2` → LIKE）：NUL 会让 pattern **截断成 `%`**。

    实测（不净化时，2 行的库里）：`q="\\x00课"` → `total=2`，
    而正确答案是 **1**（只有「选课通知」含「课」）。这比 500 危险得多——
    它是个**假数字**：页面说「共 2 条」，用户以为筛过了，其实一行都没筛。

    ⚠️ 阳性对照同上：每条 NUL 查询都配一条不带 NUL 的同义查询。
    """
    conn = sqlite3.connect(":memory:")
    _seed_two_items_for_search(conn)

    # 正确答案 1；不净化时 LIKE 被截断成 '%' → 2（全表）
    assert store.search_items(conn, q="\x00课")[1] == 1
    assert store.search_items(conn, q="\x00选课")[1] == 1
    # 阳性对照
    assert store.search_items(conn, q="课")[1] == 1
    assert store.search_items(conn, q="选课")[1] == 1

    # ── 剥完为空串 = 不筛选（与既有「空 q 等于不筛选」契约一致）──
    # 这里与 `q=""` 同义、返回全表是**契约**而非 bug：用户没输入任何可搜的字符。
    assert store.search_items(conn, q="\x00\x00")[1] == store.search_items(conn, q="")[1] == 2


def test_search_filters_by_kind_and_window():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, kind="academic", event_ts=100)
    _insert_item(conn, 2, kind="job", event_ts=200)
    assert store.search_items(conn, kind="job")[1] == 1
    assert store.search_items(conn, since=150)[1] == 1
    assert store.search_items(conn, until=150)[1] == 1


def test_search_is_newest_first():
    """信息流按时间倒着看。⚠️ 与 window_items 的 ASC 不同是**故意的**。"""
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, event_ts=100)
    _insert_item(conn, 2, event_ts=200)
    items, _ = store.search_items(conn)
    assert [i.item_id for i in items] == [2, 1]


def test_source_messages_returns_the_linked_messages():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1)
    _insert_message(conn, 11, content="原文在这里")
    conn.execute("INSERT INTO item_sources (item_id, msg_id) VALUES (1, 11)")
    srcs = store.source_messages(conn, 1)
    assert len(srcs) == 1 and srcs[0].content == "原文在这里"


def test_source_messages_of_unknown_item_is_empty():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    # ⚠️ 偏差（逃逸舱）：brief 原版没有这一行。`source_messages` JOIN `messages`，
    # 而 SQLite **在 prepare 阶段**就报 `no such table: messages`——哪怕 WHERE
    # 匹配不到任何行、结果本来就是空。必须先把表立起来，这条守的才是
    # 「未知 item 返回空」而不是「表不存在会炸」。
    _ensure_message_tables(conn)
    assert store.source_messages(conn, 999) == []


def test_digest_items_are_in_ascending_order_like_the_digest_body():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, event_ts=200)
    _insert_item(conn, 2, event_ts=100)
    conn.execute(
        "INSERT INTO digests (digest_id, window_from, window_to, body_md, model,"
        " prompt_ver, created_at) VALUES (1, 100, 300, '正文', 'm', 'v1', 1)"
    )
    conn.execute("INSERT INTO digest_items (digest_id, item_id) VALUES (1, 1), (1, 2)")
    assert [i.item_id for i in store.digest_items(conn, 1)] == [2, 1]


def test_kind_counts_groups_by_kind():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, kind="academic")
    _insert_item(conn, 2, kind="academic")
    _insert_item(conn, 3, kind="job")
    assert store.kind_counts(conn) == {"academic": 2, "job": 1}


# ── 查询层的补充守卫（brief 未覆盖的三个函数）────────────────────
#
# brief 的 10 个测试覆盖了 search_items / source_messages / kind_counts /
# digest_items，但 get_item / list_digests / **get_digest 一个测试都没有**——
# 而 get_digest 的 `DigestRow(*row)` 列序错位正是 brief 自己点名的
# 「本任务最容易犯的错」（SELECT 多加一列就静默错位，不抛任何异常）。
# T3 的 FastAPI 要直接把这几个函数的返回值序列化出去，所以补上最小守卫：
# 用**整个 dataclass 相等**断言，六个字段一个不抽查。


def test_get_item_maps_every_column_or_none():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _ensure_message_tables(conn)
    conn.execute(
        "INSERT INTO sender_names VALUES (?,?,?,?,?,?)",
        (100, "u_a", "张三", "三三", 111, 0),
    )
    conn.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, links, amount, confidence, model,"
        " prompt_ver, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (1, "job", "招兼职", "周末两小时", 1700, 1800, 100, "u_a", "三教",
         '["http://a"]', "200/天", 0.9, "m", "v1", 1),
    )
    _insert_message(conn, 11, content="招兼职，周末两小时")
    conn.execute("INSERT INTO item_sources (item_id, msg_id) VALUES (1, 11)")
    conn.commit()

    assert store.get_item(conn, 1) == store.ApiItem(
        item_id=1, kind="job", title="招兼职", detail="周末两小时", event_ts=1700,
        deadline_ts=1800, group_id=100, actor="张三", place="三教",
        amount="200/天", links=("http://a",), source_count=1,
    )
    assert store.get_item(conn, 999) is None


def test_get_digest_matches_the_row_field_by_field():
    """⚠️ brief 点名的头号实现陷阱：``DigestRow(*row)`` 靠**位置**对齐。

    ``SELECT`` 里多加一列（或用错顺序）不会抛异常，只会让六个字段整体串位——
    正文跑到窗口起点、时间戳跑到条数上，读起来还像正常 JSON。
    所以这里断言**整个 dataclass 相等**，而不是抽查一两个字段。
    变异反证：把 `get_digest` 的 SELECT 里任意两列对调，这条立刻变红。
    """
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    conn.execute(
        "INSERT INTO digests (digest_id, window_from, window_to, body_md, model,"
        " prompt_ver, created_at) VALUES (7, 111, 222, '正文九号', 'm', 'v1', 333)"
    )
    _insert_item(conn, 1)
    _insert_item(conn, 2)
    conn.execute("INSERT INTO digest_items (digest_id, item_id) VALUES (7, 1), (7, 2)")
    conn.commit()

    assert store.get_digest(conn, 7) == store.DigestRow(
        digest_id=7, window_from=111, window_to=222, body_md="正文九号",
        created_at=333, item_count=2,
    )
    assert store.get_digest(conn, 999) is None


def test_search_total_is_independent_of_limit_and_offset():
    """⚠️ 契约（计划 §「契约空洞」，波 1 窄审查定的）：`total` = **符合筛选条件的
    总数**，与 `limit`/`offset` **无关**——不是当页条数。

    前端重度依赖它：`items.length < total` 决定「加载更多」按钮出不出来。
    一旦把 total 实现成 `len(rows)`，按钮要么永远不出现、要么空转永远点不完，
    而且**接口不报错**（数字看着还很像样）。
    """
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    for i in (1, 2, 3):
        _insert_item(conn, i, event_ts=1000 + i)

    page1, total1 = store.search_items(conn, limit=2)
    assert total1 == 3 and [i.item_id for i in page1] == [3, 2]

    page2, total2 = store.search_items(conn, limit=2, offset=2)
    assert total2 == 3 and [i.item_id for i in page2] == [1]


def test_ensure_schema_rebuilds_the_index_for_rows_that_predate_it():
    """⚠️ **存量行**：触发器只管「索引建好之后」的新数据。

    这里模拟一个「索引还不存在」的老库（只建 items、直接塞一行），再跑
    ``ensure_schema``——那一行**不会**经过任何触发器，全靠 ``rebuild`` 捞进索引。
    变异反证：把 ``ensure_schema`` 里的 ``rebuild_search_index(conn)`` 删掉，
    这条立刻变红（而其余 12 个搜索用例**照样全绿**——它们都在 ensure_schema
    之后才插数据，触发器兜住了，这正是本条存在的理由）。
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript(store._ITEMS_DDL)   # 只有 items：索引尚不存在的状态
    _insert_item(conn, 1, title="校园卡补办")

    store.ensure_schema(conn)

    items, total = store.search_items(conn, q="校园卡")
    assert total == 1 and items[0].item_id == 1


def test_list_digests_is_newest_window_first():
    """日报列表按窗口倒序（最近的在前），且带上每条引用了多少条目。"""
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    for did, wf in ((1, 100), (2, 200)):
        conn.execute(
            "INSERT INTO digests (digest_id, window_from, window_to, body_md, model,"
            " prompt_ver, created_at) VALUES (?,?,?,'正文','m','v1',1)",
            (did, wf, wf + 50),
        )
    _insert_item(conn, 1)
    conn.execute("INSERT INTO digest_items (digest_id, item_id) VALUES (2, 1)")
    conn.commit()

    got = store.list_digests(conn)
    assert [d.digest_id for d in got] == [2, 1]
    assert got[0] == store.DigestSummaryRow(
        digest_id=2, window_from=200, window_to=250, created_at=1, item_count=1
    )


# ── M4 T5：写入原子性 ──────────────────────────────────────────────


def _make_item(conn: sqlite3.Connection, *, msg_id: int) -> ExtractedItem:
    """造一条 ExtractedItem，来源挂在 ``msg_id`` 上。

    ⚠️ 偏差（逃逸舱）：brief 里这一行是 ``_make_item(memdb, msg_id=1)``，
    并注明「用本文件既有的构造夹具」——**本文件没有这个夹具**。既有的
    ``_insert_item`` / ``_seed_items`` 都是**直接 SQL 插行**、不返回对象，
    而 ``save_items`` 收的是 ``ExtractedItem``；本文件既有的「造对象」写法是
    **内联构造**（见 ``test_save_items_writes_sources``）。这里只是把同一形状
    收成一个函数，字段清单与那条既有用例逐字对齐。
    """
    _ensure_message_tables(conn)
    return ExtractedItem(
        kind="activity",
        title="西太湖报告厅有讲座",
        detail=None,
        event_ts=1000,
        deadline_ts=None,
        group_id=100,
        actor_uid="u_a",
        place="西太湖报告厅",
        links=(),
        amount=None,
        confidence=0.9,
        src_msg_ids=(msg_id,),
    )


def test_transaction_rolls_back_on_exception(memdb):
    """事务里抛异常 → 之前的写全部不见。"""
    store.ensure_schema(memdb)
    item = _make_item(memdb, msg_id=1)          # 用本文件既有的构造夹具

    with pytest.raises(RuntimeError):
        with store.transaction(memdb):
            store.save_items(memdb, [item], model="m", prompt_ver="v1", commit=False)
            raise RuntimeError("模拟崩在两步之间")

    assert memdb.execute("SELECT count(*) FROM items").fetchone()[0] == 0
    assert memdb.execute("SELECT count(*) FROM item_sources").fetchone()[0] == 0


def test_transaction_commits_on_success(memdb):
    store.ensure_schema(memdb)
    item = _make_item(memdb, msg_id=1)
    with store.transaction(memdb):
        store.save_items(memdb, [item], model="m", prompt_ver="v1", commit=False)
        store.record_run(memdb, [1], status=store.STATUS_OK,
                         prompt_ver="v1", commit=False)
    assert memdb.execute("SELECT count(*) FROM items").fetchone()[0] == 1
    assert memdb.execute("SELECT count(*) FROM refine_runs").fetchone()[0] == 1


class _InsertIntoDigestsFails(sqlite3.Connection):
    """写日报时让 ``INSERT INTO digests`` 抛 sqlite3.OperationalError。

    ⚠️ 偏差（逃逸舱）：brief 原版注入的是 ``memdb.execute = boom``——**做不到**，
    实测 ``AttributeError: 'sqlite3.Connection' object attribute 'execute' is
    read-only``（C 类型的实例属性只读，Python 3.13 / 本机实测）。
    改成**子类覆盖**：``factory=`` 让连接自带这个行为。注入点与 brief 想注入的
    位置完全一致（三步里的第三步 ``INSERT INTO digests``），抛的也仍是 brief
    指定的 ``sqlite3.OperationalError``（对照组：用触发器 ``RAISE(ABORT)`` 注入
    抛的是 ``IntegrityError``，与 brief 写死的异常类型对不上）。
    """

    fail_insert = False

    def execute(self, sql, *args):  # type: ignore[override]
        if self.fail_insert and sql.strip().startswith("INSERT INTO digests"):
            raise sqlite3.OperationalError("模拟写库失败")
        return super().execute(sql, *args)


def test_save_digest_is_atomic():
    """⭐ DELETE 与 INSERT 之间崩掉，**旧日报必须还在**。

    `save_digest` 是 先删 digest_items、再删 digests、最后 INSERT。
    三步不在一个事务里的话，崩在中间会让**当天日报凭空消失**——
    而 docs/digests/ 的文件还在，归档不变量（文件集合 == 窗口日期集合）
    当场破掉，且没有任何东西会报错。

    ⚠️ 这条不用 ``memdb`` 夹具：注入点需要 ``factory=`` 的子类连接
    （见 ``_InsertIntoDigestsFails`` 的说明），``memdb`` 给的是普通连接。
    连接本身仍是 ``sqlite3.connect(":memory:")``——与夹具同一个形状。
    """
    conn = sqlite3.connect(":memory:", factory=_InsertIntoDigestsFails)
    store.ensure_schema(conn)
    first = store.save_digest(conn, window_from=10, window_to=20,
                              body_md="第一版", model="m", prompt_ver="v1",
                              item_ids=[])
    assert conn.execute("SELECT count(*) FROM digests").fetchone()[0] == 1

    conn.fail_insert = True
    try:
        with pytest.raises(sqlite3.OperationalError):
            store.save_digest(conn, window_from=10, window_to=20,
                              body_md="第二版", model="m", prompt_ver="v1",
                              item_ids=[])
    finally:
        conn.fail_insert = False

    rows = conn.execute("SELECT digest_id, body_md FROM digests").fetchall()
    assert rows == [(first, "第一版")], "崩在 INSERT 时旧日报必须原样还在"
