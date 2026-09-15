"""截止日核验：这个日期能不能在**源消息正文里逐字找到**。

为什么单独成模块：核验最初长在 M2 的日报渲染层（「别忘」那一节），
而**截止日的可信度是数据属性，不是渲染属性**。M3 的 Web 直接读
`items.deadline_ts`，只在渲染层挡的那道闸门就绕过去了——实测全库 26 条
带截止日的 item 里约半数过不了核验，Web 会把它们原样复活。

所以核验被提到数据层：写入时（refine）挡一次，历史数据用
`vigil deadline-audit --apply` 回填一次。之后**所有读取方自动安全**。
"""

from __future__ import annotations

import datetime as dt
import re


# 汉字写法里各成分之间允许的空白：实测源文有「9 月 16 日」这种写法。
#
# ⚠️ 用 ``[^\S\n]``（横向空白）而**不是** ``\s``：源文是**多条消息用 "\n" 拼起来的**
# （``store.item_sources_text``），容忍换行的话「……9月」结尾的一条消息与
# 「16日开始……」开头的另一条会被粘成一个日期——凭空造出「源文里有」的证据。
# 上一版把整个 haystack 的空白全部删掉（``\s+`` → ``""``），正是这个毛病。
_GAP = r"[^\S\n]*"


def _date_patterns(ts: int) -> tuple[re.Pattern[str], ...]:
    """同一个日期在中文语料里的常见写法（编译后的正则）。**只认带月份的写法。**

    两类，边界规则不同：

    * **数字写法**（``9-16`` / ``9/16`` / ``9.16`` / ``2026-09-16`` …）两侧
      **不能紧挨数字**。审查 F2 在真实库上实测，下面 4 行上一版**全部返回 True**
      （源文里只有 9 月 30 日，却给一条 9 月 3 日的截止日背书；后两行同形）::

          deadline_supported(9-3, "9/30截止")
          deadline_supported(9-3, "9-30截止")
          deadline_supported(9-3, "2026/09/30")
          deadline_supported(9-16, "119-16")

      边界是**纯数字**的（不含 ``-`` / ``/`` / ``.``）：这样「9/3-9/5 报名」这类
      日期区间、以及「2026-09-16」这种更完整的写法都不会被自己的边界误伤。
      注意边界**只挡数字**，所以「9-16 12:00」照旧命中——日期后面跟的是时间。
    * **汉字写法**（``9月16日`` / ``9月16号``）由「月/日」夹住，天然有边界，
      且允许成分间有横向空白（``9 月 16 日``）。
    """
    d = dt.datetime.fromtimestamp(ts)
    y, m, dd = d.year, d.month, d.day
    numeric = (
        f"{y}-{m:02d}-{dd:02d}",
        f"{y}/{m:02d}/{dd:02d}",
        f"{m:02d}-{dd:02d}",
        f"{m}-{dd}",
        f"{m:02d}/{dd:02d}",
        f"{m}/{dd}",
        f"{m:02d}.{dd:02d}",   # 实测源文有「9.11左右截止」（item 258）
        f"{m}.{dd}",           # 实测源文有「9.6上午」（item 84）
    )
    return (
        *(re.compile(rf"(?<!\d){re.escape(f)}(?!\d)") for f in numeric),
        re.compile(rf"{m}{_GAP}月{_GAP}{dd}{_GAP}[日号]"),
    )


def deadline_supported(deadline_ts: int | None, sources: str) -> bool:
    """源文里能不能逐字找到这个日期。**找不到就是没有依据。**

    ⚠️ 判据刻意做成机械可判的（不是再叫一个模型去判）：
    源文里找得到就是找得到，找不到就是没有依据。这样它可以被测试守卫，
    也不会引入第二个模型的判断。

    ⚠️ 为什么要这一步（首次冒烟的真实数据破坏）：M1 的抽取会补出原文没有的
    实体，源文只写「明早7:20集合」「周六下午4.00-8.00」时它照样填了具体日期，
    而「⏰ 别忘」把这个幻觉洗成了机器权威——用户拿去办事的地方在骗人。

    ⚠️ **只认带月份的写法**（``9月16日`` / ``9-16`` / ``9.16`` …）。「26号」「30号」
    这种**裸日不算依据**——修复轮次 1 移除的「裸日回退」在真实库上精度 **0/2**
    （item 88 源文「我有一个朋友26号就开学」被拿去给标着 09-26 的截止日背书、
    item 109 源文「30号就得到学校」给 09-30 背书，两条的语境都指向当月），
    方向同样是"往后飘"。核对月份这一步不能省。
    """
    if not deadline_ts:
        return False
    return any(p.search(sources) for p in _date_patterns(deadline_ts))


def unverified_item_ids(
    items: list[tuple[int, int | None]], sources: dict[int, str]
) -> frozenset[int]:
    """哪些 item 的截止日**在源文里没有依据**（只统计真有截止日的那些）。

    没有来源行的 item（``sources`` 里查不到）一律按**无依据**处理——
    与 ``digest.verified_deadlines`` 同一口径：**证不出来就是没有**。

    ⚠️ 这里返回的是「该清掉」的集合，而不是「该保留」的集合。命名方向
    故意与 ``verified_deadlines`` 相反，因为它们各自的调用点是反的：
    渲染层是「挑出可信的去显示」，数据层是「挑出不可信的来清掉」。
    """
    out: list[int] = []
    for item_id, deadline_ts in items:
        if deadline_ts and not deadline_supported(deadline_ts, sources.get(item_id, "")):
            out.append(item_id)
    return frozenset(out)
