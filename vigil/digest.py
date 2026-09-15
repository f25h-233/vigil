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
import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import store
from .categories import load_categories
from .config import Config, REPO_ROOT
from .llm import DEFAULT_MODEL, LLMConfig, LLMError, chat_json, sanitize_for_llm
from .redact import Redactor

# 日报有自己的提示词版本，与 refine.PROMPT_VERSION 各记各的。
#
# ⚠️ 升版范围是「**发往模型的任何文本**」，不只是 build_system_prompt：
# 模型看到的输入 = `build_system_prompt()`（system）**加上**
# `build_user_prompt()` 包裹的 `build_items_payload()`（user）。
# 这三处任何一处的**字段集或措辞**变了，产出就与前版不可比，而
# `digests.prompt_ver` 正是 M3 判断「哪些日报该重跑」的依据——漏升一次，
# 两版产出会被当成一版。**改 payload 字段的人也在范围内。**
PROMPT_VERSION = "v1"

# 系统提示词指纹：`(版本号, sha256(build_system_prompt())[:12])`。
#
# 改成指纹而不是「7 条规则各一个短语」式断言，是因为那种写法**开火方向反了**：
# 它对措辞微调过敏（规则 5「说清」→「讲清」也红），却抓不住真正改行为的
# 三类编辑（前言、末尾的 JSON 形状行、增删规则）。而且它制造反向激励——
# 改措辞必红 → 人养成「顺手改测试里的字符串」的肌肉记忆 → 同一个动作
# 正好绕开 PROMPT_VERSION。
#
# 指纹把两件事绑在一次编辑里：**测试变红时，提示词与版本号两件都要动**。
# ⚠️ 元组里的版本号与 PROMPT_VERSION 是**刻意重复**的，不是笔误：
# 若写成 `(PROMPT_VERSION, sha)`，改版本号时两边一起变、断言恒真，
# 这个守卫就废了（这正是它替换掉的那条断言的老毛病）。
#
# 已知覆盖边界（别把这条当万能）：它只覆盖 `build_system_prompt` 的正文。
# `build_user_prompt` / `build_items_payload` 的改动**没有自动守卫**，
# 只有上面那段注释提醒——改那里时靠人记住升版本。
_PROMPT_FINGERPRINT = ("v1", "a8179068830a")

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
    * **出网的每个文本字段都过同一套 ``clean()``，不留例外**——``title`` /
      ``detail`` / ``place`` / ``amount`` / **``group``** 一视同仁。两层理由：
      ① item 是模型从已脱敏文本里抽的，但它会「补出原文没有的实体」，
      所以出网前再抹一遍号码；② 群名来自人工维护的 ``config/groups.toml``，
      出号码的概率极低，但**例外需要人记住，而「记住」正是最容易失效的
      东西**（``group`` 原先只过 ``sanitize_for_llm``，就是这种例外）。
      而 ``Redactor.IDENTITY_NUM`` 的 ``群`` 分支天生就认识
      ``XX交流群421632774`` 这种写法。群名只作**合并信号**用、不直接展示，
      抹了也无害。
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
                "group": clean(names.get(item.group_id)) or "",
            }
        )
    return payload


def build_user_prompt(payload: list[dict], *, day: str) -> str:
    """用户提示词。载荷已经是脱敏过的，这里只负责拼装与注入日期。

    注入「今天是哪天」是必须的——M1 实测：不告诉模型今天，它会把
    「9月7号」猜成过去的年份。
    """
    body = json.dumps({"items": payload}, ensure_ascii=False, indent=1)
    return f"今天的日期是 {day}。\n\n以下是 {day} 这一天提炼出的条目：\n{body}"


