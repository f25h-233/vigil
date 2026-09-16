"""共享测试夹具。

原则：测试不碰真实的 QQ 加密库、不碰 data/vigil.db、不联网。
全部用内存 SQLite 与构造出来的样本数据。
"""

from __future__ import annotations

import pathlib
import sqlite3
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ⚠️ 这个 import 是**安全**的：`vigil.config` 在模块级只算路径常量
# （`REPO_ROOT` / `LOCK_PATH`），不读文件也不建目录——真正读 `.env`、读
# `groups.toml` 的都在函数里。所以 import 它不会碰到真实的 `data/`。
from vigil import lock  # noqa: E402

# 同理安全：`vigil.overrides` 模块级只算 `OVERRIDES_DB` 路径常量与几张 DDL 字符串，
# **不建目录、不连库**（真正建库的 `ensure_schema()` 在函数里）。所以 import 它不会
# 碰真实的 `data/`。
from vigil import overrides  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_overrides_path(tmp_path_factory, monkeypatch):
    """把人工干预层的默认路径挪出仓库——**否则写路径会建真实的 `data/overrides.db`**。

    ⚠️ `store.ensure_schema()` 现在会调 `overrides.ensure_schema()`（M5 Task 4 Step 5），
    而它**每次 refine / digest 都跑**（测试里有 5 个文件、几十处在调它）。
    没有这个夹具，跑一次全量就在真实的 `data/` 里留下一个干预层库；更糟的是：

      ① **污染**：将来有用例往里面写了事件（改分类 / 软删 / 撤销），那些就是
         **用户真实的人工修改数据**被测试改写——而 `data/` 不入 git，
         **没有任何东西能把它还原**；
      ② **假红**：与 `data/vigil.lock` 同族的形态——只在"真库恰好有状态"时出现，
         看着像产品缺陷、其实是测试污染。

    ⚠️ **不能用 `tmp_path`**（本夹具初版就踩了）：有些用例把 `tmp_path` 当**产品
    目录**用，并按**文件集合**断言。`tests/test_digest.py` 的两条持久化用例就是
    `sorted(p.name for p in tmp_path.iterdir()) == ["2026-09-13.md"]`——
    overlay 库一旦落在 `tmp_path` 里，它们会**变成红的，而红的原因与它们要守的
    不变量毫无关系**（实测：2 failed / 459 passed）。
    所以这里用 `tmp_path_factory.mktemp()` 另开一个**每次调用唯一**的目录：
    它不在被测代码会去列目录的那些路径下。

    ⚠️ 用 autouse：漏掉一个测试文件就退化为上面两条。
    ⚠️ 只换路径、**不建文件**：建库仍然是 `ensure_schema()` 的职责
    （读路径不建库是刻意的设计，夹具不该替它把文件先造出来）。
    """
    monkeypatch.setattr(
        overrides, "OVERRIDES_DB", tmp_path_factory.mktemp("overrides") / "overrides.db"
    )


@pytest.fixture(autouse=True)
def _isolate_lock_path(tmp_path, monkeypatch):
    """把单实例锁的默认路径挪到 tmp——**否则跑测试会碰真实的 `data/vigil.lock`**。

    ⚠️ 两个后果，第二个比第一个严重得多：

      ① **污染**：跑一次全量就在 `data/` 里造一个 `vigil.lock`（虽然 `data/`
         不入库）；
      ② **假红**：F4 之后 `cmd_export`/`cmd_refine`/`cmd_digest` 都加锁，
         而 `cli_env` 那批用例**不换锁路径**。于是**若真有实例在跑**
         （比如 M4 冒烟的短触发器正好在跑 `vigil daily`），那些测试会拿到
         退出码 **2** 而**莫名变红**——**看着像产品缺陷，其实是测试污染**。

    ⚠️ 用 autouse：漏掉一个测试文件就退化为上面第 ② 条，而它是**环境相关的**
    ——只在"恰好有实例在跑"时出现，最难查。
    """
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "vigil.lock")


@pytest.fixture
def memdb():
    """内存库。用完即弃，不污染任何真实文件。

    ⚠️ `uri=True` 是 Task 5 加的，**必须**：查询层入口会
    `ATTACH 'file:...?mode=ro'`，而 URI 形式**只在连接带 `SQLITE_OPEN_URI`
    时才被解析**（Task 4 实测、T5 复核）。不带这个标志，每条走查询层的用例都会抛
    `OverlayError`——而那不是产品缺陷。对 `:memory:` 而言这个标志
    **不影响任何行为**（路径不以 `file:` 开头时它就是个空开关），
    与生产侧三处连接的补齐（`cli.py` / `digest.py` / `refine.py`，裁决 R4）是同一件事。
    """
    conn = sqlite3.connect(":memory:", uri=True)
    yield conn
    conn.close()


@pytest.fixture
def msg_factory():
    """快速造 PendingMessage。Task 5 的预筛测试要用。"""
    from vigil.store import PendingMessage

    def make(
        msg_id: int,
        content: str,
        *,
        group_id: int = 100,
        ts: int = 1_700_000_000,
        sender: str = "某同学",
        uid: str = "u_x",
    ) -> PendingMessage:
        return PendingMessage(
            msg_id=msg_id,
            group_id=group_id,
            ts=ts,
            sender_uid=uid,
            sender=sender,
            content=content,
        )

    return make
