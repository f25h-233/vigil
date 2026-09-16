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


def _bigrams(text: str) -> frozenset[str]:
    """去掉分隔符与空白后的全部 2 字子串。

    分隔符按实测数据里真出现过的集合取（item 271 用顿号、item 137 用全角竖线）。
    """
    cleaned = _PLACE_SEP.sub("", text)
    return frozenset(cleaned[i : i + 2] for i in range(len(cleaned) - 1))


_PLACE_SEP = re.compile(r"[\s、,，/｜|·]+")


def place_supported(place: str | None, sources: str) -> bool:
    """源文里能不能找到这个地点的依据。

    ⚠️ **判据刻意做得宽**（任一 2 字子串命中即算有依据），因为 place 与 deadline
    的性质不同：deadline 驱动「⏰ 别忘」，错了会让人误事；place 只是显示提示。
    实测：整串匹配太严会误杀「西太湖校区 ← 源文『西太湖连隔板』」这类。

    ⚠️ **短于 2 字的 place 判据不适用 ⇒ 返回 True**。真实数据里 item 295 的
    place 是单字「湖」，bigram 对它恒为空集——写成 False 会静默误清，
    且没有任何测试会因此变红（M2「多分支判据必须多分支守卫」）。
    """
    if not place:
        return True
    grams = _bigrams(place)
    if not grams:
        return True
    return bool(grams & _bigrams(sources))


def deadline_sane(deadline_ts: int | None, event_ts: int) -> bool:
    """截止日不早于消息当天——`deadline` 字段的语义是**需要行动的截止日**。

    ⚠️ 这不是"幻觉检测"（那由 `deadline_supported` 负责）。item 83 的
    `档案袋封口时间：5 月 6 日` 在源文里**找得到**、抽取也没错，它是**过去的既成事实**——
    但它不满足「需要行动」这个语义，所以不该占着「⏰ 别忘」那一节。

    判据按**本地日**比较（与 `_day_start` 的口径一致）：同一天不过夜 ⇒ 放行。
    """
    if deadline_ts is None:
        return True
    day_start = _day_start_of(event_ts)
    return deadline_ts >= day_start


def _day_start_of(ts: int) -> int:
    """某个 epoch 秒**所在的本地日**的 00:00（epoch 秒）。

    ⚠️ **偏差（逃逸舱第 1 种形状，见报告「偏差」第 3 条）**：brief 只有前两行，
    而它在 Windows 上会**抛**——``datetime(1970,1,1).timestamp()`` 是负 epoch，
    本机抛 ``OSError [Errno 22]``（与 `_parse_deadline` 的 docstring 同一条限制：
    1970-01-03 之前的本地时间转不成 unix 秒，本机实测 ``fromtimestamp(-28800)``
    同样抛）。后果**不是"测试红"而是静默丢数据**：调用点在 `_to_item` 里，而它
    的外层是 `refine()` 每批的 ``try/except``——一个超前/畸形的 `event_ts` 会让
    **整批**的 items 一条都不落库，只留一行 error。既有夹具 ts=1000（1970）正好
    命中它，实测把 `test_refine_parses_deadline` 与
    `test_refine_wires_the_deadline_drop_end_to_end` 打红，这条路才被发现。

    ⇒ 正常路径**逐字保留** brief 的写法（结果与 `api._day_start` 同口径），
    只在它抛的那一格补一个**纯算术**回退：`fromtimestamp` 拿到的本地墙钟减去
    「当日已过的秒数」就是本地午夜，全程不再对负 epoch 调 `timestamp()`。
    中国无夏令时，本机两条路径逐秒一致；跨 DST 时区时回退路径的口径要重新裁决。
    """
    d = dt.datetime.fromtimestamp(ts)
    try:
        return int(dt.datetime.combine(d.date(), dt.time.min).timestamp())
    except (OSError, OverflowError):  # Windows：1970-01-03 之前的本地时间
        return ts - (d.hour * 3600 + d.minute * 60 + d.second)
