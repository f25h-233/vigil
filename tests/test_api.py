"""API 契约测试。

⚠️ 这里测的是**契约形状与边界**，不是「能不能跑通」：
每个字段名、每个状态码都是前端 `web/src/types.ts` 依赖的东西，
改名不会有任何编译错误，只会让页面静默少一栏或整页空掉。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import pathlib
import re
import sqlite3
import threading
import time

import pytest
from fastapi.testclient import TestClient

# ⚠️ 模块级别名（`_cats_mod`）：`_groups_root` 要在**造 app 之前**把它指向假根下那份
# （Fix loop 3 / FIX 3），而夹具是模块级函数、拿不到函数内的局部 import。
from vigil import categories as _cats_mod
from vigil import groups_snapshot, store
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
        "deadline_ts", "group_id", "group_name", "actor", "actor_uin", "place", "amount",
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


def test_bare_api_is_404_not_the_spa_page(client, tmp_path, monkeypatch):
    """⭐ 裸 `/api`（无尾斜杠）也必须 404。

    守卫原先只写了 `startswith("api/")`，而 `full_path == "api"` 不满足它
    → 一路走到 SPA 兜底 → **200 的 HTML**：调用方 `r.json()` 直接炸，
    而真正的 404 被吞掉（与上面 `/api/typo` 同一种病，只差一个斜杠）。

    ⚠️ 断言**正文**而不只是状态码：本项目实测过「只看状态码的测试是空的」
    ——兜底那一路返回的正是 200 的 index.html。这里把真 dist 摆上，
    兜底确实能工作（见下一条阳性对照），所以 404 只可能来自那个守卫。
    """
    import vigil.api as api

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>VIGIL 守夜人</title>", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    for path in ["/api", "/api/"]:
        r = client.get(path)
        assert r.status_code == 404, path
        assert "VIGIL 守夜人" not in r.text, f"{path} 被 SPA 兜底接走了"
        assert r.headers["content-type"].startswith("application/json"), path
        assert "detail" in r.json(), path


def test_spa_fallback_still_serves_frontend_routes(client, tmp_path, monkeypatch):
    """阳性对照：无后缀的前端路由仍由 SPA 兜底发 index.html。

    没有这条，「`/api` 是 404」可能只是因为**兜底整个坏掉了**——
    那是把要修的东西连同兜底一起关掉的假绿。
    """
    import vigil.api as api

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>VIGIL 守夜人</title>", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    r = client.get("/feed")
    assert r.status_code == 200
    assert r.text.startswith("<title>VIGIL 守夜人</title>")


def test_categories_carry_counts(client):
    cats = client.get("/api/categories").json()["categories"]
    assert len(cats) == 7
    # ⚠️ M6 T5 起 `desc` 也在响应里（编辑器要拿它回填输入框）。
    # 这条字段集合是**冻结契约**：少一个键，前端的输入框会静默空掉。
    assert {"slug", "label", "icon", "desc", "count"} == set(cats[0])
    assert [c["slug"] for c in cats][0] == "notice"     # 顺序 = config 里的顺序


# ── 日报两个端点（字段被 types.ts 冻结，Digests.tsx 直接消费）──────────
#
# ⚠️ 本文件此前对 digest **零断言**（不是"断言少"，是完全没有）。每个任务
# 「自己那部分绿了」，而冻结契约的覆盖面从来没人整体核对过——这正是缺口能
# 活到终审的结构性原因。下面几条按 `web/src/types.ts` 的 DigestSummary /
# DigestDetail 逐字段核，**不照 api.py 的实现猜**。

# types.ts 的 `Item`——日报详情里的 items 与 /api/items 是同一形状
_ITEM_FIELDS = {
    "item_id", "kind", "kind_label", "kind_icon", "title", "detail", "event_ts",
    "deadline_ts", "group_id", "group_name", "actor", "actor_uin", "place", "amount",
    "links", "source_count",
}
# types.ts 的 `DigestSummary`
_DIGEST_SUMMARY_FIELDS = {
    "digest_id", "day", "window_from", "window_to", "created_at", "item_count",
}

# 窗口起点取**本地** 9/13 00:00，与 api._day_start 同口径——`day` 的推导正是
# 要按本地日算，随手挑一个时间戳就测不到这件事（见 test_digest_day_is_local_day）。
_DIGEST_FROM = int(dt.datetime(2026, 9, 13, 0, 0).timestamp())


def _seed_digest(db: pathlib.Path, *, digest_id: int = 1) -> None:
    """往临时库塞一篇日报 + 它引用的 item 1（db_path fixture 已经建好表）。"""
    con = sqlite3.connect(str(db))
    con.execute(
        "INSERT INTO digests (digest_id, window_from, window_to, body_md, model,"
        " prompt_ver, created_at) VALUES (?,?,?,?,?,?,?)",
        (
            digest_id, _DIGEST_FROM, _DIGEST_FROM + 86400,
            "# 守夜人日报 · 2026-09-13\n\n正文一段。", "m", "v1", 1,
        ),
    )
    con.execute(
        "INSERT INTO digest_items (digest_id, item_id) VALUES (?,?)", (digest_id, 1)
    )
    con.commit()
    con.close()


def test_digests_list_carries_the_frozen_field_set(client, db_path):
    """`/api/digests` 是**有外壳的**：`{digests: [...]}`（api.ts fetchDigests 也这么解）。"""
    _seed_digest(db_path)
    body = client.get("/api/digests").json()
    assert set(body) == {"digests"}
    rows = body["digests"]
    assert isinstance(rows, list) and len(rows) == 1
    d = rows[0]
    assert set(d) == _DIGEST_SUMMARY_FIELDS          # 与 types.ts 逐字对应
    assert isinstance(d["digest_id"], int)
    assert isinstance(d["day"], str)
    assert isinstance(d["window_from"], int)
    assert isinstance(d["window_to"], int)
    assert isinstance(d["created_at"], int)
    assert isinstance(d["item_count"], int)
    assert d["item_count"] == 1                      # 列表项下面那行「N 条条目」


def test_digest_detail_carries_body_and_linked_items(client, db_path):
    _seed_digest(db_path)
    body = client.get("/api/digests/1").json()
    assert set(body) == _DIGEST_SUMMARY_FIELDS | {"body_md", "items"}
    assert isinstance(body["body_md"], str) and body["body_md"].startswith("# 守夜人日报")
    items = body["items"]
    assert isinstance(items, list) and len(items) == 1
    assert set(items[0]) == _ITEM_FIELDS             # 关联条目与 /api/items 同形状
    assert items[0]["item_id"] == 1                  # 就是日报引用的那一条


def test_digest_day_is_the_local_day(client, db_path):
    """⚠️ `day` 是**时区敏感**推导，而 Digests.tsx 拿它当整页唯一标题。

    本项目已两次栽在 UTC/本地 8 小时差上（api.py:41-42 的注释记着这件事），
    所以期望值**用 stdlib 独立算**——**不许调 `api._day_of`**：拿被测实现去
    验证被测实现是空守卫，换成 UTC 口径照样绿。
    """
    _seed_digest(db_path)
    expect = dt.datetime.fromtimestamp(_DIGEST_FROM).strftime("%Y-%m-%d")
    assert client.get("/api/digests").json()["digests"][0]["day"] == expect
    assert client.get("/api/digests/1").json()["day"] == expect
    # 本机时区是 UTC+08:00：本地 9/13 00:00 在 UTC 口径下是 09-12，所以这句
    # 对「换成 UTC 口径」有**真实区分力**（实测：把 _day_of 换成 UTC 版本，
    # 上面两句变红）。若在 UTC+00:00 的机器上跑，两个口径同串、这里就没有
    # 区分力——那种环境下它证明不了本地/UTC 之别，别把它当成证明。
    utc_day = dt.datetime.fromtimestamp(_DIGEST_FROM, dt.timezone.utc).strftime("%Y-%m-%d")
    if utc_day != expect:
        assert client.get("/api/digests/1").json()["day"] != utc_day


def test_missing_digest_is_404_json(client, tmp_path, monkeypatch):
    """不存在的日报 → 404 的 JSON，不是 200 的 HTML（同 /api/typo 那一类）。"""
    import vigil.api as api

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>VIGIL 守夜人</title>", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    r = client.get("/api/digests/999999")
    assert r.status_code == 404
    assert "VIGIL 守夜人" not in r.text
    assert r.headers["content-type"].startswith("application/json")
    assert "detail" in r.json()


def test_since_and_until_include_the_named_days(client):
    """⚠️ `until` 必须**包含**该日，否则选了 9/13 搜不到 9/13。"""
    assert client.get("/api/items", params={"since": "2026-09-13"}).json()["total"] == 1
    assert client.get("/api/items", params={"until": "2026-09-13"}).json()["total"] == 1
    assert client.get("/api/items", params={"until": "2026-09-12"}).json()["total"] == 0


def test_bad_date_is_400_not_500(client):
    r = client.get("/api/items", params={"since": "不是日期"})
    assert r.status_code == 400 and "detail" in r.json()


# ── 坏输入的第二种形状：日期合法，但落不到可表示的 epoch 秒上 ──────────
#
# ⚠️ 「能解析成日期」与「能表示成时间戳」不是同一件事。下面四条一起才完整：
# 前两条钉住两个**实测**的失败窗口，后两条是阳性对照——证明 400 不是靠
# 「把整条日期路径弄挂」换来的假绿（那种改法会让后两条也变红）。


def test_until_far_future_is_400_not_500(client):
    """`9999-12-31` 是合法日期，但 until 的右端要 +1 天 →
    `date + timedelta` 先抛 OverflowError，未捕获就是 500。"""
    r = client.get("/api/items", params={"until": "9999-12-31"})
    assert r.status_code == 400
    assert "detail" in r.json()


def test_since_before_epoch_is_400_not_500(client):
    """`1970-01-01` 是合法日期，却在本机（Windows）的 `timestamp()` 上抛
    OSError [Errno 22]。它正是用户/模型表达「最早」时最经典的哨兵。"""
    r = client.get("/api/items", params={"since": "1970-01-01"})
    assert r.status_code == 400
    assert "detail" in r.json()


def test_normal_date_window_still_200(client):
    """阳性对照：正常窗口必须照常 200——否则上面两条的 400 可能是
    「整条路径被弄挂」换来的（那种改法会让这条变红）。"""
    r = client.get(
        "/api/items", params={"since": "2026-09-13", "until": "2026-09-13"}
    )
    assert r.status_code == 200 and r.json()["total"] == 1


def test_date_inside_the_range_is_200(client):
    """边界内正常值：2038 年也在可表示范围内（本机实测 = 2145888000）。"""
    r = client.get("/api/items", params={"until": "2038-01-01"})
    assert r.status_code == 200 and r.json()["total"] == 1


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


def test_static_file_content_type_comes_from_the_table(client, tmp_path, monkeypatch):
    """⭐ 真文件的 content-type 必须与 `_MIME` 的**值**一致。

    这是**栽过一次**的同类缺陷（见 api.py 里 _MIME 上方那段长注释）：SPA 兜底
    曾让 sw.js / manifest / 图标返回 200 的 HTML，浏览器把 HTML 当 manifest
    解析、当 SW 注册，「添加到主屏」整条路走不通——**而所有状态码都是 200**，
    日志上一个异常都没有。终审实测更狠：把 ``_MIME[".js"]`` 的值改成
    ``text/html``，当时 14 条测试全绿——状态码对了、正文也对了，唯独 MIME
    错了，而**后果与「发 HTML」完全相同**。

    所以期望值在测试里**逐字写死**，绝不写成 ``api._MIME[".js"]``——那等于
    拿被测实现去验证被测实现，两边一起改就怎么改都绿（空守卫的经典形状）。
    全表覆盖：任何一格的值写错，这条都变红。

    ⚠️ 用 `startswith`：Starlette 对 ``text/*`` 会追加 ``; charset=utf-8``
    （本机实测 ``text/javascript; charset=utf-8``）。
    """
    import vigil.api as api

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>VIGIL 守夜人</title>", encoding="utf-8")
    expect = {
        ".js": "text/javascript",                    # ← PWA 的 SW：错了整条路走不通
        ".css": "text/css",
        ".webmanifest": "application/manifest+json",  # ← 「添加到主屏」的清单，同上
        ".json": "application/json",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".woff2": "font/woff2",
        ".txt": "text/plain",
    }
    for suffix in expect:
        (dist / f"probe{suffix}").write_bytes(b"x")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    for suffix, mime in expect.items():
        r = client.get(f"/probe{suffix}")
        assert r.status_code == 200, suffix
        assert r.headers["content-type"].startswith(mime), (
            suffix, r.headers["content-type"], mime,
        )


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


# ── M4 T3：_MIME 的「键缺失」守卫（M3-1）──────────────────────────────
#
# ⚠️ 这张表是**故意与 vigil/api.py 的 _MIME 重复**的，不要改成
# `for suffix in api._MIME`——那样就变成空守卫了：从 _MIME 里删掉一个键，
# 参数集合同步缩小一个，测试**照样绿**，而缺陷（缺文件时不再 404、
# 改成返回 200 的 index.html）原封不动。要抓的就是"键少了"这件事，
# 判据就必须独立于它。
_EXPECTED_STATIC_SUFFIXES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".webmanifest": "application/manifest+json",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain",
}


def test_mime_table_matches_the_frozen_contract():
    """键与值都钉死。

    值被改（`.js` → `text/html`）与键被删（少了 `.js`）**都要红**：
    前者让浏览器拒绝执行脚本，后者让「缺文件宁 404」那条守卫失效——
    两种都只有真跑才现形，所以靠这张独立的表当判据。
    """
    import vigil.api as api

    assert api._MIME == _EXPECTED_STATIC_SUFFIXES


@pytest.mark.parametrize("suffix", sorted(_EXPECTED_STATIC_SUFFIXES))
def test_missing_static_asset_is_404_not_index_html(
    client, tmp_path, monkeypatch, suffix
):
    """⭐ 「职责二」的守卫：磁盘上没有的静态资源宁可 404，绝不许拿 index.html 顶。

    这条是 M3-1 的核心——删掉 `_MIME` 里任意一个键，**这一条会红**，
    因为该后缀不再被判为静态资源，请求会落进 SPA 兜底拿到 200 的 HTML。
    """
    import vigil.api as api

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>INDEX</html>", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    r = client.get(f"/不存在{suffix}")

    assert r.status_code == 404, (
        f"{suffix} 是静态资源后缀，磁盘上没有就必须 404——"
        f"拿到 {r.status_code} 说明它落进了 SPA 兜底"
    )
    assert "INDEX" not in r.text, "绝不许把 index.html 当静态资源发出去"
# ── Task 8：写端点（只写 overlay，绝不写 vigil.db） ──────────────


def _vigil_db_fingerprint(db: pathlib.Path) -> dict[str, str]:
    """`data/vigil.db` 的**整个文件集**指纹：主文件 + WAL 边车（`-wal` / `-shm`）。

    ⚠️ **为什么不能只哈希主文件**（T8 审查的 FIX 1，实测）：生产库是
    `journal_mode=wal`，而 **WAL 下写完之后主文件的字节可以一字不变**——
    改动全在 `-wal` 里。实测（副本里，把 `api_set_kind` 变异成写主库）：
    主文件 sha256 `bdb901ec…` 前后相同，`-wal` 从 `e3b0c442…`（空）变成 `af0c6653…`，
    `status_code` 还是 200。**条件是写的过程中一直开着一条读者连接**（生产就是这样：
    api 的 `mode=ro` 与 refine/digest 的写并发，R6 加 WAL 正是为此）——
    写者 close 时不是最后一个连接，于是**不 checkpoint**，证据只留在 `-wal` 里。
    ⇒ 只哈希主文件的守卫在那时是**假绿**：「字节没变」**不等于**「没写过」。

    ⚠️ **取指纹必须在预热之后**：本 API 的第一条连接会把 `-wal`（0 字节）与
    `-shm` 造出来——那是「打开过」的痕迹，不是「写过」。所以测试先来一次读
    （`GET /api/items`）再取 before；`<missing>` 与 0 字节是两种不同的值，
    刻意不统一，免得把「侧车刚被建出来」误读成「写过了」。
    """
    out: dict[str, str] = {}
    for suffix in ("", "-wal", "-shm"):
        path = db if not suffix else db.with_name(db.name + suffix)
        out[suffix or "main"] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "<missing>"
        )
    return out


def _assert_db_untouched(before: dict[str, str], after: dict[str, str], what: str) -> None:
    """比整个文件集，并把**变了哪个文件**写进消息（诊断用：假红也要能一眼定性）。"""
    changed = [name for name in before if before[name] != after[name]]
    assert not changed, (
        "⚠️ 写端点动了 data/vigil.db——D11 的机械保证被打破",
        what,
        {name: (before[name], after[name]) for name in changed},
    )


def test_write_kind_does_not_touch_vigil_db(client, db_path):
    """⭐ D11 的机械守卫：写端点跑完，`data/vigil.db` 的字节必须**一点没变**。

    ⚠️ 这不是"检查没报错"——是把**整个文件的哈希**前后比。
    任何绕过 overlay 直接写主库的实现，都会在这里变红。
    """
    before = _vigil_db_fingerprint(db_path)

    r = client.post("/api/items/1/kind", json={"kind": "life"})
    assert r.status_code == 200
    assert r.json()["edit_id"] > 0

    _assert_db_untouched(before, _vigil_db_fingerprint(db_path), "POST /api/items/1/kind")


def test_delete_and_undo_do_not_touch_vigil_db(client, db_path):
    """⭐ FIX 1 的另一半：**删除与撤销**也上文件哈希（reviewer 问的"该不该扩"）。

    判据与 `set_kind` 那条**同源**（同一个指纹助手），但覆盖的是另外两条写路径。
    为什么它们不能只靠状态断言（"列表里没了"/"undo 之后回来了"）：
    状态断言只能证明**overlay 写对了**，证明不了**主库没被顺手写**——
    「既写 overlay 又 UPDATE 主库」的实现在那两条断言下**全绿**，而它正是
    最可能被"顺手同步一下"引入的违规形状（D11 的机械保证是"绝不允许"，不是"以 overlay 为准"）。
    """
    before = _vigil_db_fingerprint(db_path)
    assert client.delete("/api/items/1").status_code == 200
    _assert_db_untouched(before, _vigil_db_fingerprint(db_path), "DELETE /api/items/1")

    before = _vigil_db_fingerprint(db_path)
    assert client.post("/api/undo", json={"edit_id": None}).json()["undone"] is True
    _assert_db_untouched(before, _vigil_db_fingerprint(db_path), "POST /api/undo")


def test_no_write_endpoint_touches_the_wal_sidecar(client, db_path):
    """⭐ FIX 1 的核心：**生产库是 WAL**，主文件字节不变**也可能是写过**（见助手 docstring）。

    这条把夹具库切成 `journal_mode=wal`，并且**整段过程一直开着一条读者连接**
    （= 生产中 api 与 refine 并发的形状）⇒ 违规写的证据**只**会留在 `-wal` 里。
    实测：把 `api_set_kind` 变异成写主库时，**只哈希主文件的守卫全绿**，
    而本条（含 `-wal`/`-shm`）变红。三条写端点都过一遍。
    """
    con = sqlite3.connect(str(db_path))
    try:
        assert con.execute("PRAGMA journal_mode=wal").fetchone()[0] == "wal"
    finally:
        con.close()

    # 预热：让 API 的第一条连接把 `-wal`/`-shm` 建出来（那是"打开过"，不是"写过"）
    assert client.get("/api/items").status_code == 200

    reader = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        reader.execute("SELECT COUNT(*) FROM items").fetchone()
        steps = (
            ("POST /api/items/1/kind", lambda: client.post(
                "/api/items/1/kind", json={"kind": "life"})),
            ("DELETE /api/items/1", lambda: client.delete("/api/items/1")),
            ("POST /api/undo", lambda: client.post("/api/undo", json={"edit_id": None})),
        )
        for what, call in steps:
            before = _vigil_db_fingerprint(db_path)
            r = call()
            assert r.status_code == 200, (what, r.status_code, r.text)
            _assert_db_untouched(before, _vigil_db_fingerprint(db_path), what)
    finally:
        reader.close()


def test_set_kind_is_visible_in_the_list(client):
    assert client.get("/api/items").json()["items"][0]["kind"] == "academic"
    client.post("/api/items/1/kind", json={"kind": "life"})
    assert client.get("/api/items").json()["items"][0]["kind"] == "life"


def test_deleted_item_is_hidden_from_list(client):
    assert client.get("/api/items").json()["total"] == 1
    assert client.delete("/api/items/1").status_code == 200
    assert client.get("/api/items").json()["total"] == 0
    assert client.get("/api/items/1").status_code == 404


def test_delete_also_hides_it_from_the_digest(client, db_path):
    """⚠️ R13 的典型形态：只改列表不改日报 ⇒「界面上删了、日报里还在」。"""
    import sqlite3 as _sq

    from vigil import store as _store

    con = _sq.connect(str(db_path))
    _store.save_digest(
        con, window_from=1, window_to=2, body_md="x", model="m",
        prompt_ver="v1", item_ids=[1],
    )
    con.close()

    did = client.get("/api/digests").json()["digests"][0]["digest_id"]
    assert len(client.get(f"/api/digests/{did}").json()["items"]) == 1

    client.delete("/api/items/1")
    assert client.get(f"/api/digests/{did}").json()["items"] == []


def test_undo_restores_item(client):
    client.delete("/api/items/1")
    assert client.get("/api/items").json()["total"] == 0
    assert client.post("/api/undo", json={"edit_id": None}).json()["undone"] is True
    assert client.get("/api/items").json()["total"] == 1


def test_undo_with_nothing_to_undo(client):
    assert client.post("/api/undo", json={"edit_id": None}).json()["undone"] is False


def test_person_crud_round_trip(client, tmp_path, monkeypatch):
    """⚠️ `load_persons` 走的是 `REPO_ROOT / "config" / "persons.toml"`，
    必须把它挪开——否则这个测试会**写进仓库里真实的配置文件**。"""
    import pathlib

    from vigil import api as _api

    monkeypatch.setattr(
        _api, "REPO_ROOT", tmp_path / "fake_root"
    )
    (tmp_path / "fake_root" / "config").mkdir(parents=True)

    assert client.get("/api/persons").json()["persons"] == []
    r = client.post("/api/persons", json={"uin": 111, "label": "甲", "note": ""})
    assert r.status_code == 201
    body = client.get("/api/persons").json()["persons"]
    assert body[0]["label"] == "甲"
    assert client.delete("/api/persons/111").status_code == 204
    assert client.get("/api/persons").json()["persons"] == []


def test_person_rejects_anon_sentinel(client, tmp_path, monkeypatch):
    from vigil import api as _api

    monkeypatch.setattr(_api, "REPO_ROOT", tmp_path / "fake_root")
    r = client.post("/api/persons", json={"uin": 0, "label": "匿名", "note": ""})
    assert r.status_code == 400


# ── Task 8 追加：E7 双源墓碑 / R10 控制字符 / ③ path 不许省 ─────────


def test_delete_tombstones_every_source_message(client, db_path):
    """⭐ E7 的双源验收：多来源 item 被删 ⇒ **每一条**源消息都落墓碑，undo 真救得回来。

    为什么要有这条（T3 的实测形态）：`store.save_items` 的批内去重**来源取并集**
    （`store.py:307`），所以一个 item 可以有 ≥2 条源消息（真库今天 0 例 ⇒ 潜伏），
    而计划里的 `api_delete_item` 只把 `srcs[0]` 落墓碑：`refine --redo` 重抽
    兄弟消息 ⇒ **条目以新 item_id 复活**（违反 D15）。

    ⚠️ 判据必须**两个方向一起**（否则「N 条 delete 事件」那种实现也能过：
    `undo` 只删一条事件、`item_state.deleted` 仍是 1 ⇒ 撤销报成功却毫无效果）。
    """
    con = sqlite3.connect(str(db_path))
    con.execute(
        "INSERT INTO messages (msg_id, group_id, ts, sender_uid, content)"
        " VALUES (12, 12345, (SELECT event_ts FROM items WHERE item_id = 1),"
        " 'u1', '兄弟消息：同一条信息被两条消息抽出来')"
    )
    con.execute("INSERT INTO item_sources (item_id, msg_id) VALUES (1, 12)")
    con.commit()
    con.close()

    # 造场景验收：这条 item 现在真的有两个来源（不是"看起来像"）
    probe = sqlite3.connect(str(db_path))
    try:
        assert [s.msg_id for s in store.source_messages(probe, 1)] == [11, 12], (
            "造场景失败：这个 item 必须有两条源消息，否则这条测试证明不了 E7"
        )
    finally:
        probe.close()

    assert client.delete("/api/items/1").status_code == 200

    from vigil import overrides

    # 消费者视角：`refine` 读的正是 `deleted_msg_ids`
    ov = overrides.connect()
    try:
        assert overrides.deleted_msg_ids(ov) == frozenset({11, 12}), (
            "只墓碑化了第一条源消息——refine --redo 重抽兄弟消息会让条目以新 item_id 复活"
        )
    finally:
        ov.close()
    assert client.get("/api/items").json()["total"] == 0

    # 反向：undo 之后条目真的回来，**且墓碑全部消失**（不是"撤了一条、还剩一条"）
    assert client.post("/api/undo", json={"edit_id": None}).json()["undone"] is True
    assert client.get("/api/items").json()["total"] == 1
    ov = overrides.connect()
    try:
        assert overrides.deleted_msg_ids(ov) == frozenset(), (
            "undo 之后墓碑还在：条目回来了，兄弟消息却被永久冻结"
        )
    finally:
        ov.close()


def test_person_rejects_control_chars(client, tmp_path, monkeypatch):
    """⭐ R10 的另一半：**转义**（`config.toml_str`，T7 已做）与**拒绝**（API）各管一半。

    理由：`config/*.toml` 是**人手输**的。把一个换行静默存进一个"名字"里、
    再在界面上错乱显示，是**最不诚实**的做法——而且它一旦落盘，
    只能靠人肉去看那个文件才发现得了。
    """
    from vigil import api as _api

    monkeypatch.setattr(_api, "REPO_ROOT", tmp_path / "fake_root")
    (tmp_path / "fake_root" / "config").mkdir(parents=True)

    for label in ["甲\n乙", "甲\r乙", "甲\x00乙", "甲\x1b乙", "甲\x7f乙"]:
        r = client.post("/api/persons", json={"uin": 111, "label": label, "note": ""})
        assert r.status_code == 400, (label, r.status_code, r.text)
        assert "detail" in r.json()
    # note 也管（不只是 label）
    r = client.post("/api/persons", json={"uin": 111, "label": "甲", "note": "带\n换行"})
    assert r.status_code == 400 and "detail" in r.json()

    # 阳性对照：干净的值照常 201，且**落的是被挪开的那份配置**（顺带钉住 ③）
    good = client.post("/api/persons", json={"uin": 111, "label": "甲", "note": "备注"})
    assert good.status_code == 201, good.text
    text = (tmp_path / "fake_root" / "config" / "persons.toml").read_text(encoding="utf-8")
    assert "甲" in text and "备注" in text
    assert client.get("/api/persons").json()["persons"][0]["note"] == "备注"


def test_persons_endpoints_always_pass_a_path(client, tmp_path, monkeypatch):
    """⚠️③ `load_persons` / `save_persons` 的 `path` **一处都不许省**。

    `DEFAULT_PERSONS` 是 `config.py` 模块级就冻住的常量，省掉 `path` 时
    `load_persons()` / `save_persons(people)` 读写的是**仓库里真实的**
    `config/persons.toml`，而 `monkeypatch.setattr(api, "REPO_ROOT", ...)` 拦不住它
    ⇒ `test_person_crud_round_trip` 会**全绿**，而用户真实名单已被整体替换/清空。

    ⚠️ 这条判据是**参数本身**（不是行为）：spy 把每次调用的 path 记下来，
    并且**一旦看到 None 就直接抛**（绝不让它落到真实文件上——
    守卫变红可以，守卫自己去写用户的名单不行）。
    """
    from vigil import api as _api, config as _config

    monkeypatch.setattr(_api, "REPO_ROOT", tmp_path / "fake_root")
    (tmp_path / "fake_root" / "config").mkdir(parents=True)

    seen: list[tuple[str, object]] = []
    real_load, real_save = _config.load_persons, _config.save_persons

    def spy_load(path=None):
        seen.append(("load", path))
        if path is None:
            raise AssertionError("load_persons 省了 path ⇒ 读的是真实 config/persons.toml")
        return real_load(path)

    def spy_save(people, path=None):
        seen.append(("save", path))
        if path is None:
            raise AssertionError("save_persons 省了 path ⇒ 会写真实 config/persons.toml")
        return real_save(people, path)

    monkeypatch.setattr(_api, "load_persons", spy_load)
    monkeypatch.setattr(_api, "save_persons", spy_save)

    assert client.get("/api/persons").status_code == 200
    assert client.post(
        "/api/persons", json={"uin": 111, "label": "甲", "note": ""}
    ).status_code == 201
    assert client.delete("/api/persons/111").status_code == 204

    assert seen, "一个 load/save 都没调到——这条守卫是空的"
    expect = tmp_path / "fake_root" / "config" / "persons.toml"
    assert all(p == expect for _, p in seen), seen


def test_multi_value_filters_and_person_dimension_through_the_api(
    client, db_path, tmp_path, monkeypatch
):
    """⭐ **端点层的接线**：`?kind=a&kind=b` 与 `?person=1&person=2` 必须真的通。

    ⚠️ 为什么 store 层那三条不够：store 的多值筛选由 `tests/test_store.py` 钉住，
    而「HTTP 查询参数有没有接到 `kinds=` / `actor_uins=` 上」是**另一件事**——
    把 `actor_uins=person or None` 写成 `actor_uins=None`（或者哪天有人"顺手"
    把 `person` 删了），store 层那几条**照样全绿**，而界面上的「按人物筛选」
    静默退化成「不筛选」（返回全部）。本项目最忌的就是这类假数字。
    反证：把 `actor_uins=person or None` 改成 `actor_uins=None` ⇒ **只有本条红**。
    """
    con = sqlite3.connect(str(db_path))
    con.execute("INSERT INTO sender_names VALUES (12345,'u1','张三','三三',111,0)")
    con.execute("INSERT INTO sender_names VALUES (12345,'u2','李四','四四',222,0)")
    ts = con.execute("SELECT event_ts FROM items WHERE item_id = 1").fetchone()[0]
    con.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, amount, links, confidence, model, prompt_ver,"
        " created_at) VALUES (2, 'notice', '第二条', NULL, ?, NULL, 12345, 'u2',"
        " NULL, NULL, '[]', 0.9, 'm', 'v1', 1)",
        (ts - 60,),
    )
    con.commit()
    con.close()

    # ① 多值 kind：维度内**并集**
    assert client.get("/api/items", params={"kind": "academic"}).json()["total"] == 1
    assert client.get(
        "/api/items", params=[("kind", "academic"), ("kind", "notice")]
    ).json()["total"] == 2

    # ② 多值 person：维度内并集；`actor_uin` 的值真的从库里取出来了
    one = client.get("/api/items", params={"person": 111}).json()
    assert one["total"] == 1, "`?person=` 没接到 `actor_uins=` 上（筛选静默失效）"
    assert one["items"][0]["item_id"] == 1
    assert one["items"][0]["actor_uin"] == 111
    assert client.get(
        "/api/items", params=[("person", 111), ("person", 222)]
    ).json()["total"] == 2

    # ③ 维度**间**交集（spec §四 #4）：两个类目 × 一个人 ⇒ 只有 item 1
    both = client.get(
        "/api/items",
        params=[("kind", "academic"), ("kind", "notice"), ("person", 111)],
    ).json()
    assert both["total"] == 1 and both["items"][0]["item_id"] == 1

    # ④ 不在名单上的 uin 不匹配任何东西
    assert client.get("/api/items", params={"person": 999}).json()["total"] == 0

    # ⑤ `/api/persons` 的 count 与人物筛选**同源**（同一个 `search_items` 调用）
    from vigil import api as _api

    monkeypatch.setattr(_api, "REPO_ROOT", tmp_path / "fake_root")
    (tmp_path / "fake_root" / "config").mkdir(parents=True)
    assert client.post(
        "/api/persons", json={"uin": 111, "label": "张三", "note": ""}
    ).status_code == 201
    assert client.get("/api/persons").json()["persons"] == [
        {"uin": 111, "label": "张三", "note": "", "count": 1}
    ]


def test_write_endpoint_edges(client):
    """两个写端点的两条边界：空 kind ⇒ 400、不存在的条目 ⇒ 404（且都不写东西）。"""
    assert client.post("/api/items/1/kind", json={"kind": "   "}).status_code == 400
    assert client.post("/api/items/999999/kind", json={"kind": "life"}).status_code == 404
    assert client.delete("/api/items/999999").status_code == 404
    # 边界请求不许留下任何干预（否则"点错了"会变成一条撤销不掉的编辑）
    from vigil import overrides

    ov = overrides.connect()
    try:
        assert overrides.last_edit(ov) is None
    finally:
        ov.close()


def test_undo_accepts_an_explicit_edit_id(client):
    """`{"edit_id": N}` 必须真的按**给定的** id 撤，而不是永远撤最近一条。

    ⚠️ 为什么单独要一条：plan 的三条 undo 用例**全是** `{"edit_id": None}`，
    于是"显式 id"这条路径**零守护**——把 `target = body.get("edit_id")` 那段
    换成"一律撤 last_edit"，那三条照样全绿，而前端在「撤掉那一次删除」时用的
    正是显式 id（`{"undone": true}` 会变成撤错东西，或撤了个没效果的）。

    序列：改类目（edit A）→ 软删（edit B）。先撤 A：条目**仍被删着**
    （最终态由 B 决定）；再撤 B：条目可见，且类目回到原值。
    """
    eid_kind = client.post("/api/items/1/kind", json={"kind": "life"}).json()["edit_id"]
    eid_del = client.delete("/api/items/1").json()["edit_id"]
    assert eid_del > eid_kind

    assert client.post("/api/undo", json={"edit_id": eid_kind}).json()["undone"] is True
    assert client.get("/api/items").json()["total"] == 0, (
        "撤掉的是 set_kind，删除事件还在——条目不该复活（撤错了 id）"
    )

    assert client.post("/api/undo", json={"edit_id": eid_del}).json()["undone"] is True
    body = client.get("/api/items").json()
    assert body["total"] == 1
    assert body["items"][0]["kind"] == "academic", "撤销后类目该回到原值"

    # 不存在的 id ⇒ False（不是异常，也不是静默的 True）
    assert client.post("/api/undo", json={"edit_id": 999999}).json()["undone"] is False


def test_delete_item_without_sources_still_works(client, db_path):
    """条目**没有源消息**时也能删：`msg_id=None` 是允许的（T4 的 D2），不许 500。

    ⚠️ plan 写的是 `srcs[0].msg_id if srcs else None`，而那条 `else` 分支
    **零守护**（真库今天 0 条无来源 ⇒ 只会在将来炸）。变异「去掉 `if srcs else None`」
    ⇒ `IndexError` ⇒ 500，只有本条红。

    ⚠️ 反向也要钉：不知道 msg_id 的软删**不该凭空造墓碑**——造了就会把
    别的 item 的源消息一起冻住（`deleted_msg_ids` 是 exists 语义）。
    """
    con = sqlite3.connect(str(db_path))
    ts = con.execute("SELECT event_ts FROM items WHERE item_id = 1").fetchone()[0]
    con.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, amount, links, confidence, model, prompt_ver,"
        " created_at) VALUES (2, 'notice', '无来源条目', NULL, ?, NULL, 12345, NULL,"
        " NULL, NULL, '[]', 0.9, 'm', 'v1', 1)",
        (ts - 60,),
    )
    con.commit()
    con.close()

    r = client.delete("/api/items/2")
    assert r.status_code == 200, r.text
    assert r.json()["edit_id"] > 0
    assert client.get("/api/items").json()["total"] == 1     # 只剩 item 1

    from vigil import overrides

    ov = overrides.connect()
    try:
        assert overrides.deleted_msg_ids(ov) == frozenset(), (
            "不知道 msg_id 的软删凭空造了墓碑——会把别的条目的源消息也冻住"
        )
    finally:
        ov.close()


# ── M5 终审修复轮：非尾部 undo / kind 控制字符 / edit_id 严格转整 / types.ts
#    机械守卫 ─────────────────────────────────────────────────────────────


def _add_item(db_path, item_id: int, msg_id: int) -> None:
    """往临时库补一条 item（带一条源消息）。

    与 `test_delete_item_without_sources_still_works` 的造法同源：**造真库里
    本来就有的形状**，不是放宽断言。
    """
    con = sqlite3.connect(str(db_path))
    ts = con.execute("SELECT event_ts FROM items WHERE item_id = 1").fetchone()[0]
    ts = ts + 60 * item_id
    con.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, amount, links, confidence, model, prompt_ver,"
        " created_at) VALUES (?, 'academic', ?, NULL, ?, NULL, 12345, 'u1',"
        " NULL, NULL, '[]', 0.9, 'm', 'v1', 1)",
        (item_id, f"第 {item_id} 条", ts),
    )
    con.execute(
        "INSERT INTO messages (msg_id, group_id, ts, sender_uid, content)"
        " VALUES (?, 12345, ?, 'u1', ?)",
        (msg_id, ts, f"第 {item_id} 条的原文"),
    )
    con.execute(
        "INSERT INTO item_sources (item_id, msg_id) VALUES (?, ?)", (item_id, msg_id)
    )
    con.commit()
    con.close()


def _reading_state(client) -> tuple[dict, frozenset]:
    """**读取路径**能看到的全部状态：`GET /api/items` 的整个响应 + 墓碑集。

    ⚠️ 判据必须取读取侧（Web 的 ItemCard 与日报读的就是这两样），
    不能去比 `item_state` 的原始行：`item_state.kind` 对**已软删**的条目是
    读不到的（所有读取路径都 `_NOT_DELETED` 过滤 + `COALESCE(ost.kind, i.kind)`），
    拿它当判据会把「可证明惰性」的撤法也判成红。
    """
    from vigil import overrides

    ov = overrides.connect()
    try:
        return client.get("/api/items").json(), overrides.deleted_msg_ids(ov)
    finally:
        ov.close()


def test_undo_of_a_non_tail_event_never_silently_flips_state(client, db_path):
    """⭐ M5 终审 Important-1：非尾部 `undo` **绝不许静默把状态弄坏**。

    终审的复现原文：`POST /api/undo {"edit_id":1}`（一条 `set_kind`，其前其后
    夹着 `delete`）⇒ 200 `{"undone":true}`，而 `item_state` 从
    `{life, deleted:0}` 变成 `{kind:NULL, deleted:1}`——「撤销改分类」导致
    「条目被删」，Web 与日报同时消失。

    ⚠️ 先记一处**对不上**（本轮实测）：终审正文给的事件列表（set_kind → delete）
    与那个「改前」状态互相矛盾——同一个条目上**最后一条**事件是 delete 时，
    它必然是 `deleted=1`；`{life, deleted:0}` 只可能出现在
    「**delete 在前、set_kind 在后**」的日志上。两种形状都钉在下面：

    * **① 终审给的那个具体序列**（set_kind(item1) → delete(item1) → set_kind(item2)，
      再撤那条**非尾部**的 set_kind）：它被后面那条 delete **覆盖**（该条目之后
      还有事件）⇒ 撤掉它对所有读取路径**可证明惰性** ⇒ 照旧允许（`True`；
      `test_undo_accepts_an_explicit_edit_id` 钉着这条既有语义），且**幂等**。
    * **② 同形、把两条事件对调**（delete(item1) → set_kind(item1) → set_kind(item2)，
      再撤那条 set_kind）：它**没有**被覆盖 ⇒ 撤掉它会让那条软删重新生效、
      条目从 Web 与日报同时消失（`{life,0}`→`{NULL,1}`、total 2→1 就是这个形状）
      ⇒ 必须**响亮拒绝**（409），且状态一个字不动。

    ⚠️ **承重的是 ②**：没有它，这条测试在修复之前也是绿的
    （① 的前后读取态本来就一样）。变异「去掉 `undo` 里对
    `_reject_non_tail_undo` 的调用」⇒ ② 变红（409 变 200、条目消失）。
    """
    _add_item(db_path, 2, 12)
    _add_item(db_path, 3, 13)
    assert client.get("/api/items").json()["total"] == 3, "造场景失败：三条都该可见"

    # ── ① 终审给的那个具体序列 ────────────────────────────────
    e1 = client.post("/api/items/1/kind", json={"kind": "life"}).json()["edit_id"]
    e2 = client.delete("/api/items/1").json()["edit_id"]
    e3 = client.post("/api/items/2/kind", json={"kind": "life"}).json()["edit_id"]
    assert e1 < e2 < e3, "造场景失败：edit_id 必须递增"

    before = _reading_state(client)
    assert client.post("/api/undo", json={"edit_id": e1}).json()["undone"] is True, (
        "被后面事件覆盖的 set_kind 是**可证明惰性**的——既有语义要求它返回 True"
    )
    assert _reading_state(client) == before, (
        "撤一条被覆盖的事件改变了读取路径看到的状态——「撤销」不该让任何条目出现/消失"
    )

    # ── ② 同形，两条事件对调（终审报的那一格）：item 3 ────────────
    # ⚠️ 这个形状**造不出**在 HTTP 上：`api_set_kind` 会 `store.get_item`，而
    # 被软删的条目查不到 ⇒ 404。所以「delete 之后又 set_kind」只可能从
    # **overlay 层**来（`overrides.*` 是公开的数据层 API；M7 的干预 UI、
    # 以及将来任何直接调它的脚本都会走到）。而 `POST /api/undo` 是**已发布的
    # HTTP 契约**：它必须对 overlay 里真实存在的任何日志都不静默弄坏状态。
    from vigil import overrides

    ov = overrides.connect()
    try:
        e_del = overrides.delete_item(ov, item_id=3, msg_id=13)
        e_kind = overrides.set_kind(ov, item_id=3, kind="life")
    finally:
        ov.close()
    e_other = client.post("/api/items/2/kind", json={"kind": "life"}).json()["edit_id"]
    assert e_del < e_kind < e_other, "造场景失败：edit_id 必须递增"
    before2 = _reading_state(client)
    assert before2[0]["total"] == 2, (
        f"造场景失败：撤销之前 item 2/3 该可见（item 1 的软删还生效着）："
        f"{[i['item_id'] for i in before2[0]['items']]}"
    )
    assert {i["item_id"]: i["kind"] for i in before2[0]["items"]}[3] == "life", (
        "造场景失败：那条 delete 之后被 set_kind 覆盖，item 3 该以新类目可见"
    )

    r = client.post("/api/undo", json={"edit_id": e_kind})
    assert r.status_code == 409, (
        f"撤一条**非尾部、且是该条目最后一条**的事件返回了 {r.status_code}："
        "这一撤会让条目倒退回上一条事件决定的状态（终审：撤销改分类 ⇒ 条目被删）"
    )
    assert "detail" in r.json()
    assert _reading_state(client) == before2, (
        "被拒绝的撤销仍然改坏了状态——拒绝必须在写之前发生"
    )
    # 拒绝不是「卡死」：撤完它后面那条无关的编辑之后，它就回到尾部、照旧撤得掉
    assert client.post("/api/undo", json={"edit_id": e_other}).json()["undone"] is True
    assert client.post("/api/undo", json={"edit_id": e_kind}).json()["undone"] is True
    # 回到尾部再撤 ⇒ 那条软删重新生效、item 3 消失——这是**尾部**的既有语义
    # （回退最近一次操作），与 ② 拒绝的「从中间抽走」是两件事，不许混为一谈。
    assert client.get("/api/items").json()["total"] == 1   # 只剩 item 2


def test_undo_refuses_a_tombstone_row(client, db_path):
    """⭐ 非尾部的**墓碑行**也必须拒（终审 Important-1 的第二形态）。

    墓碑行对 `item_state` 完全惰性 ⇒ 撤掉它「状态一点没变、照样返回 True」
    （用户点「撤销」、毫无反应、系统说成功）；而它唯一的作用是 D15 那道
    「永不被重抽复活」的保护——撤掉之后 `refine --redo` 会把条目以新 item_id
    抽出来。所以它不是一次可独立撤销的操作。

    形状：给 item 1 补一条源消息 12（批内去重的**来源取并集**，
    真库今天 0 例、T3 之后才出现）⇒ delete 会先落墓碑行、再落 delete 行。
    """
    from vigil import overrides

    con = sqlite3.connect(str(db_path))
    con.execute(
        "INSERT INTO messages (msg_id, group_id, ts, sender_uid, content)"
        " VALUES (12, 12345, (SELECT event_ts FROM items WHERE item_id = 1),"
        " 'u1', '兄弟消息')"
    )
    con.execute("INSERT INTO item_sources (item_id, msg_id) VALUES (1, 12)")
    con.commit()
    con.close()

    e_del = client.delete("/api/items/1").json()["edit_id"]
    ov = overrides.connect()
    try:
        tombs = [
            int(r[0])
            for r in ov.execute(
                "SELECT edit_id FROM item_edits WHERE action = 'tombstone'"
                " ORDER BY edit_id"
            )
        ]
        assert tombs, "造场景失败：双源条目的 delete 应当先落一条墓碑行"
        assert tombs[0] < e_del, "墓碑行必须垫在 delete 行之前（undo 只删一条事件）"
        assert overrides.deleted_msg_ids(ov) == frozenset({11, 12})
    finally:
        ov.close()

    r = client.post("/api/undo", json={"edit_id": tombs[0]})
    assert r.status_code == 409, (
        f"墓碑行被撤掉了（{r.status_code}）：状态看不出变化，但那条源消息失去了"
        "「永不被重抽复活」的保护（D15）"
    )
    ov = overrides.connect()
    try:
        assert overrides.deleted_msg_ids(ov) == frozenset({11, 12}), "墓碑集被改动了"
    finally:
        ov.close()
    # 正面：撤那条**尾部**的 delete，条目真的回来、墓碑全消（既有语义不许被这次修复动到）
    assert client.post("/api/undo", json={"edit_id": e_del}).json()["undone"] is True
    assert client.get("/api/items").json()["total"] == 1
    ov = overrides.connect()
    try:
        assert overrides.deleted_msg_ids(ov) == frozenset()
    finally:
        ov.close()


def test_undo_maps_infrastructure_failure_to_5xx_not_a_conflict(client, monkeypatch):
    """⭐ M5 收尾 scoped re-review A2：overlay 的**基础设施故障**必须是 5xx。

    失败场景（修复前）：`api_undo` 把**任何** `OverlayError` 都映成 409 ⇒
    overlay 文件缺失 / 挂不上 / 路径非法时，客户端收到「与日志状态冲突」，
    而真相是**服务端自己坏了** ⇒ 排障被指向错方向（去看「是不是有人并发改了日志」）。
    `OverlayError` 这个父类同时罩着两种病，只按父类映射就必然合并它们。

    判据是**两种病两个码**，缺一不可（本条两半都跑）：
      ① 基础设施故障 ⇒ **5xx**（用 `attach_readonly` 那条真实的报错文案构造，
         它就是「overlay 挂不上」时调用方会看到的那一句）；
      ② 同一套映射里，**与日志状态冲突**仍必须是 **409** —— A2 的修复不许
         把终审 Important-1 那两道闸门的语义弄坏。

    ⚠️ **顺序是承重的：② 先跑、替身后打**，且全程**不许**调 `monkeypatch.undo()`。
    原因（本轮实测，写下来免得再来一次）：`monkeypatch` 是**同一测试内共用的一个
    夹具实例**，autouse 的 `_isolate_overrides_path` / `_isolate_lock_path` 打的补丁
    也记在它身上 ⇒ 一句 `undo()` 会把它们**一起**撤掉。后果是 overlay 的
    `OVERRIDES_DB` 被还原成仓库里**真实的** `data/overrides.db`——这条用例于是
    往真库里写了 9 条事件，而**没有任何断言会红**（污染是静默的）。
    所以：② 用真实现、① 只用 `setattr` 替掉一个函数，两者不互相纠缠。

    变异「把 `except overrides.UndoConflict` 那支删掉」⇒ ② 红（409 变 5xx）；
    变异「把 `except overrides.OverlayError` 那支删掉（或改回 409）」⇒ ① 红。
    """
    from vigil import overrides

    # ── ② 真实现的状态冲突：delete 之后又 set_kind（只可能从 overlay 层来，
    #    `api_set_kind` 对被软删条目会 404），撤那条非尾部的 set_kind
    ov = overrides.connect()
    try:
        e_del = overrides.delete_item(ov, item_id=1, msg_id=11)
        e_kind = overrides.set_kind(ov, item_id=1, kind="life")
        e_other = overrides.set_kind(ov, item_id=2, kind="life")
        assert e_del < e_kind < e_other, "造场景失败：edit_id 必须递增"
    finally:
        ov.close()
    r2 = client.post("/api/undo", json={"edit_id": e_kind})
    assert r2.status_code == 409, (
        f"状态冲突返回了 {r2.status_code}：A2 的修复把既有的 409 语义弄坏了"
        "（非尾部撤销那两道闸门仍必须是 409）"
    )

    def _log() -> list[int]:
        conn = overrides.connect()
        try:
            return [
                int(r[0])
                for r in conn.execute("SELECT edit_id FROM item_edits ORDER BY edit_id")
            ]
        finally:
            conn.close()

    assert _log() == [e_del, e_kind, e_other], "被拒绝的撤销动了事件日志"

    # ── ① 基础设施故障：替掉 `overrides.undo`（`api.py` 按模块属性调它），
    #    抛的是 `attach_readonly` 那条真实的报错文案
    def boom(conn, *, edit_id):
        raise overrides.OverlayError(
            "overlay 只读挂载失败（**不降级**）。常见原因：本连接不是"
            " sqlite3.connect(..., uri=True) 打开的；或 data/ 不可写导致 WAL 的"
            " -shm/-wal 无法重建。"
        )

    monkeypatch.setattr(overrides, "undo", boom)
    r = client.post("/api/undo", json={"edit_id": e_kind})
    assert r.status_code // 100 == 5, (
        f"overlay 挂不上时返回了 {r.status_code}："
        "基础设施故障必须是 5xx（409 会把排障指向「与日志状态冲突」这个错方向）"
    )
    assert "detail" in r.json()
    assert _log() == [e_del, e_kind, e_other], "500 那条路动了事件日志"


def test_set_kind_rejects_control_characters(client, db_path):
    """⭐ M5 终审 Important-2：`kind` 是**日报的章节标题**，注入会落进归档。

    终审复现：`{"kind":"x\\n\\n## ⏰ 别忘\\n- **伪造的紧急条目**"}` ⇒ 200 ⇒
    `render_markdown` 真的把它渲染成日报的一节，落进 `docs/digests/*.md`
    （**入 git 的归档**）与 `digests.body_md`。同文件的 `api_add_person` 对
    label/note 都拒了，`kind` 是漏的那一个。

    ⚠️ 判据取**三条一起**：400 / overlay 里一个字节没写 / `store.window_items`
    （日报的读取入口）拿不到那个 kind。只看状态码的话，一个「先写再拒」的实现
    也能全绿。

    变异「删掉 `api_set_kind` 里的 `_reject_controls(kind, "kind")`」⇒ 本条红。
    """
    from vigil import overrides, store

    injection = "x\n\n## ⏰ 别忘\n- **伪造的紧急条目**"
    for kind in [injection, "a\nb", "a\rb", "a\x00b", "a\x1bb", "a\x7fb"]:
        r = client.post("/api/items/1/kind", json={"kind": kind})
        assert r.status_code == 400, (kind[:20], r.status_code, r.text)

    ov = overrides.connect()
    try:
        assert ov.execute("SELECT COUNT(*) FROM item_edits").fetchone()[0] == 0, (
            "被拒绝的 kind 仍然写进了 overlay（先写再拒）"
        )
    finally:
        ov.close()
    assert client.get("/api/items").json()["items"][0]["kind"] == "academic"

    # 日报的读取入口：`window_items` 是 digest 唯一取数据的地方
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        ts = con.execute("SELECT event_ts FROM items WHERE item_id = 1").fetchone()[0]
        kinds = [r.kind for r in store.window_items(con, since=ts - 1, until=ts + 1)]
    finally:
        con.close()
    assert kinds == ["academic"], f"注入的 kind 进了日报的读取路径：{kinds}"
    assert "## ⏰ 别忘" not in client.get("/api/items").text


@pytest.mark.parametrize("bad", ["abc", "1", 1.9, 1.0, True, [], {}])
def test_undo_rejects_a_non_integer_edit_id(client, bad):
    """⭐ M5 终审 Important-4：`int(target)` 无保护 ⇒ 500（应 400），`1.9` 静默截断。

    实测：`{"edit_id":"abc"}` ⇒ `ValueError`（uvicorn 下 500）；
    `{"edit_id":1.9}` ⇒ `int(1.9) == 1` ⇒ **撤掉的是另一条事件**，
    而响应里看不出任何区别。同一文件里 `_day_start` 早就把「转不成就 400」
    做成了规矩。`True` 也要挡（`bool` 是 `int` 的子类，`True == 1`）。

    ⚠️ 除状态码外还必须断言 **`1.9` 没有把 edit 1 撤掉**——否则「截断」这个
    真正的伤害（撤错东西）依然可以发生在一个只改状态码的实现里。
    """
    from vigil import overrides

    e1 = client.post("/api/items/1/kind", json={"kind": "life"}).json()["edit_id"]
    r = client.post("/api/undo", json={"edit_id": bad})
    assert r.status_code == 400, (bad, r.status_code, r.text)
    assert "detail" in r.json()

    ov = overrides.connect()
    try:
        assert (
            ov.execute(
                "SELECT COUNT(*) FROM item_edits WHERE edit_id = ?", (e1,)
            ).fetchone()[0]
            == 1
        ), f"{bad!r} 把 edit {e1} 撤掉了——非法输入不许有副作用"
        assert overrides.last_edit(ov)[0] == e1
    finally:
        ov.close()
    # 反面：真正的整数照旧能撤（不许把这条路一起挡死）
    assert client.post("/api/undo", json={"edit_id": e1}).json()["undone"] is True


# ── 两份手抄清单之间的**机械联系**（终审 Minor-2 / T10 的 M5 变异）─────


_TS_TYPES = pathlib.Path(__file__).resolve().parent.parent / "web" / "src" / "types.ts"


def _ts_type_fields(name: str) -> set[str]:
    """从 `web/src/types.ts` 的 `export type <name> = { … }` 里抠出字段名。

    ⚠️ 注释里也有冒号（`// slug，如 "academic"`、`/** … */`），所以先剥注释
    再扫 `名字:`。**剥注释这一半必须自己先验一遍**：正则抠源码时，
    「先剥再扫」与「先扫再剥」在这个文件上结果不同（`ItemDetail = Item & {…}`
    也不能被 `export type Item = {…}` 的正则吃掉——它前面不是 ` = {`）。
    """
    text = _TS_TYPES.read_text(encoding="utf-8")
    m = re.search(rf"^export type {name} = \{{(.*?)^\}}", text, re.S | re.M)
    assert m, f"types.ts 里找不到 `export type {name} = {{…}}`——契约的一份被删了"
    body = re.sub(r"/\*.*?\*/", "", m.group(1), flags=re.S)
    body = re.sub(r"//[^\n]*", "", body)
    out = {
        g.group(1)
        for g in re.finditer(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\??\s*:", body, re.M)
    }
    assert out, f"types.ts 的 {name} 里一个字段都没抠出来——正则与文件形状脱节了"
    return out


def test_types_ts_item_fields_match_the_frozen_api_contract():
    """⭐ M5 终审 Minor-2：`types.ts` ↔ `_ITEM_FIELDS` 之间**没有任何机械联系**。

    三侧（`types.ts` / 这里的 `_ITEM_FIELDS` / `api.item_out()`）在本提交已经对齐，
    但 `grep -rn actor_uin web/src/` 只命中 `types.ts` 那一行**声明**——
    没有任何 TS 代码读它 ⇒ T10 的变异「删掉 `actor_uin`」`npx tsc -b --force`
    **exit 0**（实测属实）⇒ `tsc` 不是守卫。而两份手抄清单漂移的方向是
    「页面静默少一栏」，没有任何编译错误。

    判据：把 `types.ts` 里的 `actor_uin` 删掉 ⇒ **本条必须变红**
    （实测：删掉后 `Item` 抠出 15 个字段，与 `_ITEM_FIELDS` 差一个）。
    """
    assert _TS_TYPES.is_file(), f"前端类型文件不见了：{_TS_TYPES}"
    assert _ts_type_fields("Item") == _ITEM_FIELDS
    assert _ts_type_fields("Source") == {
        "msg_id", "ts", "sender", "group_name", "content",
    }


# ── M6 T4：群清单（只读快照）+ 加群/改群/退群 ──────────────────────
#
# ⚠️ 夹具与既有的 `client` **同一套构造方式**（`_config_for` 式的 Config +
# `TestClient(create_app(...))`），只多两件事：
#   ① 把 `api.REPO_ROOT` 挪到 tmp —— `config_path()` **每次现读**这个全局
#      （`config.DEFAULT_CONFIG` 是 import 期冻住的常量，monkeypatch 够不着）；
#   ② 可选地预置一份群清单快照。
#
# ⚠️ 不挪 REPO_ROOT 的话 `/api/groups` 读的是**仓库里真实的**
# `config/groups.toml` 与 `data/groups-snapshot.json` —— 测试会跟着用户的
# 真实配置红绿，而那份配置恰恰是 M6 邀请用户在网页上改的东西。

_GROUPS_TOML = """\
[settings]
qq_db_dir = "{qq}"
output_db = "{out}"

[[groups]]
id = 111
name = "甲群"
enabled = true
"""

# 「QQ 库里的群」：111 已纳入（config 里有），222 没有。
_QQ_GROUPS = (
    groups_snapshot.GroupInfo(id=111, name="甲群", messages=10, last_ts=1_700_000_000),
    groups_snapshot.GroupInfo(id=222, name="乙群", messages=0, last_ts=0),
)

# 这个隔离根里的类目表（M6 T5）。比 conftest 那份小——它只需要满足类目端点
# 用例的要求：`life` 既是「重复 slug」又是删类目的迁移目标，
# `academic` 是被改名/被删的那一个（`item_ids[0]` 的类目）。
_CATEGORIES_TOML = """\
[[categories]]
slug = "notice"
label = "通知公告"
desc = "隔离用类目：通知公告"

[[categories]]
slug = "academic"
label = "学业"
desc = "隔离用类目：学业"

[[categories]]
slug = "life"
label = "生活"
desc = "隔离用类目：生活"
"""

# 这个隔离根里的人物名单（M6 T7）。⚠️ **它必须在夹具里先存在**：
# `/api/config/pack` 的导出把三份配置合进一个包，而 `load_persons` 对
# **不存在**的文件返回空名单 ⇒ 包里连 `[[persons]]` 段头都不会有，
# 而那正是 `test_api_export_pack_returns_toml_text` 要断言的形状
# （「文件不存在返回空名单」是 `load_persons` 刻意的语义，不是缺陷）。
_PERSONS_TOML = """\
[[persons]]
uin = 100000001
label = "某辅导员"
"""


def _seed_items_db(db: pathlib.Path) -> None:
    """造一个最小主库：两条条目（`academic` / `life`）+ 各自的源消息。

    ⚠️ **两条、且 `item_ids[0]` 那条不是 `life`**：类目用例里「改名/迁移之后
    条目跟着走」的断言，拿一条本来就是目标类目的条目来测是**空的**
    （改不改都绿）——而 T4 的夹具从不起库，`/api/items` 在它下面本来会炸。

    ⚠️ **M6 T6 起还落 `messages` + `item_sources`**（每条源消息各挂一条条目）：
    `/api/reorder` 的输入是 `collect_source_messages`（它 JOIN `item_sources`
    与 `messages`），没有这两张表那就是**空的重排**——`plan.changes` 恒为空，
    于是 `test_api_reorder_undo_returns_to_the_previous_kinds` 里那句
    「`after != before`」会红，而红的原因与它要守的东西无关（夹具缺料）。
    正文里带「通知」二字也是承重的：预筛的保留规则靠关键词（`DEFAULT_KEYWORDS`）。

    ⚠️ **两条条目在 111 群、第三条在 222 群是刻意的**（T6 fix loop 1）：
    `prefilter.make_batches` **不跨群混批** ⇒ 111 群那两条一批、222 群那条一批
    ⇒ **两批**。取消（`POST /api/jobs/{id}/cancel`）与进度这两条用例都需要
    「第一批在飞、第二批还没发」这个中途状态；只有一批时，
    `plan_reorder` 的 `should_stop` **永远只被调一次且那时还没人喊停**
    ⇒ 那条接线是**死代码**（复审 Important-1 的实测形状）。
    """
    conn = sqlite3.connect(str(db))
    try:
        store.ensure_schema(conn)
        conn.executescript(_MESSAGE_TABLES_DDL)
        ts = int(dt.datetime(2026, 9, 13, 12, 0).timestamp())
        for item_id, kind, title, msg_id, content, gid in (
            (1, "academic", "选课通知", 11, "选课通知：9月16日截止", 111),
            (2, "life", "宿舍通知", 12, "宿舍通知：本周五停水检修", 111),
            (3, "notice", "兼职通知", 13, "兼职招聘：图书馆整理资料", 222),
        ):
            conn.execute(
                "INSERT INTO messages (msg_id, group_id, ts, sender_uid, content)"
                " VALUES (?,?,?,?,?)",
                (msg_id, gid, ts + msg_id, "u1", content),
            )
            conn.execute(
                "INSERT INTO items (item_id, kind, title, detail, event_ts,"
                " deadline_ts, group_id, actor_uid, place, amount, links, confidence,"
                " model, prompt_ver, created_at)"
                " VALUES (?,?,?,NULL,?,NULL,?,'u1',NULL,NULL,'[]',0.9,'m','v1',1)",
                (item_id, kind, title, ts, gid),
            )
            conn.execute(
                "INSERT INTO item_sources (item_id, msg_id) VALUES (?,?)",
                (item_id, msg_id),
            )
        conn.commit()
    finally:
        conn.close()


def _groups_root(tmp_path, monkeypatch, *, snapshot):
    """造一个 tmp「仓库根」+ 一份 `groups.toml` +（可选）一份快照。

    返回一个**工厂**：每次调用都造一个全新的 app（等价于「重启服务」），
    但共用同一个 tmp 根 —— 「落盘 ⇒ 重读仍在」要的正是这个形状。

    ⚠️ 路径写成**绝对 + posix**（`as_posix()`）：相对路径的解析基准是
    `config.REPO_ROOT`（**那个**全局没被挪走），写成相对就会指回真实仓库；
    反斜杠则是 TOML 基本字符串里的转义字符，必须避开。

    ⚠️ M6 T5 起这个根下还多两样东西，否则类目端点用例够不着它们：
      · `config/categories.toml`（`api.categories_path()` 与 `config_path()`
        是**同一个根**）；
      · 一个**真有条目**的主库（T4 的夹具从不起库，`/api/items` 在它下面
        直接炸 `unable to open database`）。

    ⚠️ 工厂上挂了一个 `item_ids` 属性（T5 的用例读 `client_factory.item_ids[0]`）。
    它是**函数上的属性**而不是返回值上的字段：`client_factory()` 要的仍是
    「一个本来就能直接当 TestClient 用的东西」，两者不能合成一个对象。
    """
    from vigil import api as _api

    root = tmp_path / "fake_root"
    (root / "config").mkdir(parents=True)
    data = tmp_path / "data"
    data.mkdir()
    qqdb = tmp_path / "qqdb"
    qqdb.mkdir()
    cfg_path = root / "config" / "groups.toml"
    cfg_path.write_text(
        _GROUPS_TOML.format(qq=qqdb.as_posix(), out=(data / "vigil.db").as_posix()),
        encoding="utf-8",
    )
    (root / "config" / "categories.toml").write_text(
        _CATEGORIES_TOML, encoding="utf-8"
    )
    # ⚠️ M6 T7 起再加一份 `persons.toml`：配置包的导出要它（见 `_PERSONS_TOML`），
    # 它同时是导入的落点（`persons_path()` 与 `config_path()` 同一个根）。
    (root / "config" / "persons.toml").write_text(_PERSONS_TOML, encoding="utf-8")
    # ⚠️ **FIX 3（Fix loop 3）：让「对账读的那份」与「端点写的那份」是同一个文件。**
    # 从前的夹具把 `categories.DEFAULT_CATEGORIES`（conftest 挪到的**另一个** tmp 根）
    # 与这里的 `config/categories.toml` 分成了**两个文件** ⇒
    # **「端点写文件 ⇒ 下一次读触发对账」这条生产路径，测试从未跑过**
    # ——而那正是 I-2（手改把 slug 加回来之后别名没对平）一直没被抓到的原因。
    monkeypatch.setattr(
        _cats_mod, "DEFAULT_CATEGORIES", root / "config" / "categories.toml"
    )
    _seed_items_db(data / "vigil.db")
    if snapshot is not None:
        groups_snapshot.write(snapshot, data / "groups-snapshot.json", now=1_700_000_999)
    # ⚠️ 必须在造 app 之前挪：`config_path()` 是**每次现读**这个全局的
    monkeypatch.setattr(_api, "REPO_ROOT", root)
    cfg = Config(
        qq_db_dir=qqdb,
        output_db=data / "vigil.db",
        groups=(Group(id=111, name="甲群"),),
    )

    def make(*, raise_server_exceptions: bool = True) -> TestClient:
        # ⚠️ `raise_server_exceptions=False` 是给**「未捕获异常 ⇒ 500 响应」**
        # 那类判据留的（T6 fix loop 1 的第一条用户：`/api/items/kinds` 的类目表
        # 读不出来时**必须说出原因**）。默认 `True` 时那个异常会在测试里
        # **重新抛出**，于是「响应里有没有原因」这件事**根本断言不到**
        # ——那是一条"看起来在守、实际只能证明它抛了"的空守卫。
        return TestClient(
            create_app(cfg), raise_server_exceptions=raise_server_exceptions
        )

    make.item_ids = [1, 2, 3]  # type: ignore[attr-defined]
    # ⚠️ 主库**文件路径**也挂上（T6 fix loop 1）：`test_api_reorder_never_writes_
    # the_main_db` 要按 D11 的机械判据（逐字节指纹）验**整条 API 路径**。
    make.db_path = data / "vigil.db"  # type: ignore[attr-defined]
    return make


@pytest.fixture()
def client_no_snapshot(tmp_path, monkeypatch):
    """没有任何快照的 app：`data/` 下只有那份 config（没有 `groups-snapshot.json`）。"""
    return _groups_root(tmp_path, monkeypatch, snapshot=None)()


@pytest.fixture()
def client_with_snapshot(tmp_path, monkeypatch):
    """快照里有 111（已纳入）与 222（未纳入）。"""
    return _groups_root(tmp_path, monkeypatch, snapshot=_QQ_GROUPS)()


@pytest.fixture()
def client_factory(tmp_path, monkeypatch):
    """可反复造新 app 的工厂（同一个 tmp 根）。

    ⚠️ 快照里多一个 333：它在「QQ 库」里但**不在** config 里 —— 正是
    「还没纳入、等着被加进来」的形状。「加群 ⇒ 重启后仍在」那条用例要靠它。
    """
    return _groups_root(
        tmp_path,
        monkeypatch,
        snapshot=(
            *_QQ_GROUPS,
            groups_snapshot.GroupInfo(id=333, name="丙群", messages=1, last_ts=1),
        ),
    )


def test_api_groups_says_so_when_there_is_no_snapshot(client_no_snapshot):
    """⭐ 没有快照时**明说**，不许回一个空列表。

    ⚠️ 空列表会被读成「你的 QQ 库里一个群都没有」——一句**假话**，
    而且是最容易让人不再信任这个页面的那种假话（本项目的
    「只说自己有资格说的话」判据，M2 起立下的规矩）。
    """
    r = client_no_snapshot.get("/api/groups")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "export" in body["reason"]


def test_api_groups_reads_the_snapshot_and_marks_watched(client_with_snapshot):
    body = client_with_snapshot.get("/api/groups").json()
    assert body["available"] is True
    by_id = {g["id"]: g for g in body["groups"]}
    assert by_id[111]["watched"] is True
    assert by_id[222]["watched"] is False
    assert by_id[111]["messages"] == 10
    assert body["generated_at"] > 0


def test_api_add_group_persists_and_is_visible_after_reload(tmp_path, client_factory):
    """⭐ **出口判据 1 的机械形式**：网页上加一个群 ⇒ 落盘 ⇒ **重读仍在**。

    ⚠️ 「重读仍在」是判据的全部意义所在：只断言响应体的话，
    一个"内存里加了、磁盘上没写"的实现照样绿——而它在重启后**静默消失**，
    用户要到下次开机才发现。

    ⚠️ **对本条的一处实际修正**（brief 原稿读 `body["watched"]`）：`/api/groups`
    的响应**没有**那个顶层键——契约是 `available` / `reason` / `generated_at` /
    `groups`（计划 T10 的 `GroupsResponse`，与 Step 5d 的实现一致）。
    这里改成「快照里那个群（333）在新 app 里**变成 watched**」：同样是
    「新进程从磁盘读到了刚写的配置」的机械形式，且比读文件文本更接近
    用户在页面上看到的东西。
    """
    c = client_factory()
    r = c.post("/api/groups", json={"id": 333, "name": "丙群", "tier": "high"})
    assert r.status_code == 201
    # 换一个**全新的 app**（等价于重启）后再读
    c2 = client_factory()
    body = c2.get("/api/groups").json()
    assert any(g["id"] == 333 and g["watched"] for g in body["groups"])


def test_api_add_group_rejects_a_duplicate(client_factory):
    c = client_factory()
    assert c.post("/api/groups", json={"id": 111, "name": "重复"}).status_code == 409


def test_api_add_group_rejects_a_bad_tier(client_factory):
    c = client_factory()
    assert c.post("/api/groups", json={"id": 444, "name": "群", "tier": "boss"}).status_code == 400


def test_api_add_group_rejects_a_bool_id(client_factory):
    """`true` 是 `int` 的子类 ⇒ `isinstance(True, int)` 为真。

    ⚠️ 不挡的话会建出一个群号为 1 的条目——与 M5 终审 #22 是同一个形状，
    而这里连 `toml_int` 都拦不住（它在 `save_config` 里，那时 id 已经是
    `True`、写出去是 `true`）。**闸必须在入口。**
    """
    c = client_factory()
    assert c.post("/api/groups", json={"id": True, "name": "群"}).status_code == 400


def test_api_delete_group_refuses_the_last_one(client_factory):
    """⚠️ 退掉最后一个群 = 把程序改成起不来（`load_config` 判「一个群都没配」）。

    ⚠️ 正确动作是 `enabled = false`，接口要在 detail 里**说清这一点**。
    """
    c = client_factory()  # 夹具只配了一个群
    r = c.delete("/api/groups/111")
    assert r.status_code == 409
    assert "enabled" in r.json()["detail"]


def test_api_patch_group_disables_without_deleting(client_factory):
    c = client_factory()
    assert c.patch("/api/groups/111", json={"enabled": False}).status_code == 200
    body = c.get("/api/groups").json()
    assert all(not g["watched"] for g in body["groups"])
    assert any(g["id"] == 111 for g in body["groups"]), "停用不是删除——条目还在"


# ── M6 T5：类目编辑端点 ─────────────────────────────────────────────
#
# ⚠️ 偏差（逃逸舱）：brief 这批用例逐字照抄，只多两处**夹具侧**的补丁
# （见 `_groups_root` 的 docstring）：`client_factory.item_ids` 与
# 「隔离根下要有 categories.toml / 一个真有条目的主库」。
# T4 的夹具当初只造群清单，类目这一半是 T5 才出现的。


def test_api_add_category_persists(client_factory):
    c = client_factory()
    r = c.post("/api/categories", json={
        "slug": "sport", "label": "体育", "desc": "球赛、运动会", "icon": "⚽",
    })
    assert r.status_code == 201
    slugs = [x["slug"] for x in client_factory().get("/api/categories").json()["categories"]]
    assert "sport" in slugs


def test_api_add_category_rejects_a_bad_slug(client_factory):
    c = client_factory()
    r = c.post("/api/categories", json={"slug": "Sports", "desc": "x"})
    assert r.status_code == 400
    # ⚠️ **断言详情，不只断言状态码**（勘误 E7 形态 5：输入到不了被测分支）。
    # `category_or_400` 里还有别的 400（desc 为空 / 控制字符），400 本身
    # 区分不出它是不是被 slug 规则拦下的——只有这句话能。
    assert "slug" in r.json()["detail"]


def test_api_add_category_rejects_a_duplicate(client_factory):
    c = client_factory()
    assert c.post("/api/categories", json={"slug": "life", "desc": "重复"}).status_code == 409


def test_api_rename_category_creates_an_alias_and_moves_the_items(client_factory):
    """⭐ **出口判据 6 的机械形式**：删/改一个类目之后，**不允许静默留下
    指向不存在 slug 的条目**。

    ⚠️ 判据必须查**条目那一侧**（`/api/items` 里那条的 `kind` 是不是新 slug），
    只查 `/api/categories` 的话，"配置改了、条目还指着老 slug"照样绿——
    而那是 spec 点名要禁的状态。
    """
    c = client_factory()
    item_id = client_factory.item_ids[0]
    old_kind = c.get(f"/api/items/{item_id}").json()["kind"]

    r = c.put(f"/api/categories/{old_kind}", json={"slug": "life_v2"})
    assert r.status_code == 200

    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life_v2"
    slugs = [x["slug"] for x in c.get("/api/categories").json()["categories"]]
    assert "life_v2" in slugs and old_kind not in slugs


def test_api_delete_category_refuses_when_items_still_point_at_it(client_factory):
    """⭐ 删除时**必须提示「有 N 条属于它」并要一个迁移目标**。

    ⚠️ 不回 400/409 而直接删掉的话，那些条目会指向一个不存在的 slug——
    `digest.py:465-469` 会把这个 slug 当成「类目表里没有的 kind」排到日报末尾
    （它**不静默丢**，这很好），但界面上会显示成裸 slug。
    """
    c = client_factory()
    old_kind = c.get(f"/api/items/{client_factory.item_ids[0]}").json()["kind"]
    r = c.delete(f"/api/categories/{old_kind}")
    assert r.status_code == 409
    assert "migrate_to" in r.json()["detail"]


def test_api_delete_category_with_migration_leaves_nothing_dangling(client_factory):
    c = client_factory()
    item_id = client_factory.item_ids[0]
    old_kind = c.get(f"/api/items/{item_id}").json()["kind"]

    r = c.delete(f"/api/categories/{old_kind}?migrate_to=life")
    assert r.status_code == 204
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life"
    slugs = [x["slug"] for x in c.get("/api/categories").json()["categories"]]
    assert old_kind not in slugs


def test_api_category_undo_restores_the_previous_file(client_factory):
    """⭐ 类目的「撤销」走**版本快照**，与 overlay 的撤销是两回事（spec §3.3）。"""
    c = client_factory()
    before = {x["slug"] for x in c.get("/api/categories").json()["categories"]}

    c.post("/api/categories", json={"slug": "sport", "desc": "球赛"})
    assert "sport" in {x["slug"] for x in c.get("/api/categories").json()["categories"]}

    assert c.post("/api/categories/undo").status_code == 200
    assert {x["slug"] for x in c.get("/api/categories").json()["categories"]} == before


def test_api_category_undo_says_so_when_there_is_nothing_to_undo(client_factory):
    """⚠️ 空栈时回一句「没有可撤销的操作」，而不是假装成功。

    ⚠️ 与 `/api/undo` 的既有语义对齐（它回 `{"undone": false}`）——
    两处撤销在**协议上**可以不同（一个是内容回滚、一个是事件删除），
    但在**「没得撤时要说出来」这一点上必须一致**。
    """
    c = client_factory()
    body = c.post("/api/categories/undo").json()
    assert body["undone"] is False


# ── M6 T5 的补充守卫（**brief 之外**）─────────────────────────────────
#
# 存在的理由只有一条：勘误 E7 要求「每一处改动都要答得出**删掉它什么会红**」。
# 下面四条各对着上面某个**此前只有注释、没有守卫**的断言；注释里那些
# 「为什么这样写」若没有测试兜着，就是 E7 说的那种「错的论证」的温床。


def test_api_add_category_rejection_leaves_no_snapshot_behind(client_factory):
    """⭐ `validate_or_400` **必须在 `snapshot_categories()` 之前**（注释里那句话的守卫）。

    ⚠️ 判据走**撤销栈**而不是"看文件没变"：400 时若先拍了快照再校验，
    文件确实没变，但撤销栈里多了一格**与当前内容相同**的快照 ⇒ 用户下一次
    「撤销」会撤销掉这一格假的（看到的是"点了没反应"），而**真正的上一次修改
    再也撤不回来了**（它被那一格顶掉了位置）。

    变异反证：把 `api_add_category` 里 `validate_or_400(candidate)` 挪到
    `snapshot_categories()` **之后** ⇒ 本条**必红**（undo 会回 200 而不是
    `undone: false`）。
    """
    c = client_factory()
    # 先做一次**合法**改动，让撤销栈里有且只有一格
    assert c.post("/api/categories", json={"slug": "sport", "desc": "球赛"}).status_code == 201
    # 再来一次非法改动（slug 大写）
    assert c.post("/api/categories", json={"slug": "Sports", "desc": "x"}).status_code == 400

    # 撤销：应当撤掉**sport 那一次**，而不是被那次 400 挤掉
    assert c.post("/api/categories/undo").status_code == 200
    slugs = {x["slug"] for x in c.get("/api/categories").json()["categories"]}
    assert "sport" not in slugs, "400 那次也拍了一份快照：真正的上一次修改撤不回来了"
    # 而且撤销栈**已经空了**——340 那次 400 没有留下多余的格子
    assert c.post("/api/categories/undo").json()["undone"] is False, (
        "撤销栈里还有多余的格子：400 的路径产生了快照"
    )


def test_api_add_category_rejects_a_control_character(client_factory):
    """`_reject_controls` 在类目这条路上也要有牙（R10：转义与拒绝各管一半）。

    ⚠️ 不挡的话 `toml_str` 会**老老实实把它转义**（`\n` 写成 `\u000A`），
    于是配置里存着一个带换行的 `desc`、界面与提示词里错乱显示——而
    `save_categories` **不会**报错（那是"存得进去"与"应该存"的分别）。
    """
    c = client_factory()
    r = c.post("/api/categories", json={"slug": "sport", "desc": "球赛\n换行"})
    assert r.status_code == 400
    assert "控制字符" in r.json()["detail"]


def test_api_delete_category_rejects_a_nonexistent_migration_target(client_factory):
    """迁移目标必须是**现存**类目——否则删完留下的是一条指向不存在 slug 的映射。

    ⚠️ 它守的正是出口判据 6 的另一半：`migrate_to=typo` 的话，
    条目会从一个不存在的 slug 走到**另一个**不存在的 slug，两边都悬空。
    变异反证：删掉 `api_delete_category` 里那段 `if migrate_to and migrate_to not in ...`
    ⇒ 本条**必红**（会回 204）。
    """
    c = client_factory()
    old_kind = c.get(f"/api/items/{client_factory.item_ids[0]}").json()["kind"]
    r = c.delete(f"/api/categories/{old_kind}?migrate_to=typo")
    assert r.status_code == 400
    slugs = {x["slug"] for x in c.get("/api/categories").json()["categories"]}
    assert old_kind in slugs, "被拒的删除不该改动配置"


def test_api_rename_category_reports_aliases(client_factory):
    """`/api/categories` 的 `aliases` 是**契约的一部分**（编辑器要用它显示旧名）。

    ⚠️ 单独钉它是因为：改名之后**只查 `categories` 那一半**的用例全都会绿，
    而界面上「旧名 life → 现在叫 daily」那一行会静默消失。
    """
    c = client_factory()
    item_id = client_factory.item_ids[0]
    old_kind = c.get(f"/api/items/{item_id}").json()["kind"]
    assert c.put(f"/api/categories/{old_kind}", json={"slug": "life_v2"}).status_code == 200
    assert c.get("/api/categories").json()["aliases"] == {old_kind: "life_v2"}


# ── M6 T4 复审 ⚠️-3：显示路径降级、配置载荷保持响亮 ────────────────────


def test_a_broken_config_degrades_the_display_paths_but_not_the_config_payload(
    client, db_path
):
    """⭐ 配置读不出来时：显示路径**降级**（200 + 裸群号），配置载荷**响亮**（500）。

    ⚠️ 三条显示路径（`/api/items`、`/api/items/{id}`、`/api/digests/{id}`）只需要
    一个**显示用**的群名——为它把**信息流**（主页面）整页黑成 500，与
    `groups_snapshot.load` 刻意「增强项不许 500」是同一条判据的反面。
    ⚠️ 而 `/api/groups` 的**载荷就是配置**：读不出来必须 500——否则它会若无其事地
    回一句「还没有群清单快照」（一句假话：真相是配置文件坏了）。

    ⚠️ 变异反证：把 `group_names_map()` 的降级去掉（恢复直接 `current_config()`）
    ⇒ 前三条断言红（500）。

    ⚠️ 坏掉的是**临时那份** `groups.toml`（conftest 的 autouse 夹具把
    `api.REPO_ROOT` 挪到了 tmp 根）——真实仓库里那份先 assert 确认碰不到。
    """
    from vigil import api as _api
    from vigil import config as _config

    _seed_digest(db_path)
    cfg_path = _api.REPO_ROOT / "config" / "groups.toml"
    assert cfg_path != _config.DEFAULT_CONFIG, (
        "夹具没把 `api.REPO_ROOT` 挪走 ⇒ 本条会去改仓库里真实的 groups.toml"
    )
    cfg_path.write_text("[[groups]\n", encoding="utf-8")  # 故意的 TOML 语法错

    r = client.get("/api/items")
    assert r.status_code == 200, "配置坏掉不许把信息流整页黑掉（显示路径要降级）"
    assert r.json()["items"][0]["group_name"] == "12345", (
        "降级必须是**裸群号字符串**——不是空串、不是 None、更不是 500"
    )
    one = client.get("/api/items/1")
    assert one.status_code == 200 and one.json()["group_name"] == "12345"
    assert client.get("/api/digests/1").status_code == 200

    # 阳性对照的另一半：**配置就是载荷**的那条保持响亮
    assert client.get("/api/groups").status_code == 500, (
        "`/api/groups` 读不出配置必须响亮——否则它会回一句「还没有快照」的假话"
    )


# ── M6 T5 Fix loop 1：别名剪枝 + `ka2`（C-1 / I-1 / I-2）─────────────
#
# 四条用例是一条链上的四格，各自的「删掉它什么会红」写在 docstring 里。


def test_api_renaming_a_category_then_undoing_moves_the_items_back(client_factory):
    """⭐ C-1：改名 ⇒ **撤销** ⇒ 条目必须跟着回到旧 slug（不许悬空）。

    ⚠️ 从前这条会留下一个**悬空 slug**：配置回到了 `academic`，而 `academic→life_v2`
    那条别名还在 ⇒ 条目显示 `life_v2`（一个配置里已经不存在的类目）、角标 `academic=0`。
    **撤销必须把这一次改名整体退掉**——别名也是这次改名的一部分。

    ⚠️ 变异反证：把 `api_category_undo` 里的 `prune_aliases(restored)` 删掉
    ⇒ 本条**必红**（条目仍显示 `life_v2`、aliases 仍有那一行）。
    """
    c = client_factory()
    item_id = client_factory.item_ids[0]
    old_kind = c.get(f"/api/items/{item_id}").json()["kind"]

    assert c.put(f"/api/categories/{old_kind}", json={"slug": "life_v2"}).status_code == 200
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life_v2"

    assert c.post("/api/categories/undo").status_code == 200
    assert c.get(f"/api/items/{item_id}").json()["kind"] == old_kind, (
        "撤销之后条目还走在改名后的 slug 上：配置里已经没有它了"
    )
    assert c.get("/api/categories").json()["aliases"] == {}, (
        "撤销只退了配置文件、没退别名：表里留着一条指向不存在目标的映射"
    )


def test_api_renaming_back_to_the_original_name_is_not_an_error(client_factory):
    """⭐ I-1：`A→B` 之后再把 `B` 改回 `A`，**不许成环**。

    ⚠️ 从前这里是 500（`set_kind_alias` 跟到旧行 `A→B` 判成环），而报错还赖
    「这张表是程序维护的，出现环说明有人手工改过它」——**那句话是假的**，
    是程序自己写出来的环；用户**此后永远回不去**。

    ⚠️ 变异反证：把 `api_update_category` 里那次 `prune_aliases(candidate, keep=slug)`
    删掉 ⇒ 本条**必红**（409/500）。
    """
    c = client_factory()
    item_id = client_factory.item_ids[0]
    old_kind = c.get(f"/api/items/{item_id}").json()["kind"]

    assert c.put(f"/api/categories/{old_kind}", json={"slug": "academic_v2"}).status_code == 200
    back = c.put("/api/categories/academic_v2", json={"slug": old_kind})
    assert back.status_code == 200, f"改回原名必须能成功，实际：{back.status_code} {back.text}"
    assert c.get(f"/api/items/{item_id}").json()["kind"] == old_kind
    aliases = c.get("/api/categories").json()["aliases"]
    assert old_kind not in aliases, (
        "表里留了一条 `old_kind` 是**现存 slug** 的行——不变量破了，它是下一个环的种子"
    )


def test_api_re_adding_a_slug_does_not_steal_a_manual_kind(client_factory):
    """⭐ I-2：删掉又加回来的 slug，**不许**被旧别名顶掉（`ka2` 的安全前提）。

    场景：① 手工把一条条目的类目改成 `life`；② 删掉 `life`（迁移到 `notice`）
    ⇒ 别名 `life→notice`（**必需**：那条条目的 `ost.kind='life'` 已经不存在了）；
    ③ 把 `life` 加回来。
    ⇒ 此时 `life` 又是**合法**类目 ⇒ 那条条目必须显示 `life`。
    ⚠️ 旧行 `life→notice` 若还在，`ka2`（作用在 `ost.kind` 上、无条件优先）会把它
    顶成 `notice`——**用户的手工选择被静默改掉**，这正是 FIX 2 的反例。

    ⚠️ 变异反证：把 `commit_categories` 里的 `prune_aliases(cats)` 删掉 ⇒ 本条**必红**。
    """
    c = client_factory()
    item_id = client_factory.item_ids[1]
    assert c.post(f"/api/items/{item_id}/kind", json={"kind": "life"}).status_code == 200
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life"

    assert c.delete("/api/categories/life?migrate_to=notice").status_code == 204
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "notice", (
        "迁移之后那条条目该跟着走（`ka2` 的正当用途）"
    )

    r = c.post("/api/categories", json={"slug": "life", "desc": "加回来"})
    assert r.status_code == 201
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life", (
        "手工选的合法类目被旧别名顶掉了：不变量（alias.old_kind 不许是现存 slug）没被维持"
    )
    assert "life" not in c.get("/api/categories").json()["aliases"]


