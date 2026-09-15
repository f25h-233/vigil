"""API 契约测试。

⚠️ 这里测的是**契约形状与边界**，不是「能不能跑通」：
每个字段名、每个状态码都是前端 `web/src/types.ts` 依赖的东西，
改名不会有任何编译错误，只会让页面静默少一栏或整页空掉。
"""

from __future__ import annotations

import datetime as dt
import pathlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from vigil import store
from vigil.api import create_app
from vigil.config import Config, Group

# `messages` / `sender_names` 由导出层（vigil/export.py）建，`store.ensure_schema`
# 不管这两张表。形状与 export.py 的 `_MESSAGE_TABLE_DDL` / `_SENDER_TABLE_DDL`
# 和 `tests/test_store.py::_MESSAGE_TABLES_DDL` 一致——造真库里本来就有的表，
# 不是放宽断言。
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


def _config_for(db: pathlib.Path) -> Config:
    """按 `config.Config` 的真实字段拼一个**只指向临时库**的配置。

    不读 config/groups.toml——真实配置里的群号/路径与本测试无关，
    读了只会让测试依赖仓库当前状态（那是「假红」的常见来源）。
    """
    return Config(
        qq_db_dir=db.parent,
        output_db=db,
        groups=(Group(id=12345, name="测试群"),),
    )


@pytest.fixture()
def db_path(tmp_path) -> pathlib.Path:
    """临时库：一条 9/13 的条目 + 它的源消息。**不碰真库**。"""
    db = tmp_path / "vigil.db"
    conn = sqlite3.connect(str(db))
    store.ensure_schema(conn)
    conn.executescript(_MESSAGE_TABLES_DDL)
    ts = int(dt.datetime(2026, 9, 13, 12, 0).timestamp())
    conn.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, amount, links, confidence, model, prompt_ver,"
        " created_at) VALUES (1, 'academic', '选课通知', '9月16日截止', ?, NULL,"
        " 12345, 'u1', NULL, NULL, '[\"https://x.test/a\"]', 0.9, 'm', 'v1', 1)",
        (ts,),
    )
    conn.execute(
        "INSERT INTO messages (msg_id, group_id, ts, sender_uid, content)"
        " VALUES (11, 12345, ?, 'u1', '原文在这里')",
        (ts,),
    )
    conn.execute("INSERT INTO item_sources (item_id, msg_id) VALUES (1, 11)")
    conn.commit()
    conn.close()
    return db


@pytest.fixture()
def client(db_path):
    """跑在临时库上的 TestClient（配置也指向临时库）。"""
    return TestClient(create_app(_config_for(db_path)))


def test_items_returns_the_frozen_field_set(client):
    body = client.get("/api/items").json()
    assert {"items", "total", "limit", "offset"} == set(body)
    item = body["items"][0]
    assert {
        "item_id", "kind", "kind_label", "kind_icon", "title", "detail", "event_ts",
        "deadline_ts", "group_id", "group_name", "actor", "place", "amount",
        "links", "source_count",
    } == set(item)
    assert item["links"] == ["https://x.test/a"]      # links 是数组，不是 JSON 字符串
    assert item["kind_label"] == "学业"                # 类目名解析出来了
    assert item["source_count"] == 1


def test_item_detail_includes_source_messages(client):
    body = client.get("/api/items/1").json()
    assert body["sources"][0]["content"] == "原文在这里"
    assert {"msg_id", "ts", "sender", "group_name", "content"} == set(body["sources"][0])


def test_total_is_the_filter_count_not_the_page_size(client, db_path):
    """⚠️ `total` = 符合筛选条件的**总数**，与 limit/offset 无关（不是当页条数）。

    前端三处依赖它：《共 N 条》《还有 N 条》与分页按钮出不出。哪天有人
    「顺手」把它改成 `len(items)`，页面不会有任何报错，只会永远说「共 1 条」
    并且翻不到第 2 页——这正是本项目最忌的那类假数字。
    """
    con = sqlite3.connect(str(db_path))
    con.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, amount, links, confidence, model, prompt_ver,"
        " created_at) VALUES (2, 'notice', '更早的一条', NULL,"
        " (SELECT event_ts - 3600 FROM items WHERE item_id = 1), NULL,"
        " 12345, NULL, NULL, NULL, '[]', 0.9, 'm', 'v1', 1)"
    )
    con.commit()
    con.close()

    body = client.get("/api/items", params={"limit": 1}).json()
    assert len(body["items"]) == 1 and body["total"] == 2       # 当页 1 条，总共 2 条
    page2 = client.get("/api/items", params={"limit": 1, "offset": 1}).json()
    assert len(page2["items"]) == 1 and page2["total"] == 2     # 翻页不改总数
    assert page2["items"][0]["item_id"] == 2                    # 时间倒序：新的在前


