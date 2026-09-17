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
import pathlib
import sqlite3

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from . import overrides, store
from .categories import load_categories
from .config import REPO_ROOT, Config, Person, load_persons, save_persons

WEB_DIST = REPO_ROOT / "web" / "dist"

MAX_LIMIT = 200

# ⚠️ 这张表同时承担**两个**职责，动它之前先看清两种后果不一样：
#
#   1) 真文件发出去时的 media type：`FileResponse(..., media_type=_MIME.get(suffix))`。
#      **删掉某个键，这里照样对**——`media_type=None` 时 Starlette 会回落到
#      `mimetypes.guess_type`（实测 `.js → text/javascript`）。
#   2) 「这个后缀是静态资源、不是前端路由」的判据：`if suffix in _MIME: 404`。
#      **删掉同一个键，这里静默坏掉**——该后缀不再被判为静态资源，缺文件时
#      一路落进 SPA 兜底，返回 **200 的 index.html**。
#
# 于是「删键」的后果**只**出现在职责二上，而所有只看 content-type 的测试都抓不到
# （浏览器把 HTML 当 JS/manifest 解析失败，而状态码全是 200——正是上面那段
# 注释里实测过的同一类假绿）。键与值都被 `tests/test_api.py` 逐字钉死。
#
# 定义在**模块级**而不是 `create_app` 内部：它是被测试直接断言的冻结契约
# （`api._MIME`）。放进 `create_app` 里，测试就够不着这张表了。
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

    ⚠️ 「能解析成日期」与「能表示成 epoch 秒」是**两件事**，所以坏输入有两种
    形状：``1970-01-01``（早于 epoch）在 ``timestamp()`` 上抛 ``OSError``；
    ``9999-12-31`` 配 ``plus_days=1`` 连 ``date + timedelta`` 都过不去，抛
    ``OverflowError``。它们都是**合法日期**，于是径直穿过 ``_parse_day`` 那
    一关——格式错的给 400、范围错的给 500，是同一个文件里两套错误处理，
    这正是这次缺陷的成因。所以这里**也要转 400**，与 `_parse_day` 同形。
    """
    try:
        d = _parse_day(day) + dt.timedelta(days=plus_days)
        return int(dt.datetime.combine(d, dt.time.min).timestamp())
    except (OSError, OverflowError, ValueError):
        # ValueError 其实已被 _parse_day 转成 400 了，多捕它一层只是不让
        # 任何一条漏网的转换异常有机会变成 500。
        raise HTTPException(
            status_code=400,
            detail=f"日期超出可表示范围（是合法日期，但转不成时间戳），收到：{day}",
        )


def _day_of(ts: int) -> str:
    """窗口起点 → 本地日期字符串，与 ``_day_start`` 互逆。"""
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _reject_controls(value: str, field: str) -> None:
    """`label` / `note` 里有换行或别的控制字符 ⇒ **400**（R10：转义与拒绝各管一半）。

    ⚠️ `config._toml_str` 已经能把这些字符**转义**成合法 TOML 并按原样读回来
    （那是 T7 完成的另一半），但「存得进去」不等于「应该存」：
    `config/*.toml` 是**人手输**的，把一个换行静默存进一个"名字"里、
    再在界面上错乱显示，是**最不诚实**的做法——而它一旦落盘，
    只能靠人肉去看那个文件才发现得了。
    名字/备注里要换行没有任何正当用途，所以这里选择**响亮地拒绝**。
    """
    if any(ch < " " or ord(ch) == 0x7F for ch in value):
        raise HTTPException(
            status_code=400,
            detail=f"{field} 里不能有换行/控制字符（C0 与 DEL）——"
            "名字里要换行没有任何正当用途，静默存下去只会在界面上错乱显示",
        )


def _edit_id_of(body: dict | None) -> int | None:
    """请求体里的 `edit_id`：**只接受真正的整数**，缺省/``null`` ⇒ ``None``（撤最近一条）。

    ⚠️ 不能写成 `int(body.get("edit_id"))`（M5 终审 Important-4 实测）：
    ``"abc"`` 抛 ``ValueError`` ⇒ **500**（而同一文件里 `_day_start` 早就把
    「转不成就 400」做成了规矩）；``1.9`` 会被 ``int()`` **静默截断**成 1
    ⇒ 撤掉的是**另一条**事件，而调用方从响应里看不出区别。
    ``bool`` 也要挡：``True`` 是 ``int`` 的子类（``True == 1``），会静默变成 edit_id 1。

    ⚠️ 契约是「整数」而不是「能转成整数的东西」：``"3"`` 这种字符串也拒——
    给「静默转一下」留口子，就等于把「1.9 截断」那类缺陷换个形状请回来。
    """
    if not isinstance(body, dict):
        return None
    target = body.get("edit_id")
    if target is None:
        return None
    if isinstance(target, bool) or not isinstance(target, int):
        raise HTTPException(
            status_code=400,
            detail=f"edit_id 必须是整数（null = 撤最近一条），收到：{target!r}",
        )
    return target


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="VIGIL 守夜人", docs_url=None, redoc_url=None)

    db_path = config.output_db
    db_uri = f"file:{db_path.as_posix()}?mode=ro"
    names = {g.id: g.name for g in config.groups}
    cats = load_categories()
    cat_by_slug = {c.slug: c for c in cats}

    # ⚠️ overlay 的**文件**在这里就位（D11 允许 Web 写 overlay）。之后每个
    # 请求的 `store._ensure_overlay(conn)` 才能无条件 ATTACH。
    # ⚠️ **不能**在这里调 `store.ensure_schema`——那是写 `vigil.db`，
    # 而本文件的连接是 `mode=ro`（见 connect() 的 docstring）。
    overrides.ensure_schema()

    def persons_path() -> pathlib.Path:
        """⚠️ 路径**每次现读** `REPO_ROOT` 全局，不许在 `create_app` 时算好冻进闭包。

        这与 `WEB_DIST` 的既有教训是同一件事（`api.py:289-292` 的 docstring 专门记过）：
        冻住的话，测试里 `monkeypatch.setattr(api, "REPO_ROOT", tmp_path)` 就够不着它，
        于是那些测试**测的还是仓库里真实的 `config/persons.toml`**——
        **会往真仓库里写人**，而且因为它们总能读到点什么、于是全都变成「怎么改都绿」的空守卫。
        """
        return REPO_ROOT / "config" / "persons.toml"

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
            "actor_uin": it.actor_uin,
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
        kind: list[str] = Query(default=[]),
        person: list[int] = Query(default=[]),
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
                kinds=kind or None,
                actor_uins=person or None,
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

    @app.post("/api/items/{item_id}/kind")
    def api_set_kind(item_id: int, body: dict = Body(...)) -> dict:
        """改一条条目的类目。**只写 overlay**（D11）。

        ⚠️ `kind` 也要过 `_reject_controls`（与 `api_add_person` 的 label/note
        同一条判据，同一个 helper——M5 终审 Important-2 实测）：`kind` 是
        **日报的章节标题**（`digest.render_markdown` 按 kind 分桶），一个带换行的
        kind 会让任意文本成为日报的一节，落进 `docs/digests/*.md`（**入 git 的归档**）
        与 `digests.body_md`。这跟"名字里有没有换行"是同一件事，只是后果更重。
        """
        kind = str(body.get("kind", "")).strip()
        if not kind:
            raise HTTPException(status_code=400, detail="kind 不能为空")
        _reject_controls(kind, "kind")
        con = connect()
        try:
            if store.get_item(con, item_id) is None:
                raise HTTPException(status_code=404, detail=f"没有这条条目：{item_id}")
        finally:
            con.close()
        ov = overrides.connect()
        try:
            return {"edit_id": overrides.set_kind(ov, item_id=item_id, kind=kind)}
        finally:
            ov.close()

    @app.delete("/api/items/{item_id}")
    def api_delete_item(item_id: int) -> dict:
        """软删一条条目（D15）。`msg_id` 从**源消息**取，用于"永不被重抽复活"。

        ⚠️ **每一条源消息都要落墓碑**（E7）：`store.save_items` 的批内去重
        **来源取并集**，所以一个 item 可以有 ≥2 条源消息。只墓碑化 `srcs[0]`
        的话，`refine --redo` 重抽兄弟消息会让条目**以新 item_id 复活**（违反 D15）。
        `overrides.delete_item` 的 `extra_msg_ids` 就是把这一点收在**唯一一条**
        写路径里——多开一个"只墓碑化第一条"的函数，等于给后来者留一条静默退化的路。
        """
        con = connect()
        try:
            if store.get_item(con, item_id) is None:
                raise HTTPException(status_code=404, detail=f"没有这条条目：{item_id}")
            srcs = store.source_messages(con, item_id)
        finally:
            con.close()
        ov = overrides.connect()
        try:
            return {
                "edit_id": overrides.delete_item(
                    ov,
                    item_id=item_id,
                    msg_id=srcs[0].msg_id if srcs else None,
                    extra_msg_ids=[s.msg_id for s in srcs[1:]],
                )
            }
        finally:
            ov.close()

    @app.post("/api/undo")
    def api_undo(body: dict = Body(default={})) -> dict:
        """撤销一条编辑。`edit_id` 缺省 = 撤最近一条。

        ⚠️ 非尾部 `edit_id` 只在**可证明惰性**时才允许（`overrides.undo` 的
        docstring 有论证），否则 **409** —— 而不是把一条历史事件从日志中间抽走、
        让条目的可见状态静默翻转（终审 Important-1：撤一条非尾部 `set_kind`
        能让条目从 Web 与日报同时消失，而这里返回 `{"undone": true}`）。
        409 而不是 400：请求本身是合法的，与**日志当前状态**冲突的是这次撤销。

        ⚠️ **两种 `OverlayError` 必须分开映**（M5 收尾 scoped re-review A2）。
        `overrides.UndoConflict` = 与日志状态冲突 ⇒ **409**（换一条编辑撤就能成，
        有自救路径）。其余 `OverlayError` = overlay 的**基础设施故障**
        （文件缺失/挂不上/路径非法）⇒ **5xx**：客户端重试多少次都一样，
        报 409 会把排障引向「是不是有人并发改了日志」，而真相是服务端自己坏了。
        ⚠️ 顺序是承重的：**子类必须在前**，否则 `UndoConflict` 会被下面那支吞掉。
        """
        target = _edit_id_of(body)
        ov = overrides.connect()
        try:
            if target is None:
                last = overrides.last_edit(ov)
                if last is None:
                    return {"undone": False}
                target = last[0]
            try:
                return {"undone": overrides.undo(ov, edit_id=target)}
            except overrides.UndoConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc))
            except overrides.OverlayError as exc:
                # ⚠️ 显式 500 而不是「让它冒出去」：一是给客户端一句**说清方向的**
                # 话（「不是冲突，是服务端」），二是它必须是**可断言的响应**——
                # `TestClient` 默认 `raise_server_exceptions=True`，未捕获的异常
                # 在测试里是「错误」而不是 500 响应，「映成 5xx」这件事就没人守得住。
                raise HTTPException(
                    status_code=500,
                    detail=f"overlay 基础设施故障（**不是**与日志状态冲突）：{exc}",
                )
        finally:
            ov.close()

    @app.get("/api/persons")
    def api_persons() -> dict:
        # ⚠️ `path` **一处都不许省**：`DEFAULT_PERSONS` 是 import 期就冻住的常量
        # （`config.py` 模块级），省掉 path 时读写都会落到**仓库里真实的**
        # `config/persons.toml`，而 monkeypatch 拦不住它 ⇒ 测试全绿、
        # 用户的真实名单却已经被整体替换掉了。
        people = load_persons(persons_path())
        con = connect()
        try:
            counts: dict[int, int] = {}
            for p in people:
                _, n = store.search_items(
                    con, actor_uins=[p.uin], limit=1, offset=0
                )
                counts[p.uin] = n
        finally:
            con.close()
        return {
            "persons": [
                {"uin": p.uin, "label": p.label, "note": p.note,
                 "count": counts.get(p.uin, 0)}
                for p in people
            ]
        }

    @app.post("/api/persons", status_code=201)
    def api_add_person(body: dict = Body(...)) -> dict:
        uin = body.get("uin")
        if not isinstance(uin, int) or uin <= 0:
            raise HTTPException(
                status_code=400,
                detail="uin 必须是正整数（0 是匿名哨兵，不能监视）",
            )
        label = str(body.get("label", "")).strip()
        if not label:
            raise HTTPException(status_code=400, detail="label 不能为空")
        note = str(body.get("note", ""))
        _reject_controls(label, "label")
        _reject_controls(note, "note")
        path = persons_path()
        people = [p for p in load_persons(path) if p.uin != uin]
        people.append(Person(uin=uin, label=label, note=note))
        save_persons(people, path)
        return {"uin": uin, "label": label}

    @app.delete("/api/persons/{uin}", status_code=204)
    def api_del_person(uin: int) -> None:
        path = persons_path()
        people = tuple(p for p in load_persons(path) if p.uin != uin)
        save_persons(people, path)
        return None

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
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """静态文件 + SPA 兜底。三件事按序：挡 /api、发真文件、发前端入口。

        ⚠️ 三条边界都必须挡：
        * ``/api`` 与 ``/api/*`` **都不能**落进兜底——否则 `GET /api/typo` 会返回
          200 的 HTML，调用方 ``r.json()`` 直接炸，而真正的 404 被吞掉。
          裸 ``/api`` 必须**单独**判：``startswith("api/")`` 漏掉它（``"api"``
          不以 ``"api/"`` 开头，曾是实测的漏网口），而 ``startswith("api")``
          又会把将来的 ``/apiary`` 之类一起吞掉——守卫精确到这两个形状。
        * **真存在的静态文件必须先发**（见上面 _MIME 的说明）。
        * 前端**没构建**时不许返回空白页，要明说「去跑 npm run build」——
          与日报同一条规矩：只说自己有资格说的话，没构建就说没构建。

        ⚠️ ``WEB_DIST`` 与派生的两个路径都**必须在这里现读**，不能在 create_app
        时算好冻进闭包：测试用 ``monkeypatch.setattr(api, "WEB_DIST", ...)`` 换掉
        它，冻住的话那些测试测的还是真实 web/dist（本机已构建，于是全都变成
        「怎么改都绿」的空守卫）。
        """
        # 裸 "api" 必须单列（见 docstring）：只用 startswith("api/") 时
        # `GET /api` 会一路走到 SPA 兜底，返回 200 的 HTML。
        if full_path == "api" or full_path.startswith("api/"):
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
