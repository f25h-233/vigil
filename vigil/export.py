"""按群过滤导出：把 QQ 加密库里的目标群消息落成一个小的明文库。

为什么需要它（见 docs/SETTUP 记录）：
  QQ 的 nt_msg.db 里有坏页，任何「全表扫描」都会失败——所以 1.decrypt.py
  那种全量加密导出永远跑不完。按群号过滤走 idx40027_* 索引，绝大多数群
  一次读完；个别群（消息量最大的那个）仍会撞到物理坏页，由 _read_group
  的主键二分回退兜住，把损失压到几十条。

设计取舍（阶段一·跑起来）：
  - 不做增量记账。每次全量重读已纳群 + INSERT OR REPLACE（幂等），
    15 个群 4.7 万条读一遍几秒——用简单换掉复杂（coding-creed §1）
  - 不建全文索引。索引交给 qqcli 的 `qq index`，本模块只负责「取数」
  - 输出库保持与源库相同的 schema，好让 qqcli 直接认
"""

from __future__ import annotations

import pathlib
import sqlite3
from dataclasses import dataclass, field

from . import media, qqdb, senders, text
from .config import Config

TABLE = "group_msg_table"
GROUP_COL = '"40027"'

# qqcli 兼容层用：qqcli 的全部群聊功能都读 dataline_msg_table，并把 [40020]
# 当作「会话标识」（见 qqcli-rs 的 src/schema.rs 常量 GROUP_NAME）。
# 本机 QQ 版本里群消息实际落在 group_msg_table，但两表列结构完全相同，
# 所以把群消息复制一份过去、并将 [40020] 覆盖成群号即可。
QQCLI_COMPAT_TABLE = "dataline_msg_table"
CONV_ID_INDEX = 7  # [40020] 在列序中的位置
SENDER_NAME_INDEX = 9  # [40021]，qqcli 当作发信人名

# 源表列序（38 列，列名是纯数字，只能靠位置取）
MSG_ID_INDEX = 0  # [40001]
UID_INDEX = 7  # [40020]  发信人 nt_uid（与 CONV_ID_INDEX 同列，角色不同）
TS_INDEX = 13  # [40050]  真 unix 时间戳
CONTENT_INDEX = 17  # [40800]  protobuf 正文

