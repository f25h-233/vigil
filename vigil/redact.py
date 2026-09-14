"""发送前的脱敏：把能指到具体人的东西挡在本机。

**保留姓名是刻意的**——实测的群昵称直接编码了角色
（「储运263班主任助理卞雨琦19551968610」），这是判断「谁发的、
是不是官方」最可靠的信号，剥掉等于废掉抽取层。

抹掉手机号与长数字串（学号）——这两样在实测的群昵称里高频出现
（`2600090309张韩18368500707`），是真正的身份标识。

为什么不会误伤日期：`2026-10-08` 中间的连字符让它不命中 `\\d{10,}`，
`9月15日` 同理。这条边界有测试守着（test_does_not_touch_dates_or_amounts）。
"""

from __future__ import annotations

import re

PLACEHOLDER = "<号码>"

# 手机号：11 位、1 开头、第二位 3-9
PHONE = re.compile(r"1[3-9]\d{9}")

# 学号等长数字串。放 10 位是有意的：QQ 号最长 11 位、
# 学号常见 10-12 位，而日期与金额都远短于 10 位。
LONGNUM = re.compile(r"\d{10,}")


def redact_text(text: str) -> str:
    """抹掉手机号与长数字串，保留其余一切。"""
    return LONGNUM.sub(PLACEHOLDER, PHONE.sub(PLACEHOLDER, text))


class Redactor:
    """一次 run 内保持代号稳定的映射器。

    映射只活在内存里：`items` 表存的是原始 `group_id` 与 `sender_uid`，
    回填时不需要从代号反解，所以这套映射不落盘——落盘反而是多余的泄漏面。
    """

    def __init__(self) -> None:
        self._groups: dict[int, str] = {}
        self._actors: dict[str, str] = {}

    def group(self, gid: int) -> str:
        if gid not in self._groups:
            self._groups[gid] = f"G{len(self._groups) + 1}"
        return self._groups[gid]

    def actor(self, uid: str) -> str:
        if uid not in self._actors:
            self._actors[uid] = f"U{len(self._actors) + 1}"
        return self._actors[uid]

    def text(self, s: str) -> str:
        return redact_text(s)
