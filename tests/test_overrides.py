"""人工干预层：append-only 的事件日志 + 物化状态。"""

import sqlite3

import pytest

from vigil import overrides

# ⚠️ 下面两行是 **brief 之外新增的**，只给文件尾「新增守卫」那一节用。
from vigil import store
from vigil.config import REPO_ROOT


@pytest.fixture
def ov():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    overrides.ensure_tables(conn)
    yield conn
    conn.close()


def test_set_kind_writes_event_and_state(ov):
    edit_id = overrides.set_kind(ov, item_id=7, kind="academic")
    assert edit_id > 0
    row = ov.execute("SELECT kind, deleted FROM item_state WHERE item_id=7").fetchone()
    assert row["kind"] == "academic"
    assert row["deleted"] == 0
    ev = ov.execute("SELECT * FROM item_edits WHERE edit_id=?", (edit_id,)).fetchone()
    assert ev["action"] == "set_kind"
    assert ev["item_id"] == 7
    assert ev["new_value"] == "academic"


def test_set_kind_is_append_only_old_value_recorded(ov):
    overrides.set_kind(ov, item_id=7, kind="academic")
    overrides.set_kind(ov, item_id=7, kind="life")
    rows = ov.execute(
        "SELECT new_value FROM item_edits WHERE item_id=7 ORDER BY edit_id"
    ).fetchall()
    assert [r["new_value"] for r in rows] == ["academic", "life"]
    assert ov.execute("SELECT kind FROM item_state WHERE item_id=7").fetchone()["kind"] == "life"


def test_delete_marks_state_and_records_msg_id(ov):
    overrides.delete_item(ov, item_id=9, msg_id=555)
    assert ov.execute("SELECT deleted FROM item_state WHERE item_id=9").fetchone()["deleted"] == 1
    assert overrides.deleted_msg_ids(ov) == frozenset({555})


def test_delete_then_set_kind_last_wins(ov):
    """事件序决定状态——后发生的覆盖先发生的。"""
    overrides.delete_item(ov, item_id=9, msg_id=555)
    overrides.set_kind(ov, item_id=9, kind="life")
    row = ov.execute("SELECT kind, deleted FROM item_state WHERE item_id=9").fetchone()
    assert row["deleted"] == 0
    assert row["kind"] == "life"


def test_undo_removes_event_and_rebuilds_state(ov):
    overrides.set_kind(ov, item_id=7, kind="academic")
    eid = overrides.set_kind(ov, item_id=7, kind="life")
    assert overrides.undo(ov, edit_id=eid) is True
    assert ov.execute("SELECT kind FROM item_state WHERE item_id=7").fetchone()["kind"] == "academic"
    assert ov.execute("SELECT COUNT(*) FROM item_edits WHERE item_id=7").fetchone()[0] == 1


def test_undo_unknown_edit_returns_false(ov):
    assert overrides.undo(ov, edit_id=9999) is False


def test_undo_delete_restores_visibility(ov):
    eid = overrides.delete_item(ov, item_id=9, msg_id=555)
    assert overrides.undo(ov, edit_id=eid) is True
    assert ov.execute("SELECT COUNT(*) FROM item_state WHERE item_id=9").fetchone()[0] == 0


def test_last_edit(ov):
    assert overrides.last_edit(ov) is None
    overrides.set_kind(ov, item_id=7, kind="life")
    eid = overrides.delete_item(ov, item_id=8, msg_id=1)
    assert overrides.last_edit(ov) == (eid, 8, "delete")


def test_ensure_tables_is_idempotent(ov):
    overrides.ensure_tables(ov)
    overrides.ensure_tables(ov)
    assert ov.execute("SELECT COUNT(*) FROM item_edits").fetchone()[0] == 0


def test_rebuild_state_matches_incremental(ov):
    """⚠️ 增量折叠与全量重算必须恒等——否则 undo 之后的 state 会与事件日志脱节。"""
    overrides.set_kind(ov, item_id=7, kind="academic")
    overrides.delete_item(ov, item_id=8, msg_id=1)
    overrides.set_kind(ov, item_id=8, kind="life")
    overrides.delete_item(ov, item_id=7, msg_id=2)

    before = [dict(r) for r in ov.execute("SELECT * FROM item_state ORDER BY item_id")]
    overrides.rebuild_state(ov)
    after = [dict(r) for r in ov.execute("SELECT * FROM item_state ORDER BY item_id")]
    assert before == after