# 归一化时剥掉的字符：空白与常见中英文标点。
# 目的是容忍「（640）」vs「(640)」这类**格式**差异，不是容忍改写。
#
# ⚠️ 取值比 refine.py 的 `_PUNCT` **多一组引号**（`“”` 与 `"`），这是刻意的：
# 本模块的匹配是拿「**出网后的**引号」去对「**库内原文的**引号」。
# `build_items_payload` 出网前用 `sanitize_for_llm` 把 `“”` 换成 `「」`，
# 而这里的 blob 是 `items` 表里的原文（仍是 `“”`）；模型照规则 3 逐字回抄
# 它**看到的** `「」`。只剥 `「」` 不剥 `“”` 的话两侧对不齐——引号夹在
# 中间时（如 title「“风之海310”卖笔记」）整行匹配不上、被丢弃，退化成
# 机械补行，而 CLI 退出码仍是 0（静默）。反过来（库里是 `「」`、模型回抄成
# `“”`）同样靠这一条兜住。refine 不需要这组：它的引号两侧都是库内原文，
# 没有「出网时换过一次字符」这层。
_PUNCT = re.compile(r'[\s，。！？、：；「」『』【】（）()\[\]…~～\-—“”"]+')


def _norm(text: str) -> str:
    """归一化。**只动标点与空白，不动汉字与数字。**

    ⚠️ 为什么必须归一化而不是直接 `in`：实测模型会在数字两侧插空格
    （原文「风之海310」它写成「风之海 310」）。直接子串匹配会漏掉这种
    纯格式差异，而归一化后两侧都无空格、仍逐字对应。
    """
    return _PUNCT.sub("", text)


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


def verified_deadlines(
    items: list[store.WindowItem], sources: dict[int, str]
) -> set[int]:
    """哪些 item 的截止日在源文里有字面依据。

    没有来源行的 item（``sources`` 里查不到）一律按**无依据**处理。
    """
    return {
        it.item_id
        for it in items
        if deadline_supported(it.deadline_ts, sources.get(it.item_id, ""))
    }


@dataclass(frozen=True)
class DigestLine:
    """模型返回的一行，已匹配回具体的 items。"""

    label: str
    text: str
    item_ids: tuple[int, ...]


@dataclass(frozen=True)
class Row:
    """日报里最终要渲染的一行。渲染只认它，不认模型返回的原始结构。"""

    label: str
    text: str
    kind: str
    group_id: int
    deadline_ts: int | None
    low_confidence: bool
    mechanical: bool = False
    # 截止日在**源文里**有没有字面依据（见 ``verified_deadlines``）。
    # 只有 True 的行才进「⏰ 别忘」、才被打「截止 MM-DD」戳。
    # 默认 False 是刻意的：失败方向要选安全的那边（宁可漏催，不可乱催）。
    deadline_trusted: bool = False


