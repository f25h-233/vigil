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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