def test_undo_then_rebuild_still_consistent(ov):
    overrides.set_kind(ov, item_id=7, kind="academic")
    eid = overrides.delete_item(ov, item_id=7, msg_id=2)
    overrides.undo(ov, edit_id=eid)
    overrides.rebuild_state(ov)
    row = ov.execute("SELECT kind, deleted FROM item_state WHERE item_id=7").fetchone()
    assert row["kind"] == "academic"
    assert row["deleted"] == 0


# ---------------------------------------------------------------------------
# 新增守卫（**brief 之外**）——每一条都对着 `task-4-report.md` 的
# `## 变异反证` 里实测**存活**的变异体。brief 的三个代码块本身逐字未改。
# ---------------------------------------------------------------------------


def test_ensure_schema_default_path_is_isolated():
    """Global Constraint 8：测试不许碰真实的 `data/overrides.db`。

    这是 conftest 里 `_isolate_overrides_path` 夹具的**守卫**。
    变异反证：把那个夹具的 `autouse=True` 去掉 ⇒ 这条立刻变红；
    **没有这条时，全量 461 条里一条都不会红**。
    """
    assert overrides.OVERRIDES_DB != REPO_ROOT / "data" / "overrides.db"
    overrides.ensure_schema()
    conn = sqlite3.connect(str(overrides.OVERRIDES_DB))
    try:
        names = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert {"item_edits", "item_state"} <= names


def test_store_ensure_schema_provisions_the_overlay_file(memdb):
    """Task 4 Step 5 的落地：写路径（`refine` / `digest`）跑过之后 overlay 就已就位。

    ⚠️ 变异反证：把 `store.ensure_schema` 里那三行删掉，**461 条一条都不红**。
    掉的是这条链：服务启动时（D11 允许 Web 写 overlay）要"库已经存在"，
    才敢在每个请求上无条件 ATTACH。
    """
    assert not overrides.OVERRIDES_DB.exists()
    store.ensure_schema(memdb)
    assert overrides.OVERRIDES_DB.exists()


def test_deleted_msg_ids_folds_like_item_state(ov):
    """**R5**：`deleted_msg_ids` 与 `item_state` 必须是**同一次折叠**的两个视图。

    两条序列只差最后一步，答案必须相反（reviewer 用 400 条随机事件序列实测旧实现
    在此分歧 65 次：`delete` 后 `set_kind` ⇒ 条目**可见**，而 msg 仍被墓碑化）。

    ⚠️ 判据：`msg_id` 被墓碑化 ⟺ **最终态** `deleted=1` 的 item 的源 msg 包含它。
    依据是 brief 自己早就裁定过的语义——`test_delete_then_set_kind_last_wins`。
    """
    # ① delete 之后没有后续事件 ⇒ 最终态仍被删 ⇒ msg 被墓碑化
    overrides.delete_item(ov, item_id=9, msg_id=555)
    assert ov.execute("SELECT deleted FROM item_state WHERE item_id=9").fetchone()["deleted"] == 1
    assert overrides.deleted_msg_ids(ov) == frozenset({555})

    # ② delete 之后跟着 set_kind ⇒ 最终态**可见** ⇒ 这个 msg 不再算被墓碑化
    overrides.delete_item(ov, item_id=10, msg_id=777)
    overrides.set_kind(ov, item_id=10, kind="life")
    assert ov.execute("SELECT deleted FROM item_state WHERE item_id=10").fetchone()["deleted"] == 0
    assert overrides.deleted_msg_ids(ov) == frozenset({555}), (
        "视图与 item_state 分歧：条目已经可见了，msg 却还被墓碑化"
    )


def test_deleted_msg_ids_uses_exists_semantics_for_multi_item_messages(ov):
    """**R5 的边角**：一条消息产出**多条** item 时取 **exists** 语义。

    构造：同一条源消息 888 产出两条 item——12 已被 `set_kind` 复活、11 仍被删。
    · exists ⇒ 888 **仍**被墓碑化（否则重抽会把 11 复活，直接违反 D15）；
    · and（"该 msg 的**所有** item 都被删才墓碑化"）⇒ 888 会被漏掉。

    ⚠️ 两条 item 必须**都真的引用 888**——12 要先 `delete(msg_id=888)` 再 `set_kind`
    （`set_kind` 自己不带 msg_id，光靠它构造不出这个局面）。
    ⚠️ 代价（12 这样的同源条目也会被冻结）写在 task-4-report.md 的「疑虑」里。
    """
    overrides.delete_item(ov, item_id=12, msg_id=888)
    overrides.set_kind(ov, item_id=12, kind="life")   # 兄弟条目复活 ⇒ 仍引用 888
    overrides.delete_item(ov, item_id=11, msg_id=888)  # 这一条仍被删
    assert ov.execute("SELECT deleted FROM item_state WHERE item_id=12").fetchone()["deleted"] == 0
    assert ov.execute("SELECT deleted FROM item_state WHERE item_id=11").fetchone()["deleted"] == 1
    assert overrides.deleted_msg_ids(ov) == frozenset({888}), (
        "exists 语义被破坏：同源的另一条还删着，msg 却没被墓碑化（重抽会把它复活）"
    )


