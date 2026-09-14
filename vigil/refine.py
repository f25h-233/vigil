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
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import prefilter, store
from .categories import Category, prompt_block
from .config import Config
from .llm import DEFAULT_MODEL, LLMConfig, LLMError, chat_json
from .redact import Redactor
from .store import PendingMessage

PROMPT_VERSION = "v1"

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
    input_tokens: int = 0
    output_tokens: int = 0
    budget_hit: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def build_system_prompt(cats: tuple[Category, ...]) -> str:
    """系统提示词。类目表从配置渲染，改 categories.toml 即改提示词。"""
    return f"""你是校园 QQ 群的信息提炼助手。从群聊消息里挑出对大学生真正有价值的信息。

类目（只能选这些）：
{prompt_block(cats)}

闲聊、纯表情、无信息量的发言**直接不出现在结果里**——不要为它们输出任何占位元素。

输出必须是 JSON 对象，形如 {{"items": [...]}}，其中 items 是数组。
每个元素的结构：
{{"idx": 29, "kind": "notice", "title": "一句话摘要（≤{_BATCH_TITLE_MAX}字）",
 "detail": "补充细节或null", "deadline": "YYYY-MM-DD 或 null",
 "place": "地点或null", "amount": "金额或null", "confidence": 0.9}}

⚠️ `idx` 是下面消息列表里的**序号**（从 1 开始），**不是消息 ID**。

死线日期必须结合下面提供的「今天」推算正确年份。没有死线的填 null。"""


def build_user_prompt(
    messages: list[PendingMessage], redactor: Redactor, *, today: str
) -> str:
    """用户提示词。**脱敏在这一步完成**——所有离开本机的内容都经过这里。

    形如 ``29. U3 昵称: 内容``：**序号让模型能指回来源**，代号（姓名保留、
    号码已抹）让模型能看出「同一人说了两次」。

    ⚠️ 用**批内序号**而不是 msg_id——这是 Task 8 冒烟实测逼出来的关键改动：

    msg_id 是 19 位雪花号，同一批 30 条的 ID 只有末 3 位不同
    （`…673881` / `…673929` / `…673918`）。实测模型在这种「抄 30 个几乎相同的
    长数字」上的错误是**系统性**的：对照实验里 msg_id 版**命中 0/2**，且返回的
    都是「在批内但不对应」的 ID——错归因被静默接受，可回溯性直接失效。

    换成 1-2 位序号后**命中 1/1**，输入 token 还从 1424 降到 819（**-43%**）。

    ⚠️ 匿名发送者（uid 为空串）**必须逐条区分**。实测全库 1,218 条（2.55%）
    匿名消息；若一律走 ``redactor.actor('')``，它们会全部拿到同一个代号
    （W1 波级审查实测：两个不同群的匿名者都是 ``U1``），模型便会把互不相识
    的人当成同一个人。**匿名者没有身份可言，所以给每条一个互不相同的标记。**
    """
    lines = []
    for index, m in enumerate(messages, start=1):
        body = redactor.text(m.content)
        if m.sender_uid:
            name = redactor.text(m.sender) or "未知"
            who = f"{redactor.actor(m.sender_uid)} {name}"
        else:
            who = f"匿名{index}"  # 逐条唯一——避免把不同人当成同一人
        lines.append(f"{index}. {who}: {body}")
    return f"今天的日期是 {today}。\n\n消息如下：\n" + "\n".join(lines)


def _parse_deadline(value: object) -> int | None:
    """把 'YYYY-MM-DD' 转成 unix 秒。解析不了就当没有——不猜。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return int(dt.datetime.strptime(value.strip(), "%Y-%m-%d").timestamp())
    except ValueError:
        return None


def _to_item(
    raw: dict, batch: list[PendingMessage], *, known_kinds: frozenset[str]
) -> store.ExtractedItem | None:
    """把模型返回的一条 JSON 转成 ExtractedItem。

    任何不合法（idx 越界、类目不在表里、缺 title）都返回 None——
    模型会编，宁可不入库也不入脏数据。

    ⚠️ `idx` 是**批内序号**（1 基），与 `build_user_prompt` 的编号一一对应。
    越界即丢弃：宁可少一条，也不能把条目挂到错误的消息上——那会让
    「可回溯」变成假的（M1 出口标准要求能跳回原文**且内容对得上**）。
    """
    try:
        idx = int(raw["idx"])
    except (KeyError, TypeError, ValueError):
        return None

    if not 1 <= idx <= len(batch):
        return None
    source = batch[idx - 1]

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
        llm_cfg = LLMConfig(api_key=api_key, model=model)

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

            stats.input_tokens += result.input_tokens
            stats.output_tokens += result.output_tokens

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

        return stats
    finally:
        if owns_conn and conn is not None:
            conn.close()
