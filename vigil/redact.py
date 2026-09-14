"""发送前的脱敏：把能指到具体人的东西挡在本机。

**保留姓名是刻意的**——实测的群昵称直接编码了角色
（「储运263班主任助理卞雨琦19551968610」），这是判断「谁发的、
是不是官方」最可靠的信号，剥掉等于废掉抽取层。

四层遮蔽，各挡一类东西：

1. **URL 段整体豁免**（见 ``redact_text``）——链接里的文档 ID / 分享 token
   是结构化标识符，不是身份号；抹掉会把链接打烂，而 ``links`` 是 item
   schema 的一等字段。**实测依据**：不豁免时全库 34 条链接有 2 条被打烂
   （B 站分享链的 32 位 hex ``vd_source``）。
2. **手机号** —— 两侧带数字边界，不在更长的数字串内部匹配。缺了边界，
   ``1788234567890`` 的前 11 位会被咬掉、留下 ``90`` 的残渣。
3. **长数字串（≥10 位）** —— 学号、订单号一类。
4. **身份标签后的短数字** —— QQ 号常见 8 位、群号 9 位，**位数阈值够不着**，
   只能靠上下文。**实测依据**：不加这条时 ``81464214``（QQ）、
   ``421632774``（群号）会原样出网。

为什么不会误伤日期：``2026-10-08`` 中间的连字符让它不命中 ``\\d{10,}``，
``9月15日`` 同理；身份标签规则要求前面必须有 ``QQ``/``群号`` 之类的词，
所以 ``第 3 教学楼`` 不会被误伤。两条边界都有测试守着。
"""

from __future__ import annotations

import re

PLACEHOLDER = "<号码>"

# 链接：整段豁免。\S+ 是刻意的——QQ 消息里的链接后面常紧跟中文标点。
URL = re.compile(r"https?://\S+|www\.\S+")

# 手机号：11 位、1 开头、第二位 3-9。
# 两侧的数字边界不能省：没有它，13 位的 1788234567890 会被咬掉前 11 位、
# 留下 "90" 这样的残渣（W1 审查实测）。
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

# 学号/订单号一类。10 位是下限：日期与金额远短于此，不会误伤。
LONGNUM = re.compile(r"\d{10,}")

# 身份标签后的短数字。QQ 号/群号常见 5-9 位，位数阈值挡不住，只能靠上下文。
#
# ⚠️ 第一版只枚举了 `QQ|群号|微信` 一类字面标签——**实测几乎没起作用**：
# 真实语料里 5-11 位泄漏只从 107 降到 100。中文写法太散，枚举是打地鼠。
# 关键修法是把 **「群」字本身** 当标签（`交流群548412164`、`QQ通知群：421632774`、
# `加qq群 831560802` 全都以它收口），并加 IGNORECASE 覆盖 qq/Qq/QQ 大小写。
# `(?!\d)` 是防残渣：12 位数字若被 `\d{5,12}` 咬掉前 12 位会留下一位尾巴。
IDENTITY_NUM = re.compile(
    r"((?:qq|Q号|企鹅|群号|学号|工号|微信号|微信|wx|vx|群)\s*[:：]?\s*)"
    r"(\d{5,12})(?!\d)",
    re.IGNORECASE,
)

# ⚠️ `群号` 与 `群` 两个备选**都必须留**，不能只留 `群`：
# 「群号 421632774」里 群 后面跟的是「号」不是数字，光靠 `群` 匹配不上。
# （这条是 controller 誊写计划时删错备选、被自测抓回来的。）


def _redact_segment(text: str) -> str:
    """对**不含 URL** 的片段做遮蔽。"""
    text = IDENTITY_NUM.sub(lambda m: m.group(1) + PLACEHOLDER, text)
    text = PHONE.sub(PLACEHOLDER, text)
    return LONGNUM.sub(PLACEHOLDER, text)


def redact_text(text: str) -> str:
    """抹掉可识别到个人的号码，保留其余一切（含姓名）。

    URL 段**整体豁免**：链接里的文档 ID / 分享 token 是结构化标识符，
    抹掉会把链接打烂，而报名链接正是本项目最想抽出来的东西。
    代价是 URL 里若嵌了手机号会一并放行——这个取舍是刻意的：
    打在链接上的损失是确定的（实测 2/34），而手机号出现在 URL 里极罕见。
    """
    parts: list[str] = []
    last = 0
    for match in URL.finditer(text):
        parts.append(_redact_segment(text[last : match.start()]))
        parts.append(match.group(0))  # URL 原样保留
        last = match.end()
    parts.append(_redact_segment(text[last:]))
    return "".join(parts)


class Redactor:
    """一次 run 内保持代号稳定的映射器。

    映射只活在内存里：`items` 表存的是原始 `group_id` 与 `sender_uid`，
    回填时不需要从代号反解，所以这套映射不落盘——落盘反而是多余的泄漏面。

    ⚠️ ``actor('')`` 会抛 ``ValueError``，这是刻意的。匿名发送者
    （实测全库 1,218 条 = 2.55%）**没有身份可言**：给它们一个共享代号，
    模型就会把互不相识的人当成同一个人。调用方必须对空 uid 特判、
    逐条区分（见 ``refine.build_user_prompt``）。

    至于为什么用 fail-fast 而不是静默返回一个占位符：静默的话，
    一次误调用就会把后续**所有真实 uid 的代号整体错位**（W1 审查实测），
    而错误要到产出质量变差时才被发现——那时已经烧掉一整轮 token 了。
    """

    def __init__(self) -> None:
        self._groups: dict[int, str] = {}
        self._actors: dict[str, str] = {}

    def group(self, gid: int) -> str:
        if gid not in self._groups:
            self._groups[gid] = f"G{len(self._groups) + 1}"
        return self._groups[gid]

    def actor(self, uid: str) -> str:
        if not uid:
            raise ValueError(
                "actor() 不接受空 uid——匿名发送者没有身份，"
                "必须由调用方逐条区分（见 refine.build_user_prompt）"
            )
        if uid not in self._actors:
            self._actors[uid] = f"U{len(self._actors) + 1}"
        return self._actors[uid]

    def text(self, s: str) -> str:
        return redact_text(s)