def test_api_a_manual_kind_follows_a_later_rename(client_factory):
    """⭐ FIX 2：手工改过的类目**也要**跟着 slug 改名走（我上一轮报的 C2）。

    ⚠️ 没有 `ka2` 的话：把那条条目手工改成 `life`、再把 `life` 改名成 `life_v2`
    ⇒ 它**永远停在 `life`**——一个已经不存在的 slug（spec §4.2 ④ 点名要禁）。

    ⚠️ 变异反证：把 `store._EFFECTIVE_KIND` 里的 `ka2.new_kind` 去掉
    （连同那条 JOIN）⇒ 本条**必红**（显示 `life`）。
    """
    c = client_factory()
    item_id = client_factory.item_ids[1]
    assert c.post(f"/api/items/{item_id}/kind", json={"kind": "life"}).status_code == 200

    assert c.put("/api/categories/life", json={"slug": "life_v2"}).status_code == 200
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life_v2", (
        "手工改过的类目没跟着改名走：界面上它指着一条不存在的 slug"
    )


def test_api_rename_keeps_the_alias_chain_alive(client_factory):
    """⭐ `prune_aliases(..., keep=slug)` 里那个 `keep` 的**理由**（实测）。

    链条：① 删 `academic`（迁移到 `life`）⇒ 别名 `academic→life`；
    ② 把 `life` 改名成 `life_v2` ⇒ 那条 `academic→life` 会被**扁平**成
    `academic→life_v2`（`set_kind_alias` 的第二步），条目走到 `life_v2`。

    ⚠️ 剪枝若用的 live 集**不含那个待废的 `life`**，`academic→life` 会在
    `set_kind_alias` **之前**被删掉 ⇒ 扁平的 UPDATE 找不到它 ⇒ 条目退化成
    裸 slug `academic`。⇒ `keep=slug` 不是顺手多传一个参数。

    ⚠️ 变异反证：把那次调用的 `keep=slug` 去掉 ⇒ 本条**必红**。
    """
    c = client_factory()
    item_id = client_factory.item_ids[0]          # 库里的 raw kind = academic
    assert c.delete("/api/categories/academic?migrate_to=life").status_code == 204
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life"

    assert c.put("/api/categories/life", json={"slug": "life_v2"}).status_code == 200
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life_v2", (
        "别名链在改名时被剪断了：条目退化成裸 slug（`keep=slug` 的意义就在这里）"
    )


