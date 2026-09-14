"""对照实验：批内序号 vs 19 位 msg_id，哪个归因更可靠。

同一批真实消息、同一个模型，只换提示词里的标识方式，对比归因正确率。
不是产品代码。

跑法（仓库根）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe _probe_index.py
"""

from __future__ import annotations

import sqlite3
import sys

from vigil import refine
from vigil.categories import load_categories, prompt_block
from vigil.config import load_llm_key
from vigil.llm import LLMConfig, chat_json
from vigil.redact import Redactor
from vigil.store import PendingMessage

TARGET = 7685024133064673881  # 有人捡到校园卡和钥匙（640）吗
TITLE_KEY = "校园卡和钥匙"


def load_batch() -> tuple[list[PendingMessage], int]:
    conn = sqlite3.connect("data/vigil.db")
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    gid, ts = conn.execute(
        "SELECT group_id, ts FROM messages WHERE msg_id = ?", (TARGET,)
    ).fetchone()
    rows = conn.execute(
        """
        SELECT msg_id, ts, COALESCE(sender_uid, ''), content
        FROM messages WHERE group_id = ? AND ts BETWEEN ? AND ?
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
    pos = next(i for i, m in enumerate(msgs, 1) if m.msg_id == TARGET)
    return msgs, pos


def build_index_prompt(msgs: list[PendingMessage], today: str) -> tuple[str, str]:
    """序号版提示词：把 [msg_id] 换成 1..N 的序号。"""
    cats = load_categories()
    system = f"""你是校园 QQ 群的信息提炼助手。从群聊消息里挑出对大学生真正有价值的信息。

类目（只能选这些）：
{prompt_block(cats)}

闲聊、纯表情、无信息量的发言**直接不出现在结果里**。

输出必须是 JSON 对象，形如 {{"items": [...]}}，其中 items 是数组。
每个元素的结构：
{{"idx": 29, "kind": "notice", "title": "一句话摘要（≤40字）",
 "detail": "补充细节或null", "deadline": "YYYY-MM-DD 或 null",
 "place": "地点或null", "amount": "金额或null", "confidence": 0.9}}

⚠️ idx 是下面消息列表里的**序号**（从 1 开始），不是消息 ID。
死线日期必须结合提供的「今天」推算正确年份。"""

    redactor = Redactor()
    lines = []
    for i, m in enumerate(msgs, 1):
        body = redactor.text(m.content)
        who = redactor.actor(m.sender_uid) if m.sender_uid else f"匿名{m.msg_id}"
        lines.append(f"{i}. {who}: {body}")
    user = f"今天的日期是 {today}。\n\n消息如下：\n" + "\n".join(lines)
    return system, user


def judge(payload: dict, key_name: str, msgs: list[PendingMessage], pos: int) -> None:
    items = payload.get("items") or []
    print(f"  返回 {len(items)} 条：")
    for it in items:
        got = it.get(key_name)
        title = str(it.get("title") or "")
        if key_name == "idx" and isinstance(got, int) and 1 <= got <= len(msgs):
            ok = got == pos
            where = f"批内第 {got} 条 = {msgs[got - 1].content[:26]}"
        elif key_name == "msg_id":
            ok = got == TARGET
            where = next(
                (f"批内第 {i} 条" for i, m in enumerate(msgs, 1) if m.msg_id == got),
                "不在批内",
            )
        else:
            ok, where = False, "非法"
        mark = "✓" if ok else "✗"
        print(f"    {mark} [{it.get('kind')}] {title[:34]}")
        print(f"        {key_name}={got}  → {where}")
    hits = sum(
        1
        for it in items
        if (it.get(key_name) == pos if key_name == "idx" else it.get(key_name) == TARGET)
    )
    print(f"  命中 {hits}/{len(items)}")


def main() -> int:
    key = load_llm_key()
    msgs, pos = load_batch()
    print(f"批次 {len(msgs)} 条；真来源（{TITLE_KEY}）在第 {pos} 条")
    print(f"真来源 msg_id = {TARGET}\n")

    cfg = LLMConfig(api_key=key)

    print("=" * 70)
    print("【A】现有实现：msg_id 版")
    print("=" * 70)
    r1 = chat_json(
        cfg,
        system=refine.build_system_prompt(load_categories()),
        user=refine.build_user_prompt(msgs, Redactor(), today="2026-09-14"),
    )
    print(f"  token: {r1.input_tokens}/{r1.output_tokens}")
    judge(r1.payload, "msg_id", msgs, pos)

    print()
    print("=" * 70)
    print("【B】候选修法：批内序号版")
    print("=" * 70)
    sys_b, user_b = build_index_prompt(msgs, "2026-09-14")
    r2 = chat_json(cfg, system=sys_b, user=user_b)
    print(f"  token: {r2.input_tokens}/{r2.output_tokens}")
    judge(r2.payload, "idx", msgs, pos)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
