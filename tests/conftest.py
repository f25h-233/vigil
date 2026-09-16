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
    """内存库。用完即弃，不污染任何真实文件。"""
    conn = sqlite3.connect(":memory:")
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