def test_api_items_survives_an_unreadable_config(client, monkeypatch):
    """⭐ FIX 8：显示路径的降级必须**真的**降级——`OSError` 也算「读不出来」。

    ⚠️ T4 那轮只捕 `HTTPException`，于是「配置读不出来」里**只有** TOML 语法错
    会被降级；`OSError`（权限 / 文件被占 / 路径异常）**不是** `HTTPException`
    ⇒ 它一路冒成 500，把主页面整页黑掉。T4 的 re-reviewer 实测探针证实了这一点。

    ⚠️ 变异反证：把 `group_names_map()` 的 `except` 改回 `except HTTPException`
    ⇒ 本条**必红**（500）。⚠️ E7 判据：**放宽成 `except Exception` 之前，
    全仓没有任何东西会红**——这条缝从前没人守。

    ⚠️ 阳性对照的另一半在 `test_a_broken_config_degrades_the_display_paths_but_not_
    the_config_payload`：`/api/groups`（配置就是它的载荷）仍**保持响亮**。
    """
    import vigil.api as _api

    def boom(*_a, **_kw):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(_api, "load_config", boom)

    r = client.get("/api/items")
    assert r.status_code == 200, "`OSError` 也是「读不出来」，不许把信息流整页黑掉"
    assert r.json()["items"][0]["group_name"] == "12345", (
        "降级必须是**裸群号字符串**——不是空串、不是 None、更不是 500"
    )


