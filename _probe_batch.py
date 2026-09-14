"""诊断：复现真实管线的批次构造，dump 送出内容与模型返回原文。

回答一个问题：修复后仍然错归因的那些 item，模型到底看到了什么、
返回了什么。不是产品代码。

跑法（仓库根）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe _probe_batch.py
"""

from __future__ import annotations

import json
import sqlite3

from vigil import prefilter, refine
from vigil.categories import load_categories
from vigil.config import load_llm_key
from vigil.llm import LLMConfig, chat_json
from vigil.redact import Redactor
from vigil.store import PendingMessage

TARGET = 7685024133064673881  # 有人捡到校园卡和钥匙（640）吗
GROUP = 643375490


def main() -> int:
    conn = sqlite3.connect("data/vigil.db")
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    target_ts = conn.execute(
        "SELECT ts FROM messages WHERE msg_id = ?", (TARGET,)
    ).fetchone()[0]

    # 取一个比批次大得多的窗口，复现 expand_context + make_batches
    rows = conn.execute(
        """
        SELECT msg_id, ts, COALESCE(sender_uid,''), content FROM messages
        WHERE group_id = ? AND ts BETWEEN ? AND ? AND ts > 0
        ORDER BY ts, msg_id
        """,
        (GROUP, target_ts - 4000, target_ts + 4000),
    ).fetchall()
    msgs = [
        PendingMessage(
            msg_id=r[0], group_id=GROUP, ts=r[1], sender_uid=r[2], sender="", content=r[3]
        )
        for r in rows
    ]
    print(f"窗口 {len(msgs)} 条（复现管线）")

    def tier_of(_gid: int) -> str:
        return "normal"  # 该群在 config 里是 normal

    candidates, stats = prefilter.screen(msgs, tier_of=tier_of)
    print(f"预筛：保留 {len(candidates)} / 硬丢弃 {stats.dropped}")
    print(f"  真来源是否入选候选：{any(c.msg_id == TARGET for c in candidates)}")

    in_scope = prefilter.expand_context(msgs, candidates, context=2)
    batches = prefilter.make_batches(in_scope, max_batch=30)
    print(f"in_scope {len(in_scope)} 条 → {len(batches)} 批")

    hit = None
    for bi, b in enumerate(batches, 1):
        for i, m in enumerate(b, 1):
            if m.msg_id == TARGET:
                hit = (bi, i, b)
    if hit is None:
        print("!! 真来源不在任何批次里 —— 那它根本不可能被正确归因")
        return 0

    bi, pos, batch = hit
    print(f"\n真来源在第 {bi} 批的第 {pos} 位\n")

    user = refine.build_user_prompt(batch, Redactor(), today="2026-09-14")
    print("【送出的提示词正文】")
    print(user)
    print()

    result = chat_json(
        LLMConfig(api_key=load_llm_key()),
        system=refine.build_system_prompt(load_categories()),
        user=user,
    )
    print(f"【模型返回】token {result.input_tokens}/{result.output_tokens}")
    print(json.dumps(result.payload, ensure_ascii=False, indent=2))
    print()
    print(f"真来源 msg_id={TARGET}，在第 {pos} 位")
    for it in result.payload.get("items") or []:
        got = it.get("idx")
        mark = "✓" if got == pos else "✗"
        print(f"  {mark} idx={got}  {str(it.get('title'))[:44]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
