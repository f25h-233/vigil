"""抽取引擎：messages → items。

流水线：
    取待处理 → 规则预筛 → 按群切批 → 展开上下文 → 脱敏 → 批量调 LLM
    → 落 items + item_sources → 记账 refine_runs

设计的两个关键取舍：
  * **丢掉的消息也要记账**。refine_runs 必须覆盖全部消息，
    否则「哪些看过、哪些没看过」分不清，增量就无从谈起。
  * **单批失败不中断整轮**。沿用 export.py 对 senders/media 的既有取舍：
    外部环境的问题降级并记录，不拖垮主流程。
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import prefilter, store
from .categories import Category, prompt_block
from .config import Config
from .deadline import deadline_supported
from .llm import DEFAULT_MODEL, LLMConfig, LLMError, chat_json
from .redact import Redactor
from .store import PendingMessage

PROMPT_VERSION = "v2"

# 输出 token 的上限估计，用于把「输出」也算进预算
_BATCH_TITLE_MAX = 40


@dataclass
class RefineStats:
    """如实报告——失败与跳过都要看得见。"""

    scanned: int = 0
    discarded_local: int = 0
    sent_messages: int = 0
    batches_planned: int = 0  # 计划要跑多少批
    batches: int = 0  # **实际**跑了几批——预算 break 之后会小于 planned
    items_saved: int = 0
    deadlines_dropped: int = 0   # 源文里找不到依据、被降级的截止日条数
    input_tokens: int = 0
    output_tokens: int = 0
    budget_hit: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def build_system_prompt(cats: tuple[Category, ...]) -> str:
    """系统提示词。类目表从配置渲染，改 categories.toml 即改提示词。

    ⚠️ 「以下一律直接不出现在结果里」那三条是用户反馈逼出来的（纯询问价值低、
    多为噪声）。**它一度只写进了计划文档而没进代码**——commit 481dfb9 的
    范围是 `feat(plan)`，改的是 docs/superpowers/plans/…md 里的代码块，
    `vigil/refine.py` 一行没动。后果在 2026-09-14 的模型对照实验里现形：
    模型照样把「怎么向一卡通里充钱啊」「我们不体检吗」抽成条目。

    改这里务必同步 `PROMPT_VERSION`，否则 refine_runs 里新老提示词的产出
    混在一起，谁也说不清哪条是哪个提示词抽的。
    """
    return f"""你是校园 QQ 群的信息提炼助手。从群聊消息里挑出对大学生真正有价值的信息。

类目（只能选这些）：
{prompt_block(cats)}

**以下一律直接不出现在结果里**——不要为它们输出任何占位元素：

* 闲聊、纯表情、无信息量的发言
* **纯询问 / 提问类消息**——「XX 在哪个校区」「能不能带电脑」「什么时候开学」
  这类**提问本身不含信息**，价值低且多为噪声。
  只有当消息**给出了答案或明确信息**时才产出
  （例：「30 号就得到学校」是信息，「30 号开学吗」不是）
* 同学间的感慨、吐槽、附和

输出必须是 JSON 对象，形如 {{"items": [...]}}，其中 items 是数组。
每个元素的结构：
{{"quote": "从原消息里逐字摘录的连续片段",
 "kind": "notice", "title": "一句话摘要（≤{_BATCH_TITLE_MAX}字）",
 "detail": "补充细节或null", "deadline": "YYYY-MM-DD 或 null",
 "place": "地点或null", "amount": "金额或null", "confidence": 0.9}}

⚠️ `quote` 必须是原消息里**原样连续出现**的片段（10-30 字）。**不要改写、
不要补全、不要跨消息拼接**——程序会拿它去逐字匹配来源消息。
摘录不准的条目会被直接丢弃，所以**宁可短而准**。