def test_api_undo_refuses_a_corrupt_snapshot_without_consuming_it(client_factory):
    """⭐ FIX 5：坏快照被拒时**不许**把它从撤销栈里吃掉。

    ⚠️ 从前的顺序是 `pop` → 校验 ⇒ 坏快照被**静默消费**，用户下一次撤销会
    **多退一格**（跳过更早那次编辑），而响应只说「配置未被改动」——
    **那句话只对文件成立**。现在校验在消费之前：拒了就是拒了，栈原样。

    ⚠️ 变异反证：把 `pop_config_snapshot` 挪到校验**之前** ⇒ 本条**必红**
    （第二次撤销会回 `{"undone": false}` 而不是 500）。
    """
    from vigil import overrides as _ov

    c = client_factory()
    w = _ov.connect()
    try:
        _ov.save_config_snapshot(w, body="[[categories]\n", now=1)   # 坏 TOML
    finally:
        w.close()

    r = c.post("/api/categories/undo")
    assert r.status_code == 500 and "快照" in r.json()["detail"]
    # ⚠️ 关键：**第二次仍然是同一个错误**（栈没被消费），而不是「没有可撤销的」
    assert c.post("/api/categories/undo").status_code == 500, (
        "坏快照被静默消费了：第二次撤销退回「没得撤」，用户永远看不到那句 500 的原因"
    )
    w = _ov.connect()
    try:
        assert _ov.peek_config_snapshot(w) is not None, "peek 说栈空了——它被消费掉了"
    finally:
        w.close()


