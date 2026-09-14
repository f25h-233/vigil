"""一次性诊断：msg_id 归因错误是「模型抄错数字」还是「模型指错邻居」。

复现 refine 的提示词构造，对一批真实消息跑一次，看模型返回的 msg_id
与真实来源的命中情况。不是产品代码。

跑法（仓库根）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe _probe_attribution.py
"""

from __future__ import annotations

import json
import sqlite3

from vigil import refine
from vigil.categories import load_categories
from vigil.config import load_llm_key
from vigil.llm import LLMConfig, chat_json
from vigil.redact import Redactor
from vigil.store import PendingMessage

TARGET = 7685024133064673881  # 真来源：有人捡到校园卡和钥匙（640）吗


def main() -> int:
    key = load_llm_key()
    conn = sqlite3.connect("data/vigil.db")
    conn.text_factory = lambda b: b.decode("utf-8", "replace")

    gid, ts = conn.execute(
        "SELECT group_id, ts FROM messages WHERE msg_id = ?", (TARGET,)
    ).fetchone()
    rows = conn.execute(
        """
        SELECT msg_id, ts, COALESCE(sender_uid, ''), content
        FROM messages
        WHERE group_id = ? AND ts BETWEEN ? AND ?
        ORDER BY ts, msg_id LIMIT 30
        """,
        (gid, ts - 5000, ts + 5000),
    ).fetchall()

    msgs = [
        PendingMessage(
            msg_id=r[0], group_id=gid, ts=r[1], sender_uid=r[2], sender="", content=r[3]
        )
        for r in rows
    ]
    pos = next((i + 1 for i, m in enumerate(msgs) if m.msg_id == TARGET), None)
    print(f"批次 {len(msgs)} 条；真来源是第 {pos} 条\n")

    print("【送入的原文】")
    for i, m in enumerate(msgs, 1):
        mark = " ← 真来源" if m.msg_id == TARGET else ""
        print(f"  {i:>2}. [{m.msg_id}] {m.content[:52]}{mark}")

    result = chat_json(
        LLMConfig(api_key=key),
        system=refine.build_system_prompt(load_categories()),
        user=refine.build_user_prompt(msgs, Redactor(), today="2026-09-14"),
    )

    print(f"\n用量: 输入 {result.input_tokens} / 输出 {result.output_tokens}")
    items = result.payload.get("items") or []
    print(f"\n模型返回 {len(items)} 条：")
    hit = miss = 0
    for it in items:
        got = it.get("msg_id")
        ok = got == TARGET
        inside = any(m.msg_id == got for m in msgs)
        if ok:
            hit += 1
        else:
            miss += 1
        print(f"  [{it.get('kind')}] {str(it.get('title'))[:44]}")
        print(f"       返回 msg_id={got}")
        print(f"       {'✓ 命中真来源' if ok else '✗ 不是真来源'}   在批内: {inside}")
    print(f"\n真来源 msg_id = {TARGET}")
    print(f"命中 {hit} / 错 {miss}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