死线日期必须结合下面提供的「今天」推算正确年份。没有死线的填 null。"""


def build_user_prompt(
    messages: list[PendingMessage], redactor: Redactor, *, today: str
) -> str:
    """用户提示词。**脱敏在这一步完成**——所有离开本机的内容都经过这里。

    形如 ``- U3 昵称: 内容``：代号（姓名保留、号码已抹）让模型能看出
    「同一人说了两次」。**消息本身不带任何编号**——来源定位走 `quote`。

    ⚠️ 为什么不用编号（msg_id 和序号都试过了，都不行）——Task 8 冒烟实测结论：

    * **msg_id 不行**：19 位雪花号，同批 30 条只有末 3 位不同
      （`…673881` / `…673929` / `…673918`）。实测命中 **0/2**，返回的全是
      「在批内但不对应」的 ID——错归因被静默接受。
    * **序号也不行**：换 1-2 位序号后 A/B 测试命中 1/1，但**真实管线里仍然错**
      ——实测一个 4 条消息的批次，真来源在第 3 位，模型读对了内容却返回
      `idx=1`。7B 在「4 条里选 1 个序号」这种任务上也不可靠。

    最终方案是**不问模型编号**：让它逐字摘录，由 `_match_source` 本地定位。
    7B 上实测命中，且**自校验**——匹配不上就丢弃，不可能静默挂错来源。

    ⚠️ 匿名发送者（uid 为空串）**必须逐条区分**。实测全库 1,218 条（2.55%）
    匿名消息；若一律走 ``redactor.actor('')``，它们会全部拿到同一个代号
    （W1 波级审查实测：两个不同群的匿名者都是 ``U1``），模型便会把互不相识
    的人当成同一个人。**匿名者没有身份可言，所以给每条一个互不相同的标记。**
    """
    lines = []
    anonymous = 0
    for m in messages:
        body = redactor.text(m.content)
        if m.sender_uid:
            name = redactor.text(m.sender) or "未知"
            who = f"{redactor.actor(m.sender_uid)} {name}"
        else:
            # 批内计数器，不用 msg_id——不给模型任何长数字，断掉它"抄数字"的路径
            anonymous += 1
            who = f"匿名{anonymous}"
        lines.append(f"- {who}: {body}")
    return f"今天的日期是 {today}。\n\n消息如下：\n" + "\n".join(lines)


def _parse_deadline(value: object) -> int | None:
    """把 'YYYY-MM-DD' 转成 unix 秒。解析不了就当没有——不猜。

    ⚠️ 只捕 ``ValueError`` 是不够的：``"1970-01-01"`` 是**合法日期**，却在
    ``timestamp()`` 上抛 ``OSError``（实测本机：1970-01-03 之前的日期、
    以及 4000 年以后的日期都落不进去）。而它恰恰是模型表达「没有截止日」
    最经典的哨兵——只挡格式不挡范围，等于把最常见的那个值留成了地雷。
    捕获范围与 ``api._day_start`` 对齐：**格式错的、范围错的都当"没有"处理**。

    ⚠️ 返回值保持"没把握就不猜"：抛异常和返回 None 对调用方是同一件事，
    但没有第二个人知道要在这里接异常——M3 的接线点（`_to_item`）就在
    每批 try/except 的**外面**，一个日期串足以掀掉整轮 refine。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return int(dt.datetime.strptime(value.strip(), "%Y-%m-%d").timestamp())
    except (ValueError, OSError, OverflowError):
        return None


# 归一化时剥掉的字符：空白与常见中英文标点。
# 目的是容忍「（640）」vs「(640)」这类**格式**差异，而不是容忍改写。
_PUNCT = re.compile(r"[\s，。！？、：；「」『』【】（）()\[\]…~～\-—]+")


def _normalize(text: str) -> str:
    return _PUNCT.sub("", text)


def _match_source(quote: str, batch: list[PendingMessage]) -> PendingMessage | None:
    """按【逐字摘录】在批次里定位来源消息。

    ⚠️ 这是 Task 8 冒烟实测逼出来的设计——**不问模型要编号**：

    * **msg_id 不行**：19 位雪花号，同批 30 条只有末 3 位不同（`…673881` /
      `…673929`）。实测命中 0/2，返回的全是「在批内但不对应」的 ID。
    * **批内序号也不行**：实测一个 4 条消息的批次，真来源在第 3 位，
      模型读对了内容却返回 `idx=1`。7B 在「4 条里选 1 个序号」上也不可靠。

    改成让模型逐字摘录、由本地匹配后，**7B 上一次命中**。

    **匹配不上就返回 None，调用方丢弃该条目。** 宁可少一条，也不能把来源挂错
    ——M1 出口标准要求能跳回原文**且内容对得上**，挂错的来源比没有来源更糟。
    """
    needle = _normalize(quote)
    if len(needle) < 4:  # 太短的摘录容易误命中，宁可丢
        return None
    for m in batch:
        if needle in _normalize(m.content):
            return m
    return None


