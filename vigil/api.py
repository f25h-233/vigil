"""只读 JSON API + 前端静态托管。

**只读是机械保证，不是口头约定**：连接一律 ``mode=ro`` 打开，
写操作会被 SQLite 直接拒绝（实测 ``attempt to write a readonly database``）。
这样 Web 这一侧永远不可能改到 `data/vigil.db`。

⚠️ **每请求一条连接**，不复用：FastAPI 的同步端点跑在线程池里，而
``sqlite3.Connection`` 默认不能跨线程。本地文件开连接是微秒级，
省下的复杂度远比省下的那点时间值钱。
"""

from __future__ import annotations

import datetime as dt
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from . import store
from .categories import load_categories
from .config import REPO_ROOT, Config

WEB_DIST = REPO_ROOT / "web" / "dist"

MAX_LIMIT = 200


def _parse_day(day: str) -> dt.date:
    try:
        return dt.datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"日期格式应为 YYYY-MM-DD，收到：{day}"
        )


def _day_start(day: str, *, plus_days: int = 0) -> int:
    """``YYYY-MM-DD`` → **本地**当天 00:00 的 epoch 秒。

    ⚠️ 必须用 ``datetime`` 而不是 SQLite 的 ``strftime('%s', ...)``：后者按
    **UTC** 解释同一个日期串，与产品的「本地日」口径差 8 小时（M2 实测记录）。
    """
    d = _parse_day(day) + dt.timedelta(days=plus_days)
    return int(dt.datetime.combine(d, dt.time.min).timestamp())