def match_lines(
    raw_lines: object, items: list[store.WindowItem]
) -> tuple[list[DigestLine], list[str]]:
    """把模型返回的行匹配回 items，返回 ``(命中行, 未命中的 quotes)``。

    **匹配不上就丢掉那一行，由 build_rows 用机械补行兜住**——宁可读起来
    生硬，也不能把条目静默丢了。未命中的 quotes 会返回给调用方计数上报。

    一个 quote 可能命中**多条** item（实测全库有重复标题，如「校园卡办理」
    系列 5 条）——全都要算覆盖，否则那些条目会被误判成「模型漏了」而
    补出重复的机械行。
    """
    if not isinstance(raw_lines, list):
        return [], []

    normed = [
        (it, _norm(it.title), _norm(f"{it.title} {it.detail or ''}")) for it in items
    ]
    lines: list[DigestLine] = []
    unmatched: list[str] = []

    for raw in raw_lines:
        if not isinstance(raw, dict):
            continue
        quotes = raw.get("quotes")
        if not isinstance(quotes, list):
            continue
        hits: list[store.WindowItem] = []
        for quote in quotes:
            raw_quote = str(quote).strip()
            needle = _norm(raw_quote)
            if not needle:
                continue
            # ⚠️ 先按「整个 title 逐字相等」找。**这一步不能省**：title 本身
            # 可能只有两三个字（「讲座」「体检表」），下面那条子串规则有长度
            # 下限，短标题只能靠这条路命中。
            #
            # 这是规划期实测抓到的缺陷：初版把 refine._match_source 的
            # 「摘录短于 4 字就丢」原样照搬了过来，结果 8 条断言全红
            # ——短标题一条都匹配不上，日报会退化成全机械补行。**那条例外的
            # 适用前提不同**：refine 的摘录是 10-30 字的原文片段，这里的摘录
            # 是整个 title。
            found = [it for it, title, _ in normed if title == needle]
            if not found and len(needle) >= 4:
                # 再按子串找。**下限 4 个字**：摘录太短容易误命中别的条目。
                # ⚠️ 多认领**不只**是「归到某一行、不会丢」这么轻。
                # 规划期审查实测：锚点取的是 `picked[0]`，所以子串多认领一个
                # event_ts 更早的无关条目，会把整行的**分区与署名群**换掉
                # ——实测能把 activity/群200 的事渲染成「· 群100」并归进通知公告。
                # 条目确实没丢，但署错了群、归错了分区。
                # （「锚点优先取整 title 精确命中」的改进已记为延迟项。）
                # 下限取 4 是保守取值，不是硬约束。
                found = [it for it, _, blob in normed if needle in blob]
            if not found:
                unmatched.append(raw_quote)
            for it in found:
                if it not in hits:
                    hits.append(it)
        if not hits:
            continue
        hits.sort(key=lambda it: (it.event_ts, it.item_id))
        label = str(raw.get("label") or "").strip() or hits[0].title
        text = str(raw.get("text") or "").strip()
        lines.append(
            DigestLine(
                label=label,
                text=text,
                item_ids=tuple(it.item_id for it in hits),
            )
        )
    return lines, unmatched


def build_rows(
    lines: list[DigestLine],
    items: list[store.WindowItem],
    *,
    low_confidence: float = LOW_CONFIDENCE,
    trusted: set[int] | None = None,
) -> list[Row]:
    """命中行 + 机械补行 → 最终的渲染行清单。

    **没被任何一行引用的 item 会被机械补一行**（label 用 title、text 用 detail）。
    日报的价值在「不漏事」，所以宁可读起来生硬，也不能因为模型漏写就丢条目
    ——那正是 spec §2.3 要避免的「日报有、列表没有」的反面：列表有、日报没有。

    ``trusted`` 是**截止日在源文里有字面依据**的 item_id 集合（见
    ``verified_deadlines``）。合并行只要有一条的截止日没依据，整行就不算
    可信——行里的日期是 ``min()`` 出来的一个数，说不清它是哪条的依据。

    ⚠️ 默认必须是 ``None`` → 空集 → **全部截止日都不进「别忘」**。
    默认成全信任的话，任何忘记传参的调用方都会静默退回危险行为：
    把模型编出来的日期用机器口吻打出来催人办事。**失败方向选安全的那边。**
    """
    trusted = set() if trusted is None else trusted
    by_id = {it.item_id: it for it in items}
    used: set[int] = set()
    rows: list[Row] = []

    for line in lines:
        picked = [by_id[iid] for iid in line.item_ids if iid in by_id]
        if not picked:
            continue
        used.update(it.item_id for it in picked)
        deadlines = [it.deadline_ts for it in picked if it.deadline_ts]
        rows.append(
            Row(
                label=line.label,
                text=line.text,
                kind=picked[0].kind,
                group_id=picked[0].group_id,
                deadline_ts=min(deadlines) if deadlines else None,
                low_confidence=all(it.confidence < low_confidence for it in picked),
                deadline_trusted=bool(deadlines)
                and all(it.item_id in trusted for it in picked if it.deadline_ts),
            )
        )

    for item in items:
        if item.item_id in used:
            continue
        rows.append(
            Row(
                label=item.title,
                text=item.detail or "",
                kind=item.kind,
                group_id=item.group_id,
                deadline_ts=item.deadline_ts,
                low_confidence=item.confidence < low_confidence,
                mechanical=True,
                deadline_trusted=item.item_id in trusted,
            )
        )
    return rows


