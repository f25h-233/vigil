#!/usr/bin/env python3
"""诊断 `vigil groups` 崩溃：group_msg_table 里 "40027"（群号）为 NULL 的行。

**只读**——全是 SELECT，不改任何数据。用法（在仓库根）：

    uv run python scripts/diag_null_group.py

它回答三件事：
  1. 群号列为 NULL 的行有多少条？占比多少？
  2. 它们的时间戳（40058）落在哪一段？是历史的还是最近的？
  3. 少数字段（40021 是另一个群号列）在那些行里是什么？

背景：`list_group_message_counts` 的 `GROUP BY "40027"` 会给 NULL 建一个组，
于是 `int(g)` 拿到 None 崩掉。要知道该跳过还是该保留，先看清这些行是什么。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from vigil import config as config_mod  # noqa: E402
from vigil import qqdb  # noqa: E402


def _clear_db_path(config) -> Path:
    """`vigil groups`/`export` 用的「去假头后的明文库」路径。

    故意**不** import `export._clear_db_path`（私有名）：诊断脚本不该依赖
    别的模块内部结构。这条路径由 `cmd_groups` 与 `export` 共用地拼出，
    稳定且唯一（见 vigil/export.py）。
    """
    return config.output_db.parent / "cache" / "nt_msg_clear.db"


def main() -> int:
    try:
        config = config_mod.load_config()
    except config_mod.ConfigError as exc:
        print(f"[配置错误] {exc}")
        return 1

    key = config_mod.load_key()
    if not key:
        print("[配置错误] 没有数据库密钥（.env 里的 VIGIL_DB_KEY）")
        return 1

    clear_path = _clear_db_path(config)
    if not clear_path.is_file():
        print(f"[错误] 明文库不存在：{clear_path}")
        print("       先跑一次 `uv run vigil export`（或 `vigil daily`）生成它。")
        return 1

    print(f"明文库：{clear_path}")
    conn = qqdb.open_encrypted(clear_path, key)
    try:
        total = conn.execute("SELECT count(*) FROM group_msg_table").fetchone()[0]
        null_row = conn.execute(
            'SELECT count(*), min("40058"), max("40058") '
            'FROM group_msg_table WHERE "40027" IS NULL'
        ).fetchone()
        n_null, t_min, t_max = int(null_row[0]), null_row[1], null_row[2]

        print()
        print(f"总行数              : {total:,}")
        print(f'群号("40027") 为 NULL: {n_null:,}   ({n_null / total * 100:.3f}%)' if total else "总行数 0")

        if n_null:
            print(f"  这些行的时间戳范围: {t_min} .. {t_max}")
            # 40021 是另一个群号列（TEXT）——看它们在那儿是不是也空
            alt = conn.execute(
                'SELECT "40021", count(*) FROM group_msg_table '
                'WHERE "40027" IS NULL GROUP BY "40021" ORDER BY count(*) DESC LIMIT 5'
            ).fetchall()
            print(f'  同批行的 "40021"(TEXT 群号) 分布（前 5）:')
            for g21, c in alt:
                print(f"    {g21!r}: {c:,}")
            # 抽样看几行，判断是破页噪声还是真消息
            print("  抽样 3 行（40001 ID / 40003 序号 / 40058 时间 / 40800 正文长度）:")
            for r in conn.execute(
                'SELECT "40001", "40003", "40058", length("40800") '
                'FROM group_msg_table WHERE "40027" IS NULL LIMIT 3'
            ).fetchall():
                print(f"    id={r[0]}  seq={r[1]}  ts={r[2]}  body_len={r[3]}")
        else:
            print("  → 没有 NULL 群号的行。若仍崩溃，请把完整栈贴出来。")

        # 对照：正常群的条数（走索引，不触表扫描）
        print()
        print("对照——按群号分组的条数（前 5）:")
        for g, n in conn.execute(
            'SELECT "40027", count(*) FROM group_msg_table '
            'WHERE "40027" IS NOT NULL GROUP BY "40027" ORDER BY count(*) DESC LIMIT 5'
        ).fetchall():
            print(f"    {g}: {n:,}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
