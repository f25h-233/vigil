"""重排：改了类目定义之后，让模型按**新定义**重判已有条目（D16）。

**它与 `repass` 的唯一区别**：`repass` 拿「有没有产出」决定删不删，
本模块拿「产出的是哪一类」决定改不改类目。所以建批、上下文复现、
失败不写判定、slug 白名单**全部 import 复用**——那四件事每一件都是踩过坑
才写对的，抄一份就会漂移。

⚠️ **只写 overlay 的 `set_kind` 事件，绝不碰 `items` 表**。
这一条同时守住两个不变量：D11（`data/vigil.db` 只读）与 D16（`item_id` 不变
⇒ `digest_items` 的引用不会断）。
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from . import overrides, store
from .categories import Category, load_categories
from .config import Config
from .llm import DEFAULT_BASE, DEFAULT_MODEL, LLMConfig, chat_json
from .redact import Redactor
from .refine import build_system_prompt, build_user_prompt
from .repass import _scan_payload, collect_source_messages, context_batches


@dataclass(frozen=True)
class ReorderChange:
    item_id: int
    old_kind: str
    new_kind: str


@dataclass(frozen=True)
class ReorderPlan:
    changes: tuple[ReorderChange, ...] = ()
    # ⚠️ **没判成**的 item：失败批次、预算提前停止、取消……一条也没写进 verdicts
    # 的那些。它们与「判了、但结论是不用改」是**两回事**，必须分开报
    # （`repass` 的 E5 就是这条：把没判成的当成判死，方向是数据丢失）。
    unjudged: tuple[int, ...] = ()


@dataclass
class ReorderStats:
    scanned_msgs: int = 0
    sent_batches: int = 0
    sent_messages: int = 0
    batches: int = 0
    failed_batches: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    budget_hit: bool = False
    stopped: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        """`plan_reorder` 的预算闸用它。⚠️ 与 `RefineStats` / `RepassStats`
        同名的属性**必须是同一种算法**——两处算不一样的话，
        「预算 30 万」在两个命令里的含义就不同了。"""
        return self.input_tokens + self.output_tokens


def _current_kinds(conn: sqlite3.Connection, item_ids: Sequence[int]) -> dict[int, str]:
    """取这些条目的**有效类目**（含 overlay 与别名，走 `_EFFECTIVE_KIND`）。

    ⚠️ 必须走 `store.get_item`（它用 `_ITEM_COLS`）而**不是**自己写一句
    `SELECT kind FROM items`：后者会读到**别名之前**的老 slug，于是
    「刚改过名的类目」会被判成"需要重排"，而重排的结果是把它改回旧 slug
    ——一个**自己打自己**的循环。
    """
    out: dict[int, str] = {}
    for iid in item_ids:
        it = store.get_item(conn, iid)
        if it is not None:
            out[iid] = it.kind
    return out


def plan_reorder(
    conn: sqlite3.Connection,
    *,
    config: Config,
    api_key: str,
    cats: tuple[Category, ...] | None = None,
    batch_size: int = 30,
    context: int = 2,
    budget_tokens: int | None = None,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE,
    enable_thinking: bool | None = False,
    on_progress=print,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[ReorderPlan, ReorderStats]:
    """出一份「哪些条目的类目该改」的清单。**不写任何东西。**

    ⚠️ `should_stop` 在**每一批之间**被检查——这是取消能生效的唯一机制
    （Python 无法从外部杀掉线程）。漏掉这个检查点就是"点了取消没反应"。
    """
    cats = cats or load_categories()
    known_kinds = frozenset(c.slug for c in cats)
    system = build_system_prompt(cats)
    redactor = Redactor()
    today = dt.date.today().isoformat()
    stats = ReorderStats()

    src_msgs = collect_source_messages(conn)
    stats.scanned_msgs = len(src_msgs)
    if not src_msgs:
        on_progress("[reorder] 没有可重排的源消息")
        return ReorderPlan(), stats

    batches, src_ids = context_batches(
        conn, config=config, batch_size=batch_size, context=context
    )
    stats.sent_batches = len(batches)
    stats.sent_messages = sum(len(b) for b in batches)
    on_progress(
        f"[reorder] 源消息 {stats.scanned_msgs} 条 → {stats.sent_batches} 批 / "
        f"送 {stats.sent_messages} 条消息"
    )
    if not batches:
        on_progress("[reorder] 没有任何含源消息的上下文批次，结束（一条都不会动）")
        return ReorderPlan(), stats

    llm_cfg = LLMConfig(
        api_key=api_key, model=model, base_url=base_url,
        enable_thinking=enable_thinking,
    )

    # ⚠️ `judged[msg_id] = 模型为这条源消息产出的条目`。**失败时绝不写它**
    # （`repass` 勘误 E5 的同一条判据）：一次 429 被当成「模型说它该是别的类目」，
    # 方向是**静默改错分类**。
    judged: dict[int, store.ExtractedItem] = {}

    for index, batch in enumerate(batches, start=1):
        if should_stop is not None and should_stop():
            stats.stopped = True
            on_progress(f"[reorder] 已取消（完成 {index - 1}/{len(batches)} 批）")
            break
        if budget_tokens is not None and stats.total_tokens >= budget_tokens:
            stats.budget_hit = True
            on_progress(f"[reorder] 已达预算上限，提前停止（{index - 1} 批）")
            break

        try:
            result = chat_json(
                llm_cfg, system=system,
                user=build_user_prompt(batch, redactor, today=today),
            )
        except Exception as exc:  # noqa: BLE001 — 见上：**不写判定**
            stats.failed_batches += 1
            stats.errors.append(f"第 {index} 批失败: {exc}")
            on_progress(f"[reorder]{stats.errors[-1]}")
            continue

        # ⚠️ token 累加**留在保护圈外**：token 是真花掉的，本地后处理炸了
        # 不代表模型没被调用——圈进去会让账目说谎（与 refine / repass 同一取舍）。
        stats.input_tokens += result.input_tokens
        stats.output_tokens += result.output_tokens

        try:
            outcome = _scan_payload(
                result.payload, batch, known_kinds=known_kinds, target_ids=src_ids
            )
        except Exception as exc:  # noqa: BLE001 — 单批本地炸不许掀掉整轮
            stats.failed_batches += 1
            stats.errors.append(f"第 {index} 批本地后处理失败: {exc}")
            on_progress(f"[reorder]{stats.errors[-1]}")
            continue

        stats.batches += 1
        for mid, n in outcome.counts.items():
            if n and mid not in judged:
                for it in outcome.produced:
                    if mid in it.src_msg_ids:
                        judged[mid] = it
                        break
        on_progress(
            f"[reorder] 批次 {index}/{len(batches)}：{len(batch)} 条 → "
            f"{outcome.landed} 条 item"
        )

    # ── 把判定折成变更清单 ────────────────────────────────────────────
    items_by_msg = store.existing_items_for_messages(conn, list(judged))
    # ⚠️ 一条源消息可能对应**多个** item（`save_items` 的批内去重来源取并集，
    # 见 `overrides.delete_item` 的 E7 论证）⇒ 用列表而不是单值。
    item_ids: dict[int, list[int]] = {}
    for mid, iids in items_by_msg.items():
        item_ids[mid] = list(iids) if isinstance(iids, (list, tuple, set)) else [iids]

    wanted: dict[int, str] = {}
    for mid, produced in judged.items():
        for iid in item_ids.get(mid, ()):
            wanted.setdefault(iid, produced.kind)

    # ⚠️ 已软删的条目**不参与**（本模块的 docstring 与 `test_reorder_skips_soft_deleted_items`
    # 记着理由）：一条 delete 之后的 set_kind 会让"撤销这批重排"把条目
    # 从可见**变回已删**——那是一个静默的状态翻转。
    alive = {
        iid for iid in wanted
        if store.get_item(conn, iid) is not None
    }

    current = _current_kinds(conn, sorted(alive))
    changes = tuple(
        ReorderChange(item_id=iid, old_kind=current[iid], new_kind=wanted[iid])
        for iid in sorted(alive)
        if iid in current and current[iid] != wanted[iid]
    )
    judged_items = set(alive)
    all_items = {iid for iids in item_ids.values() for iid in iids}
    unjudged = tuple(sorted(all_items - judged_items))

    on_progress(
        f"[reorder] 判定完成：{len(alive)} 条有结论 → **{len(changes)} 条需要改类目**，"
        f"{len(unjudged)} 条没判成（它们不会被动）"
    )
    return ReorderPlan(changes=changes, unjudged=unjudged), stats


def apply_reorder(
    ov: sqlite3.Connection, plan: ReorderPlan, *, actor: str
) -> int:
    """把计划写成 overlay 的 `set_kind` 事件。返回写了多少条。

    ⚠️ **全部事件共用同一个 `actor`**——这是「撤销这一整批」的键
    （`overrides.undo_batch`）。逐条 `set_kind` 而各带各的 actor 的话，
    撤销 N 次才能退回重排前，而中途任何一次别的操作都会把它切成两段。
    """
    for change in plan.changes:
        overrides.set_kind(
            ov, item_id=change.item_id, kind=change.new_kind, actor=actor
        )
    return len(plan.changes)
