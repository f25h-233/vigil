"""日报合成：把某个时间窗内的 items 写成给同学看的一页 Markdown。

三条设计判断，每条都有实测或 spec 支撑：

1. **输入是 items，不是原始消息**（spec §2.4）。筛选在 M1 已经做完，
   日报**不再筛第二遍**——窗口内每条 item 都必须出现在日报里，
   否则就是又一个静默过滤器，而「静默漏掉」正是这个工具最不能犯的错。
2. **不问模型要 item_id**。M1 实测：19 位雪花号命中 0/2、批内序号在真实
   管线里也错。改成让模型**逐字摘录 title**，由 ``match_lines`` 本地定位。
3. **模型只负责措辞与合并，版式由程序确定性渲染**（与 spec §4.6 的偏差 1）。
   自由发挥的 Markdown 无法可靠回连 ``digest_items``，而 spec §2.3 要求
   「日报里说的每一条，必然能在 Web 里找到」。

模型输出契约（``{"lines": [{"quotes": [...], "label": "...", "text": "..."}]}``）
的措辞经真实数据探针验证：9/13 的 10 条并成 8 行、9/8 的 13 条并成 7 行，
两天都是 100% 覆盖、0 处 quote 未命中。
"""

from __future__ import annotations

import datetime as dt

from . import store
from .llm import sanitize_for_llm
from .redact import Redactor

# 日报有自己的提示词版本，与 refine.PROMPT_VERSION 各记各的。
# 改了 build_system_prompt 就要升这里，否则 digests 表里新老产出分不清。
PROMPT_VERSION = "v1"

# 低于这个置信度的行不混进正文，单列到末尾的「🤔 拿不准的」区块。
# 实测全库只有 1 条落在这个区间（M1 误抽的「咨询：四六级报名时间」，0.10），
# 所以它是安全阀而非常态。
LOW_CONFIDENCE = 0.5

# 输出上限。正常一天 20 条 item 的日报约 550 输出 token，2000 有充足余量；
# 但要小到能在模型退化时及时掐断（见 vigil/llm.py 的退化说明）。
MAX_TOKENS = 2000


def build_system_prompt() -> str:
    """系统提示词。

    ⚠️ 第 6 条（不要写群名）是实测逼出来的：不写这条时模型会把群名当主语
    写进 text（「常大二手咸鱼⑤群发布兼职招聘」），而群名是程序在行尾另外
    追加的，读起来就重复了。但群名**又必须发**——它是模型判断「哪些条目
    属于同一件事」的信号，去掉后 9/13 的合并从 8 行退化回 10 行。
    所以：**发群名，但明令禁止写进输出。**

    ⚠️ 第 2 条（合并）要写在 rules 前部：合并是 spec §4.6 明确要求的
    「合并同类项」，漏掉它日报就退化成 items 的流水账。
    """
    return """你是校园信息日报的编辑。把当天从各个 QQ 群里提炼出的条目，写成一份给同学看的一页日报。

读者的诉求是：**一眼看完，不漏事**。

规则：

1. **每一条 item 都必须出现在日报里**——不能因为"这条不重要"就省略。
2. **讲同一件事的多条 item 合并成一行**：同一个活动、同一个部门、同一件事的
   多条动态，合成一行讲清楚。合并时 quotes 要把涉及的每一条都列上。
3. quotes：逐字摘录你引用的那几条 item 的 title 原文片段。程序拿它回连条目，
   **匹配不上的行会被丢弃**，所以必须逐字照抄，不要改写。
4. label：**不超过 12 个字**的短标签，说明这一行讲的是什么。它会加粗显示在行首，
   要能一眼扫到，**不要写成完整句子**。
5. text：一句话说清细节，让人不看原文就知道该怎么办；没有额外信息时给空串。
6. 输入里的 group 字段只用来帮你判断哪些条目属于同一件事，
   **不要把它写进 label 或 text**——程序会在行尾自动标注来源群。
7. **不要编造 item 里没有的信息**——时间、地点、部门、人名，宁可不写也不能补。

输出必须是 JSON 对象，形如 {"lines": [{"quotes": ["..."], "label": "...", "text": "..."}]}。"""


def build_items_payload(
    items: list[store.WindowItem],
    names: dict[int, str],
    redactor: Redactor,
) -> list[dict]:
    """把窗口内的 items 整理成发给模型的 JSON。

    ⚠️ 三条硬规则，每条都有实测支撑，少一条都出过事：

    * **只发群名，不发群号**（spec §4.5）。规划期间的探针第一版就是把
      ``group_id`` 明文发了出去——全库 15 个群号本来就不该出网。
    * **过 Redactor**：item 是模型从已脱敏文本里抽的，但它会「补出原文
      没有的实体」，所以出网前再抹一遍号码。
    * **过 sanitize_for_llm**：全角引号会让模型退化成无限空格循环。
    """

    def clean(value: str | None) -> str | None:
        if not value:
            return None
        return sanitize_for_llm(redactor.text(value)) or None

    payload = []
    for item in items:
        payload.append(
            {
                "title": clean(item.title) or "",
                "detail": clean(item.detail),
                "kind": item.kind,
                "time": dt.datetime.fromtimestamp(item.event_ts).strftime("%H:%M"),
                "place": clean(item.place),
                "amount": clean(item.amount),
                "deadline": (
                    dt.datetime.fromtimestamp(item.deadline_ts).strftime("%Y-%m-%d")
                    if item.deadline_ts
                    else None
                ),
                "group": sanitize_for_llm(names.get(item.group_id, "")),
            }
        )
    return payload


def build_user_prompt(payload: list[dict], *, day: str) -> str:
    """用户提示词。载荷已经是脱敏过的，这里只负责拼装与注入日期。

    注入「今天是哪天」是必须的——M1 实测：不告诉模型今天，它会把
    「9月7号」猜成过去的年份。
    """
    import json

    body = json.dumps({"items": payload}, ensure_ascii=False, indent=1)
    return f"今天的日期是 {day}。\n\n以下是 {day} 这一天提炼出的条目：\n{body}"