# ── M6 T6：重排 job + 人工批量改 ────────────────────────────────────
#
# ⚠️ 本节全部用例**必须**用 `fake_llm` / `slow_llm`：`/api/reorder` 背后是真
# `chat_json`，不换掉的话点一下按钮就是一次**联网**调用（Global Constraint 9）。
# 它们顺带把 `api.load_llm_key` 也换掉，理由见下面那个夹具的 docstring。

# 假模型判出的类目：与夹具库里前两条（`academic` / `life`）都不同 ⇒ 一定产生变更。
_NEW_KIND = "notice"

# 假模型的响应：**三条消息各一条**（第三批——222 群那条——也要有产出，
# 否则"两批"里有一批永远什么都不产出，进度与取消两条用例的"中途"就没意义了）。
# ⚠️ `quote` 必须**逐字**出现在正文里（`refine._match_source` 按摘录定位）。
_REORDER_PAYLOAD = {
    "items": [
        {"quote": "选课通知：9月16日截止", "kind": _NEW_KIND,
         "title": "选课通知", "confidence": 0.9},
        {"quote": "宿舍通知：本周五停水检修", "kind": _NEW_KIND,
         "title": "宿舍通知", "confidence": 0.9},
        {"quote": "兼职招聘：图书馆整理资料", "kind": _NEW_KIND,
         "title": "兼职通知", "confidence": 0.9},
    ]
}