def stat_line(*, groups: int, messages: int, items: int) -> str:
    """日报开头那句话。数字全部由程序算，不问模型——它编过。"""
    base = f"当天 {groups} 个群 {messages:,} 条消息"
    return f"{base}，提炼出 {items} 条。" if items else f"{base}。"


def _render_row(row: Row, names: dict[int, str], *, with_deadline: bool) -> str:
    parts = [f"- **{row.label}**"]
    if row.text:
        parts.append(row.text)
    line = " ".join(parts)
    tail = names.get(row.group_id, "")
    if with_deadline and row.deadline_ts:
        stamp = dt.datetime.fromtimestamp(row.deadline_ts).strftime("%m-%d")
        tail = f"截止 {stamp} · {tail}" if tail else f"截止 {stamp}"
    # 群名查不到就什么都不缀——**不要退回群号**，那是本不该出现在成品里的数字
    return f"{line} · {tail}" if tail else line


def render_markdown(
    *,
    day: str,
    stat_line: str,
    rows: list[Row],
    cats: tuple,
    names: dict[int, str],
    window_from: int = 0,
) -> str:
    """确定性渲染。模型只提供 label 与 text，版式全在这里。

    分区顺序：**别忘 → 各类目 → 拿不准的**。

    * 「别忘」= 有 deadline 且 **deadline 不早于窗口起点** 的行。加下界是真实
      数据逼出来的：全库有 1 条 item 的截止日早于事件日（8/5 的条目挂 5/6），
      不过滤就会在八月日报里冒出「别忘 5 月 6 日」。
    * **截止日还必须在源文里有字面依据**（``deadline_trusted``，Task 6）。
      实测 4 条里 3 条是模型编的，而「别忘」正是用户拿去办事的地方。
      没有依据的行**照常出现在它的类目区块里**（不漏事），只是不再以权威口吻催办。
    * 进了「别忘」的行**不再出现在类目区块**——同一件事读两遍是负担。
    * 低置信度的行只进「拿不准的」，即使它有截止日：存疑的信息不该催人去办。
    """
    head = f"# 守夜人日报 · {day}\n\n{stat_line}\n"
    if not rows:
        return head + "\n没有值得一提的信息。\n"

    alert_idx = {
        i
        for i, r in enumerate(rows)
        if r.deadline_trusted
        and r.deadline_ts
        and r.deadline_ts >= window_from
        and not r.low_confidence
    }
    unsure_idx = {i for i, r in enumerate(rows) if r.low_confidence}

    icons = {c.slug: (c.icon, c.label) for c in cats}
    order = [c.slug for c in cats]

    buckets: dict[str, list[int]] = {}
    for i, row in enumerate(rows):
        if i in alert_idx or i in unsure_idx:
            continue
        buckets.setdefault(row.kind, []).append(i)
    # 类目表里没有的 kind 排到最后——**不静默丢**
    for kind in buckets:
        if kind not in icons:
            order.append(kind)

    out = [head]
    if alert_idx:
        out.append("## ⏰ 别忘\n")
        out += [_render_row(rows[i], names, with_deadline=True)
                for i in sorted(alert_idx)]
        out.append("")
    for slug in order:
        idx = buckets.get(slug)
        if not idx:
            continue
        icon, label = icons.get(slug, ("", slug))
        title = f"{icon} {label}".strip() if icon else label
        out.append(f"## {title}\n")
        out += [_render_row(rows[i], names, with_deadline=False) for i in idx]
        out.append("")
    if unsure_idx:
        out.append("## 🤔 拿不准的\n")
        out += [_render_row(rows[i], names, with_deadline=False)
                for i in sorted(unsure_idx)]
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def yesterday(today: dt.date | None = None) -> str:
    """默认日报日期 = 昨天。日报是「回看昨天」，不是「看今天」。"""
    base = today or dt.date.today()
    return (base - dt.timedelta(days=1)).isoformat()