def test_deleted_msg_ids_ignores_msgs_of_items_that_are_not_deleted(ov):
    """R5 语义下的两条边界（旧注解说的"只认 delete 事件"已不准确，见 R5）：

    · **没被删**的 item 上记的 `msg_id` 不许混进来（`set_field` 这类事件也带
      `msg_id`，表结构允许）——混进来会让没被删的条目在重抽时被跳过，静默丢数据；
    · `msg_id=None` 的软删是 `delete_item` 明确允许的（界面不知道 msg_id 时），
      不能让 `deleted_msg_ids` 炸——而 `refine` 每次重抽都要调它。

    ⚠️ 一条 item 的**多个**源 msg 今天不可能同时出现（只有 `delete` 事件带 msg_id），
    所以"取全部源 msg"与"只取 delete 事件的 msg"**今天等价**；若 T7 让 `set_field`
    也带 msg_id，这个选择才第一次可观测（报告「疑虑」里记了它）。
    """
    # 直接调私有 `_append`：要走**真实写路径**，不手搓 INSERT。
    overrides._append(
        ov, item_id=5, msg_id=777, action=overrides.ACTION_SET_FIELD, field="place",
        old_value=None, new_value="三教", actor="web", now=1,
    )
    overrides.delete_item(ov, item_id=9, msg_id=555)
    overrides.delete_item(ov, item_id=10, msg_id=None)
    assert overrides.deleted_msg_ids(ov) == frozenset({555})


def test_attach_readonly_is_readonly_and_idempotent(tmp_path):
    """读取路径专用（T5 在 `store.py` 的查询层调它）：**只读**，且重复挂不炸。

    ⚠️ 变异反证：`mode=ro` → `mode=rw`、以及删掉幂等短路，**两条都是零守护**。
    第一条是 D11 的机械保证：读取路径"顺手写一下" overlay 是可能的，
    所以要在**挂载方式**上拦住它，而不是靠调用方自觉。

    ⚠️ 支撑它的平台事实（Task 4 实测）：URI 形式的 `mode=ro` **只在连接带
    `SQLITE_OPEN_URI` 时被解析**，所以读取路径要像 `api.py:110` 那样用
    `sqlite3.connect(..., uri=True)`。不带这个标志的连接会在
    `test_attach_readonly_on_non_uri_connection_fails_loudly` 里被钉住。
    """
    target = tmp_path / "overrides.db"
    overrides.ensure_schema(target)
    conn = sqlite3.connect(":memory:", uri=True)
    try:
        overrides.attach_readonly(conn, target)
        overrides.attach_readonly(conn, target)  # 幂等：重复 ATTACH 同名会报错
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute(
                "INSERT INTO ov.item_edits (item_id, action, actor, created_at)"
                " VALUES (1, 'delete', 't', 0)"
            )
        # 只读是**按库**的，不是按连接的：主库仍然可写。
        # （这条也是「不许退化成 `PRAGMA query_only` 兜底」的守卫：那是连接级的，
        #   会把 digest.py / refine.py 那种"同一个连接先读后写"的路径写坏。）
        conn.execute("CREATE TABLE IF NOT EXISTS t_probe (x)")
    finally:
        conn.close()