@pytest.fixture
def fake_llm(monkeypatch):
    """假模型：把两条源消息都判成 `notice`（与库里那两条的类目都不同 ⇒ 一定变更）。

    ⚠️ **为什么连 `api.load_llm_key` 一起换掉**：它读的是**仓库根真实的 `.env`**
    （`load_llm_key()` 的默认路径 `config.DEFAULT_ENV` 是 import 期算好的常量，
    夹具的 `monkeypatch` 够不着 `config.REPO_ROOT`）。不换的话，这些用例的成败
    取决于「本机恰好配了密钥」——一条与环境相关的绿，而 CI/别人机器上是红。
    """
    from vigil import api as _api
    from vigil import reorder as _reorder
    from vigil.llm import LLMResult

    seen: list[str] = []

    def fake(cfg, *, system, user, **kw):  # noqa: ANN001, ANN003
        seen.append(user)
        return LLMResult(payload=_REORDER_PAYLOAD, input_tokens=10, output_tokens=5)

    monkeypatch.setattr(_reorder, "chat_json", fake)
    monkeypatch.setattr(_api, "load_llm_key", lambda *a, **k: "k-llm")
    return seen


@pytest.fixture
def slow_llm(monkeypatch):
    """假模型：**卡住不返回**，让 job 停在 `running`（用例结束后解封）。"""
    from vigil import api as _api
    from vigil import reorder as _reorder

    gate = threading.Event()

    def fake(cfg, *, system, user, **kw):  # noqa: ANN001, ANN003
        gate.wait(30)
        raise AssertionError("slow_llm 不该被解封")

    monkeypatch.setattr(_reorder, "chat_json", fake)
    monkeypatch.setattr(_api, "load_llm_key", lambda *a, **k: "k-llm")
    yield gate
    gate.set()