def day_window(date_str: str) -> tuple[int, int]:
    """把 ``YYYY-MM-DD`` 变成 ``[当天 00:00, 次日 00:00)`` 的 unix 秒区间。

    ⚠️ 用 datetime + timedelta 而不是 ``since + 86400``：后者在有夏令时的
    时区会差一小时。国内用不着，但这是免费的正确答案。
    """
    try:
        start = dt.datetime.strptime(date_str, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"日期格式应为 YYYY-MM-DD，实际是 {date_str!r}"
        ) from exc
    return int(start.timestamp()), int((start + dt.timedelta(days=1)).timestamp())


# 日报落盘目录。相对仓库根，与 spec §4.6 的约定一致。
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "digests"


@dataclass
class DigestStats:
    """如实报告——模型漏写的、匹配失败的、程序补的，都要看得见。"""

    day: str = ""
    window_from: int = 0
    window_to: int = 0
    items: int = 0
    lines: int = 0          # 模型返回且匹配成功的行数
    mechanical: int = 0     # 程序补的行数——**不为 0 就说明模型漏写了**
    # 截止日核验（Task 6）：源文里有字面依据的 / 找不到依据被降级的。
    # 静默丢弃截止日是另一种失败，所以两个数都要如实上报、由 CLI 打出来。
    deadlines_kept: int = 0
    deadlines_dropped: int = 0
    unmatched_quotes: int = 0
    messages: int = 0
    groups: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    digest_id: int | None = None
    output_path: str = ""
    errors: list[str] = field(default_factory=list)


