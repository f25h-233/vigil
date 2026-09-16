"""存量重判：让**已有的** items 跟上新的判据（prompt v3 + 两道要素闸门）。

⚠️ **语义是「只删不换」**（spec D10 / R9 实测）：

* 源消息在新判据下**不再产出**条目 → 删掉它的旧 item
* 源消息在新判据下**仍然产出** → **保留旧 item**（不重建、不翻新 `item_id`）
* **被 `digest_items` 引用的**条目一律不删，进 `skipped_referenced` 并报告

不这样做的代价已经量过：`digest_items` 66 行指向 66 条，
整批替换会让它们全部悬空，而**日报正文里那些话还印着**。

⚠️ 例外是**字段降级**：`place`/`deadline_ts` 用 UPDATE 同步到新闸门的结果。
UPDATE 不翻新 id，所以与"保留旧 item"不矛盾——而少了这一步，
M5 出口判据 3（不再有 `deadline_ts < event_ts`）根本达不到。

⚠️ 三条与计划正文不同的地方（勘误 E4/E5/E6，每条都有实测理由）：

* **E4 批内去重**：产出集合在**算条数之前**过 `store.dedupe_batch`。
  不去重的话，模型对同一条消息重抽两次（真库 item 290/296 的真实行为）
  会让 `n_new` 算成 2 ⇒ 两条重复都留下、报「0 deleted」，而 `refine` 路径
  （`save_items` 里有去重）只写 1 行——同一条消息在两条路径上得到相反结论。
* **E5 失败 ≠ 产出 0 条**：LLM 或本地后处理失败的批次**不写 verdict**，
  它的源消息整批进 `plan.unjudged`。计划原文的
  `verdicts.setdefault(m.msg_id, 0)` 把「没判成」翻译成「产出 0 条」，
  而这在本命令的语义里等于**删光那批消息的旧条目**——一次 429、
  一次超时、一次解析失败就能造成不可逆的数据丢失。
* **E6 不碰用户软删的行**：软删（D15）说「库里行仍在」，本命令做的是
  `DELETE FROM items`。把用户软删的条目物理删掉，等于把"软删"升级成
  "物理删"——`item_edits` 里那条 delete 事件还在、`undo` 照样成功，
  但**没有任何行可以恢复**。
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field

from . import prefilter, store
from .categories import load_categories
from .config import Config
from .deadline import deadline_sane, place_supported
from .llm import DEFAULT_MODEL, LLMConfig, chat_json
from .redact import Redactor
from .refine import _to_item, build_system_prompt, build_user_prompt


@dataclass
class RepassPlan:
    """一次重判的**可核对清单**。做事之前先把它打出来给人看。

    ⚠️ 五只桶（`to_delete` / `to_keep` / `skipped_referenced` /
    `skipped_soft_deleted` / `unjudged`）**两两不交**：一条 item 只会出现在
    其中一只里。这不是形式主义——`item_sources` 允许一个 item 挂 ≥2 条源消息
    （`store.dedupe_batch` 的来源取并集），所以同一条 item 完全可能从两条
    消息的视角各被看到一次。
    """

    to_delete: list[int] = field(default_factory=list)
    to_keep: list[int] = field(default_factory=list)
    skipped_referenced: list[int] = field(default_factory=list)
    # 用户软删过的（D15：行仍在）——本命令一律不碰（勘误 E6）
    skipped_soft_deleted: list[int] = field(default_factory=list)
    # 这一轮**没判成**的源消息产出的条目（LLM 失败 / 预算打到）——勘误 E5
    unjudged: list[int] = field(default_factory=list)
    # (item_id, place, deadline_ts) —— 保留但需要降级的条目
    downgrades: list[tuple[int, str | None, int | None]] = field(default_factory=list)
    verdicts: dict[int, int] = field(default_factory=dict)   # msg_id -> 新产出条数


@dataclass
class RepassStats:
    scanned_msgs: int = 0
    deleted: int = 0
    kept: int = 0
    skipped_referenced: int = 0
    skipped_soft_deleted: int = 0
    unjudged_items: int = 0
    downgraded: int = 0
    batches: int = 0          # **成功**跑完的批次
    failed_batches: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    budget_hit: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def build_plan(
    conn: sqlite3.Connection,
    *,
    verdicts: dict[int, int],
    item_ids_by_msg: dict[int, list[int]] | None = None,
    judged: dict[int, store.ExtractedItem] | None = None,
    unjudged_msg_ids: Iterable[int] = (),
) -> RepassPlan:
    """把「每条源消息在新判据下产出几条」折叠成一张执行计划。

    ⚠️ 本函数是**纯的**（只读 conn，不写）——这样才能在真库上先跑一遍看清单，
    确认无误再 `apply_plan`。存量重判是不可逆操作，事前可见比事后回滚值钱。

    `verdicts`: `msg_id -> 新判据下产出的条目数`（0 = **确实**判为不该入库）。
    `item_ids_by_msg`: 该消息**曾经**产出过的 item_id（缺省时现查）。
    `judged`: `msg_id -> 新判据下的条目`，用于算出字段降级值。
    `unjudged_msg_ids`: 这一轮**没取得判定**的源消息（批次失败 / 预算提前停止）。
        它们的条目一条都不许删——「没判」与「判成 0 条」是两种状态（勘误 E5）。

    分桶优先级（前者压倒后者）：

    1. **软删过** ⇒ `skipped_soft_deleted`（用户已经把它从界面上拿掉了）
    2. **没判成** ⇒ `unjudged`（没有判据就没有结论）
    3. **被日报引用** ⇒ `skipped_referenced`（删了 `digest_items` 会悬空）
    4. **在保留名额内** ⇒ `to_keep`
    5. **多余的** ⇒ `to_delete`

    ⚠️ 第 4/5 步**分两趟走**，不是一条消息一条消息地定：一条 item 挂两条源
    消息、一个判 0 一个判 1 时，**以留为准**。删是不可逆的，而留着顶多多一条
    旧条目——两个方向的不对称是刻意的。

    ⚠️ 软删过的条目**不占保留名额**：否则同一个消息的两条 item 里用户软删了
    一条、留了一条，新判据仍产出 1 条时名额会花在看不见的那条上，
    **用户还能看见的那条反而被删掉**。
    """
    plan = RepassPlan(verdicts=dict(verdicts))
    unjudged = sorted({int(m) for m in unjudged_msg_ids})
    if item_ids_by_msg is None:
        item_ids_by_msg = store.existing_items_for_messages(
            conn, [*verdicts.keys(), *unjudged]
        )

    all_existing = sorted({iid for ids in item_ids_by_msg.values() for iid in ids})
    referenced = store.items_used_in_digests(conn, all_existing)
    soft_deleted = store.soft_deleted_item_ids(conn, all_existing)

    classified: set[int] = set()

    def _put(bucket: list[int], iid: int) -> None:
        """归桶。**同一条 item 只归一只桶**——先到先得，调用序就是优先级。"""
        if iid in classified:
            return
        classified.add(iid)
        bucket.append(iid)

    for iid in all_existing:
        if iid in soft_deleted:
            _put(plan.skipped_soft_deleted, iid)

    for msg_id in unjudged:
        for iid in item_ids_by_msg.get(msg_id, []):
            _put(plan.unjudged, iid)

    keep_candidates: list[int] = []
    delete_candidates: list[int] = []
    for msg_id, n_new in verdicts.items():
        olds = [iid for iid in item_ids_by_msg.get(msg_id, []) if iid not in soft_deleted]
        keep_n = max(0, min(len(olds), int(n_new)))
        keep_candidates.extend(olds[:keep_n])
        delete_candidates.extend(olds[keep_n:])

    for iid in keep_candidates:
        if iid in referenced:
            _put(plan.skipped_referenced, iid)
        else:
            _put(plan.to_keep, iid)
    for iid in delete_candidates:
        if iid in referenced:
            _put(plan.skipped_referenced, iid)
        else:
            _put(plan.to_delete, iid)

    if judged:
        plan.downgrades = _plan_downgrades(conn, plan.to_keep, judged, item_ids_by_msg)
    return plan


def _plan_downgrades(
    conn: sqlite3.Connection,
    keep_ids: list[int],
    judged: dict[int, store.ExtractedItem],
    item_ids_by_msg: dict[int, list[int]],
) -> list[tuple[int, str | None, int | None]]:
    """算出保留条目里需要降级的 `(item_id, place, deadline_ts)`。

    ⚠️ 现有条目的 `place`/`deadline_ts` 是**旧判据**下写的——新闸门没管过它们。
    这里按新判据重算一遍，只降级、不升级（新判据下"该有值"而旧条目没有的，不动它：
    那属于"抽取质量"问题，不是本次要修的）。

    ⚠️ 只对**留下了的**条目算（`plan.to_keep`）：软删的、被引用的、以及这一轮
    没判成的条目一个都不许碰——降级它们同样是"替用户改了他已经决定过的行"。
    """
    if not keep_ids:
        return []
    by_item = {iid: mid for mid, ids in item_ids_by_msg.items() for iid in ids}
    rows = conn.execute(
        "SELECT item_id, place, deadline_ts, event_ts FROM items WHERE item_id IN"
        f" ({','.join('?' * len(keep_ids))})",
        keep_ids,
    ).fetchall()

    out: list[tuple[int, str | None, int | None]] = []
    for item_id, place, deadline_ts, event_ts in rows:
        src = judged.get(by_item.get(int(item_id)))
        if src is None:
            continue
        sources_text = ""
        if src.src_msg_ids:
            row = conn.execute(
                "SELECT content FROM messages WHERE msg_id = ?", (src.src_msg_ids[0],)
            ).fetchone()
            sources_text = (row[0] or "") if row else ""
        new_place = place if place_supported(place, sources_text) else None
        new_dl = deadline_ts
        if deadline_ts is not None and not deadline_sane(deadline_ts, event_ts):
            new_dl = None
        if (new_place, new_dl) != (place, deadline_ts):
            out.append((int(item_id), new_place, new_dl))
    return out


def apply_plan(conn: sqlite3.Connection, plan: RepassPlan) -> RepassStats:
    """执行计划。**整批一个事务**——要么全成要么全废，不留半个状态。

    ⚠️ 只读 `to_delete` 与 `downgrades` 两栏：`to_keep` / 三只 skip 桶
    在这里**没有任何写路径**，清单里写什么就只做什么。
    """
    stats = RepassStats()
    with store.transaction(conn):
        stats.deleted = store.delete_items(conn, plan.to_delete)
        stats.downgraded = store.downgrade_item_fields(conn, plan.downgrades)
    return stats


def _fill_plan_counts(stats: RepassStats, plan: RepassPlan) -> None:
    stats.kept = len(plan.to_keep)
    stats.skipped_referenced = len(plan.skipped_referenced)
    stats.skipped_soft_deleted = len(plan.skipped_soft_deleted)
    stats.unjudged_items = len(plan.unjudged)
    stats.downgraded = len(plan.downgrades)


def collect_source_messages(conn: sqlite3.Connection) -> list[store.PendingMessage]:
    """所有**已产出条目**的源消息（去重），按 (ts, msg_id) 升序。

    ⚠️ 这是 D10 划定的重判范围——不碰 4.7 万条全量，只碰产出过条目的那批。
    实测真库规模：328 条 item ⇒ 约 328 条源消息 ⇒ 约 11 批。

    ⚠️ 范围由 `item_sources` 定义，**不是**由 `refine_runs.prompt_ver` 定义：
    后者记的是"这条消息跑过哪一版提示词"，而本命令要重判的是"已经有产物的
    那批消息"——两者在真库上恰好接近，但语义不同（一条 v2 消息的条目可能
    已经被删光了，那时它不该再占一轮 token）。
    """
    rows = conn.execute(
        "SELECT DISTINCT m.msg_id, m.group_id, m.ts,"
        " COALESCE(m.sender_uid, '') AS uid,"
        " COALESCE(NULLIF(sn.group_nick, ''), NULLIF(sn.qq_nick, ''), '') AS sender,"
        " m.content"
        " FROM item_sources src"
        " JOIN messages m ON m.msg_id = src.msg_id"
        " LEFT JOIN sender_names sn"
        "        ON sn.group_id = m.group_id AND sn.uid = m.sender_uid"
        " ORDER BY m.ts ASC, m.msg_id ASC"
    ).fetchall()
    return [store.PendingMessage(*row) for row in rows]


def repass(
    config: Config,
    *,
    api_key: str,
    conn: sqlite3.Connection | None = None,
    db_path=None,
    batch_size: int = 30,
    budget_tokens: int | None = None,
    model: str = DEFAULT_MODEL,
    enable_thinking: bool | None = False,
    apply: bool = False,
    on_progress=print,
) -> tuple[RepassPlan, RepassStats]:
    """跑一轮存量重判。`apply=False` 时**只出清单不写库**。

    ⚠️ 返回 `(plan, stats)`：即使 apply，调用方也拿得到清单去写报告。
    """
    cats = load_categories()
    known_kinds = frozenset(c.slug for c in cats)
    system = build_system_prompt(cats)
    redactor = Redactor()
    today = dt.date.today().isoformat()

    owns = conn is None
    if conn is None:
        # ⚠️ `uri=True` 不能省（裁决 R4）：`build_plan` 要读 overlay
        # （`store.soft_deleted_item_ids`），而 `ATTACH 'file:...?mode=ro'`
        # 只在连接带 `SQLITE_OPEN_URI` 时才被解析。
        path = db_path if db_path is not None else config.output_db
        conn = sqlite3.connect(str(path), uri=True)
    stats = RepassStats()
    try:
        msgs = collect_source_messages(conn)
        stats.scanned_msgs = len(msgs)
        if not msgs:
            on_progress("[repass] 没有需要重判的源消息")
            return RepassPlan(), stats

        batches = prefilter.make_batches(msgs, max_batch=batch_size)
        llm_cfg = LLMConfig(
            api_key=api_key, model=model, enable_thinking=enable_thinking
        )

        verdicts: dict[int, int] = {}
        judged: dict[int, store.ExtractedItem] = {}
        for index, batch in enumerate(batches, start=1):
            if budget_tokens is not None and stats.total_tokens >= budget_tokens:
                stats.budget_hit = True
                on_progress(
                    f"[repass] 已达预算上限 {budget_tokens:,} token，提前停止"
                    f"（已完成 {index - 1}/{len(batches)} 批）"
                )
                break

            try:
                result = chat_json(
                    llm_cfg,
                    system=system,
                    user=build_user_prompt(batch, redactor, today=today),
                )
            except Exception as exc:  # noqa: BLE001 — 见下：**不写 verdict**
                # ⚠️⚠️ 失败**不写 verdicts**（勘误 E5）。计划原文这里是
                # `verdicts.setdefault(m.msg_id, 0)`——而 0 在本命令的语义里是
                # 「这条消息不再产出任何条目」⇒ 它的旧 item 全删。一次 429、
                # 一次超时、一次解析失败就能删掉一整批真实条目，方向是数据丢失。
                # 没判成的消息由下面 `unjudged_ids` 统一收进 `plan.unjudged`。
                #
                # 捕 `Exception` 而不是 `LLMError`：`chat_json` 之外还有
                # `build_user_prompt`/脱敏这一段，它们炸了同样没取得判定——
                # 捕窄一类，下一个未知异常类型会**再次**掀掉整轮。
                stats.failed_batches += 1
                stats.errors.append(f"第 {index} 批失败: {exc}")
                on_progress(f"[repass]{stats.errors[-1]}")
                continue

            # ⚠️ token 累加**留在保护圈外**：token 是真花掉的，本地后处理炸了
            # 不代表模型没被调用——圈进去会让账目说谎（与 refine 同一取舍）。
            stats.input_tokens += result.input_tokens
            stats.output_tokens += result.output_tokens

            try:
                produced = _produce(result.payload, batch, known_kinds=known_kinds)
            except Exception as exc:  # noqa: BLE001 — 单批本地炸不许掀掉整轮
                stats.failed_batches += 1
                stats.errors.append(f"第 {index} 批本地后处理失败: {exc}")
                on_progress(f"[repass]{stats.errors[-1]}")
                continue
            stats.batches += 1  # 只有真的解析出结果的那批才算跑过

            # ⚠️ 先给整批填 0，再把**产出**累加上去：`counts[mid] == 0` 的语义
            # 是「模型看了这一批、明确没为它产出任何条目」——那才是该删的信号。
            # 它与「没判成」（上面那两个 except）必须是两种状态（勘误 E5）。
            counts: dict[int, int] = {m.msg_id: 0 for m in batch}
            for it in produced:
                for mid in it.src_msg_ids:
                    counts[mid] = counts.get(mid, 0) + 1
                    judged.setdefault(mid, it)
            verdicts.update(counts)

            on_progress(
                f"[repass] 批次 {index}/{len(batches)}：{len(batch)} 条 → "
                f"{len(produced)} 条 item"
            )

        # ⚠️ 「没判成」= 一条消息也**不在** verdicts 里。这是**唯一**的判据
        # （不另立计数器）：失败、预算提前停止、将来的任何新 `continue`
        # 都会自动落进这个集合，不需要有人记得去登记。
        unjudged_ids = [m.msg_id for m in msgs if m.msg_id not in verdicts]
        plan = build_plan(
            conn, verdicts=verdicts, judged=judged, unjudged_msg_ids=unjudged_ids
        )
        _fill_plan_counts(stats, plan)
        if apply:
            applied = apply_plan(conn, plan)
            stats.deleted = applied.deleted            # DB 的实际行数说了算
            stats.downgraded = applied.downgraded
        return plan, stats
    finally:
        if owns:
            conn.close()


def _produce(payload: object, batch, *, known_kinds) -> list[store.ExtractedItem]:
    """复用 refine 的 `_to_item`——**不重写一遍**。

    ⚠️ 重写会让两条路径的判据漂移：存量重判说"该删"，而新抽取说"该留"，
    同一个消息在两次运行里得到相反结论，而**没有任何测试会发现**。

    ⚠️ 出口处过 `store.dedupe_batch`——**必须在算产出条数之前**（勘误 E4）。
    它是 `save_items` 用的同一个函数对象（`store.dedupe_batch` 是
    `_dedupe_batch` 的公开别名），不是"相似的一段代码"。
    """
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        return []
    out: list[store.ExtractedItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        try:
            it = _to_item(raw, batch, known_kinds=known_kinds)
        except Exception:  # noqa: BLE001 —— 单条脏数据不该掀掉整轮
            continue
        if it is not None:
            out.append(it)
    return store.dedupe_batch(out)
