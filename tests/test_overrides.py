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
