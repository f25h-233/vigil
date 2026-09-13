"""发信人姓名解析：把消息里的 nt_uid 还原成「谁说的」。

数据源是 group_info.db 的 group_member3 表（列义由 QQDecrypt 文档确认）：

    1000  = nt_uid      ← 对应消息表 group_msg_table 的 [40020]
    64003 = 群昵称      （未设置为空）
    20002 = QQ 昵称
    1002  = QQ 号
    64016 = 是否仍是群成员（0=在群，1=已退群）

本机实测：97% 的 (群号, uid) 组合可解析出姓名——远好于 nt_msg.db 里
只有 44 行的 nt_uid_mapping_table。
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from . import qqdb


@dataclass(frozen=True)
class Sender:
    """一个人的三种称呼。群昵称优先，因为它才是群里认得出的那个名字。"""

    group_nick: str = ""
    qq_nick: str = ""
    uin: int = 0
    in_group: bool = True

    @property
    def display_name(self) -> str:
        return self.group_nick or self.qq_nick or (str(self.uin) if self.uin else "未知")


def load_senders(group_info_path: pathlib.Path, key: str) -> dict[tuple[int, str], Sender]:
    """返回 {(群号, nt_uid): Sender}。

    取不到就返回空字典——姓名是锦上添花，不该让导出失败。
    """
    try:
        conn = qqdb.open_encrypted(group_info_path, key)
    except Exception:  # noqa: BLE001
        return {}

    try:
        rows = conn.execute(
            "SELECT [60001], [1000], [64003], [20002], [1002], [64016] FROM group_member3"
        ).fetchall()
    except Exception:  # noqa: BLE001
        return {}
    finally:
        conn.close()

    senders: dict[tuple[int, str], Sender] = {}
    for gid, uid, group_nick, qq_nick, uin, left in rows:
        if not uid:
            continue
        senders[(int(gid), str(uid))] = Sender(
            group_nick=(group_nick or "").strip(),
            qq_nick=(qq_nick or "").strip(),
            uin=int(uin or 0),
            in_group=(left or 0) == 0,
        )
    return senders