def test_api_reorder_starts_a_job_and_the_poll_says_it_finished(client_factory, fake_llm):
    """⭐ 出口判据 7 的接口形式：起一个 job、轮询到结束、结果落 overlay。"""
    c = client_factory()
    r = c.post("/api/reorder")
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    for _ in range(100):
        body = c.get(f"/api/jobs/{job_id}").json()
        if body["state"] != "running":
            break
        time.sleep(0.02)
    assert body["state"] == "done"
    assert body["kind"] == "reorder"


def test_api_reorder_refuses_a_second_job_while_one_runs(client_factory, slow_llm):
    c = client_factory()
    assert c.post("/api/reorder").status_code == 202
    assert c.post("/api/reorder").status_code == 409


def test_api_jobs_unknown_id_is_404(client_factory):
    assert client_factory().get("/api/jobs/nope").status_code == 404


def test_api_reorder_undo_returns_to_the_previous_kinds(client_factory, fake_llm):
    """⭐ 判据 7 的后半条：**撤销能回到重排前**。"""
    c = client_factory()
    item_id = client_factory.item_ids[0]
    before = c.get(f"/api/items/{item_id}").json()["kind"]

    job_id = c.post("/api/reorder").json()["job_id"]
    for _ in range(100):
        body = c.get(f"/api/jobs/{job_id}").json()
        if body["state"] != "running":
            break
        time.sleep(0.02)

    after = c.get(f"/api/items/{item_id}").json()["kind"]
    assert after != before, "夹具必须造出至少一条真的会变，否则本条是空守卫"

    r = c.post(f"/api/jobs/{job_id}/undo")
    assert r.status_code == 200
    assert c.get(f"/api/items/{item_id}").json()["kind"] == before


def test_api_bulk_set_kind_is_one_actor_so_it_can_be_undone_together(client_factory):
    """人工多选批量改：**同一次提交共用一个 actor**，于是能一次撤销。"""
    c = client_factory()
    ids = client_factory.item_ids[:2]
    before = [c.get(f"/api/items/{i}").json()["kind"] for i in ids]

    r = c.post("/api/items/kinds", json={"item_ids": ids, "kind": "life"})
    assert r.status_code == 200
    assert all(c.get(f"/api/items/{i}").json()["kind"] == "life" for i in ids)

    job_actor = r.json()["actor"]
    assert c.post("/api/bulk-undo", json={"actor": job_actor}).status_code == 200
    assert [c.get(f"/api/items/{i}").json()["kind"] for i in ids] == before


# ── M6 T6 fix loop 1：取消 / 进度 / 主库指纹 ────────────────────────


def _wait_for_job(client, job_id: str, *, timeout: float = 10.0) -> dict:
    """轮询到 job 结束（`state != "running"`）。超时**响亮地抛**。

    ⚠️ 超时不许静默返回一个半成品 dict：那样 `body["state"] == "done"` 会以
    「看起来像产品缺陷」的方式红，而真相是 job 卡住了（或夹具的假模型忘了放行）
    ——一条把排障指向错方向的假红。这里直接说清是哪一种。

    ⚠️ 轮询按**次数**而不是钟表（`test_two_reorders_never_share_an_actor` 会把
    `time.time` 冻住）——用 `time.time()` 计时的循环在那种用例里会**立刻超时**。
    """
    body: dict = {}
    for _ in range(int(timeout / 0.02)):
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["state"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} 一直没结束（{timeout}s）：{body}")


def _main_db_fingerprint(db: pathlib.Path) -> dict[str, str]:
    """主库 + 侧车文件的 sha256（与 `test_repass` / `test_reorder` 里那两条同形）。"""
    out: dict[str, str] = {}
    for suffix in ("", "-wal", "-shm", "-journal"):
        p = db if not suffix else db.with_name(db.name + suffix)
        out[suffix or "main"] = (
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "<missing>"
        )
    return out


class _GatedLLM:
    """假模型：**第 1 次**调用卡住等测试放行，之后各次立刻返回。

    ⚠️ 为什么要"卡住"：job 跑在后台线程里。没有它的话用例只能"等它跑完再断言"，
    而「取消」与「进度」这两个卖点**全在中途**——跑完就什么都看不到，
    两条用例都会退化成"看结果对不对"的空守卫。

    ⚠️ 只卡第一次：第二次立刻返回，这样「取消之后第二批还发不发」是可数的
    （`calls`）——那正是 `should_stop` 那条接线的机械判据。
    """

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.entered = threading.Event()   # 第 1 次调用已进入（确认"真的在飞"）
        self.gate = threading.Event()      # 测试放行
        self.calls = 0

    def __call__(self, cfg, *, system, user, **kw):  # noqa: ANN001, ANN003
        from vigil.llm import LLMResult

        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            self.gate.wait(30)
        return LLMResult(payload=self.payload, input_tokens=1, output_tokens=1)


@pytest.fixture
def gated_llm(monkeypatch):
    """见 `_GatedLLM`。⚠️ 同时换掉 `api.load_llm_key`（理由同 `fake_llm`）。"""
    from vigil import api as _api
    from vigil import reorder as _reorder

    llm = _GatedLLM(_REORDER_PAYLOAD)
    monkeypatch.setattr(_reorder, "chat_json", llm)
    monkeypatch.setattr(_api, "load_llm_key", lambda *a, **k: "k-llm")
    yield llm
    llm.gate.set()   # 收尾放行：别让工作线程一直挂在 chat_json 里


def test_api_cancel_stops_the_job_and_writes_nothing(client_factory, gated_llm):
    """⭐ 复审 Important-1：跑着的重排**必须能被中断**。

    ⚠️ 此前 `JobRegistry.cancel` **全仓零生产调用方**（只有测试碰它），
    而 `/api/jobs/{id}/undo` 的 409 却写着「先取消它再撤销」——
    要用户去做一件**做不到**的事，且那个 job 全程占着唯一的 JobBusy 名额。

    ⚠️ 这一条同时钉住**两条**接线，缺任何一条它就红：
      · 端点里真的调 `registry.cancel`（否则 `cancel.is_set()` 永远是 False）；
      · `plan_reorder` 的 `should_stop=job.cancel.is_set`（否则**第二批照发**）。
    """
    c = client_factory()
    item_id = client_factory.item_ids[0]
    before = c.get(f"/api/items/{item_id}").json()["kind"]

    job_id = c.post("/api/reorder").json()["job_id"]
    assert gated_llm.entered.wait(5), "假模型没被调到——后面全是空断言"
    assert c.get(f"/api/jobs/{job_id}").json()["state"] == "running"

    r = c.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200 and r.json()["cancelled"] is True

    # 取消是**协作式**的：它只可能在批次边界生效 ⇒ 必须先把在飞的那一批放行
    gated_llm.gate.set()
    body = _wait_for_job(c, job_id)

    assert body["state"] == "cancelled"
    assert gated_llm.calls == 1, (
        f"取消之后仍然发了第 {gated_llm.calls} 批——`should_stop` 没接到 `job.cancel`"
    )
    assert c.get(f"/api/items/{item_id}").json()["kind"] == before, (
        "取消之后还是把计划写进了 overlay —— `work()` 的取消早退没接线"
    )


def test_api_cancel_says_so_when_there_is_nothing_to_cancel(client_factory, fake_llm):
    """⚠️ 对**已经结束**的 job 点取消不是错误：200 + `cancelled: false`。

    ⚠️ 409 会把"手慢了一步"报成"你的请求有问题"，而前端此时需要的只是
    「它已经不在跑了」——`state` 就在同一个响应里。真正的 404 是**没有这个 job**。
    """
    c = client_factory()
    job_id = c.post("/api/reorder").json()["job_id"]
    _wait_for_job(c, job_id)

    r = c.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200
    assert r.json()["cancelled"] is False
    assert r.json()["state"] == "done"
    assert c.post("/api/jobs/nope/cancel").status_code == 404


def test_api_reorder_reports_progress_while_running(client_factory, gated_llm):
    """⭐ 复审 ⚠️W-2：`total` / `done` / `message` 必须**在跑的时候**就有值。

    ⚠️ 「等它跑完再断言」抓不到这条缺陷：那时 `total`/`done` 会被收尾逻辑填上，
    而 spec §4.2 ④ 要的"进度"全在中途。所以这里卡住第一批、在**中途**读一次。
    """
    c = client_factory()
    job_id = c.post("/api/reorder").json()["job_id"]
    assert gated_llm.entered.wait(5)

    mid = c.get(f"/api/jobs/{job_id}").json()
    assert mid["state"] == "running"
    assert mid["total"] == 2, (
        f"跑到中途 total={mid['total']}（夹具是两批）——进度没接线"
    )
    assert mid["done"] == 0
    assert "源消息" in mid["message"], f"跑到中途 message 是空的：{mid['message']!r}"

    gated_llm.gate.set()
    done = _wait_for_job(c, job_id)
    assert done["state"] == "done"
    assert (done["total"], done["done"]) == (2, 2)


def test_api_reorder_never_writes_the_main_db(client_factory, fake_llm):
    """⭐ D11 的机械判据，罩住**整条 API 路径**（含工作线程）。

    ⚠️ 与 `test_reorder.py::test_reorder_writes_only_overlay_and_never_touches_items`
    的分工：那条只罩 `plan_reorder` / `apply_reorder` 的调用路径。而 job 跑在
    **工作线程**里——复审实测过：线程里加一句 `UPDATE items SET deadline_ts=NULL`，
    上面那条**看不见**（它的指纹只在函数边界上取）。

    ⚠️ 生产 `db_uri` 是 `mode=ro`，所以那是**覆盖缺口**、不是现网漏洞；
    这条把缺口补上：谁的写落进主库，指纹就变。
    """
    c = client_factory()
    db = client_factory.db_path
    item_id = client_factory.item_ids[0]
    before_fp = _main_db_fingerprint(db)

    body = _wait_for_job(c, c.post("/api/reorder").json()["job_id"])
    assert body["state"] == "done"
    # ⚠️ 非空守卫：重排**真的改了东西**，否则"指纹没变"可能只是"什么都没干"
    assert c.get(f"/api/items/{item_id}").json()["kind"] == _NEW_KIND

    after_fp = _main_db_fingerprint(db)
    changed = [k for k in before_fp if before_fp[k] != after_fp[k]]
    assert not changed, f"`/api/reorder` 动了 data/vigil.db 的字节（D11）：{changed}"


def test_api_bulk_undo_refuses_an_actor_it_did_not_mint(client_factory):
    """⚠️ 复审 Minor-2：`{"actor": "web"}` 能把**尾部那一整段人工操作**撤掉。

    ⚠️ 撤掉的是什么值得说清：`delete` 行（条目重新可见）与墓碑行（D15 的
    「永不被重抽复活」保护）都在 `item_edits` 里、actor 都是 `web` ⇒
    一个"撤刚才那批重排"的误操作可以把**用户的删除**一起翻回来。

    ⚠️ **这条边界的性质**：它挡的是**误用**，不是**权限**——单机自用、没有
    用户模型，能点这个按钮的人本来就有权改。别把它读成一道安全边界。
    """
    c = client_factory()
    item_id = client_factory.item_ids[0]
    assert c.post(f"/api/items/{item_id}/kind", json={"kind": "life"}).status_code == 200

    r = c.post("/api/bulk-undo", json={"actor": "web"})
    assert r.status_code == 400
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life", (
        "被拒了却还是撤了——前缀闸必须在**写之前**"
    )