# 派生表：正文已抽成文本，查询/检索直接用它。
# 为什么必须有它：原始正文是 BLOB，SQLite 的 LIKE 无法在 BLOB 上做文本匹配，
# 不抽出来就搜不了；顺带把解 protobuf 的开销从「每次查询」降到「导出一次」。
MESSAGE_TABLE = "messages"
_MESSAGE_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {MESSAGE_TABLE} (
    msg_id     INTEGER PRIMARY KEY,
    group_id   INTEGER NOT NULL,
    ts         INTEGER NOT NULL,
    sender_uid TEXT,
    content    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_group_ts ON {MESSAGE_TABLE}(group_id, ts);
"""

# 发信人姓名表——导出库里自带，查询时无需再碰加密库
SENDER_TABLE = "sender_names"
_SENDER_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {SENDER_TABLE} (
    group_id   INTEGER NOT NULL,
    uid        TEXT    NOT NULL,
    group_nick TEXT,
    qq_nick    TEXT,
    uin        INTEGER,
    in_group   INTEGER,
    PRIMARY KEY (group_id, uid)
)
"""

# 图片引用表：把「消息里的图」与「本地缓存文件」对应起来。
# path 为 NULL = 这条消息引用了图，但本地没有缓存（实测占 93%）。
# 记下未缓存的那些，是为了将来若要联网补全时知道缺哪些。
MEDIA_TABLE = "msg_media"
_MEDIA_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {MEDIA_TABLE} (
    msg_id   INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    ts       INTEGER NOT NULL,
    md5      TEXT    NOT NULL,
    ext      TEXT,
    path     TEXT,
    PRIMARY KEY (msg_id, md5)
);
CREATE INDEX IF NOT EXISTS msg_media_group ON {MEDIA_TABLE}(group_id, ts);
"""


@dataclass
class ExportStats:
    """导出结果汇总——失败也要如实报告，不粉饰。"""

    per_group: list[tuple[int, str, int]] = field(default_factory=list)
    failed_groups: list[tuple[int, str]] = field(default_factory=list)
    skipped_by_group: list[tuple[int, str, int]] = field(default_factory=list)  # (群号, 群名, 条数)
    media_total: int = 0  # 消息里引用的图片数
    media_local: int = 0  # 其中本地有缓存文件的

    @property
    def total_rows(self) -> int:
        return sum(n for _, _, n in self.per_group)

    @property
    def total_skipped(self) -> int:
        return sum(n for _, _, n in self.skipped_by_group)


@dataclass
class GroupRead:
    rows: list[tuple]
    skipped_ranges: list[tuple[int, int]]  # 读不到的段 [(起始 rowid, 条数)]

    @property
    def skipped_count(self) -> int:
        return sum(n for _, n in self.skipped_ranges)


# 二分细化下限：切到这么小仍失败，就认定这片页物理损坏，放弃这几十条。
# 实测 100 条粒度已能到 99.8% 读出率，20 条是留的余量。
_MIN_BATCH = 20


def _read_group(src_factory, gid: int) -> GroupRead:
    """读一个群的全部行。

    快路径：整群一次查完（实测 20 万行可行，走 idx40027_* 索引）。
    快路径撞上坏页时：按**主键**二分切分，把坏页的影响压到最小。

    为什么按主键而不是按时间（实测，同一份快照、同一个群 643375490）：
      按 40058 日粒度二分 → 2026-07-21 坏一页导致**整天陪葬**，只读出 91.2%
      按 40001 主键二分   → 仅 1 批失败，读出 99.8%
    坏页是**页级**损坏，切分粒度越细、损失越小（coding-creed §5 优雅降级）。
    """
    src = src_factory()
    try:
        rows = src.execute(
            f"SELECT * FROM {TABLE} WHERE {GROUP_COL} = ?", (gid,)
        ).fetchall()
        return GroupRead(rows, [])
    except Exception:  # noqa: BLE001 — 转分块路径
        pass

    # ── 分块回退 ──────────────────────────────────────────
    # 先取该群全部 rowid：只扫索引、不碰数据页，因此这一步不会因坏页失败。
    try:
        ids = [
            r[0]
            for r in src.execute(
                f'SELECT "40001" FROM {TABLE} WHERE {GROUP_COL} = ? ORDER BY "40001"',
                (gid,),
            )
        ]
    except Exception:  # noqa: BLE001 — 连索引都读不到，整群读不到
        # ⚠️ **不许**在这里 `return GroupRead([], [])` 当作"这个群读完了"。
        # 那个返回值与「这个群本来就没消息」**完全同形**：调用方会把它记进
        # `per_group`（0 条）、**不进 `failed_groups`** ⇒ `cmd_export` 退 0、
        # `daily` 的「export 失败 ⇒ 跳过 digest」判据失效 ⇒ **日报照写**——
        # 而那篇日报会以「这天很安静」的口气，叙述一个整个群没读进来的日子。
        # （M4 终审在副本里实测过：`✓ 100 班级群：0 条` / `report.ok=True` / 退出码 0。）
        #
        # 抛出去，让调用方（`export()` 里 per-group 的 `except Exception`）
        # 把它记进 `failed_groups` —— **整群读不到本来就是失败**。
        # ⚠️ 只有这一条路要改：坏页那条（`skipped_ranges`）是**已上报的降级**，
        # 不是静默——它进 `skipped_by_group`，CLI 会照实报出来。
        src.close()
        raise
    src.close()

    rows_out: list[tuple] = []
    skipped: list[tuple[int, int]] = []  # [(起始 rowid, 条数)]

    def fetch(lo_i: int, hi_i: int) -> None:
        """读 ids[lo_i:hi_i) 对应的行；失败则重连并二分。"""
        nonlocal src
        if lo_i >= hi_i:
            return
        try:
            rows_out.extend(
                src.execute(
                    f'SELECT * FROM {TABLE} WHERE {GROUP_COL} = ? '
                    f'AND "40001" BETWEEN ? AND ?',
                    (gid, ids[lo_i], ids[hi_i - 1]),
                ).fetchall()
            )
            return
        except Exception:  # noqa: BLE001
            src.close()
            src = src_factory()  # 坏页后连接状态不可靠，重开
        if hi_i - lo_i <= _MIN_BATCH:
            skipped.append((ids[lo_i], hi_i - lo_i))  # 细到下限仍失败，放弃
            return
        mid = (lo_i + hi_i) // 2
        fetch(lo_i, mid)
        fetch(mid, hi_i)

    src = src_factory()
    try:
        fetch(0, len(ids))
    finally:
        src.close()
    return GroupRead(rows_out, skipped)


def _clear_db_path(config: Config) -> pathlib.Path:
    cache_dir = config.output_db.parent / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "nt_msg_clear.db"


def _open_output_db(path: pathlib.Path, table_ddls: list[tuple[str, str]]) -> sqlite3.Connection:
    """打开（或新建）明文输出库，并建出源库的完整空表结构。

    为什么建全部表而不是只建 group_msg_table：
    qqcli 打开库时会校验 c2c_msg_table 是否存在（db.rs:565），
    部分命令还会去查其他表。所以「schema 完整、数据最小」——
    结构照抄，行只灌我们要的群。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    for _name, ddl in table_ddls:
        try:
            conn.execute(ddl)
        except sqlite3.Error:
            continue  # 个别虚拟表/影子表建不出来不影响主流程
    conn.executescript(_MESSAGE_TABLE_DDL)  # 派生表（executescript 会隐式提交）
    conn.executescript(_MEDIA_TABLE_DDL)
    conn.commit()
    return conn


def _source_table_ddls(src: sqlite3.Connection) -> list[tuple[str, str]]:
    """取源库所有表的建表语句（只取结构，不含数据）。"""
    rows = src.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL"
    ).fetchall()
    if not any(name == TABLE for name, _ in rows):
        raise qqdb.QQDBError(f"源库里没有 {TABLE} 表——QQ 版本可能变了")
    return [(name, sql) for name, sql in rows]