def test_writes_are_committed_and_visible_to_another_connection(tmp_path):
    """`_append` / `undo` 必须**落盘**——读路径是**另一个连接**（`api.py` 挂的 `ov`）。

    ⚠️ 变异反证：把 `_append`（或 `undo`）末尾的 `conn.commit()` 删掉，
    在 brief 的 `:memory:` 夹具下**一条都不红**——同一个连接看得见未提交的行。
    而生产里写路径与读路径**是两条连接**（`refine` 写 / `api` 读），
    漏 commit 的后果是「人工修改悄悄没了」。这条用文件库 + 两条连接把它钉住，
    顺带覆盖 `overrides.connect()`（写端点专用，brief 里也没有测试）。
    """
    path = tmp_path / "overrides.db"
    overrides.ensure_schema(path)

    # ① 最后一次写是 `_append`（软删）⇒ 它的 commit 是承重的
    w = overrides.connect(path)
    try:
        eid_del = overrides.delete_item(w, item_id=8, msg_id=555)
    finally:
        w.close()  # 未提交的事务在这里被回滚 ⇒ `_append` 漏 commit 就红
    r = overrides.connect(path)
    try:
        assert overrides.last_edit(r) == (eid_del, 8, "delete")
        assert overrides.deleted_msg_ids(r) == frozenset({555})
    finally:
        r.close()

    # ② 最后一次写是 `undo` ⇒ undo 的 commit 是承重的（①单独抓不到它）
    w = overrides.connect(path)
    try:
        eid_set = overrides.set_kind(w, item_id=7, kind="academic")
        eid_del2 = overrides.delete_item(w, item_id=7, msg_id=777)
        assert overrides.undo(w, edit_id=eid_del2) is True
    finally:
        w.close()  # 未提交的事务在这里被回滚 ⇒ undo 漏 commit 就红
    r = overrides.connect(path)
    try:
        assert overrides.last_edit(r) == (eid_set, 7, "set_kind")
        assert overrides.deleted_msg_ids(r) == frozenset({555})  # 777 已被撤销
    finally:
        r.close()


def test_attach_readonly_on_non_uri_connection_fails_loudly(tmp_path):
    """**哨兵**：连接没开 `uri=True` 时，只读挂载必须**报错**，不许静默变可写。

    实测（SQLite 3.53.1 / Windows）：`file:` 前缀会被当成**字面文件名**，
    报 `unable to open database: file:C:/...?mode=ro`。本仓库有两条这样的连接
    （`cli.py:502` 的 `deadline-audit`、`digest.py:577`、`refine.py:399`），
    所以 `attach_readonly` 把那句"怎么修"写进了异常里。

    ⚠️ 这条是**平台事实的哨兵**：若将来 SQLite 编译时开了 `SQLITE_USE_URI`、
    URI 不再需要连接标志，它会变红——那不是产品坏了，是这条事实变了，
    请连同 `attach_readonly` 里的诊断分支一起删掉。
    """
    target = tmp_path / "overrides.db"
    overrides.ensure_schema(target)
    conn = sqlite3.connect(":memory:")  # 刻意不开 uri=True
    try:
        with pytest.raises(overrides.OverlayError, match="uri=True"):
            overrides.attach_readonly(conn, target)
        # 关键不变量：失败**绝不**退化成"挂上了一个能写的 ov"。
        assert "ov" not in {r[1] for r in conn.execute("PRAGMA database_list")}
    finally:
        conn.close()


# --- Fix loop 第 1 轮：裁决 R5 / R6 + reviewer 的 FIX 2 ---------------------------------


def test_undo_with_unknown_edit_id_does_not_discard_caller_writes(ov):
    """**FIX 2 回归**（reviewer 实测）：未知 `edit_id` 的 `undo` 不许回滚**调用方**的事务。

    旧实现里那句 `conn.rollback()` 会把调用方已经写进来、还没 commit 的行一起丢掉
    （实测：先 INSERT 一行，再 `undo(99999)` ⇒ 那行消失，1→0）。
    今天 `_append` 自带 commit 碰不到它；**T8 只要做"批量写 + 末尾校验"就会静默丢写**。
    """
    ov.execute(
        "INSERT INTO item_edits (item_id, msg_id, action, actor, created_at)"
        " VALUES (1, 2, 'delete', 't', 0)"
    )
    assert overrides.undo(ov, edit_id=999999) is False
    assert ov.execute("SELECT COUNT(*) FROM item_edits").fetchone()[0] == 1, (
        "undo 的失败分支把调用方未提交的写入回滚掉了"
    )