def test_api_bulk_set_kind_says_why_when_the_category_file_is_broken(client_factory):
    """⚠️ 复审 Minor-1：类目表读不出来时，`/api/items/kinds` 的 500 要**说出原因**。

    ⚠️ 两类响应都"响亮"（都是 500），差的只是**排障那一档**：裸
    `load_categories(...)` 让 `CategoryError` 逃出去，FastAPI 兜成一句
    `Internal Server Error`——用户与日志里**一个字的原因都没有**；
    `current_categories()` 会写清是 `config/categories.toml` 读不出来（还带上原始错误）。

    ⚠️ 这里**不降级**（与 `group_names_map()` 的显示路径刻意相反）：类目表是这条
    端点的**前提**——不知道有哪些类目就判不了 `kind` 合不合法。
    """
    from vigil import api as _api

    c = client_factory(raise_server_exceptions=False)   # 见工厂的 docstring
    cfg = _api.REPO_ROOT / "config" / "categories.toml"
    cfg.write_text("[[categories]\nslug = \"broken\"\n", encoding="utf-8")   # 坏 TOML

    r = c.post("/api/items/kinds", json={"item_ids": [1], "kind": "life"})
    assert r.status_code == 500
    # ⚠️ 断言 `r.text` 而不是 `r.json()["detail"]`：变异体（裸 `load_categories`）
    # 的响应体是 Starlette 那句**纯文本** `Internal Server Error`，`r.json()`
    # 会先抛 JSONDecodeError ⇒ 又变成"红的原因不是这条断言"。
    assert "categories.toml" in r.text and "读不出来" in r.text, (
        f"500 没有说出原因（用户只能看到一句 Internal Server Error）：{r.text[:200]!r}"
    )


def test_two_reorders_never_share_an_actor(client_factory, fake_llm, monkeypatch):
    """⭐ 复审 Minor-2 的另一半：`actor` 里必须有随机性，不只是秒级时间戳。

    ⚠️ 后果是具体的：两个 job 撞成同一个 actor ⇒ 第二次的 `undo_batch`
    会把**两次重排的事件一起撤掉**（它们尾部连续、actor 相同），
    而用户以为自己只撤了后一次。

    ⚠️ 时钟**冻结**是刻意的：正常跑的话两次 POST 之间时钟总会走一点，
    这条就成了"看运气"的守卫——夹具给的输入必须真的区分得开（E7 的默认值陷阱）。
    """
    from vigil import api as _api

    monkeypatch.setattr(_api.time, "time", lambda: 1_700_000_000)
    c = client_factory()
    first = c.post("/api/reorder").json()
    _wait_for_job(c, first["job_id"])
    second = c.post("/api/reorder").json()
    assert first["actor"] != second["actor"], (
        "同一个秒里两个 job 撞成同一个 actor ⇒ 撤销会把两次重排一起撤掉"
    )


# ── M6 T5 Fix loop 2：撤销要整表还原别名（FIX 1）+ 写失败要保守（FIX 3）──


def test_api_undo_restores_the_alias_table_along_with_the_file(client_factory):
    """⭐ C-1：**改两次名再撤销一次**——配置与别名表必须**一起**回到同一时刻。

    ⚠️ 从前只回滚文件：配置停在中间名 `life_v2`，而条目显示的是**裸 slug**
    （别名表空、`life_v2` 角标 0）。根因是 `set_kind_alias` 的**压平 UPDATE
    已经把可复原的信息改掉了**——`life→life_v2` 在第二次改名时被改写成了
    `life→life_v3`，"上一次的表"从文件名里反推不出来。

    ⚠️ 变异反证：把 `api_category_undo` 里的 `replace_kind_aliases` 换回
    「按还原后的 slug 集剪枝」（Fix loop 1 的写法）⇒ 本条**必红**（裸 slug）。

    ⚠️ 另外查过：「改名 + **带迁移删除** + 撤销」那条路**不需要**这一步
    ——剪枝恰好也能修好它（那条 `旧名→迁移目标` 行的 old_kind 一回到现存集里
    就会被剪掉）。**能区分两种实现的只有这条"连改两次名"**。
    """
    c = client_factory()
    item_id = client_factory.item_ids[1]          # 库里的 raw kind = life
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life"

    assert c.put("/api/categories/life", json={"slug": "life_v2"}).status_code == 200
    assert c.put("/api/categories/life_v2", json={"slug": "life_v3"}).status_code == 200
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life_v3"

    assert c.post("/api/categories/undo").status_code == 200
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life_v2", (
        "撤销之后条目显示的是裸 slug：配置文件回去了、别名表没回去"
    )
    assert c.get("/api/categories").json()["aliases"] == {"life": "life_v2"}
    assert "life_v2" in {x["slug"] for x in c.get("/api/categories").json()["categories"]}


def test_api_undo_after_a_delete_with_migration_restores_the_alias_table(client_factory):
    """同上的另一半：**带迁移的删除**撤销之后，条目要回到被删掉的那个 slug。

    ⚠️ 这一条与上一条**不是**同一个判据（上一条才区分得出"整表替换 vs 剪枝"），
    留着它是因为「删除 + 迁移」是本端点的另一半用法，撤销要一起覆盖。
    """
    c = client_factory()
    item_id = client_factory.item_ids[0]          # 库里的 raw kind = academic
    assert c.delete("/api/categories/academic?migrate_to=life").status_code == 204
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life"

    assert c.post("/api/categories/undo").status_code == 200
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "academic"
    assert c.get("/api/categories").json()["aliases"] == {}


def test_api_a_failed_write_leaves_the_alias_table_alone(client_factory, monkeypatch):
    """⭐ FIX 3：**写文件失败时别名表一动不动**（保守），而不是"剪了但没写成"。

    ⚠️ 顺序反过来的话（先剪、后写）：写失败留下的是「别名已按新 slug 集剪掉、
    文件还是旧集」——**不变量当场破**，而 `reconcile_if_stale` 只会在
    **下一次读**时才把它对平。Windows 上文件被占用是真实可发生的失败。

    场景：① 删 `academic`（迁移到 `life`）⇒ 别名 `academic→life`；
    ② 把 `academic` 加回来，但**让写文件失败**。
    ⇒ 那条别名必须**还在**（它此刻还在把 `academic` 的条目映射到 `life`）。

    ⚠️ 变异反证：把 `commit_categories` 里的顺序换回"先剪枝、后写文件"
    ⇒ 本条**必红**（条目显示裸 slug `academic`）。
    """
    from vigil import categories as categories_mod

    c = client_factory()
    item_id = client_factory.item_ids[0]          # raw kind = academic
    assert c.delete("/api/categories/academic?migrate_to=life").status_code == 204
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life"

    def boom(*_a, **_kw):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(categories_mod, "atomic_write_text", boom)
    with pytest.raises(OSError):
        c.post("/api/categories", json={"slug": "academic", "desc": "加回来"})

    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life", (
        "写失败却把别名剪掉了：文件里还留着旧状态，条目却已经开始悬空"
    )


# ── M6 T5 Fix loop 3：写窗口 vs 并发读（FIX 2）+ 生产路径（FIX 3）────


def test_a_concurrent_read_cannot_prune_a_freshly_written_alias(client_factory, monkeypatch):
    """⭐ FIX 2：写端点的窗口（**别名已写、文件还没写**）里插进一次**读**，
    不许把那条刚写进去的别名剪掉。

    ⚠️ 为什么那条别名会被剪：窗口里**磁盘上那份文件还是旧的**，而那条别名的
    `new_kind`（`life_v2`）在旧文件里**不存在** ⇒ 对账按"目标不存在"删掉它 ⇒
    文件写完之后配置里也没有 `life` 了 ⇒ 条目**永久悬空**（spec §4.2 ④）。

    ⚠️ 判据在**条目那一侧**（不是"别名表里有几行"）：别名的职责就是让条目走在
    合法的 slug 上。

    ⚠️ 为什么必须用**真线程**：`ALIAS_LOCK` 是 `RLock`——同一条线程里嵌套调用
    是**可重入**的（写端点自己也会经 `store.kind_counts` 走到对账，正是为此选的
    RLock），只有**另一条线程**才会被挡住。

    ⚠️ 测试先"手改"一次文件（内容等价、多一行注释）把闸门**打开**：对账是按
    `(mtime_ns, size)` 判断"这份文件我看过没有"的，窗口里文件没变时它压根不会跑
    ——reviewer 探针 P2 抓到的正是"闸门开着 + 窗口里来了一次读"。

    变异反证：把 `reconcile_if_stale` 里的 `with ALIAS_LOCK:` 去掉 ⇒ 本条**必红**。
    """
    import threading

    from vigil import categories as categories_mod
    from vigil import overrides as ov_mod

    c = client_factory()
    item_id = client_factory.item_ids[1]          # 库里的 raw kind = life
    assert c.post(f"/api/items/{item_id}/kind", json={"kind": "life"}).status_code == 200

    # 外部手改一次 ⇒ 闸门开（`FIX 3` 之后那份文件与端点写的是同一个）
    cfg = _cats_mod.DEFAULT_CATEGORIES
    cfg.write_text(cfg.read_text(encoding="utf-8") + "# 手改\n", encoding="utf-8")

    real_save = categories_mod.save_categories
    read_done = threading.Event()
    seen: list[str] = []

    def reader() -> None:
        # 这次读会走到 `store._ensure_overlay` ⇒ 对账 ⇒ 抢 ALIAS_LOCK
        try:
            seen.append(c.get(f"/api/items/{item_id}").json()["kind"])
        finally:
            read_done.set()

    def slow_save(cats, path=None):
        threading.Thread(target=reader, daemon=True).start()
        # ⚠️ 带锁时它拿不到锁 ⇒ 一直停在这儿 ⇒ 这里超时（超时只影响**耗时**，
        # 不影响结论：带锁时那次读**不可能**在窗口里剪枝）；
        # 不带锁时它立刻跑完，并**在窗口里**把那条别名剪掉。
        read_done.wait(0.8)
        return real_save(cats, path)

    monkeypatch.setattr(categories_mod, "save_categories", slow_save)
    assert c.put("/api/categories/life", json={"slug": "life_v2"}).status_code == 200
    assert read_done.wait(5), "读线程没回来（夹具写错了）"

    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life_v2", (
        "并发的一次读把刚写进去的别名剪掉了：配置里已经没有 life ⇒ 条目悬空"
    )
    assert seen == ["life_v2"], f"窗口里那次读看到的是 {seen}（它不该看见旧状态）"
    # 收尾：别名表此刻与文件一致（对账与写端点都没有留下破口）
    w = ov_mod.connect()
    try:
        assert ov_mod.kind_aliases(w) == {"life": "life_v2"}
    finally:
        w.close()


def test_a_hand_edit_of_the_endpoint_config_is_reconciled_on_the_next_read(client_factory):
    """⭐ FIX 3：**生产路径**（端点写 `categories.toml` ⇒ 下一次读按 mtime 触发对账）
    要真的被跑过一次。

    ⚠️ 从前夹具里「对账读的那份」（conftest 挪到的那个 tmp 根）与
    「端点写的那份」（`_groups_root` 的假根）是**两个文件**
    ⇒ **这条路径测试从未跑过**——而那正是 I-2（手改把 slug 加回来之后别名没对平）
    一直没被抓到的原因。

    变异反证：把 `_groups_root` 里那句
    `monkeypatch.setattr(_cats_mod, "DEFAULT_CATEGORIES", root / "config" / "categories.toml")`
    删掉 ⇒ 本条**必红**（对账读的是另一个文件，永远看不到这次手改）。
    """
    c = client_factory()
    item_id = client_factory.item_ids[1]          # 库里的 raw kind = life
    assert c.post(f"/api/items/{item_id}/kind", json={"kind": "life"}).status_code == 200
    assert c.put("/api/categories/life", json={"slug": "life_v2"}).status_code == 200
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life_v2"

    # **手改**那份文件（就是端点写的那份）：把 `life` 加回来
    cfg = _cats_mod.DEFAULT_CATEGORIES
    cfg.write_text(
        cfg.read_text(encoding="utf-8")
        + '\n[[categories]]\nslug = "life"\nlabel = "生活"\ndesc = "手改加回来的"\n',
        encoding="utf-8",
    )

    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life", (
        "手改之后没对账：合法的手工类目 life 被旧别名顶成了 life_v2"
    )


# ── M6 T7：配置包端点 ───────────────────────────────────────────────


def test_api_export_pack_returns_toml_text(client_factory):
    body = client_factory().get("/api/config/pack").json()
    assert "[[categories]]" in body["toml"]
    assert "[[persons]]" in body["toml"]


def test_api_import_pack_rejects_a_bad_document(client_factory):
    c = client_factory()
    r = c.post("/api/config/pack", json={"toml": "[settings\n", "apply": True})
    assert r.status_code == 400


def test_api_import_pack_applies(client_factory):
    c = client_factory()
    text = c.get("/api/config/pack").json()["toml"]
    r = c.post("/api/config/pack", json={"toml": text, "apply": True})
    assert r.status_code == 200
    assert r.json()["categories"] >= 1


def test_api_import_pack_returns_400_not_500_for_a_shape_error(client_factory, tmp_path):
    """⭐ C6 在**端点层**的形态：形状错的**外部**包必须是 400，不是 500。

    ⚠️ 这正是 C6（T2 的 deferred）挡着 T7 的理由：`configpack.parse` 消费
    `validate_config_raw`，而它接的是**用户拷来拷去的文件**。修前
    `groups = [1, 2]` 抛 `AttributeError` ⇒ FastAPI 兜成 **500**——排障方向
    完全错（去查服务端，而真相是包写错了）。

    ⚠️ `groups = [1, 2]` 写在 `[settings]` **之前**，且 `qq_db_dir` 指向一个
    **真实存在**的目录：`validate_config_raw` 先查 `[settings]`（含 `.is_dir()`）
    再进群循环——不这么写，这个包会死在「QQ 数据库目录不存在」那条更早的分支上，
    C6 的守卫**根本不在执行路径上**（勘误 E7 的形态 5）。

    ⚠️ `raise_server_exceptions=False` 是**承重的**：默认 True 时那个异常会在
    测试里重新抛出，「响应到底是不是 400」根本断言不到——那是一条
    "看起来在守、实际只能证明它抛了"的空守卫（T4 的 FIX 里记过这一条）。

    ⚠️ 变异反证：把 `config.validate_config_raw` 里那句 `isinstance(entry, dict)`
    删掉 ⇒ 本条**必红**（500 + `AttributeError`）。
    """
    c = client_factory(raise_server_exceptions=False)
    broken = (
        "schema = 1\n"
        "groups = [1, 2]\n"
        "\n"
        "[settings]\n"
        f'qq_db_dir = "{tmp_path.as_posix()}"\n'
        f'output_db = "{(tmp_path / "vigil.db").as_posix()}"\n'
        "\n"
        "[[categories]]\n"
        'slug = "notice"\n'
        'label = "通知"\n'
        'desc = "正式通知"\n'
    )
    r = c.post("/api/config/pack", json={"toml": broken, "apply": True})
    assert r.status_code == 400, r.text
    assert "键值表" in r.json()["detail"]