def _to_item(
    raw: dict, batch: list[PendingMessage], *, known_kinds: frozenset[str]
) -> store.ExtractedItem | None:
    """把模型返回的一条 JSON 转成 ExtractedItem。

    任何不合法（摘录匹配不上、类目不在表里、缺 title）都返回 None——
    模型会编，宁可不入库也不入脏数据。
    """
    quote = str(raw.get("quote") or "").strip()
    source = _match_source(quote, batch)
    if source is None:
        return None

    kind = str(raw.get("kind", "")).strip()
    if kind not in known_kinds:
        return None

    title = str(raw.get("title") or "").strip()
    if not title:
        return None

    links_raw = raw.get("links") or []
    links = tuple(str(x) for x in links_raw) if isinstance(links_raw, list) else ()

    try:
        confidence = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    def _text(key: str) -> str | None:
        value = raw.get(key)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    return store.ExtractedItem(
        kind=kind,
        title=title,
        detail=_text("detail"),
        event_ts=source.ts,
        deadline_ts=_parse_deadline(raw.get("deadline")),
        group_id=source.group_id,
        actor_uid=source.sender_uid or None,
        place=_text("place"),
        links=links,
        amount=_text("amount"),
        confidence=max(0.0, min(1.0, confidence)),
        src_msg_ids=(source.msg_id,),
    )


def _drop_unsupported_deadlines(
    produced: list[store.ExtractedItem], batch: list[store.PendingMessage]
) -> tuple[list[store.ExtractedItem], int]:
    """写入前核验：源文里找不到字面依据的截止日一律置 None。

    ⚠️ 核验放在**写入边界**而不是渲染层：数据一旦入库就到处流，每个读取方
    各挡一次，迟早有人忘——M2 就只在日报挡过，M3 的 Web 差一点把那 13 条
    幻觉日期原样复活（「今天下午16点之前」被填成 9-14、「明早7:20」被填成 9-15）。

    ⚠️ 只降级 deadline_ts 这一个字段：条目的标题、正文、来源一概不动。
    用户仍然看得到这条信息，只是不再被告知一个编出来的日期。
    """
    texts = {m.msg_id: (m.content or "") for m in batch}
    out: list[store.ExtractedItem] = []
    dropped = 0
    for it in produced:
        if it.deadline_ts and not deadline_supported(
            it.deadline_ts, "\n".join(texts.get(mid, "") for mid in it.src_msg_ids)
        ):
            dropped += 1
            it = replace(it, deadline_ts=None)
        out.append(it)
    return out, dropped


