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
import threading
import tomllib
from collections.abc import Sequence

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from . import categories as categories_mod
from . import groups_snapshot, overrides, store
from .categories import Category, load_categories
from .config import (
    REPO_ROOT,
    TIER_NORMAL,
    VALID_TIERS,
    Config,
    ConfigError,
    Group,
    Person,
    atomic_write_text,
    load_config,
    load_persons,
    save_config,
    save_persons,
)

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

    ⚠️ `config.toml_str` 已经能把这些字符**转义**成合法 TOML 并按原样读回来
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

    # ⚠️ overlay 的**文件**在这里就位（D11 允许 Web 写 overlay）。之后每个
    # 请求的 `store._ensure_overlay(conn)` 才能无条件 ATTACH。
    # ⚠️ **不能**在这里调 `store.ensure_schema`——那是写 `vigil.db`，
    # 而本文件的连接是 `mode=ro`（见 connect() 的 docstring）。
    overrides.ensure_schema()

    # ⚠️ **不许用 `create_app` 收到的那个 `config` 去回答「现在有哪些群」**
    # （它在进程启动那一刻就冻住了）。网页上加了一个群之后，那个对象里没有它
    # ⇒ 新群在信息流里显示成裸群号，而用户刚从「配置」页把它加进去、
    # 看着自己的操作没生效。（与 `persons_path()` 同一族：路径与文件内容
    # 都必须**每次现读**。）
    #
    # ⚠️ **`db_uri` 仍然用启动时那份 `config.output_db`**：改它要重启服务。
    # 这不是妥协——`output_db` 是「这个服务读哪个库」，热切换它意味着
    # 正在飞的请求读一半换了库，比要求重启糟得多。
    def config_path() -> pathlib.Path:
        return REPO_ROOT / "config" / "groups.toml"

    def current_config() -> Config:
        try:
            return load_config(config_path())
        except ConfigError as exc:
            # 配置文件被手工改坏了 ⇒ 500 而不是 503：后者在浏览器里会被
            # 读成「服务没起来」，而真相是**配置文件有语法错**，方向完全不同。
            raise HTTPException(
                status_code=500, detail=f"config/groups.toml 读不出来：{exc}"
            )

    # ⚠️ 进程内的写锁。`save_config` 是**整体替换**（读 → 改 → 写），
    # 两个并发请求各自读到旧版本、各自 append、后写的赢 ⇒ **丢一个群**。
    # 单用户自用下概率低，但 spec §6 R10 明说「不能因为概率低就不做原子写」——
    # 而这里的代价只是一把 `threading.Lock`。
    # ⚠️ 它是**进程内**的：本服务只有一个 uvicorn worker（`uvicorn.run(app, ...)`
    # 不带 workers 参数），所以够用。跨进程那把是 `lock.SingleInstance`，
    # 它保护的是 QQ 库与主库，**语义不同、别混用**：CLI 拿不到锁时会拒绝运行，
    # 而 Web 不该因为「任务计划在跑」就整个不能保存配置。
    write_lock = threading.Lock()

    # ── 类目编辑（M6 T5）────────────────────────────────────────────
    #
    # ⚠️ 这里开始，`categories.toml` 由**程序**整体重写（`save_categories`）。
    # 配置仍是唯一真相源，只是从此有了一个比手写更常见的来源。

    def categories_path() -> pathlib.Path:
        """⚠️ 与 `config_path()` 一样**每次现读** `REPO_ROOT` 全局
        （Global Constraint 11：不许在 `create_app` 时算好冻进闭包）。

        ⚠️ **实测（M6 T5）：把这一处冻住，全量 704 passed / 0 red。**
        原因清楚——所有隔离夹具都是**在造 app 之前**就
        `monkeypatch.setattr(api, "REPO_ROOT", tmp)` 的，于是"冻住的那一份"
        也落在 tmp 根里。⇒ **这一处的『现读』今天没有牙**，它不是被测试逼出来的形状。

        ⇒ 仍然现读，是照约束 11 与同族的 `config_path()` / `persons_path()`
        （后者那次「测试往真仓库写人」的事故，是**那处**的实测历史，不是这一处的）。
        ⚠️ 写清楚这一点是刻意的：本项目最贵的一课是**错的论证比没有论证更危险**
        （勘误 E7）——把一个没被守卫的形状说成"不然测试会红"，会让下一个读的人
        以为自己理解了，于是不去验证。
        """
        return REPO_ROOT / "config" / "categories.toml"

    def current_categories() -> tuple[Category, ...]:
        """**每次现读**的类目表（名字对齐 `current_config()`）。

        ⚠️ 读不出来 ⇒ **500**（同 `current_config()`）：这是服务端自己的配置问题，
        而 503 在浏览器里会被读成「服务没起来」，方向完全不同。
        """
        try:
            return load_categories(categories_path())
        except categories_mod.CategoryError as exc:
            raise HTTPException(
                status_code=500, detail=f"config/categories.toml 读不出来：{exc}"
            )

    def category_map() -> dict[str, Category]:
        """slug → `Category`，**每次现读**（与 `group_names_map()` 同族）。

        ⚠️ 只在**端点入口**读一次、再传进 `item_out`：列表接口一页 50 条，
        写在 `item_out` 里就是 50 次读同一份文件。
        """
        return {c.slug: c for c in current_categories()}

    def snapshot_categories() -> None:
        """把**当前** `categories.toml` 的原文存进 overlay。每次改动**之前**调。

        ⚠️ 文件不存在时静默跳过：那意味着这份配置还没被创建过，
        而"撤销到一个不存在的文件"没有意义。
        """
        path = categories_path()
        if not path.is_file():
            return
        ov = overrides.connect()
        try:
            overrides.save_config_snapshot(ov, body=path.read_text(encoding="utf-8"))
        finally:
            ov.close()

    def category_or_400(body: dict) -> Category:
        """把请求体变成一个 `Category`，**校验不过一律 400**（不是 500）。

        ⚠️ 校验**必须在写之前**：`save_categories` 自己也会校验（T2），
        但那是最后一道闸——先校验一次，才能做到「400 的时候
        **一份快照都没产生、一个字节都没落盘**」。
        """
        slug = str(body.get("slug", "")).strip()
        label = str(body.get("label", "")).strip() or slug
        desc = str(body.get("desc", "")).strip()
        icon = str(body.get("icon", "")).strip()
        for fname, value in (
            ("slug", slug), ("label", label), ("desc", desc), ("icon", icon),
        ):
            _reject_controls(value, fname)
        if not desc:
            raise HTTPException(
                status_code=400,
                detail="desc 不能为空——它会被**逐字**渲染进 LLM 的提示词，是类目的判据",
            )
        return Category(slug=slug, label=label, desc=desc, icon=icon)

    def validate_or_400(cats: Sequence[Category]) -> None:
        try:
            categories_mod.validate_categories(
                categories_mod.as_dicts(cats), categories_path()
            )
        except categories_mod.CategoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    def commit_categories(cats: Sequence[Category]) -> None:
        try:
            categories_mod.save_categories(cats, categories_path())
        except categories_mod.CategoryError as exc:
            # 走到这里说明 `validate_or_400` 放行了一份 `save_categories` 拒绝的
            # 东西——那是**程序自己的 bug**，500 才对（400 会把排障引向用户输入）。
            raise HTTPException(status_code=500, detail=f"内部错误：{exc}")

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

    def group_names_map() -> dict[int, str]:
        """群号 → 群名，**每次现读**（与 `current_config()` 同一族，M6 T4）。

        ⚠️ **不许用 `create_app` 收到的那份 `config`**：它冻在启动那一刻，
        而「配置」页可以让用户随时改群名 / 停用 / 加群 —— 冻住的话，刚加的群
        在信息流里显示成裸群号，用户看着自己的操作没生效。

        ⚠️ 只在**端点入口**读一次、再传进 `item_out`：列表接口一页 50 条，
        写在 `item_out` 里就是 50 次读同一份 3KB 的 TOML。
        """
        return {g.id: g.name for g in current_config().groups}

    def item_out(
        it: store.ApiItem, names: dict[int, str], cats: dict[str, Category]
    ) -> dict:
        """⚠️ `cats` 由调用方**每次现读**后传进来（见 `category_map()`）。

        不是为了省一次读（虽然也省了 50 次同一份文件的读），而是因为**冻住的
        那一份会过时**：网页上刚加的类目在信息流里会显示成**裸 slug**——
        用户看着自己刚做的操作没生效（与 `group_names_map()` 是同一条判据）。
        """
        cat = cats.get(it.kind)
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
        # ⚠️ 原实现用的是 `create_app` 时冻住的 `cats` / `cat_by_slug`。改成**现读**
        # （同 T4 的 `current_config`）：编辑器刚存下的类目必须立刻在这个响应里，
        # 否则用户看到的还是旧表、以为自己没存上。
        # 变量名从 `cats` 改成 `cfg_cats` 是刻意的，好让 `grep -n "cats" vigil/api.py`
        # 一眼看出还有哪里在用旧的那一份。
        cfg_cats = current_categories()
        con = connect()
        try:
            counts = store.kind_counts(con)
        finally:
            con.close()
        ov = overrides.connect()
        try:
            aliases = overrides.kind_aliases(ov)
        finally:
            ov.close()
        return {
            "categories": [
                {
                    "slug": c.slug,
                    "label": c.label,
                    "icon": c.icon,
                    # ⚠️ `desc` 也在契约里（M6 T5）：编辑器要拿它回填输入框，
                    # 而这个字段是**逐字进 LLM 提示词的判据**——不给的话，
                    # 界面上改一次别的字段就会把它抹掉。
                    "desc": c.desc,
                    "count": counts.get(c.slug, 0),
                }
                for c in cfg_cats
            ],
            # ⚠️ 一次把别名映射也交出去，供界面显示「旧名 life → 现在叫 daily」。
            # 单独开一个端点也行，但界面每次都要它，多一次往返不值。
            "aliases": aliases,
        }

    # ⚠️ **四个写端点里每一步都在 `write_lock` 里**（与 `api_add_group` 同形）。
    # 读在锁外的话，「读 → 改 → 写」这个整体替换就会被两个并发请求交错
    # （各自读到旧版本、各自算 candidate、后写的赢）⇒ 可能丢一次编辑。
    # 那正是 `write_lock` 上面那段注释点名要防的事，不因为「单用户自用概率低」
    # 就可以省（spec §6 R10）。
    # ⚠️ **实测：这一层今天没有牙**——把锁换成空上下文，全量 **704 passed / 0 red**
    # （没有任何并发用例）。它守的是一个**单线程测试看不见**的性质，
    # 与上面 `categories_path()` 那条是同一族的诚实标注（勘误 E7）。
    #
    # ⚠️ 快照的**位置**也是承重的：`snapshot_categories()` 必须在
    # `commit_categories()` **之前**。反过来（先 commit 再拍快照）实测 ⇒
    # `test_api_category_undo_restores_the_previous_file` **红**：撤销会"回滚"到
    # 刚写进去的那一份，即点了撤销什么都没发生。
    #
    # ⚠️ `api_update_category` / `api_delete_category` 里「**先写别名、再写配置**」
    # 的顺序**没有测试**（两种顺序在单请求里都绿）：它防的是**两次写之间崩溃**
    # 留下的"配置里已经没有 life 了、但别名还没建"⇒ 条目永久悬空。
    # 这一条是**设计选择**，不是被测试逼出来的——如实标注，免得后来者以为有守卫。

    @app.post("/api/categories", status_code=201)
    def api_add_category(body: dict = Body(...)) -> dict:
        cat = category_or_400(body)
        with write_lock:
            existing = current_categories()
            if any(c.slug == cat.slug for c in existing):
                raise HTTPException(status_code=409, detail=f"类目 {cat.slug} 已经存在")
            candidate = existing + (cat,)
            validate_or_400(candidate)      # ⚠️ 先验，后拍快照 ⇒ 400 时零副作用
            snapshot_categories()
            commit_categories(candidate)
        return {"slug": cat.slug, "label": cat.label}

    @app.put("/api/categories/{slug}")
    def api_update_category(slug: str, body: dict = Body(...)) -> dict:
        """改一个类目。**body 里带 `slug` 且与路径不同 ⇒ 这是一次改名**。

        ⚠️ **写入顺序是承重的：先写别名，再写配置文件。**
        反过来的话，中间崩溃会留下「配置里已经没有 `life` 了、但别名还没建」
        ⇒ 条目永久悬空（正是 spec §4.2 ④ 点名要禁的状态）；
        先写别名的话，中间崩溃只留下一条约不到的别名——无害，
        配置文件写好之后它立刻生效。
        """
        with write_lock:
            existing = current_categories()
            old = next((c for c in existing if c.slug == slug), None)
            if old is None:
                raise HTTPException(status_code=404, detail=f"没有这个类目：{slug}")

            new_slug = str(body.get("slug", slug)).strip() or slug
            merged = category_or_400(
                {
                    "slug": new_slug,
                    "label": body.get("label", old.label),
                    "desc": body.get("desc", old.desc),
                    "icon": body.get("icon", old.icon),
                }
            )
            # ⚠️ 空操作**不拍快照**：拍下去的话，一次"什么都改"的 PUT
            # 会往撤销栈里塞一格假的——用户点撤销时会看到"配置没变"
            # （因为那一格就是当前内容），于是以为撤销坏了。
            if merged == old:
                return {"slug": slug, "label": old.label}

            candidate = tuple(merged if c.slug == slug else c for c in existing)
            validate_or_400(candidate)

            if new_slug != slug:
                ov = overrides.connect()
                try:
                    overrides.set_kind_alias(ov, old_kind=slug, new_kind=new_slug)
                finally:
                    ov.close()
            snapshot_categories()
            commit_categories(candidate)
        return {"slug": merged.slug, "label": merged.label}

    @app.delete("/api/categories/{slug}", status_code=204)
    def api_delete_category(slug: str, migrate_to: str | None = None) -> None:
        """删一个类目。**还有条目指着它时必须给 `?migrate_to=`**。

        ⚠️ 「有 N 条属于它」这句话**必须真的说出来**（spec 出口判据 6）：
        只回一句「不能删」是没用的，用户需要知道**有多少条**、
        以及**不迁移会怎样**。所以 detail 里带上条数。

        ⚠️ 迁移的实现就是一条别名（`slug → migrate_to`），**不碰 `items`**
        ——那正是 `kind_alias` 存在的理由。
        """
        with write_lock:
            existing = current_categories()
            if not any(c.slug == slug for c in existing):
                raise HTTPException(status_code=404, detail=f"没有这个类目：{slug}")

            candidate = tuple(c for c in existing if c.slug != slug)
            if not candidate:
                raise HTTPException(
                    status_code=409,
                    detail="这是最后一个类目，删掉它会让 refine 的提示词没有类目表可用。",
                )
            validate_or_400(candidate)

            con = connect()
            try:
                n = store.kind_counts(con).get(slug, 0)
            finally:
                con.close()

            if n and not migrate_to:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"类目 {slug} 还有 {n} 条条目指着它。删之前必须给一个迁移目标："
                        f"`DELETE /api/categories/{slug}?migrate_to=<某个现存 slug>`。"
                        "不给的话那些条目会指向一个不存在的类目。"
                    ),
                )
            if migrate_to and migrate_to not in {c.slug for c in candidate}:
                raise HTTPException(
                    status_code=400, detail=f"迁移目标 {migrate_to!r} 不是一个现存类目"
                )

            if migrate_to:
                # ⚠️ 先写别名（见 `api_update_category` 的 docstring）
                ov = overrides.connect()
                try:
                    overrides.set_kind_alias(ov, old_kind=slug, new_kind=migrate_to)
                finally:
                    ov.close()
            snapshot_categories()
            commit_categories(candidate)
        return None

    @app.post("/api/categories/undo")
    def api_category_undo() -> dict:
        """把 `categories.toml` 回滚到上一次程序写它之前的样子。

        ⚠️ **与 `/api/undo` 是两回事**（spec §3.3：「两者都做，别混为一谈」）：
        那条撤的是**对条目的人工修改**（删事件），这条回滚的是**配置文件**
        （整份存档）。协议上也刻意分开：这条回 `{"undone": bool}`，
        与 `/api/undo` 对齐，但**不接受 `edit_id`**——快照没有"中间某一条"，
        只有"上一格"。
        """
        ov = overrides.connect()
        try:
            popped = overrides.pop_config_snapshot(ov)
        finally:
            ov.close()
        if popped is None:
            return {"undone": False}

        _, body = popped
        # ⚠️ 恢复的是一份**手里没有第二份**的内容：先校验再落盘。
        # 直接 `atomic_write_text` 的话，一份坏快照会把配置永久写坏
        # （原子写、无回滚），而 `categories.toml` 是 refine 与 api 的硬依赖。
        try:
            raw = tomllib.loads(body)
            categories_mod.validate_categories(
                raw.get("categories"), categories_path()
            )
        except (tomllib.TOMLDecodeError, categories_mod.CategoryError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"快照内容已损坏，拒绝写回（配置未被改动）：{exc}",
            )
        with write_lock:
            atomic_write_text(categories_path(), body)
        return {"undone": True}

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
        names = group_names_map()
        cats = category_map()
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
            "items": [item_out(it, names, cats) for it in items],
            # ⚠️ total 是**符合筛选条件的总数**，与 limit/offset 无关（不是当页条数）。
            # 前端三处依赖它：分页按钮出不出、「共 N 条」、「还有 N 条」。
            # store.search_items 已经把两者一起返回，这里照传即可。
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/items/{item_id}")
    def api_item(item_id: int) -> dict:
        names = group_names_map()
        cats = category_map()
        con = connect()
        try:
            it = store.get_item(con, item_id)
            if it is None:
                raise HTTPException(status_code=404, detail=f"没有这条条目：{item_id}")
            payload = item_out(it, names, cats)
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

    # ── 群：清单走只读快照（M6 T4 / spec §1.6），增删改走 groups.toml ──────

    @app.get("/api/groups")
    def api_groups() -> dict:
        """QQ 库里的群清单 —— **只读快照**（M6 T4 / spec §1.6）。

        ⚠️ 本端点**绝不接触 QQ 库、绝不写 `data/cache/`、也不需要数据库密钥**。
        它读的是 `vigil export` / `vigil groups` 预生成的
        `data/groups-snapshot.json`。理由与代价都写在 `groups_snapshot`
        模块的 docstring 里，改这里之前先读它。
        """
        cfg = current_config()
        snap = groups_snapshot.load(groups_snapshot.default_path(cfg))
        watched = {g.id: g for g in cfg.groups}
        if snap is None:
            # ⚠️ **明说**，绝不回一个空列表：空列表会被读成
            # 「你的 QQ 库里一个群都没有」——一句假话，而且是最容易让人
            # 不再信任这个页面的那种（「只说自己有资格说的话」）。
            return {
                "available": False,
                "reason": (
                    "还没有群清单快照。请先在仓库根目录跑一次 "
                    "`uv run vigil export`（或 `uv run vigil groups`）——"
                    "它会把 QQ 库里所有群的清单写成 data/groups-snapshot.json。"
                    "本服务只读那份产物，不直接读 QQ 库。"
                ),
                "generated_at": None,
                "groups": [],
            }
        return {
            "available": True,
            "reason": "",
            "generated_at": snap.generated_at,
            "groups": [
                {
                    "id": g.id,
                    "name": g.name,
                    "messages": g.messages,
                    "last_ts": g.last_ts,
                    "watched": g.id in watched and watched[g.id].enabled,
                    "known": g.id in watched,
                }
                for g in snap.groups
            ],
        }

    @app.post("/api/groups", status_code=201)
    def api_add_group(body: dict = Body(...)) -> dict:
        """新增一个监视群，落盘到 `config/groups.toml`（原子、整体替换）。

        ⚠️ **群号必须在这里挡死 `bool`**（`isinstance(True, int)` 为真）：
        `save_config` 里的 `toml_int` 拦不住它——到那时 id 已经是 `True`、
        写出去是 `true`，读回来是 `1`。**闸必须在入口。**
        （与 M5 终审 #22「`uin = true` 被接受」是同一个形状。）
        """
        gid = body.get("id")
        if isinstance(gid, bool) or not isinstance(gid, int) or gid <= 0:
            raise HTTPException(
                status_code=400,
                detail="群号必须是正整数（拒绝 true：bool 是 int 的子类，会静默变成 1）",
            )
        name = str(body.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="群名不能为空")
        _reject_controls(name, "name")
        tier = str(body.get("tier", TIER_NORMAL))
        if tier not in VALID_TIERS:
            raise HTTPException(
                status_code=400, detail=f"tier 只能是 {sorted(VALID_TIERS)}，收到：{tier!r}"
            )

        path = config_path()
        with write_lock:
            cfg = current_config()
            if any(g.id == gid for g in cfg.groups):
                raise HTTPException(status_code=409, detail=f"群 {gid} 已经在配置里了")
            save_config(
                Config(
                    qq_db_dir=cfg.qq_db_dir,
                    output_db=cfg.output_db,
                    groups=cfg.groups + (Group(id=gid, name=name, tier=tier),),
                ),
                path,
            )
        return {"id": gid, "name": name, "tier": tier}

    @app.patch("/api/groups/{gid}")
    def api_patch_group(gid: int, body: dict = Body(...)) -> dict:
        """改一个已配群的名字 / 启停 / 档位。**不做删除**（见下）。"""
        path = config_path()
        with write_lock:
            cfg = current_config()
            old = next((g for g in cfg.groups if g.id == gid), None)
            if old is None:
                raise HTTPException(status_code=404, detail=f"配置里没有群 {gid}")

            name = old.name
            if "name" in body:
                name = str(body["name"]).strip()
                if not name:
                    raise HTTPException(status_code=400, detail="群名不能为空")
                _reject_controls(name, "name")
            enabled = old.enabled
            if "enabled" in body:
                if not isinstance(body["enabled"], bool):
                    raise HTTPException(status_code=400, detail="enabled 必须是布尔值")
                enabled = body["enabled"]
            tier = old.tier
            if "tier" in body:
                tier = str(body["tier"])
                if tier not in VALID_TIERS:
                    raise HTTPException(
                        status_code=400, detail=f"tier 只能是 {sorted(VALID_TIERS)}"
                    )

            updated = Group(id=gid, name=name, enabled=enabled, tier=tier)
            groups = tuple(updated if g.id == gid else g for g in cfg.groups)
            save_config(
                Config(qq_db_dir=cfg.qq_db_dir, output_db=cfg.output_db, groups=groups),
                path,
            )
        return {"id": gid, "name": name, "enabled": enabled, "tier": tier}

    @app.delete("/api/groups/{gid}", status_code=204)
    def api_delete_group(gid: int) -> None:
        """从配置里删掉一个群。

        ⚠️ **拒绝删掉最后一个群**：`load_config` 把「一个群都没配」判成
        配置错误 ⇒ 删掉它 = **把这个服务改成起不来**，而且下一次启动才现形，
        那时用户已经在网页上点过删除、拿到了「成功」。
        ⚠️ 正确动作是 `enabled = false`（保留配置、保留已导出的历史），
        **detail 里必须说清这一点**——只回一句「不能删」是没用的。
        """
        path = config_path()
        with write_lock:
            cfg = current_config()
            if not any(g.id == gid for g in cfg.groups):
                raise HTTPException(status_code=404, detail=f"配置里没有群 {gid}")
            remaining = tuple(g for g in cfg.groups if g.id != gid)
            if not remaining:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "这是最后一个群，删掉它会让配置变成「一个群都没配」——"
                        "而那是致命的配置错误，下次启动服务会直接起不来。"
                        "要停掉它请改用 enabled = false（保留配置与已导出的历史）。"
                    ),
                )
            save_config(
                Config(
                    qq_db_dir=cfg.qq_db_dir, output_db=cfg.output_db, groups=remaining
                ),
                path,
            )
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
        names = group_names_map()
        cats = category_map()
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
            "items": [item_out(it, names, cats) for it in items],
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