def _day_of(ts: int) -> str:
    """窗口起点 → 本地日期字符串，与 ``_day_start`` 互逆。"""
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="VIGIL 守夜人", docs_url=None, redoc_url=None)

    db_path = config.output_db
    db_uri = f"file:{db_path.as_posix()}?mode=ro"
    names = {g.id: g.name for g in config.groups}
    cats = load_categories()
    cat_by_slug = {c.slug: c for c in cats}

    def connect() -> sqlite3.Connection:
        # ⚠️ 只开 `mode=ro`，且**绝不**在这里调 `store.ensure_schema`——
        # 它内部会 `rebuild_search_index`（`INSERT INTO items_fts(...) VALUES
        # ('rebuild')`），是**写操作**，在只读连接上是硬失败：
        # `OperationalError: attempt to write a readonly database`。
        # 建表/重建索引属于写路径（refine / digest），不归这里。
        return sqlite3.connect(db_uri, uri=True)

    def item_out(it: store.ApiItem) -> dict:
        cat = cat_by_slug.get(it.kind)
        return {
            "item_id": it.item_id,
            "kind": it.kind,
            "kind_label": cat.label if cat else it.kind,
            "kind_icon": cat.icon if cat else "",
            "title": it.title,
            "detail": it.detail,
            "event_ts": it.event_ts,
            # ⚠️ 这里**不做二次核验**，因为未经核验的值在数据层就已经是 NULL
            # （见 vigil/deadline.py）。这正是「把核验提到数据层」的收益：
            # 读取方不需要各自记得再挡一次——那种「每个读者都要记得」的约定
            # 迟早会有人忘（M2 只在日报挡过，Web 差一点就把幻觉日期复活了）。
            "deadline_ts": it.deadline_ts,
            "group_id": it.group_id,
            "group_name": names.get(it.group_id, str(it.group_id)),
            "actor": it.actor,
            "place": it.place,
            "amount": it.amount,
            "links": list(it.links),
            "source_count": it.source_count,
        }

    @app.get("/api/categories")
    def api_categories() -> dict:
        con = connect()
        try:
            counts = store.kind_counts(con)
        finally:
            con.close()
        return {
            "categories": [
                {
                    "slug": c.slug,
                    "label": c.label,
                    "icon": c.icon,
                    "count": counts.get(c.slug, 0),
                }
                for c in cats
            ]
        }

    @app.get("/api/items")
    def api_items(
        kind: str | None = None,
        since: str | None = None,
        until: str | None = None,
        group: int | None = None,
        q: str | None = None,
        limit: int = Query(50, ge=1, le=MAX_LIMIT),
        offset: int = Query(0, ge=0),
    ) -> dict:
        # since/until 都按**包含该日**理解：内部窗口右端取次日 00:00（左闭右开）。
        # 否则选了 9/13 却搜不到 9/13 当天，是最容易让人不信任搜索的错法。
        q = (q or "").strip()
        con = connect()
        try:
            items, total = store.search_items(
                con,
                kind=kind or None,
                since=_day_start(since) if since else None,
                until=_day_start(until, plus_days=1) if until else None,
                group=group,
                q=q or None,
                limit=limit,
                offset=offset,
            )
        finally:
            con.close()
        return {
            "items": [item_out(it) for it in items],
            # ⚠️ total 是**符合筛选条件的总数**，与 limit/offset 无关（不是当页条数）。
            # 前端三处依赖它：分页按钮出不出、「共 N 条」、「还有 N 条」。
            # store.search_items 已经把两者一起返回，这里照传即可。
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/items/{item_id}")
    def api_item(item_id: int) -> dict:
        con = connect()
        try:
            it = store.get_item(con, item_id)
            if it is None:
                raise HTTPException(status_code=404, detail=f"没有这条条目：{item_id}")
            payload = item_out(it)
            payload["sources"] = [
                {
                    "msg_id": s.msg_id,
                    "ts": s.ts,
                    # ⚠️ 这里**不**把空署名统一成 None：SourceRow.sender 的契约是
                    # `str`（无署名 = ""），ApiItem.actor 的契约是 `str | None`。
                    # 前端 types.ts 也分别是 `sender: string` / `actor: string | null`。
                    # 「顺手统一一下」会让契约与前端类型对不上。
                    "sender": s.sender,
                    "group_name": names.get(s.group_id, str(s.group_id)),
                    "content": s.content,
                }
                for s in store.source_messages(con, item_id)
            ]
            return payload
        finally:
            con.close()

    @app.get("/api/digests")
    def api_digests(limit: int = Query(30, ge=1, le=MAX_LIMIT)) -> dict:
        con = connect()
        try:
            # store.list_digests 按 window_from 排序（不是 digest_id）——契约要的
            # 就是「最近的在前」，同日多篇的窗口起点相同，顺序由 LIMIT 内的天然序决定。
            rows = store.list_digests(con, limit=limit)
        finally:
            con.close()
        return {
            "digests": [
                {
                    "digest_id": r.digest_id,
                    "day": _day_of(r.window_from),
                    "window_from": r.window_from,
                    "window_to": r.window_to,
                    "created_at": r.created_at,
                    "item_count": r.item_count,
                }
                for r in rows
            ]
        }

    @app.get("/api/digests/{digest_id}")
    def api_digest(digest_id: int) -> dict:
        con = connect()
        try:
            row = store.get_digest(con, digest_id)
            if row is None:
                raise HTTPException(status_code=404, detail=f"没有这篇日报：{digest_id}")
            items = store.digest_items(con, digest_id)
        finally:
            con.close()
        return {
            "digest_id": row.digest_id,
            "day": _day_of(row.window_from),
            "window_from": row.window_from,
            "window_to": row.window_to,
            "created_at": row.created_at,
            "item_count": row.item_count,
            "body_md": row.body_md,
            "items": [item_out(it) for it in items],
        }

    # ⚠️ **不要**用 `app.mount("/assets", StaticFiles(...))` 那一套。
    #
    # 挂载只覆盖 /assets 前缀，而 PWA 要的 `/sw.js`、`/manifest.webmanifest`、
    # `/icon-192.png` 全在**根路径**上——它们会掉进下面的 SPA 兜底，被当成
    # 前端路由返回一份 **200 的 index.html**。实测（真实进程 + curl）：
    #
    #     GET /manifest.webmanifest → 200  712 字节   ← 712 就是 index.html 的大小
    #     GET /sw.js                → 200  712 字节
    #     GET /icon-192.png         → 200  text/html
    #
    # 后果是浏览器把 HTML 当 manifest 解析、把 HTML 当 Service Worker 注册
    # （MIME 不符直接失败），「添加到主屏」整条路走不通——**而所有状态码都是
    # 200，日志上一个异常都没有**。这类缺陷只有真跑进程才现形。
    _MIME = {
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

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """静态文件 + SPA 兜底。三件事按序：挡 /api、发真文件、发前端入口。

        ⚠️ 三条边界都必须挡：
        * ``/api/*`` **不能**落进兜底——否则 `GET /api/typo` 会返回 200 的 HTML，
          调用方 ``r.json()`` 直接炸，而真正的 404 被吞掉。
        * **真存在的静态文件必须先发**（见上面 _MIME 的说明）。
        * 前端**没构建**时不许返回空白页，要明说「去跑 npm run build」——
          与日报同一条规矩：只说自己有资格说的话，没构建就说没构建。

        ⚠️ ``WEB_DIST`` 与派生的两个路径都**必须在这里现读**，不能在 create_app
        时算好冻进闭包：测试用 ``monkeypatch.setattr(api, "WEB_DIST", ...)`` 换掉
        它，冻住的话那些测试测的还是真实 web/dist（本机已构建，于是全都变成
        「怎么改都绿」的空守卫）。
        """
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"没有这个端点：/{full_path}")

        dist_root = WEB_DIST.resolve()
        index_file = dist_root / "index.html"

        if full_path:
            # 这是全文件里唯一一处把**用户输入**拼进文件路径的地方，
            # 所以目录逃逸（`../.env` 之类）必须在这里挡死。
            candidate = (dist_root / full_path).resolve()
            if candidate.is_relative_to(dist_root) and candidate.is_file():
                return FileResponse(
                    candidate, media_type=_MIME.get(candidate.suffix.lower())
                )
            # 请求的是**前端要用的那类静态资源**（js/css/图标/webmanifest…）而
            # 磁盘上没有 → 宁可 404，绝不许拿 index.html 顶。否则「manifest 不存在」
            # 会变成「manifest 是 HTML」：浏览器解析失败，而状态码是 200——
            # 正是上面那三个字段实测出来的同一类假绿。
            if candidate.suffix.lower() in _MIME:
                raise HTTPException(
                    status_code=404, detail=f"没有这个静态文件：/{full_path}"
                )

        if not index_file.is_file():
            return HTMLResponse(
                "<meta charset='utf-8'>"
                "<body style='font-family:sans-serif;padding:2rem'>"
                "<h1>前端尚未构建</h1>"
                "<p>请在仓库根目录运行：</p>"
                "<pre>cd web &amp;&amp; npm install &amp;&amp; npm run build</pre>"
                "</body>",
                status_code=503,
            )
        return FileResponse(index_file)

    return app
