"""VIGIL 命令行入口。

    vigil groups    列出 QQ 本地库里所有群（含是否已纳入监听）
    vigil export    把纳入的群导出成明文库，供 qqcli 建索引
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys

from . import export as export_mod
from . import lock, logs
from . import qqdb, reader
from . import refine as refine_mod
from . import store
from .config import ConfigError, load_config, load_key, load_llm_key


def _load_config_only():
    """只读配置（不需要密钥）——查询层用。"""
    try:
        return load_config()
    except ConfigError as exc:
        sys.exit(f"[配置错误] {exc}")


def _require_export_db(config):
    if not config.output_db.is_file():
        sys.exit(
            f"[错误] 导出库不存在: {config.output_db}\n  请先运行 vigil export"
        )
    return config.output_db


def _load_or_die():
    """加载配置与密钥。出错就快速失败——配置问题不该被静默绕过。"""
    try:
        config = load_config()
    except ConfigError as exc:
        sys.exit(f"[配置错误] {exc}")
    key = load_key()
    if not key:
        sys.exit(
            "[配置错误] 没有数据库密钥。\n"
            "  请在仓库根目录建 .env 并写入：VIGIL_DB_KEY=<16位密钥>\n"
            "  密钥获取方式见 docs/SETUP-ROUTE-C.md"
        )
    return config, key


def _fmt_ts(ts: int) -> str:
    if not ts or ts <= 0:
        return "-"
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def cmd_groups(args) -> int:
    config, key = _load_or_die()

    counts = qqdb.list_group_message_counts(
        qqdb.open_encrypted(
            qqdb.strip_fake_header(
                config.qq_db_dir / "nt_msg.db",
                config.output_db.parent / "cache" / "nt_msg_clear.db",
            ),
            key,
        )
    )

    names: dict[str, str] = {}
    try:
        gi_clear = qqdb.strip_fake_header(
            config.qq_db_dir / "group_info.db",
            config.output_db.parent / "cache" / "group_info_clear.db",
        )
        names = qqdb.group_names(qqdb.open_group_info(gi_clear, key))
    except Exception as exc:  # noqa: BLE001 — 群名缺失不该让 listing 失败
        print(f"[警告] 群名读取失败（不影响群号）：{str(exc)[:70]}\n", file=sys.stderr)

    watched = {g.id for g in config.enabled_groups}
    known = {g.id for g in config.groups}

    print(f"{'':<3}{'消息数':>9}  {'最新':<11} {'群号':<11} 群名")
    print("-" * 76)
    for gid, n, tmax in counts:
        if args.only_watched and gid not in watched:
            continue
        mark = "★" if gid in watched else ("·" if gid in known else " ")
        print(f"{mark:<3}{n:>9,}  {_fmt_ts(tmax):<11} {gid:<11} {names.get(str(gid), '?')}")
    print("-" * 76)
    print("★ = 已纳入监听   · = 在配置里但已停用   空格 = 未纳入")
    print(f"共 {len(counts)} 个群有消息记录，已纳入 {len(watched)} 个")

    # 提示：已纳入但库里没消息的群（可能是刚加、还没同步）
    counted = {gid for gid, _, _ in counts}
    for g in config.enabled_groups:
        if g.id not in counted:
            print(f"  [注意] 已纳入的 {g.id} {g.name} 在库里没有任何消息")
    return 0


def cmd_export(args) -> int:
    # ⚠️ **人工跑也要上锁**（M4 独立审查 F4）：`docs/SETUP-自动化.md` §七 给退出码 2
    # 写的理由就是「用户手动又跑一次」这个场景，而此前只有 `cmd_daily` 上锁 ⇒
    # 人工命令与任务计划撞车时**完全不受保护**——spec §4.8 的「幂等可重入」
    # 只堵了一半（两个 refine 并发会各读同一批待处理消息 ⇒ 抽两遍、烧两份 token）。
    # ⚠️ 不会与 `cmd_daily` 重入：`daily.run()` 调的是库函数（`export_mod.export`
    # 等）而不是 `cmd_*`，而锁**刻意不做重入**（见 `lock.py` 的 docstring）。
    try:
        with lock.SingleInstance():
            config, key = _load_or_die()
            logs.emit(f"导出 {len(config.enabled_groups)} 个群 → {config.output_db}")

            stats = export_mod.export(config, key, on_progress=logs.emit)
            logs.emit("-" * 60)
            logs.emit(f"完成：{len(stats.per_group)} 个群，共 {stats.total_rows:,} 条消息")

            if stats.skipped_by_group:
                logs.emit(f"\n[注意] 有 {stats.total_skipped:,} 条消息因 QQ 数据库坏页读不到：")
                for gid, gname, n in stats.skipped_by_group:
                    logs.emit(f"  {gid} {gname}：{n:,} 条")
                logs.emit("  这是 QQ 数据库自身的物理坏页，非导出错误；同群其余消息不受影响。")

            if stats.failed_groups:
                logs.emit(f"\n[失败] {len(stats.failed_groups)} 个群整群读不到：")
                for gid, err in stats.failed_groups:
                    logs.emit(f"  {gid}: {err}")

            if stats.media_total:
                pct = stats.media_local / stats.media_total * 100
                logs.emit(
                    f"\n图片引用：{stats.media_total:,} 张，本地可取 "
                    f"{stats.media_local:,} 张（{pct:.0f}%）"
                )
                logs.emit(
                    "  取不到的并非「对不上号」，而是 QQ 没有缓存该图（见 vigil/media.py）。"
                )
            if stats.failed_groups:
                # ⚠️ 非零退出码是 M4 自动化的报警信号——别吞掉。旧版这里无条件
                # return 0，于是「N 个群整群读不到」在任务计划看来是**成功**。
                # 坏页（skipped_by_group）**不算失败**：那是 QQ 库的物理损坏，
                # 已知、非致命、且同群其余消息不受影响，上面已经照实报了。
                return 1
            return 0
    except lock.AlreadyRunning as exc:
        # 与 `cmd_daily` 同一语义：2 不是 1——「上一次还没跑完」等着就行，
        # 「这次跑失败了」才要人来看（计划 §三 3.4）。
        logs.emit(f"[跳过] {exc}")
        return 2


def cmd_read(args) -> int:
    """读消息。不设任何过滤 = 全量保底检索。"""
    config = _load_config_only()
    db = _require_export_db(config)
    try:
        messages = reader.read_messages(
            db,
            group=args.group,
            sender=args.sender,
            keyword=args.keyword,
            since=args.since,
            until=args.until,
            limit=args.limit,
        )
    except ValueError as exc:
        sys.exit(f"[参数错误] {exc}")

    if not messages:
        print("（没有匹配的消息）")
        return 0

    names = {g.id: g.name for g in config.groups}
    for m in messages:
        gname = names.get(m.group_id, "")
        print(f"{m.time_str}  [{gname or m.group_id}]  {m.sender}: {m.content}")
    print(f"--- 共 {len(messages)} 条 ---")
    return 0


def cmd_who(args) -> int:
    """谁在说：按发言条数排行，用于「锁定哪个人」。"""
    config = _load_config_only()
    db = _require_export_db(config)
    try:
        stats = reader.sender_stats(
            db, group=args.group, since=args.since, limit=args.limit
        )
    except ValueError as exc:
        sys.exit(f"[参数错误] {exc}")

    if not stats:
        print("（没有匹配的消息）")
        return 0

    names = {g.id: g.name for g in config.groups}
    scope = names.get(args.group, str(args.group)) if args.group else "全部已纳群"
    print(f"发言排行 —— {scope}")
    print(f"{'条数':>7}  {'QQ号':<12} 姓名")
    print("-" * 52)
    for name, count, uin in stats:
        print(f"{count:>7,}  {uin or '-':<12} {name}")
    return 0


def cmd_media(args) -> int:
    """列出本地已有缓存的图片——这些是能直接打开的。"""
    config = _load_config_only()
    db = _require_export_db(config)
    try:
        items = reader.local_images(
            db, group=args.group, since=args.since, limit=args.limit
        )
    except ValueError as exc:
        sys.exit(f"[参数错误] {exc}")

    if not items:
        print("（没有本地可取的图片）")
        return 0

    names = {g.id: g.name for g in config.groups}
    for it in items:
        gname = names.get(it.group_id, "")
        print(f"{it.time_str}  [{gname or it.group_id}]  {it.sender}")
        print(f"    {it.path}")
    print(f"--- 共 {len(items)} 张 ---")
    return 0


def cmd_refine(args) -> int:
    """抽取：把消息变成结构化条目。"""
    # ⚠️ **人工跑也要上锁**（M4 独立审查 F4）：`docs/SETUP-自动化.md` §七 给退出码 2
    # 写的理由就是「用户手动又跑一次」这个场景，而此前只有 `cmd_daily` 上锁 ⇒
    # 人工命令与任务计划撞车时**完全不受保护**——spec §4.8 的「幂等可重入」
    # 只堵了一半（两个 refine 并发会各读同一批待处理消息 ⇒ 抽两遍、烧两份 token）。
    # ⚠️ 不会与 `cmd_daily` 重入：`daily.run()` 调的是库函数（`export_mod.export`
    # 等）而不是 `cmd_*`，而锁**刻意不做重入**（见 `lock.py` 的 docstring）。
    try:
        with lock.SingleInstance():
            from . import refine as refine_mod
            from .config import load_llm_key

            config = _load_config_only()
            db = _require_export_db(config)

            api_key = load_llm_key()
            if not api_key and not args.dry_run:
                sys.exit(
                    "[配置错误] 没有 LLM 密钥。\n"
                    "  请在仓库根目录的 .env 里写入：SILICONFLOW_API_KEY=sk-...\n"
                    "  （--dry-run 不需要密钥）"
                )

            try:
                since_ts = reader._to_epoch(args.since)
                until_ts = reader._to_epoch(args.until)
            except ValueError as exc:
                sys.exit(f"[参数错误] {exc}")

            # refine() 会对 --redo/--limit 的非法组合抛 ValueError。不接的话用户看到的是
            # 裸 traceback，而不是一行可读的参数错误——与 other 子命令的既有风格不一致。
            try:
                stats = refine_mod.refine(
                    config,
                    api_key=api_key,
                    db_path=db,
                    since=since_ts,
                    until=until_ts,
                    limit=args.limit,
                    redo=args.redo,
                    batch_size=args.batch,
                    context=args.context,
                    budget_tokens=args.budget,
                    # --model 不给时是 None，而 None 会绕过 refine() 的默认值，所以这里兜底
                    model=args.model or refine_mod.DEFAULT_MODEL,
                    enable_thinking=args.think,
                    prompt_ver=args.prompt_ver,
                    dry_run=args.dry_run,
                    on_progress=logs.emit,
                )
            except ValueError as exc:
                sys.exit(f"[参数错误] {exc}")

            logs.emit("-" * 60)
            # ⚠️ 三个数必须**自洽**：本地筛掉 + 送模型 == 扫描。
            # ⚠️ **不许用「其中」**连接「规则硬丢弃」与「本地筛掉」——两者**不是**
            # 包含关系：`prefilter.expand_context` 取 ±2 邻居时不看那条消息有没有
            # 被硬规则判死，所以被判死的消息照样可能作为上下文出网
            # （`digest.py:713-720` 的 docstring 记着这条，并且正是因此把"硬丢弃"
            # 计数从日报文案里删掉了）。旧版写「（其中硬丢弃 N 条）」——实测在真库上
            # 是假话。这里改用「；」并列，两个数各自独立。
            #
            # dry-run 时要报**计划**批数：实际批数必然是 0，显示「0 批」会让人
            # 以为什么都没准备好（Task 7 fix 实测指出）。
            shown_batches = stats.batches_planned if args.dry_run else stats.batches
            logs.emit(
                f"完成：扫描 {stats.scanned:,} 条 → 本地筛掉 "
                f"{stats.scanned - stats.sent_messages:,} 条"
                f" → 送模型 {stats.sent_messages:,} 条（{shown_batches:,} 批）"
                f"（候选 {stats.candidates:,} 条；规则硬丢弃 {stats.discarded_local:,} 条）"
            )
            logs.emit(f"产出条目：{stats.items_saved:,} 条")
            if not args.dry_run:
                logs.emit(f"token 用量：输入 {stats.input_tokens:,} / 输出 {stats.output_tokens:,}")
            if stats.budget_hit:
                # 报「实际跑了多少」而不是计划数——预算 break 后两者会差很多
                logs.emit(
                    f"[注意] 达到预算上限提前停止：实际跑了 {stats.batches} 批，"
                    f"计划 {stats.batches_planned} 批。剩余消息留待下次（或调大 --budget）"
                )
            if stats.deadlines_dropped:
                # 降级必须看得见——静默丢掉一个日期和静默编造一个日期同样有害
                logs.emit(
                    f"[注意] {stats.deadlines_dropped} 条截止日在源消息里找不到字面依据，"
                    f"未落库（条目本身仍照常出现）"
                )
            if stats.errors:
                logs.emit(f"\n[失败] {len(stats.errors)} 批出错：")
                for e in stats.errors[:5]:
                    logs.emit(f"  {e}")
            if args.dry_run:
                logs.emit("（--dry-run：未调用模型、未写库）")
                return 0
            # ⚠️ 非零退出码是 M4 自动化的报警信号——别吞掉。旧版无条件 return 0，
            # 于是「3 批出错」在任务计划看来是成功。
            return 1 if stats.errors else 0
    except lock.AlreadyRunning as exc:
        # 与 `cmd_daily` 同一语义：2 不是 1——「上一次还没跑完」等着就行，
        # 「这次跑失败了」才要人来看（计划 §三 3.4）。
        logs.emit(f"[跳过] {exc}")
        return 2


def cmd_digest(args) -> int:
    """日报：把 items 写成一天一页 Markdown。"""
    # ⚠️ **人工跑也要上锁**（M4 独立审查 F4）：`docs/SETUP-自动化.md` §七 给退出码 2
    # 写的理由就是「用户手动又跑一次」这个场景，而此前只有 `cmd_daily` 上锁 ⇒
    # 人工命令与任务计划撞车时**完全不受保护**——spec §4.8 的「幂等可重入」
    # 只堵了一半（两个 refine 并发会各读同一批待处理消息 ⇒ 抽两遍、烧两份 token）。
    # ⚠️ 不会与 `cmd_daily` 重入：`daily.run()` 调的是库函数（`export_mod.export`
    # 等）而不是 `cmd_*`，而锁**刻意不做重入**（见 `lock.py` 的 docstring）。
    try:
        with lock.SingleInstance():
            from . import digest as digest_mod
            from .config import load_llm_key

            config = _load_config_only()
            db = _require_export_db(config)

            api_key = load_llm_key()
            if not api_key and not args.dry_run:
                sys.exit(
                    "[配置错误] 没有 LLM 密钥。\n"
                    "  请在仓库根目录的 .env 里写入：SILICONFLOW_API_KEY=sk-...\n"
                    "  （--dry-run 不需要密钥）"
                )

            day = args.date or digest_mod.yesterday()
            try:
                since, until = digest_mod.day_window(day)
            except ValueError as exc:
                sys.exit(f"[参数错误] {exc}")

            stats = digest_mod.digest(
                config,
                api_key=api_key,
                db_path=db,
                since=since,
                until=until,
                day_label=day,
                # --model 不给时是 None，而 None 会绕过 digest() 的默认值，所以这里兜底
                model=args.model or digest_mod.DEFAULT_MODEL,
                enable_thinking=args.think,
                write_file=not args.no_write,
                dry_run=args.dry_run,
                on_progress=logs.emit,
            )

            logs.emit("-" * 60)
            # ⚠️ 失败**不再提前 return**：提前返回会让日志里只有一句「[失败]」，
            # 而没有本次的计数——事后根本判断不出这轮跑到哪、抓到几条。所以先报错，
            # 汇总照打，最后由这一处统一给退出码。
            for err in stats.errors:
                logs.emit(f"[失败] {err}")

            logs.emit(
                f"完成：{stats.day} 窗口内 {stats.groups} 个群 {stats.messages:,} 条消息"
                f" → {stats.items} 条 item → 日报 {stats.lines} 行"
            )
            if stats.mechanical:
                # 不为 0 就说明模型漏写了条目，是提示词该改的信号——必须显眼
                logs.emit(
                    f"[注意] 其中 {stats.mechanical} 行是程序补的（模型没写到），"
                    f"读起来会生硬——这通常意味着提示词该调了"
                )
            if stats.deadlines_dropped:
                # 静默丢弃截止日是另一种失败——降级必须看得见
                logs.emit(
                    f"[注意] {stats.deadlines_dropped} 条截止日在源消息里找不到字面依据，"
                    f"未进「别忘」（条目本身仍照常出现）——已保留 {stats.deadlines_kept} 条"
                )
            if stats.unmatched_quotes:
                logs.emit(f"[注意] 有 {stats.unmatched_quotes} 处摘录没匹配上条目，已丢弃")
            if args.dry_run:
                logs.emit("（--dry-run：未调用模型、未写库、未落文件）")
                return 0

            logs.emit(f"token 用量：输入 {stats.input_tokens:,} / 输出 {stats.output_tokens:,}")
            if stats.output_path:
                logs.emit(f"日报文件：{stats.output_path}")
            else:
                logs.emit("（--no-write：只入库，未落文件）")
            # ⚠️ 非零退出码是 M4 自动化的报警信号——别吞掉
            return 1 if stats.errors else 0
    except lock.AlreadyRunning as exc:
        # 与 `cmd_daily` 同一语义：2 不是 1——「上一次还没跑完」等着就行，
        # 「这次跑失败了」才要人来看（计划 §三 3.4）。
        logs.emit(f"[跳过] {exc}")
        return 2


def cmd_daily(args) -> int:
    """每日管线。任务计划的入口——见 docs/SETUP-自动化.md。

    ⚠️ **加锁是在这里、不是在 daily.run() 里**：锁是**进程级**关注点，
    而 run() 只做编排。分开也让 run() 能在测试里不碰文件系统。

    ⚠️ 退出码契约（计划 §三 3.4，冻结）：0 成功 / 1 失败或不完整 /
    **2 = 已有实例在跑**。2 不并进 1：无人值守下「上一次还没跑完」（等就行）
    与「这次跑失败了」（要人来看）需要两种不同处置。

    ⚠️ 这里的 `except Exception` 是**顶层兜底**，必须留痕并返回非零。
    不许写成 `except Exception: logs.emit(...); return 0`——那正好是本
    milestone 要消灭的形状（`exit 0 但日志有洞`，见计划 §8.5）。
    外面也不许套"吞掉并继续"的 try/except：真有异常冒上来（如跨零点换文件
    失败，T1 把它钉成必抛），它**一路往外走**才对。

    ⚠️ 但别以为这一层能兜住"日志写失败"：普通写失败（磁盘满）被
    `logging.StreamHandler.emit` 自带的 `try/except` 吞掉、只调 `handleError`
    往 stderr 打一份，而任务计划**丢弃 stderr** ⇒ 它**到不了这里**。
    那条路径归 `logs.py` 的 `handleError`（T1 的文件）。
    """
    from . import daily as daily_mod

    logs.setup()
    # 开跑就清 LAST-ERROR：于是「文件存在」⟺「本次跑失败过」（见 logs 的 docstring）
    logs.clear_last_error()
    logs.prune_old_logs()

    try:
        config = load_config()
    except ConfigError as exc:
        logs.emit(f"[配置错误] {exc}")
        logs.write_last_error(f"配置错误：{exc}")
        return 1
    key = load_key()
    if not key:
        msg = "没有数据库密钥（.env 里的 VIGIL_DB_KEY）"
        logs.emit(f"[配置错误] {msg}")
        logs.write_last_error(msg)
        return 1
    llm_key = load_llm_key()
    if not llm_key:
        msg = "没有 LLM 密钥（.env 里的 SILICONFLOW_API_KEY）"
        logs.emit(f"[配置错误] {msg}")
        logs.write_last_error(msg)
        return 1

    try:
        with lock.SingleInstance():
            report = daily_mod.run(
                config=config, key=key, llm_key=llm_key, day=args.date,
            )
    except lock.AlreadyRunning as exc:
        # ⚠️ 退出码 2 不是 1：无人值守下「上一次还没跑完」只要等着就行，
        # 「这次跑失败了」才要人来看。详见计划 §三 3.4。
        logs.emit(f"[跳过] {exc}")
        return 2


    except Exception as exc:  # noqa: BLE001 — 顶层兜底，必须留痕
        logs.emit(f"[失败] daily 未预期地抛出：{exc!r}")
        logs.write_last_error(f"daily 未预期异常：{exc!r}")
        return 1

    if not report.ok:
        logs.write_last_error(report.last_error)
        return 1
    return 0


def cmd_deadline_audit(args) -> int:
    """截止日核验：列出源文里**找不到字面依据**的 deadline_ts。--apply 才写库。"""
    from . import deadline as deadline_mod

    config = _load_config_only()
    db = _require_export_db(config)

    conn = sqlite3.connect(str(db))
    try:
        rows = store.items_with_deadline(conn)
        if not rows:
            print("（库里没有带截止日的条目）")
            return 0
        sources = store.item_sources_text(conn, [r[0] for r in rows])
        bad = deadline_mod.unverified_item_ids(rows, sources)
        kept = [r for r in rows if r[0] not in bad]

        print(f"带截止日的条目：{len(rows)} 条")
        print(f"  源文里找得到依据：{len(kept)} 条")
        print(f"  找不到依据（应清掉）：{len(bad)} 条")
        for item_id, ts in rows:
            if item_id in bad:
                title = conn.execute(
                    "SELECT title FROM items WHERE item_id = ?", (item_id,)
                ).fetchone()[0]
                print(
                    f"    item {item_id}: 标着 "
                    f"{dt.datetime.fromtimestamp(ts):%Y-%m-%d} · {title[:24]}"
                )
        if not bad:
            print("无需改动。")
            return 0
        if not args.apply:
            print("\n（--dry-run：未写库。确认无误后加 --apply）")
            return 0

        # ⚠️ **这是第四个写库命令，也要上锁**（M4 终审 U-3/M-1）：F4 的裁定是
        # 「人工命令也要上锁」（R71），但实现的是**按名字枚举**的三个
        # （export/refine/digest）⇒ 终审实测：锁被持有时 `export` 退 2（被保护），
        # 而 `deadline-audit --apply` 退 **0** 且 `data/vigil.db` **仍被改**。
        # 拿不到锁 ⇒ 退 2 + 一句「[跳过]」，与那三个同一语义：等着就行，不是失败。
        #
        # ⚠️ **只有 `--apply` 上锁，dry-run 不上锁**（判断与理由）：
        # `lock.SingleInstance` 的语义是「同一时刻只许一个**写库**的 vigil 进程」
        # （见 `lock.py` 的模块 docstring），而默认那条路只有 SELECT + print——
        # 它与 `read`/`who`/`media`/`groups` 是同一族的**人工即时查询**
        # （`tests/test_cli.py::test_query_commands_do_not_write_to_the_log`
        # 正是这么归类的）。给只读的检查上锁会凭空造出一个**假拒绝**（rc=2），
        # 而 2 的约定含义是「已经有实例在写」。
        #
        # ⚠️ 代价（知情取舍）：审计的那些 SELECT 已经跑完，结果与被写的这一刻之间
        # 隔了一小段。这是安全的——`clear_deadlines` 只把 `deadline_ts` 置 NULL
        # （只影响传入的行、可重复执行），而并发的 refine 只**新增** items，
        # 不改任何已有行的这一列。
        try:
            with lock.SingleInstance():
                changed = store.clear_deadlines(conn, sorted(bad))
        except lock.AlreadyRunning as exc:
            # 与其它三个写库命令同一行话术（`logs.emit` 先 print 后写日志）
            logs.emit(f"[跳过] {exc}")
            return 2
        print(f"\n已把 {changed} 条的 deadline_ts 置 NULL（其余字段未动）。")
        return 0
    finally:
        conn.close()


def cmd_serve(args) -> int:
    """起本地只读 Web 服务。手机访问见 spec §4.7（tailscale serve 代理本端口）。"""
    import uvicorn  # 延迟导入：不跑服务的人不该为它付启动成本

    from .api import WEB_DIST, create_app

    config = _load_config_only()
    _require_export_db(config)

    if not (WEB_DIST / "index.html").is_file():
        # 不许静默起一个空白页：明说前端没构建，并给出构建命令。
        # ⚠️ flush=True：stdout 重定向到文件时 print 是块缓冲的（实测日志 0 字节），
        # 而这句正是「不许静默」的载体——被缓冲就等于没说过。
        print(
            f"[注意] 前端还没构建（找不到 {WEB_DIST / 'index.html'}）。\n"
            f"  服务仍会启动，但页面只会显示一行提示。构建：\n"
            f"      cd web && npm install && npm run build",
            flush=True,
        )

    app = create_app(config)
    print(f"VIGIL 服务：http://{args.host}:{args.port}", flush=True)
    if args.host == "127.0.0.1":
        print(
            "  （只监听本机——手机访问见 spec §4.7：tailscale serve 代理本端口）",
            flush=True,
        )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vigil", description="VIGIL 守夜人")
    sub = parser.add_subparsers(dest="command", required=True)

    p_groups = sub.add_parser("groups", help="列出 QQ 本地库里的群")
    p_groups.add_argument(
        "--only-watched", action="store_true", help="只显示已纳入监听的群"
    )
    p_groups.set_defaults(func=cmd_groups)

    p_export = sub.add_parser("export", help="导出纳入的群为明文库")
    p_export.set_defaults(func=cmd_export)

    p_who = sub.add_parser("who", help="谁在说：发言排行")
    p_who.add_argument("--group", type=int, help="限定群号")
    p_who.add_argument("--since", help="起始日期 YYYY-MM-DD")
    p_who.add_argument("--limit", type=int, default=20, help="显示人数")
    p_who.set_defaults(func=cmd_who)

    p_read = sub.add_parser("read", help="读消息（可按群/人/时间/关键词过滤）")
    p_read.add_argument("--group", type=int, help="限定群号")
    p_read.add_argument("--sender", help="限定发信人（姓名片段或完整 QQ 号）")
    p_read.add_argument("--keyword", help="正文关键词")
    p_read.add_argument("--since", help="起始日期 YYYY-MM-DD")
    p_read.add_argument("--until", help="结束日期 YYYY-MM-DD")
    p_read.add_argument("--limit", type=int, default=50, help="显示条数")
    p_read.set_defaults(func=cmd_read)

    p_media = sub.add_parser("media", help="本地可取的图片（已在磁盘上）")
    p_media.add_argument("--group", type=int, help="限定群号")
    p_media.add_argument("--since", help="起始日期 YYYY-MM-DD")
    p_media.add_argument("--limit", type=int, default=20, help="显示条数")
    p_media.set_defaults(func=cmd_media)

    p_refine = sub.add_parser("refine", help="抽取：把消息提炼成结构化条目")
    p_refine.add_argument("--since", help="起始日期 YYYY-MM-DD")
    p_refine.add_argument("--until", help="结束日期 YYYY-MM-DD")
    p_refine.add_argument("--limit", type=int, help="最多处理多少条")
    p_refine.add_argument("--redo", action="store_true", help="重抽已处理过的消息")
    p_refine.add_argument("--batch", type=int, default=30, help="每批消息数")
    p_refine.add_argument("--context", type=int, default=2, help="候选各带几条上下文")
    p_refine.add_argument("--budget", type=int, help="token 预算上限")
    p_refine.add_argument("--model", default=None, help="覆盖默认模型")
    p_refine.add_argument(
        "--think",
        action="store_true",
        help="打开模型的思考模式（默认关闭：实测 Qwen3.5-35B-A3B 开思考时"
        "单批要 111.5s / 11,124 输出 token，关掉只要 2.8s / 220 token）",
    )
    p_refine.add_argument(
        "--prompt-ver", default=refine_mod.PROMPT_VERSION,
        help="提示词版本号；改了提示词就换个号，便于区分与重跑",
    )
    p_refine.add_argument("--dry-run", action="store_true", help="只报告不调用模型")
    p_refine.set_defaults(func=cmd_refine)

    p_dl = sub.add_parser(
        "deadline-audit", help="截止日核验：源文里找不到依据的一律清掉"
    )
    p_dl.add_argument("--apply", action="store_true", help="真的写库（默认只报告）")
    p_dl.set_defaults(func=cmd_deadline_audit)

    p_serve = sub.add_parser("serve", help="起本地 Web 服务（只读库）")
    p_serve.add_argument("--host", default="127.0.0.1", help="监听地址")
    p_serve.add_argument("--port", type=int, default=8787, help="端口")
    p_serve.set_defaults(func=cmd_serve)

    p_digest = sub.add_parser("digest", help="日报：把 items 合成一天一页 Markdown")
    p_digest.add_argument("--date", help="日报日期 YYYY-MM-DD（默认昨天）")
    p_digest.add_argument("--model", default=None, help="覆盖默认模型")
    p_digest.add_argument(
        "--think",
        action="store_true",
        help="打开模型的思考模式（默认关闭，与 refine 一致）",
    )
    p_digest.add_argument(
        "--no-write", action="store_true", help="只入库，不写 docs/digests/ 文件"
    )
    p_digest.add_argument("--dry-run", action="store_true", help="只报告不调用模型")
    p_digest.set_defaults(func=cmd_digest)

    p_daily = sub.add_parser(
        "daily", help="每日管线：export → refine → digest（任务计划入口）"
    )
    p_daily.add_argument("--date", help="日报日期 YYYY-MM-DD（默认昨天）")
    p_daily.set_defaults(func=cmd_daily)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
