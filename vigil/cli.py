"""VIGIL 命令行入口。

    vigil groups    列出 QQ 本地库里所有群（含是否已纳入监听）
    vigil export    把纳入的群导出成明文库，供 qqcli 建索引
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

from . import export as export_mod
from . import qqdb, reader
from . import refine as refine_mod
from .config import ConfigError, load_config, load_key


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
    config, key = _load_or_die()
    print(f"导出 {len(config.enabled_groups)} 个群 → {config.output_db}")

    stats = export_mod.export(config, key)
    print("-" * 60)
    print(f"完成：{len(stats.per_group)} 个群，共 {stats.total_rows:,} 条消息")

    if stats.skipped_by_group:
        print(f"\n[注意] 有 {stats.total_skipped:,} 条消息因 QQ 数据库坏页读不到：")
        for gid, gname, n in stats.skipped_by_group:
            print(f"  {gid} {gname}：{n:,} 条")
        print("  这是 QQ 数据库自身的物理坏页，非导出错误；同群其余消息不受影响。")

    if stats.failed_groups:
        print(f"\n[失败] {len(stats.failed_groups)} 个群整群读不到：")
        for gid, err in stats.failed_groups:
            print(f"  {gid}: {err}")

    if stats.media_total:
        pct = stats.media_local / stats.media_total * 100
        print(
            f"\n图片引用：{stats.media_total:,} 张，本地可取 "
            f"{stats.media_local:,} 张（{pct:.0f}%）"
        )
        print("  取不到的并非「对不上号」，而是 QQ 没有缓存该图（见 vigil/media.py）。")
    return 0


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
            prompt_ver=args.prompt_ver,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        sys.exit(f"[参数错误] {exc}")

    print("-" * 60)
    # ⚠️ 账目必须自洽：只报「硬丢弃」的话，用户会拿 scanned − discarded_local
    # 去对 sent_messages，然后发现差了三万多条不知道去哪了（Task 7 审查实测）。
    # 所以主数字用「本地筛掉」（= scanned − sent），硬丢弃作为其中一项列出。
    print(
        f"完成：扫描 {stats.scanned:,} 条 → 本地筛掉 "
        f"{stats.scanned - stats.sent_messages:,} 条"
        f"（其中硬丢弃 {stats.discarded_local:,} 条）"
        f" → 送模型 {stats.sent_messages:,} 条（{stats.batches:,} 批）"
    )
    print(f"产出条目：{stats.items_saved:,} 条")
    if not args.dry_run:
        print(f"token 用量：输入 {stats.input_tokens:,} / 输出 {stats.output_tokens:,}")
    if stats.budget_hit:
        # 报「实际跑了多少」而不是计划数——预算 break 后两者会差很多
        print(
            f"[注意] 达到预算上限提前停止：实际跑了 {stats.batches} 批，"
            f"计划 {stats.batches_planned} 批。剩余消息留待下次（或调大 --budget）"
        )
    if stats.errors:
        print(f"\n[失败] {len(stats.errors)} 批出错：")
        for e in stats.errors[:5]:
            print(f"  {e}")
    if args.dry_run:
        print("（--dry-run：未调用模型、未写库）")
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
        "--prompt-ver", default=refine_mod.PROMPT_VERSION,
        help="提示词版本号；改了提示词就换个号，便于区分与重跑",
    )
    p_refine.add_argument("--dry-run", action="store_true", help="只报告不调用模型")
    p_refine.set_defaults(func=cmd_refine)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