def _column_count(src: sqlite3.Connection) -> int:
    return len(src.execute(f'PRAGMA table_info("{TABLE}")').fetchall())


def _to_compat_row(row: tuple, group_id: int, display_name: str) -> tuple:
    """改装成 qqcli 认得的样子。

    [40020] ← 群号（它会话标识）    [40021] ← 发信人姓名（它当发信人名用）
    """
    cols = list(row)
    cols[CONV_ID_INDEX] = str(group_id)
    cols[SENDER_NAME_INDEX] = display_name
    return tuple(cols)


def _write_messages(out: sqlite3.Connection, group_id: int, rows: list[tuple]) -> None:
    """把整群消息抽成文本写入派生表（表由 _open_output_db 建好）。"""
    out.executemany(
        f"INSERT OR REPLACE INTO {MESSAGE_TABLE} VALUES (?,?,?,?,?)",
        [
            (
                row[MSG_ID_INDEX],
                group_id,
                row[TS_INDEX] or 0,
                row[UID_INDEX],
                text.readable(row[CONTENT_INDEX]),
            )
            for row in rows
        ],
    )


def _compat_rows(rows: list[tuple], group_id: int, sender_map: dict) -> list[tuple]:
    """把整群消息改装成 qqcli 兼容行；源码里的 [40020] 是发信人 uid。"""
    out = []
    for row in rows:
        sender = sender_map.get((group_id, row[CONV_ID_INDEX]))
        out.append(_to_compat_row(row, group_id, sender.display_name if sender else ""))
    return out


def _write_senders(
    out: sqlite3.Connection, group_ids: set[int], sender_map: dict
) -> int:
    """把关注群的成员姓名写入导出库，让查询不必再碰加密库。"""
    out.execute(_SENDER_TABLE_DDL)
    rows = [
        (gid, uid, s.group_nick, s.qq_nick, s.uin, 1 if s.in_group else 0)
        for (gid, uid), s in sender_map.items()
        if gid in group_ids
    ]
    out.executemany(f"INSERT OR REPLACE INTO {SENDER_TABLE} VALUES (?,?,?,?,?,?)", rows)
    out.commit()
    return len(rows)


