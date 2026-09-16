"""⭐ overlay 端到端验收：**一条人工干预，两处消费方都生效**（M5 出口判据 6 的机械守卫）。

为什么这个文件必须存在（T5 审查的结论）：出口判据 6 原先只挂在 Task 8 Step 10 的
**手工**「浏览器逐条验」上——**手工不构成机械守卫**；而变异实测（W1b / W3）说明
**日报侧的语义继承当时没有任何自动测试**（6 条 overlay 测试全在 `test_store.py`）。

本文件钉三件事，**全部走产品自己的入口**（不在 store 层打桩）：
① Web：`/api/items`、`/api/items/{id}`、kind 筛选、`/api/categories` 角标按**覆盖后**的值；
② 日报：被软删的条目不进正文、被改过类目的条目按**新**类目分桶
   （`digest.digest(db_path=…)`——正是 R4 补了 `uri=True` 的那条连接）；
③ **阴性对照**：把 `OVERRIDES_DB` 指到空库，同一天**照旧**进日报——否则 ② 证明不了因果。

⚠️ 用**真库文件**而不是内存库：`create_app` 只认 db 路径（它自己开 `mode=ro` 连接），
而「两处都验」的意义就在于两个**独立进程内入口**各自开连接、各自挂 overlay。
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from vigil import digest, overrides, store
from vigil.api import create_app
from vigil.config import Config, Group

GID = 12345

# ⚠️ `messages` / `sender_names` 由导出层（`vigil/export.py`）建，`store.ensure_schema`
# 不管这两张表。形状与 `export.py` 的 DDL、`tests/test_store.py::_MESSAGE_TABLES_DDL`
# 一致——造真库里本来就有的表，不是放宽断言。
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

# 两条时间线：09-13 有两条（改类目的 + 不动的），09-14 **只有**将被软删的那条。
# ⇒ 软删之后 09-14 变成「空窗日」：不调模型、正文直接算得出来（对照才有意义）。
_D13 = int(dt.datetime(2026, 9, 13, 12, 0).timestamp())
_D14 = int(dt.datetime(2026, 9, 14, 12, 0).timestamp())

_ITEMS = (
    # (item_id, kind, title, event_ts)
    (1, "notice", "办卡广告（要被删掉）", _D14),
    (2, "notice", "选课通知（要改成 academic）", _D13),
    (3, "lostfound", "失物招领（不动）", _D13),
)


class _StubLLM:
    """假 LLM：记录调用次数、返回预设载荷。**绝不联网**。"""

    def __init__(self, lines):
        self.lines = lines
        self.calls = 0

    def __call__(self, cfg, *, system, user, sleep=None):
        from vigil.llm import LLMResult

        self.calls += 1
        return LLMResult(payload={"lines": self.lines}, input_tokens=1, output_tokens=1)


def _window(day: int, month: int) -> tuple[int, int]:
    a = int(dt.datetime(2026, month, day).timestamp())
    b = int(dt.datetime(2026, month, day + 1).timestamp())
    return a, b


@pytest.fixture
def scene(tmp_path):
    """一个**真库文件** + 一张最小 messages/sender_names（不碰 `data/vigil.db`）。

    ⚠️ `store.ensure_schema` 会顺带把 overlay 库建到 conftest 那条 autouse 夹具
    挪过的默认路径上——所以这里不需要、也**不应该**自己去碰真实的 `data/overrides.db`。
    """
    db = tmp_path / "vigil.db"
    conn = sqlite3.connect(str(db))
    try:
        store.ensure_schema(conn)
        conn.executescript(_MESSAGE_TABLES_DDL)
        conn.execute(
            "INSERT INTO sender_names VALUES (?,?,?,?,?,?)",
            (GID, "u1", "张三", "三三", 111, 0),
        )
        for item_id, kind, title, ts in _ITEMS:
            conn.execute(
                "INSERT INTO items (item_id, kind, title, detail, event_ts,"
                " deadline_ts, group_id, actor_uid, place, amount, links, confidence,"
                " model, prompt_ver, created_at)"
                " VALUES (?,?,?,NULL,?,NULL,?,'u1',NULL,NULL,'[]',0.9,'m','v1',1)",
                (item_id, kind, title, ts, GID),
            )
            conn.execute(
                "INSERT INTO messages (msg_id, group_id, ts, sender_uid, content)"
                " VALUES (?,?,?,'u1',?)",
                (100 + item_id, GID, ts, title),
            )
            conn.execute(
                "INSERT INTO item_sources (item_id, msg_id) VALUES (?,?)",
                (item_id, 100 + item_id),
            )
            # 覆盖率记账：空窗日靠它区分「没有值得一提的信息」与「还没抽取」
            conn.execute(
                "INSERT INTO refine_runs (msg_id, refined_at, status, item_count,"
                " prompt_ver, err) VALUES (?,?,'ok',1,'v3',NULL)",
                (100 + item_id, ts),
            )
        conn.commit()
    finally:
        conn.close()

    cfg = Config(qq_db_dir=tmp_path, output_db=db, groups=(Group(id=GID, name="测试群"),))
    return SimpleNamespace(db=db, cfg=cfg, out_dir=tmp_path)


def _apply_interventions() -> None:
    """走**真实写路径**落两条干预：删 item 1、把 item 2 改成 academic。"""
    overrides.ensure_schema()      # autouse 夹具已把 OVERRIDES_DB 挪到 tmp
    w = overrides.connect()
    try:
        overrides.delete_item(w, item_id=1, msg_id=101)
        overrides.set_kind(w, item_id=2, kind="academic")
    finally:
        w.close()


# ── ① Web 侧 ──────────────────────────────────────────────────────────


def test_overlay_applies_to_every_web_reading_path(scene):
    """Web 的**四条**读路径都要按覆盖后的值：列表 / 单条 / 筛选 / 类目角标。

    这四条分别落在 `search_items`（含它的 COUNT）、`get_item`、`_item_filters`、
    `kind_counts` 上——即 spec §3.3 那张表里 Web 侧的全部入口。
    """
    _apply_interventions()
    client = TestClient(create_app(scene.cfg))

    # ① 列表：被删的条目消失（**含 total**——否则分页与「共 N 条」会说谎）
    r = client.get("/api/items")
    assert r.status_code == 200
    payload = r.json()
    assert payload["total"] == 2, "被软删的条目必须从列表与 total 里一起消失"
    got = {i["item_id"]: i["kind"] for i in payload["items"]}
    assert 1 not in got, "被软删的条目还在列表里"
    # ② 改过类目的条目显示**新**类目
    assert got[2] == "academic", "改过分类的条目必须显示新类目"

    # ③ 单条：软删 ⇒ 404（不是 200 + 旧数据）
    assert client.get("/api/items/1").status_code == 404

    # ④ 筛选：按**覆盖后**的类目筛（改了分类却筛不出来 = 用户看不见自己的修改）
    assert client.get("/api/items", params={"kind": "academic"}).json()["total"] == 1
    assert client.get("/api/items", params={"kind": "notice"}).json()["total"] == 0

    # ⑤ 类目角标（`kind_counts`）：计数与列表同源
    counts = {
        c["slug"]: c["count"]
        for c in client.get("/api/categories").json()["categories"]
    }
    assert (counts["academic"], counts["notice"], counts["lostfound"]) == (1, 0, 1)


# ── ② 日报侧（+ ③ 阴性对照）────────────────────────────────────────────


def test_overlay_drives_the_daily_digest(scene, monkeypatch):
    """软删之后，那天在日报里**真的**变成「没有值得一提的信息」——且不调模型。

    ⚠️ 这条是 R13 在日报侧的机械守卫：`digest.py` 不直接读 `items`，它走
    `store.window_items`；本用例从 `db_path` 进（**不是**传内存 conn），
    所以它同时覆盖了 R4 给 `digest.py` 补的 `uri=True`。
    """
    fake = _StubLLM([{"quotes": ["办卡广告"], "label": "办卡", "text": "速办"}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)
    _apply_interventions()

    since, until = _window(14, 9)
    stats = digest.digest(
        scene.cfg, api_key="k", db_path=scene.db, since=since, until=until,
        day_label="2026-09-14", output_dir=scene.out_dir,
    )

    assert stats.items == 0, "软删的条目不许进日报"
    assert fake.calls == 0, "窗口里没有可见条目 ⇒ 不该调模型（空窗日不花钱）"
    body = (scene.out_dir / "2026-09-14.md").read_text(encoding="utf-8")
    assert "办卡广告" not in body, "「界面上删了、日报里还在」= R13"
    assert "没有值得一提的信息" in body


def test_daily_digest_control_without_the_overlay(scene, monkeypatch, tmp_path):
    """**阴性对照**：干预层是空的时候，**同一天照旧进日报**。

    没有这条对照，上面那条「日报里没有它」证明不了**因果**——它也可能只是
    因为窗口/筛选写错了。⚠️ 这里的空 overlay 用的是**从不存在的路径**，
    顺带覆盖「读取路径自己把 overlay 库就位」（brief Step 3 / T4 的 F5 形态）。
    """
    fake = _StubLLM([{"quotes": ["办卡广告"], "label": "办卡", "text": "速办"}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)
    empty = tmp_path / "never_written" / "overrides.db"
    assert not empty.exists()
    monkeypatch.setattr(overrides, "OVERRIDES_DB", empty)

    since, until = _window(14, 9)
    stats = digest.digest(
        scene.cfg, api_key="k", db_path=scene.db, since=since, until=until,
        day_label="2026-09-14", output_dir=scene.out_dir,
    )

    assert stats.items == 1, "没有干预时它必须照旧进日报（否则上面那条不算数）"
    assert fake.calls == 1
    body = (scene.out_dir / "2026-09-14.md").read_text(encoding="utf-8")
    assert "办卡" in body
    assert empty.is_file(), "读取路径应当把缺失的 overlay 库就位"


# ── ④ T8 的写端点：干预的**第三个入口**（HTTP），两个消费方都要同效 ──────


def test_http_write_endpoints_drive_both_consumers(scene, monkeypatch):
    """⭐ 在 Web 上删/改（走 T8 的 HTTP 端点），日报侧必须**同效**。

    与 ①② 的分工：那两条把干预**直接写进 overlay**（`overrides.delete_item(...)`），
    这条走**产品自己的 HTTP 端点**。没有这条，「端点的写入落到了哪条连接、哪个库」
    就没人验过——`create_app` 里的 `overrides.ensure_schema()` 与端点里的
    `overrides.connect()` **各自读一次** `OVERRIDES_DB` 全局，任何一处被冻进闭包
    （或写死成真实 `data/` 路径），Web 侧自己的测试**照样全绿**，
    而日报（另一条连接）什么都看不到。

    ⚠️ 走 `db_path` 进 `digest.digest`（不是传内存 conn）：这是另一个进程内入口、
    自己开连接、自己 ATTACH overlay（R4 补的 `uri=True`）。
    """
    fake = _StubLLM([{"quotes": ["办卡广告"], "label": "办卡", "text": "速办"}])
    monkeypatch.setattr("vigil.digest.chat_json", fake)
    client = TestClient(create_app(scene.cfg))

    # ① 用**端点**落两条干预：删 item 1（09-14 那天唯一一条）、把 item 2 改成 academic
    assert client.delete("/api/items/1").status_code == 200
    assert client.post(
        "/api/items/2/kind", json={"kind": "academic"}
    ).status_code == 200

    # ② Web 侧：与端点写的一致
    payload = client.get("/api/items").json()
    assert payload["total"] == 2
    assert {i["item_id"] for i in payload["items"]} == {2, 3}
    assert client.get("/api/items", params={"kind": "academic"}).json()["total"] == 1

    # ③ 日报侧：09-14 变成空窗、**不调模型**
    since, until = _window(14, 9)
    stats = digest.digest(
        scene.cfg, api_key="k", db_path=scene.db, since=since, until=until,
        day_label="2026-09-14", output_dir=scene.out_dir,
    )
    assert stats.items == 0, "HTTP 端点删掉的条目不许进日报（R13）"
    assert fake.calls == 0, "窗口里没有可见条目 ⇒ 不该调模型"
    body = (scene.out_dir / "2026-09-14.md").read_text(encoding="utf-8")
    assert "办卡广告" not in body

    # ④ 改分类那条：日报的**读取路径**（`window_items`）看到的是**新**类目
    con = sqlite3.connect(f"file:{scene.db.as_posix()}?mode=ro", uri=True)
    try:
        got = {
            w.item_id: w.kind
            for w in store.window_items(con, since=_D13, until=_D13 + 3600)
        }
    finally:
        con.close()
    assert got.get(2) == "academic", "HTTP 端点改的类目没进日报的读取路径"
    assert 1 not in got, "被端点软删的条目还在日报的读取路径里"