def test_ensure_schema_sets_wal_journal_mode(tmp_path):
    """**R6**：spec §3.3 明写 WAL，而默认建出来的库是 `delete`。

    为什么必须**在建库时**设：T5 之后 `api.py` 的 `mode=ro` 只读连接会与
    `refine` / T8 的写端点**并发**访问同一个库。rollback-journal 下写者持
    EXCLUSIVE 锁 ⇒ 读请求撞 `database is locked`；而 `mode=ro` 的连接**不能**
    把库转成 WAL（它连库头都写不了）。

    ⚠️ 顺带钉住 R6 的风险面（实测）：WAL **不妨碍** `mode=ro` 的挂载
    ——`-shm` / `-wal` 由 SQLite 按需重建（写者干净关闭时它们会被删掉）。
    """
    path = tmp_path / "overrides.db"
    overrides.ensure_schema(path)
    # 第二条连接：journal_mode 是**库**的属性，不是连接的
    conn = overrides.connect(path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()
    # WAL 也不影响只读挂载（T5 的读路径形状）
    ro = sqlite3.connect(":memory:", uri=True)
    try:
        overrides.attach_readonly(ro, path)
        assert ro.execute("SELECT COUNT(*) FROM ov.item_edits").fetchone()[0] == 0
    finally:
        ro.close()


# --- T5 Fix loop 第 1 轮：裁决 R8（挂载失败分两种情形）-------------------------------


def test_attach_readonly_degrades_to_empty_overlay_when_file_cannot_be_created(
    tmp_path, caplog
):
    """**R8 情形②**：库不存在、而且**建不出来** ⇒ 降级为「无干预」，**不许抛**。

    ⚠️ reviewer 实测的失败面：`data/` 不可写时，`ensure_schema` 的 `mkdir`/`connect`
    抛的是**裸 `OperationalError`**（那两行原本在 `try` **外**）⇒ **Web 全部读端点
    与日报一起 500**，而这时"用户从没做过任何干预"与"库被删了"在语义上等价
    ——本该只是"没有干预"。

    ⚠️ 降级**必须响亮**（日志），否则真正的部署问题会表现成「我的干预全没了」。
    用**父路径是文件**来制造"建不出来"：`mkdir(parents=True)` 必失败（NotADirectoryError），
    且与平台/权限无关，测试在 CI 上也稳定。
    """
    import logging

    blocker = tmp_path / "blocker"
    blocker.write_text("不是目录", encoding="utf-8")
    target = blocker / "overrides.db"

    conn = sqlite3.connect(":memory:", uri=True)
    try:
        with caplog.at_level(logging.WARNING, logger="vigil.overrides"):
            overrides.attach_readonly(conn, target)  # ⚠️ 不许抛
        assert "ov" in {r[1] for r in conn.execute("PRAGMA database_list")}
        # 降级挂的是**空库**：两张表都在、都是 0 行
        assert conn.execute("SELECT COUNT(*) FROM ov.item_state").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ov.item_edits").fetchone()[0] == 0
        # 零写：没有凭空造出文件、也没碰主库
        assert not target.exists()
        assert any("降级" in r.getMessage() for r in caplog.records), (
            "降级必须响亮：日志里没有这条警告"
        )
    finally:
        conn.close()


def test_attach_readonly_never_degrades_when_the_file_exists(tmp_path):
    """**R8 情形①**：文件**存在**但挂不上 ⇒ **必须响亮失败**，绝不降级。

    为什么不能一刀切降级：文件里**可能有墓碑**。降级 = 被软删的条目悄悄复活
    + 改过的类目回退——**直接违反 D15**，而且是"看起来一切正常"的那种违反。

    这里制造"挂不上"的手段与 T4 的哨兵同源（连接没开 `uri=True`，URI 被当成
    字面文件名）。与哨兵的分工：哨兵钉**平台事实**，本条钉**失败时的处置**。
    """
    target = tmp_path / "overrides.db"
    overrides.ensure_schema(target)  # ⚠️ 先让文件**存在**——这才是情形①
    assert target.is_file()

    conn = sqlite3.connect(":memory:")  # 刻意不开 uri=True ⇒ 挂载必失败
    try:
        with pytest.raises(overrides.OverlayError, match="不降级"):
            overrides.attach_readonly(conn, target)
        # 关键不变量：失败**绝不**退化成"挂上了一个空的 ov"
        assert "ov" not in {r[1] for r in conn.execute("PRAGMA database_list")}
    finally:
        conn.close()
    # 文件原样还在（没有因为它挂不上就删/重建）
    assert target.is_file()


def test_attach_readonly_fails_loudly_when_the_file_was_just_provisioned(tmp_path):
    """**R8-bis**：`ensure_schema` **成功**、但 `ATTACH` 失败 ⇒ 响亮失败，**不降级**。

    ⚠️ 判据是「**谁**失败」，不是「文件在不在」：
    · `ensure_schema` 失败 ⇒ 根本碰不到文件 ⇒ **降级**（上一条测试）；
    · `ensure_schema` 成功（或文件本来就在）但 `ATTACH` 失败 ⇒ **抛**（本条）。

    ⚠️ 这一格此前**没有任何测试**：降级分支与这一条之间只差「`ensure_schema`
    成功与否」，而"库是刚建出来的空库、里面肯定没有干预"是个**听起来很合理**的
    降级理由——按它降级，就把 T4 那句刻意设计（「新连接忘带 `uri=True` ⇒
    **响亮**失败，不是静默降级」）退回去了。
    """
    target = tmp_path / "fresh" / "overrides.db"
    assert not target.exists()
    conn = sqlite3.connect(":memory:")  # 刻意不开 uri=True ⇒ ATTACH 必失败
    try:
        with pytest.raises(overrides.OverlayError, match="不降级"):
            overrides.attach_readonly(conn, target)
        assert "ov" not in {r[1] for r in conn.execute("PRAGMA database_list")}
        # 与降级分支的分界：这里 `ensure_schema` **是成功**的（空库已建出来）
        assert target.is_file(), "ensure_schema 应当已经把空库建出来了（这才是分界）"
    finally:
        conn.close()


def test_delete_with_extra_sources_tombstones_every_message(ov):
    """⭐ E7/T8 裁决：一个 item 的**每一条**源消息都要落墓碑，**且 undo 要真救得回来**。

    形状的由来：`store.save_items` 的批内去重**来源取并集**（`store.py:307`），
    所以一个 item 可以有 ≥2 条源消息；`api_delete_item` 若只把 `srcs[0]` 落墓碑，
    `refine --redo` 重抽兄弟消息就会让条目**以新 item_id 复活**（违反 D15）。

    ⚠️ 判据必须**两个方向一起**：
    ① 删完：每条源 msg 都在墓碑集里（否则重抽复活）；
    ② undo 之后：条目复活 **且** 墓碑**全部消失**。
    只有 ① 的话，把 N 条源消息都写成 `delete` 事件也能过——而那种写法下
    `undo` 只删一条事件，`item_state.deleted` 仍是 1 ⇒ 条目**照旧隐藏**、
    undo 却报成功（用户看到「撤销没用」）。
    """
    eid = overrides.delete_item(ov, item_id=9, msg_id=555, extra_msg_ids=[556, 557])

    assert overrides.deleted_msg_ids(ov) == frozenset({555, 556, 557}), (
        "有源消息没被墓碑化——refine --redo 会把它重抽出来，条目以新 item_id 复活"
    )
    # 末尾那条事件必须是 delete 本身（undo 缺省撤的是它）
    assert overrides.last_edit(ov) == (eid, 9, "delete"), (
        "delete 事件不在尾部：墓碑行垫后的话 undo 撤掉的是墓碑行，条目仍被隐藏"
    )

    assert overrides.undo(ov, edit_id=eid) is True
    assert overrides.deleted_msg_ids(ov) == frozenset(), (
        "undo 之后墓碑还在——条目复活了，兄弟消息却被永久冻结"
    )
    assert ov.execute(
        "SELECT COUNT(*) FROM item_state WHERE item_id=9"
    ).fetchone()[0] == 0, "undo 之后条目仍被隐藏：这就是「撤销报成功、界面毫无反应」"


# --- M5 终审修复轮：非尾部 undo 不许静默弄坏状态（Important-1）-------


def _state_row(conn, item_id: int):
    row = conn.execute(
        "SELECT kind, deleted FROM item_state WHERE item_id = ?", (item_id,)
    ).fetchone()
    return (row["kind"], row["deleted"]) if row else None


def _edit_ids(conn) -> list[int]:
    return [int(r[0]) for r in conn.execute("SELECT edit_id FROM item_edits ORDER BY edit_id")]


def test_undo_refuses_when_it_would_re_hide_a_visible_item(ov):
    """⭐ M5 终审 Important-1：撤一条「某条目最后一条」事件，会让它**重新被软删** ⇒ 拒绝。

    形状（终审报的 `{life, deleted:0}` → `{kind:NULL, deleted:1}`）：先软删、
    再改分类 ⇒ 条目可见；此时撤掉那条 set_kind，它前面那条 delete 重新生效，
    条目从 Web 与日报同时消失，而调用方拿到「撤销成功」。

    ⚠️ 为什么**不是**一律拒绝非尾部：`test_undo_accepts_an_explicit_edit_id` 钉着
    「撤一条被后面 delete 覆盖的 set_kind 必须返回 True」——那种撤法对所有读取
    路径都惰性（放行的那半在下面两条里钉）。这里拒绝的是**会改变用户看得见的
    状态**的那一种。

    变异「把 `_reject_non_tail_undo` 里那段 savepoint 试算/`raise` 去掉」⇒ 本条红。
    """
    e_del = overrides.delete_item(ov, item_id=9, msg_id=555)
    e_kind = overrides.set_kind(ov, item_id=9, kind="life")
    # ⚠️ 必须再有一条**别的条目**的事件：否则 `e_kind` 就是全局尾部，
    # 而尾部的撤销是「回退最近一次操作」的既有语义，不走这道闸门。
    e_other = overrides.set_kind(ov, item_id=10, kind="life")
    assert e_del < e_kind < e_other
    assert _state_row(ov, 9) == ("life", 0), "造场景失败：set_kind 之后条目该是可见的"

    with pytest.raises(overrides.OverlayError, match="重新被软删"):
        overrides.undo(ov, edit_id=e_kind)

    assert _state_row(ov, 9) == ("life", 0), "被拒绝的撤销改动了状态——拒绝必须在写之前"
    assert _edit_ids(ov) == [e_del, e_kind, e_other], "被拒绝的撤销动了事件日志"
    assert overrides.deleted_msg_ids(ov) == frozenset(), "被拒绝的撤销动了墓碑集"

    # 拒绝不是「卡死」：撤掉它后面那条无关的编辑之后，它就回到**尾部**、照旧撤得掉
    # （尾部撤销 = 回退最近一次操作，那条软删重新生效是既有语义，不是本闸门的事）
    assert overrides.undo(ov, edit_id=e_other) is True
    assert overrides.undo(ov, edit_id=e_kind) is True
    assert _state_row(ov, 9) == (None, 1), (
        "尾部撤销应当让那条软删重新生效（deleted=1；kind 由 items 侧兜底）"
    )


def test_undo_allows_a_covered_event_and_a_plain_reclassification(ov):
    """放行的那两种形状（**既有的、被钉住的**语义不许被这次修复动到）：

    ① **被后面事件覆盖**的 set_kind ⇒ 惰性（最终态由那条决定），返回 True；
    ② **改分类的条目没被软删过** ⇒ 撤掉它只是把类目退回基础值，条目照旧可见
       ——「撤掉我早先给某条改的类目」是正常用法，不许被一刀切成 409。
    """
    # ① 同一个条目：set_kind 被后面那条 delete 覆盖，且后面还有别的条目的事件
    e_kind_a = overrides.set_kind(ov, item_id=7, kind="life")
    overrides.delete_item(ov, item_id=7, msg_id=1)
    e_other = overrides.set_kind(ov, item_id=8, kind="life")
    assert e_kind_a < e_other
    assert _state_row(ov, 7) == ("life", 1), "造场景失败：delete 之后 item 7 该被软删"

    assert overrides.undo(ov, edit_id=e_kind_a) is True, (
        "被覆盖的事件是惰性的——既有语义（test_undo_accepts_an_explicit_edit_id）要求 True"
    )
    # ⚠️ 判据是**读取路径能看到的东西**：`deleted` 不变（条目照旧隐藏）、
    # 墓碑集不变。`kind` 那一格会从 'life' 变成 NULL——它是 `delete` 折叠时
    # 保留旧 kind 的副产物，而所有读取路径都 `_NOT_DELETED` 过滤 +
    # `COALESCE(ost.kind, i.kind)` ⇒ 对一条**已被软删**的条目读不到。
    assert _state_row(ov, 7)[1] == 1, "撤一条被覆盖的事件把条目弄成可见了"
    assert overrides.deleted_msg_ids(ov) == frozenset({1}), "墓碑集也不该动"

    # ② 没被软删过的条目：非尾部地撤掉它早先那次改分类 ⇒ 类目退回基础值、条目仍可见
    e_kind_b = overrides.set_kind(ov, item_id=9, kind="work")
    overrides.set_kind(ov, item_id=10, kind="life")
    assert overrides.undo(ov, edit_id=e_kind_b) is True
    assert _state_row(ov, 9) is None, (
        "item 9 的事件被撤光了 ⇒ 物化表里不该留行（= 完全没被干预过）"
    )


def test_undo_refuses_a_tombstone_row(ov):
    """墓碑行不是可独立撤销的操作：撤它不改变任何可见状态，却拆掉 D15 的保护。

    终审记的第二形态原话：「undo 一条墓碑行 ⇒ 状态一点没变，照样返回 True
    （用户点「撤销」、毫无反应、系统说成功）」。而 `deleted_msg_ids` 一旦少一条，
    `refine --redo` 会把被软删的条目**以新 item_id 复活**。

    变异「把 `undo` 里墓碑行那道 `raise` 去掉」⇒ 本条红。
    """
    e_del = overrides.delete_item(ov, item_id=9, msg_id=555, extra_msg_ids=[556, 557])
    tombs = [
        int(r[0])
        for r in ov.execute(
            "SELECT edit_id FROM item_edits WHERE action = 'tombstone' ORDER BY edit_id"
        )
    ]
    assert len(tombs) == 2 and tombs[-1] < e_del, "造场景失败：墓碑行该垫在 delete 之前"
    assert overrides.deleted_msg_ids(ov) == frozenset({555, 556, 557})

    with pytest.raises(overrides.OverlayError, match="墓碑"):
        overrides.undo(ov, edit_id=tombs[0])

    assert _edit_ids(ov) == [*tombs, e_del]
    assert overrides.deleted_msg_ids(ov) == frozenset({555, 556, 557})


def test_undo_refusal_does_not_discard_caller_writes(ov):
    """拒绝分支与 savepoint 试算都不许丢掉调用方**未提交**的写入（FIX 2 同族）。

    `undo` 的试算是「真删一次、`rebuild_state`、然后 `ROLLBACK TO SAVEPOINT`」：
    省掉那个 savepoint 就会把调用方已经写进来、还没 commit 的行一起回滚掉
    ——这正是 reviewer 当年实测的 FIX 2（1→0）。而 savepoint 本身也是**写**，
    所以这条要单独钉住。
    """
    e_del = overrides.delete_item(ov, item_id=9, msg_id=555)
    e_kind = overrides.set_kind(ov, item_id=9, kind="life")
    ov.execute(
        "INSERT INTO item_edits (item_id, msg_id, action, actor, created_at)"
        " VALUES (30, 31, 'delete', 't', 0)"
    )

    with pytest.raises(overrides.OverlayError):
        overrides.undo(ov, edit_id=e_kind)

    assert ov.execute(
        "SELECT COUNT(*) FROM item_edits WHERE item_id = 30"
    ).fetchone()[0] == 1, "undo 的拒绝分支把调用方未提交的写入回滚掉了"
    assert len(_edit_ids(ov)) == 3, (
        "试算那次 DELETE 没有被回滚干净：日志里只剩 3 条（两条真实的 + 调用方那一条）"
    )
    assert _state_row(ov, 9) == ("life", 0)


def test_undo_conflict_is_its_own_type_not_a_dumb_overlay_error(ov):
    """⭐ M5 收尾 scoped re-review A2：两道闸门抛的是 **`UndoConflict`**。

    `OverlayError` 这个父类罩着两种后果完全不同的病：
      * **与日志状态冲突**（`_reject_non_tail_undo`）⇒ 请求合法、换一条编辑撤就能成
        ⇒ API 侧该 409；
      * **基础设施故障**（overlay 文件缺失/挂不上/路径非法）⇒ 服务端自己坏了
        ⇒ API 侧该 5xx。

    修复前 `api_undo` 一网打尽映成 409，于是 overlay 挂不上时客户端收到
    「与日志状态冲突」，排障指向错方向。这条在**数据层**钉住判据的**类型**：
    两处 raise 都必须给 `UndoConflict`（子类），同时它必须仍是 `OverlayError`
    的子类（既有 `except OverlayError` 的调用方一个都不用改）。

    变异「把两处 `raise UndoConflict(` 改回 `raise OverlayError(`」⇒ 本条红
    （2 failed——两处各一条），而 API 侧那条 5xx 守卫也一起红。
    """
    assert issubclass(overrides.UndoConflict, overrides.OverlayError), (
        "UndoConflict 必须仍是 OverlayError 的子类——否则既有的 except OverlayError 全漏"
    )

    # 闸门一：墓碑行
    e_del = overrides.delete_item(ov, item_id=9, msg_id=555, extra_msg_ids=[556])
    tomb = ov.execute(
        "SELECT MIN(edit_id) FROM item_edits WHERE action = 'tombstone'"
    ).fetchone()[0]
    with pytest.raises(overrides.UndoConflict, match="墓碑"):
        overrides.undo(ov, edit_id=int(tomb))

    # 闸门二：撤掉会让可见条目重新被软删
    e_kind = overrides.set_kind(ov, item_id=9, kind="life")
    e_other = overrides.set_kind(ov, item_id=10, kind="life")
    assert e_del < e_kind < e_other
    with pytest.raises(overrides.UndoConflict, match="重新被软删"):
        overrides.undo(ov, edit_id=e_kind)
    assert _state_row(ov, 9) == ("life", 0), "被拒绝的撤销改动了状态"