def digest(
    config: Config,
    *,
    api_key: str,
    db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
    since: int,
    until: int,
    day_label: str,
    model: str = DEFAULT_MODEL,
    enable_thinking: bool | None = False,
    output_dir: Path | None = None,
    write_file: bool = True,
    dry_run: bool = False,
    prompt_ver: str = PROMPT_VERSION,
    on_progress=print,
) -> DigestStats:
    """合成一天的日报并落库（可选落文件）。

    连接由调用方持有：CLI 传 db_path，测试传内存 conn（与 refine 同款约定）。
    """
    if until <= since:
        raise ValueError(f"结束时间必须晚于开始时间：{since} → {until}")

    stats = DigestStats(
        day=day_label, window_from=since, window_to=until,
    )
    names = {g.id: g.name for g in config.groups}
    cats = load_categories()
    out_dir = output_dir or DEFAULT_OUTPUT_DIR

    owns_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(str(db_path or config.output_db))
    try:
        store.ensure_schema(conn)
        items = store.window_items(conn, since=since, until=until)
        # 截止日核验：只有能在**该条自己的源消息**里逐字找到的日期才进「别忘」。
        # 数据是 M1 抽的（它会补出原文没有的实体），核验放在 M2 是因为
        # 「催办」这个动作发生在 M2——本设计裁决原意是可靠，实测却把幻觉
        # 洗成了机器权威。降级的条数照实上报（见 CLI），不静默丢。
        sources = store.item_sources_text(conn, [it.item_id for it in items])
        trusted = verified_deadlines(items, sources)
        stats.deadlines_kept = len(trusted)
        stats.deadlines_dropped = sum(
            1 for it in items if it.deadline_ts and it.item_id not in trusted
        )
        messages, groups = store.window_stats(conn, since=since, until=until)
        stats.items = len(items)
        stats.messages = messages
        stats.groups = groups

        summary = stat_line(groups=groups, messages=messages, items=len(items))

        # ⚠️ --dry-run 必须排在「空窗」分支**前面**。
        #
        # 规划期的端到端实测抓到过这个顺序错误：原本空窗分支在前且无条件
        # ``_persist``，于是 `vigil digest --date <空窗日> --dry-run` **照样写库
        # 落文件**。单元测试没抓到，是因为它用的样本有 item、走的是另一条分支
        # ——空窗 + dry-run 这个组合当时根本没被测过（「空守卫」那一类）。
        if dry_run:
            if items:
                on_progress(
                    f"[digest] --dry-run：窗口内 {len(items)} 条 item，"
                    f"将调用 1 次模型，不写库、不落文件"
                )
            else:
                on_progress(
                    f"[digest] --dry-run：{day_label} 窗口内没有条目，"
                    f"将写一篇「没有值得一提的信息」的日报，不调用模型、不写库"
                )
            return stats

        # 空窗日**不调模型**：既不该花钱，也不该给模型机会编出点什么。
        # 但照样出文件——spec §4.6 要求「明确输出没有值得一提的信息，不假装有事」。
        if not items:
            body = render_markdown(
                day=day_label, stat_line=summary, rows=[], cats=cats, names=names,
            )
            on_progress(f"[digest] {day_label}：窗口内没有条目")
            return _persist(stats, conn, body, model, prompt_ver, [], write_file,
                            out_dir, day_label)

        payload = build_items_payload(items, names, Redactor())
        try:
            result = chat_json(
                LLMConfig(
                    api_key=api_key, model=model,
                    enable_thinking=enable_thinking, max_tokens=MAX_TOKENS,
                ),
                system=build_system_prompt(),
                user=build_user_prompt(payload, day=day_label),
            )
        except LLMError as exc:
            # ⚠️ 不降级。拼一篇只有机械行的「日报」写进 docs/digests/ 的话，
            # 那篇文件与正常日报长得一模一样——正是不许出现的假绿。
            stats.errors.append(f"模型调用失败: {exc}")
            on_progress(f"[digest] {stats.errors[-1]}")
            return stats

        stats.input_tokens = result.input_tokens
        stats.output_tokens = result.output_tokens

        lines, unmatched = match_lines(result.payload.get("lines"), items)
        rows = build_rows(lines, items, trusted=trusted)
        stats.lines = len(lines)
        stats.unmatched_quotes = len(unmatched)
        stats.mechanical = sum(1 for r in rows if r.mechanical)

        body = render_markdown(
            day=day_label, stat_line=summary, rows=rows, cats=cats, names=names,
            window_from=since,
        )
        # 窗口内**每条** item 都挂上——行里有的是模型写的，有的是机械补的，
        # 但两种都对应真实条目，所以覆盖率必然是 100%。
        return _persist(
            stats, conn, body, model, prompt_ver,
            [it.item_id for it in items], write_file, out_dir, day_label,
        )
    finally:
        if owns_conn and conn is not None:
            conn.close()


def _persist(
    stats: DigestStats,
    conn: sqlite3.Connection,
    body: str,
    model: str,
    prompt_ver: str,
    item_ids: list[int],
    write_file: bool,
    out_dir: Path,
    day_label: str,
) -> DigestStats:
    """落库 + 落文件。两件都做，或（write_file=False）只落库。

    ⚠️ **落文件必须显式 ``newline="\\n"``。** `Path.write_text` 的
    ``newline=None`` 会把 ``\\n`` 翻译成 ``os.linesep``，于是 Windows 上
    落出来的 ``.md`` 是 CRLF、而库里 ``body_md`` 是 LF——**同一篇日报的两个
    副本在字节层就不相等**（审查实测：文件 204 字节 / 库 106 字节）。
    后果不是「多了几个 \\r」这么轻：任何按字节对账的下游（M3 的 Web 与文件
    比对、hash 校验、把 .md 提交进 git 后被 autocrlf 反复改写）都会看到
    无意义 diff，而且「库副本 == 文件副本」这条不变量**没法用最自然的写法
    断言**——只能打折扣按文本比，那种折扣正是将来出事的入口。
    """
    stats.digest_id = store.save_digest(
        conn,
        window_from=stats.window_from,
        window_to=stats.window_to,
        body_md=body,
        model=model,
        prompt_ver=prompt_ver,
        item_ids=item_ids,
    )
    if write_file:
        path = out_dir / f"{day_label}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
        stats.output_path = str(path)
    return stats