def test_no_signature_shapes_differ_between_item_and_source(client):
    """⚠️ 两处「没署名」的形状**故意不同**，不许「统一」。

    源文 `sender` 是 `""`（str），条目 `actor` 是 `None`（str | None）——
    前端 types.ts 正是 `sender: string` / `actor: string | null`。统一成一样
    不会有任何编译错误，只会让前端某一栏静默空掉或显示成 "None"。
    """
    assert client.get("/api/items").json()["items"][0]["actor"] is None
    assert client.get("/api/items/1").json()["sources"][0]["sender"] == ""


def test_missing_item_is_404_with_detail(client):
    r = client.get("/api/items/999999")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_api_typo_is_404_not_the_spa_page(client):
    """⭐ `/api/*` 绝不能被 SPA 兜底接走。

    否则 `GET /api/typo` 返回 **200 的 HTML**，前端 `r.json()` 直接炸，
    而真正的 404 被吞掉——排查时会往完全错误的方向找。
    """
    r = client.get("/api/typo")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_categories_carry_counts(client):
    cats = client.get("/api/categories").json()["categories"]
    assert len(cats) == 7
    assert {"slug", "label", "icon", "count"} == set(cats[0])
    assert [c["slug"] for c in cats][0] == "notice"     # 顺序 = config 里的顺序


def test_since_and_until_include_the_named_days(client):
    """⚠️ `until` 必须**包含**该日，否则选了 9/13 搜不到 9/13。"""
    assert client.get("/api/items", params={"since": "2026-09-13"}).json()["total"] == 1
    assert client.get("/api/items", params={"until": "2026-09-13"}).json()["total"] == 1
    assert client.get("/api/items", params={"until": "2026-09-12"}).json()["total"] == 0


def test_bad_date_is_400_not_500(client):
    r = client.get("/api/items", params={"since": "不是日期"})
    assert r.status_code == 400 and "detail" in r.json()


def test_limit_over_max_is_422(client):
    assert client.get("/api/items", params={"limit": 99999}).status_code == 422


def test_spa_returns_503_when_frontend_not_built(client, tmp_path, monkeypatch):
    """前端没构建时不许返回空白页——要明说「去跑 npm run build」。"""
    import vigil.api as api

    monkeypatch.setattr(api, "WEB_DIST", tmp_path / "nope")
    r = client.get("/")
    assert r.status_code == 503
    assert "npm run build" in r.text


def test_static_file_is_served_as_a_file_not_the_spa_page(client, tmp_path, monkeypatch):
    """⭐ PWA 的 sw.js / manifest 必须发**真文件**。

    实测踩到过：`app.mount("/assets", ...)` 只覆盖 /assets 前缀，而
    sw.js / manifest.webmanifest / 图标都在根路径 → 全被 SPA 兜底接走，
    返回 200 的 index.html。浏览器把 HTML 当 manifest 解析、当 SW 注册，
    「添加到主屏」整条路走不通，**而所有状态码都是 200**。
    """
    import vigil.api as api

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>VIGIL 守夜人</title>", encoding="utf-8")
    (dist / "sw.js").write_text("self.define = 1", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.text == "self.define = 1"                  # 不是 index.html
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 404                          # 真没有就 404，不许拿 index.html 顶
    assert client.get("/some/route").text.startswith("<title>VIGIL")   # SPA 兜底仍工作


def test_path_traversal_is_blocked(client, tmp_path, monkeypatch):
    """⚠️ 逃逸测试**必须断言正文**——只看状态码会得到 200，测试是空的。

    规划期实测：只看状态码时，逃逸请求返回 200（其实是 index.html），
    看不出有没有泄露。所以这里断言正文**不含**密钥字样。
    """
    import vigil.api as api

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>VIGIL 守夜人</title>", encoding="utf-8")
    (tmp_path / ".env").write_text("VIGIL_DB_KEY=0123456789abcdef", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    for path in ["/..%2f.env", "/..%2f..%2f.env", "/%2e%2e/%2e%2e/.env"]:
        r = client.get(path)
        assert "VIGIL_DB_KEY" not in r.text, f"{path} 泄露了密钥！"


def test_traversal_test_has_detection_power(client, tmp_path, monkeypatch):
    """阳性对照：把 .env 放进 dist 再请求，**测试必须能抓到**。

    没有这条，「不泄露」可能只是因为**测试根本读不到东西**。
    """
    import vigil.api as api

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>x</title>", encoding="utf-8")
    (dist / ".env").write_text("VIGIL_DB_KEY=0123456789abcdef", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    assert "VIGIL_DB_KEY" in client.get("/.env").text    # 能读到 → 上一条不是空的
