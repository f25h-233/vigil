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
    assert {"slug", "label", "icon", "count"} == set(cats[0])
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


def test_write_kind_does_not_touch_vigil_db(client, db_path):
    """⭐ D11 的机械守卫：写端点跑完，`data/vigil.db` 的字节必须**一点没变**。

    ⚠️ 这不是"检查没报错"——是把**整个文件的哈希**前后比。
    任何绕过 overlay 直接写主库的实现，都会在这里变红。
    """
    import hashlib

    before = hashlib.sha256(db_path.read_bytes()).hexdigest()

    r = client.post("/api/items/1/kind", json={"kind": "life"})
    assert r.status_code == 200
    assert r.json()["edit_id"] > 0

    assert hashlib.sha256(db_path.read_bytes()).hexdigest() == before, (
        "⚠️ 写端点动了 data/vigil.db——D11 的机械保证被打破"
    )


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
    """⭐ R10 的另一半：**转义**（`config._toml_str`，T7 已做）与**拒绝**（API）各管一半。

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