def refine(
    config: Config,
    *,
    api_key: str,
    db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
    since: int | None = None,
    until: int | None = None,
    limit: int | None = None,
    redo: bool = False,
    batch_size: int = 30,
    context: int = 2,
    budget_tokens: int | None = None,
    model: str = DEFAULT_MODEL,
    enable_thinking: bool | None = False,
    prompt_ver: str = PROMPT_VERSION,
    dry_run: bool = False,
    on_progress=print,
) -> RefineStats:
    """跑一轮抽取。幂等——已处理的消息会被跳过，除非 redo=True。

    连接由调用方持有：CLI 传 db_path，测试传内存 conn。
    """
    from .categories import load_categories

    cats = load_categories()
    known_kinds = frozenset(c.slug for c in cats)
    stats = RefineStats()

    # redo + limit 叠加是有害组合（W1 Task 4 审查实测）：
    # redo 把已抽过的消息重新抽一遍，limit 又只取最早的 N 条——
    # 结果是重复产出 items、白烧 token。快速失败挡住它，别让它静默发生。
    if redo and limit is not None:
        raise ValueError(
            "redo 与 limit 不能同时用：redo 会重抽已处理的消息，"
            "limit 又只取最早的 N 条，两者叠加会重复产出 items 并白烧 token。"
            "要限量重抽，请用 since/until 圈定时间窗。"
        )

    owns_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(str(db_path))
    try:
        store.ensure_schema(conn)

        messages = store.pending_messages(
            conn, since=since, until=until, limit=limit, redo=redo
        )
        stats.scanned = len(messages)
        if not messages:
            on_progress("[refine] 没有待处理的消息")
            return stats

        candidates, screen_stats = prefilter.screen(
            messages, tier_of=config.tier_of
        )
        stats.discarded_local = screen_stats.dropped
        on_progress(
            f"[refine] 扫描 {screen_stats.total:,} 条 → 规则保留 {screen_stats.kept:,} 条"
            f"（本地丢弃 {screen_stats.dropped:,}）"
        )

        # 没进候选的一律记账为 discarded，其中既含硬丢弃也含「没命中保留规则」。
        # 记账必须做全：refine_runs 覆盖不到的消息会让增量同步永远重扫它们。
        # 集合先建好——47k 条消息下逐条重建集合是 O(n²)。
        candidate_ids = {c.msg_id for c in candidates}
        not_candidate_ids = [m.msg_id for m in messages if m.msg_id not in candidate_ids]
        if not dry_run and not_candidate_ids:
            store.record_run(
                conn, not_candidate_ids, status=store.STATUS_DISCARDED,
                prompt_ver=prompt_ver,
            )

        if not candidates:
            on_progress("[refine] 预筛后没有候选，结束")
            return stats

        in_scope = prefilter.expand_context(messages, candidates, context=context)
        batches = prefilter.make_batches(in_scope, max_batch=batch_size)
        stats.sent_messages = len(in_scope)
        stats.batches_planned = len(batches)

        if dry_run:
            on_progress(
                f"[refine] --dry-run：将发送 {len(in_scope):,} 条、分 {len(batches)} 批，"
                f"不调用模型、不写库"
            )
            return stats

        system = build_system_prompt(cats)
        today = dt.date.today().isoformat()
        llm_cfg = LLMConfig(
            api_key=api_key, model=model, enable_thinking=enable_thinking
        )

        for index, batch in enumerate(batches, start=1):
            if budget_tokens is not None and stats.total_tokens >= budget_tokens:
                stats.budget_hit = True
                on_progress(
                    f"[refine] 已达预算上限 {budget_tokens:,} token，提前停止"
                    f"（已完成 {index - 1}/{len(batches)} 批）"
                )
                break

            stats.batches += 1  # 实际跑了——放在预算闸之后，break 的那批不算跑过
            redactor = Redactor()
            user = build_user_prompt(batch, redactor, today=today)
            batch_ids = [m.msg_id for m in batch]

            try:
                result = chat_json(llm_cfg, system=system, user=user)
            except LLMError as exc:
                msg = f"第 {index} 批失败: {exc}"
                stats.errors.append(msg)
                on_progress(f"[refine] {msg}")
                store.record_run(
                    conn, batch_ids, status=store.STATUS_ERROR,
                    prompt_ver=prompt_ver, err=str(exc)[:200],
                )
                continue

            # ⚠️ token 累加**留在保护圈外**：token 是真花掉的，本地后处理炸了
            # 不代表模型没被调用——圈进去会让账目说谎（成功路径行为不变）。
            stats.input_tokens += result.input_tokens
            stats.output_tokens += result.output_tokens

            # ⚠️ 保护圈**从这一行起，到本批结束**：解析、核验、落库、记账、
            # 报进度。设计里那句「单批失败不中断整轮」以前只对**网络**失败
            # 成立——这里的每一步都在上一版 try/except 的圈外，于是一条 item
            # 带个 ``deadline: "1970-01-01"`` 就能让整轮 refine 抛异常终止：
            # 前面跑完的批次白跑，剩下的批次永远不跑。
            # 这是 M1 留下的保护圈缺口，M3 只是又往缺口里塞了一个新调用点
            # （核验接线），所以修法是**把整段本地后处理挪进圈里**，
            # 而不是逐个去堵已知的异常类型。
            try:
                raw_items = result.payload.get("items")
                if not isinstance(raw_items, list):
                    raw_items = []

                produced: list[store.ExtractedItem] = []
                hit_ids: set[int] = set()
                for raw in raw_items:
                    if not isinstance(raw, dict):
                        continue
                    item = _to_item(raw, batch, known_kinds=known_kinds)
                    if item is None:
                        continue
                    produced.append(item)
                    hit_ids.update(item.src_msg_ids)

                if produced:
                    produced, dropped = _drop_unsupported_deadlines(produced, batch)
                    stats.deadlines_dropped += dropped
                    stats.items_saved += store.save_items(
                        conn, produced, model=model, prompt_ver=prompt_ver
                    )

                store.record_run(
                    conn, batch_ids, status=store.STATUS_DISCARDED,
                    prompt_ver=prompt_ver,
                )
                if hit_ids:
                    store.record_run(
                        conn, sorted(hit_ids), status=store.STATUS_OK,
                        prompt_ver=prompt_ver, item_count=len(produced),
                    )

                on_progress(
                    f"[refine] 批次 {index}/{len(batches)}：{len(batch)} 条 → "
                    f"{len(produced)} 条 item"
                )
            except Exception as exc:
                # 捕 `Exception` 而不是某个具体类型：设计意图是「单批失败不中断
                # 整轮」，捕窄一类，下一个未知异常类型会**再次**掀掉整轮——
                # 那正是这次在修的模式（同一类缺陷在本项目已是第三次出现）。
                # 捕宽的前提是**可见**：异常照样进 stats.errors、照样
                # on_progress 出来、照样记进 refine_runs；静默吞异常不可接受。
                msg = f"第 {index} 批本地后处理失败: {exc}"
                stats.errors.append(msg)
                on_progress(f"[refine] {msg}")
                store.record_run(
                    conn, batch_ids, status=store.STATUS_ERROR,
                    prompt_ver=prompt_ver, err=str(exc)[:200],
                )
                continue

        return stats
    finally:
        if owns_conn and conn is not None:
            conn.close()
