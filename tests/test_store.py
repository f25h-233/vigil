"""持久化层的测试。全部用内存库，不碰 data/vigil.db。"""

from __future__ import annotations

import sqlite3

import pytest

from vigil import store
from vigil.store import ExtractedItem, PendingMessage


def _seed_messages(conn: sqlite3.Connection) -> None:
    """造一张最小的 messages + sender_names，形状与 export.py 产出的完全一致。"""
    conn.executescript(
        """
        CREATE TABLE messages (
            msg_id     INTEGER PRIMARY KEY,
            group_id   INTEGER NOT NULL,
            ts         INTEGER NOT NULL,
            sender_uid TEXT,
            content    TEXT NOT NULL
        );
        CREATE TABLE sender_names (
            group_id   INTEGER NOT NULL,
            uid        TEXT    NOT NULL,
            group_nick TEXT,
            qq_nick    TEXT,
            uin        INTEGER,
            in_group   INTEGER,
            PRIMARY KEY (group_id, uid)
        );
        """
    )
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