def _write_media(
    out: sqlite3.Connection, group_id: int, rows: list[tuple], cache: dict
) -> tuple[int, int]:
    """把消息里的图片引用写入映射表，返回 (引用总数, 本地有文件的数)。

    同一消息可能引用多张图（转发/相册），全部记录。
    """
    records = []
    for row in rows:
        for md5, ext in media.refs(row[CONTENT_INDEX]):
            found = cache.get(md5)
            records.append(
                (
                    row[MSG_ID_INDEX],
                    group_id,
                    row[TS_INDEX] or 0,
                    md5,
                    ext,
                    str(found) if found else None,
                )
            )
    if records:
        out.executemany(
            f"INSERT OR REPLACE INTO {MEDIA_TABLE} VALUES (?,?,?,?,?,?)", records
        )
    return len(records), sum(1 for r in records if r[5])


def export(config: Config, key: str, *, on_progress=print) -> ExportStats:
    """导出配置里所有 enabled 的群。"""
    clear_path = qqdb.strip_fake_header(
        config.qq_db_dir / "nt_msg.db", _clear_db_path(config)
    )
    src = qqdb.open_encrypted(clear_path, key)
    stats = ExportStats()

    try:
        table_ddls = _source_table_ddls(src)
        ncols = _column_count(src)
        placeholders = ",".join("?" * ncols)
        out = _open_output_db(config.output_db, table_ddls)

        # 发信人姓名。取不到就退化成空——姓名是增强项，不该拖垮导出。
        try:
            gi_clear = qqdb.strip_fake_header(
                config.qq_db_dir / "group_info.db",
                _clear_db_path(config).with_name("group_info_clear.db"),
            )
            sender_map = senders.load_senders(gi_clear, key)
        except Exception:  # noqa: BLE001
            sender_map = {}
        n_senders = _write_senders(out, {g.id for g in config.enabled_groups}, sender_map)
        on_progress(f"发信人姓名：{n_senders:,} 人（来自 group_member3）")

        # 本地图片缓存索引：只扫一次，所有群共用。图片是增强项，取不到不拖垮导出。
        #
        # ⚠️ `on_progress` **必须留在 try 外面**（计划 §8.5）。它原先和
        # `index_cache` 挤在同一个 try 里，于是「报进度失败」（比如日志写不进去）
        # 会被 `except Exception` 吞成 `cache = {}` —— 后果不只是那句话丢了，
        # 而是 `stats.media_local` 变成 0，汇总行会报出「本地可取 0 张」这个**假数字**。
        # 能吞的只有「打扫类」失败；**报进度属于本次运行的记录，它的失败必须冒出去**。
        try:
            cache = media.index_cache(config.qq_db_dir.parent / "nt_data" / "Pic")
        except Exception:  # noqa: BLE001 — 图片是增强项，取不到不拖垮导出
            cache = {}
        on_progress(f"本地图片缓存：{len(cache):,} 个")

        try:
            for group in config.enabled_groups:
                try:
                    result = _read_group(
                        lambda: qqdb.open_encrypted(clear_path, key), group.id
                    )
                except Exception as exc:  # noqa: BLE001 — 外部环境问题，降级而非中断
                    stats.failed_groups.append((group.id, str(exc)[:80]))
                    on_progress(f"  ✗ {group.id} {group.name}：{str(exc)[:60]}")
                    continue

                out.executemany(
                    f"INSERT OR REPLACE INTO {TABLE} VALUES ({placeholders})",
                    result.rows,
                )
                # 兼容层：让 qqcli 也能读到（它只认 dataline_msg_table）
                out.executemany(
                    f"INSERT OR REPLACE INTO {QQCLI_COMPAT_TABLE} VALUES ({placeholders})",
                    _compat_rows(result.rows, group.id, sender_map),
                )
                _write_messages(out, group.id, result.rows)
                n_media, n_local = _write_media(out, group.id, result.rows, cache)
                stats.media_total += n_media
                stats.media_local += n_local
                out.commit()
                stats.per_group.append((group.id, group.name, len(result.rows)))

                note = ""
                if result.skipped_count:
                    stats.skipped_by_group.append(
                        (group.id, group.name, result.skipped_count)
                    )
                    note = f"  [坏页：跳过 {result.skipped_count} 条]"
                on_progress(f"  ✓ {group.id} {group.name}：{len(result.rows):,} 条{note}")
        finally:
            out.close()
    finally:
        src.close()

    return stats
