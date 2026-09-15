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
from dataclasses import dataclass, field

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
    body = json.dumps({"items": payload}, ensure_ascii=False, indent=1)
    return f"今天的日期是 {day}。\n\n以下是 {day} 这一天提炼出的条目：\n{body}"


# 归一化时剥掉的字符：空白与常见中英文标点。与 refine.py 同款取值。
# 目的是容忍「（640）」vs「(640)」这类**格式**差异，不是容忍改写。
_PUNCT = re.compile(r"[\s，。！？、：；「」『』【】（）()\[\]…~～\-—]+")


def _norm(text: str) -> str:
    """归一化。**只动标点与空白，不动汉字与数字。**

    ⚠️ 为什么必须归一化而不是直接 `in`：实测模型会在数字两侧插空格
    （原文「风之海310」它写成「风之海 310」）。直接子串匹配会漏掉这种
    纯格式差异，而归一化后两侧都无空格、仍逐字对应。
    """
    return _PUNCT.sub("", text)


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
                # 注意是「命中更多条目」而不是「命中错的」——多认领只会让条目
                # 归到某一行，不会丢；所以这里的下限是保守取值，不是硬约束。
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
) -> list[Row]:
    """命中行 + 机械补行 → 最终的渲染行清单。

    **没被任何一行引用的 item 会被机械补一行**（label 用 title、text 用 detail）。
    日报的价值在「不漏事」，所以宁可读起来生硬，也不能因为模型漏写就丢条目
    ——那正是 spec §2.3 要避免的「日报有、列表没有」的反面：列表有、日报没有。
    """
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
    * 进了「别忘」的行**不再出现在类目区块**——同一件事读两遍是负担。
    * 低置信度的行只进「拿不准的」，即使它有截止日：存疑的信息不该催人去办。
    """
    head = f"# 守夜人日报 · {day}\n\n{stat_line}\n"
    if not rows:
        return head + "\n没有值得一提的信息。\n"

    alert_idx = {
        i for i, r in enumerate(rows)
        if r.deadline_ts and r.deadline_ts >= window_from and not r.low_confidence
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
