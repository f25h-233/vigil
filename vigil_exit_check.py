"""M1 出口标准的**机械**核验 —— 不调模型、**不写 `data/vigil.db`**，只查。

人工判不了的那几条（覆盖无遗漏、来源可回溯、类目不越界）在这里一次算清；
需要人判的「分类准确率 ≥80%」由 `vigil_acceptance.py` 出材料。

存在的理由：这几条以前是靠一次性 SQL 手敲的，敲完就没留下痕迹，
下一轮要重验时得重新拼。固化成脚本，每次跑完 refine 一条命令复核。

⚠️ M6 T5 起「类目越界」那一项走 `store.kind_counts`（**有效类目**口径），
而读取路径会在 overlay 库**不存在**时就地建一个**空的**（`attach_readonly` 的既有
语义）——所以严格说本脚本可能建出 `data/overrides.db`（空库，零行）。
主库仍然是全程 `mode=ro`，不写一个字节。

跑法（仓库根）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe vigil_exit_check.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from vigil import store
from vigil.categories import load_categories


def _bad_kind_count(conn: sqlite3.Connection, live: set[str]) -> int:
    """**有效类目**越界的条数（Fix loop 1 / FIX 4）。

    ⚠️ 它**必须**与四条读路径同源（`store.kind_counts` 用的就是
    `store._EFFECTIVE_KIND`，含 overlay 与两级别名），**不能**自己写一句
    `WHERE kind NOT IN (...)`：那句读的是**库里的原值**，于是双向都不可信——

      · **误报**：合法改名之后它报 `bad_kind > 0`（条目显示的其实是新 slug，
        一切正常）⇒ 会把一次正确操作判成出口不合格；
      · **漏报**：`ost.kind` 是个废 slug 时它报 0（界面上那条正显示着一个
        不存在的类目）⇒ 悬空条目从验收里溜过去。

    而本脚本是**冒烟 / 出口检查的仪器**：判据坏了会**误导里程碑验收**，
    比一个普通函数的 bug 更贵。

    ⚠️ 口径与读路径一致 ⇒ **不含软删**（D15：软删的条目在所有读取路径上都不存在，
    它的类目再越界也不构成任何可观测的问题）。
    """
    return sum(n for k, n in store.kind_counts(conn).items() if k not in live)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/vigil.db")
    args = ap.parse_args()

    # ⚠️ 类目表**在这里现读**，不再是 import 期的模块级常量：一个在 import 时读
    # 真实仓库文件的常量，测试够不着它（要测就得改仓库里那份 categories.toml）。
    live = {c.slug for c in load_categories()}

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
    bad_kind = _bad_kind_count(conn, live)
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
        ("4. 类目越界（**有效**类目不在 categories.toml）", str(bad_kind), bad_kind == 0),
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
    print("\n✓ 机械项全过。")
    print("  ⚠️ 本脚本**判不了**「分类准确率 ≥80%」——那要人工读抽样材料，")
    print("     且只在改了 categories.toml / 提示词后才需要重判（重跑会换一批抽样）：")
    print("       PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe "
          "vigil_acceptance.py --n 100 --m 20 > 新抽样.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
