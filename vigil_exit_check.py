"""M1 出口标准的**机械**核验 —— 不调模型、不写库，只查。

人工判不了的那几条（覆盖无遗漏、来源可回溯、类目不越界）在这里一次算清；
需要人判的「分类准确率 ≥80%」由 `vigil_acceptance.py` 出材料。

存在的理由：这几条以前是靠一次性 SQL 手敲的，敲完就没留下痕迹，
下一轮要重验时得重新拼。固化成脚本，每次跑完 refine 一条命令复核。

跑法（仓库根）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe vigil_exit_check.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from vigil.categories import load_categories


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/vigil.db")
    args = ap.parse_args()

    if not Path(args.db).is_file():
        sys.exit(f"找不到库：{args.db}")
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")

    def one(sql: str, *params):
        return conn.execute(sql, params).fetchone()[0]

    # 判据是「有没有哪条消息拿不到 refine_runs 记录」，不是「两边行数相不相等」。
    # 早先写成 `COUNT(messages WHERE ts>0)` 对 `COUNT(refine_runs)`，差出 14 条
    # 报了假红——那 14 条是 ts=0 的 `[非文本]` 占位行，**本来就该被处理**，
    # 拿它们当分母等于凭空给出口标准加了一条约束。分母必须是 messages 全量。
    total = one("SELECT COUNT(*) FROM messages")
    missing = one(
        "SELECT COUNT(*) FROM messages m "
        "WHERE NOT EXISTS (SELECT 1 FROM refine_runs r WHERE r.msg_id = m.msg_id)"
    )
    orphan_runs = one(
        "SELECT COUNT(*) FROM refine_runs r "
        "WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.msg_id = r.msg_id)"
    )
    covered = total - missing
    ok = one("SELECT COUNT(*) FROM refine_runs WHERE status = 'ok'")
    err = one("SELECT COUNT(*) FROM refine_runs WHERE status = 'error'")
    items = one("SELECT COUNT(*) FROM items")
    bad_kind = one(
        "SELECT COUNT(*) FROM items WHERE kind NOT IN (%s)"
        % ",".join("?" * len(KINDS)),
        *KINDS,
    )
    orphan = one(
        "SELECT COUNT(*) FROM items i "
        "WHERE NOT EXISTS (SELECT 1 FROM item_sources s WHERE s.item_id = i.item_id)"
    )
    dangling = one(
        "SELECT COUNT(*) FROM item_sources s "
        "WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.msg_id = s.msg_id)"
    )
    dup = one(
        "SELECT COUNT(*) FROM ("
        "  SELECT item_id, msg_id FROM item_sources"
        "  GROUP BY item_id, msg_id HAVING COUNT(*) > 1)"
    )

    runs = conn.execute(
        "SELECT prompt_ver, status, COUNT(*) FROM refine_runs GROUP BY prompt_ver, status"
    ).fetchall()
    versions = conn.execute(
        "SELECT model, prompt_ver, COUNT(*) FROM items GROUP BY model, prompt_ver"
    ).fetchall()
    conn.close()

    print("=" * 74)
    print("M1 出口标准 · 机械核验")
    print("=" * 74)

    checks = [
        ("1. 「无遗漏」每条消息都有 refine_runs 记录", f"{covered:,} / {total:,}", missing == 0),
        ("2. 无来源的 items", str(orphan), orphan == 0),
        ("3. 指向不存在消息的来源", str(dangling), dangling == 0),
        ("4. 类目越界（不在 categories.toml 里）", str(bad_kind), bad_kind == 0),
        ("5. item_sources 重复行", str(dup), dup == 0),
        ("6. refine_runs 里的孤儿行（消息已不在）", str(orphan_runs), orphan_runs == 0),
        ("7. 失败批次（记录在案，非致命）", str(err), None),
    ]
    for label, value, verdict in checks:
        mark = "✓" if verdict is True else ("—" if verdict is None else "✗")
        print(f"  {mark} {label:<44} {value:>18}")

    print(f"\n  items 总数：{items:,}（其中 status=ok 的消息 {ok:,} 条）")
    print("\n  refine_runs 分版：")
    for ver, status, n in runs:
        print(f"    {ver or '(空)'} / {status:<10} {n:>8,}")
    print("\n  items 按模型与提示词版本（**混版就是脏数据**）：")
    for model, ver, n in versions:
        print(f"    {model or '(空)'} / {ver or '(空)'}  {n:>8,}")

    if len(versions) > 1:
        print("\n  ⚠️ items 里出现多于一种「模型 + 提示词版本」组合——")
        print("     验收抽样会混进旧产出，先清表重跑再来。")
        return 1

    failed = [c for c in checks if c[2] is False]
    if failed:
        print(f"\n✗ {len(failed)} 项未通过，M1 不能判过。")
        return 1
    print("\n✓ 机械项全过。剩下「分类准确率 ≥80%」需人工判定：")
    print("    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe "
          "vigil_acceptance.py --n 100 --m 20 > M1-验收抽样.md")
    return 0


KINDS = tuple(c.slug for c in load_categories())

if __name__ == "__main__":
    raise SystemExit(main())
