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
