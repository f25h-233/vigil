"""一次性探针：验证 SiliconFlow 抽取的真实可行性与响应形态。

不是产品代码——只为在写实施计划前，把「外部 API 契约」从猜测变成实测。
跑法（仓库根）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe _probe_refine.py [模型名]
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3
import sys
import urllib.error
import urllib.request

KEY_PATH = pathlib.Path(r"C:/Users/qwe13/.claude/toolkit/.cache/siliconflow.key")
API = "https://api.siliconflow.cn/v1/chat/completions"
GROUP = 1074335063  # 储运263班级群：296 条，小且高价值
BATCH = 15

SYSTEM = """你是校园 QQ 群的信息提炼助手。从群聊消息里挑出对大学生真正有价值的信息。

类目（只能选这些）：
notice     通知公告：辅导员/班助/老师/管理部门发的正式通知（办事、缴费、体检、材料、纪律）
academic   学业：作业、考试、课程调整、选课、成绩、补考、四六级
activity   活动：讲座、社团招新、比赛、晚会、志愿活动
life       生活：食堂、宿舍、水电、校园卡、校车、快递、门禁、维修
secondhand 二手：转让、出售、求购物品
lostfound  失物招领：寻物、认领
job        兼职招聘：兼职、实习、校招、家教

闲聊、纯表情、无信息量的发言**直接不出现在结果里**（不要为它们输出任何东西）。

输出必须是 JSON 对象，形如 {"items": [...]}，其中 items 是数组。
items 里**只放有价值的信息**，无价值的消息不要占位。每个元素：
{"msg_id": 123, "kind": "notice", "title": "一句话摘要（≤30字）",
 "detail": "补充细节或null", "deadline": "YYYY-MM-DD 或 null",
 "place": "地点或null", "amount": "金额或null", "confidence": 0.9}

死线日期必须结合提供的「今天」推算正确年份。"""


def call(key: str, model: str, convo: str, today: str) -> tuple[dict, str]:
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"今天的日期是 {today}。\n\n消息如下：\n{convo}"},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        API,
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8")), body.decode("utf-8")


def main() -> int:
    model = sys.argv[1] if len(sys.argv) > 1 else "Qwen/Qwen2.5-7B-Instruct"
    key = KEY_PATH.read_text(encoding="utf-8").strip()

    conn = sqlite3.connect("data/vigil.db")
    rows = conn.execute(
        """
        SELECT m.msg_id, m.ts, m.content,
               COALESCE(NULLIF(s.group_nick,''), NULLIF(s.qq_nick,''), '未知') AS sender
        FROM messages m
        LEFT JOIN sender_names s ON s.group_id = m.group_id AND s.uid = m.sender_uid
        WHERE m.group_id = ? AND m.content != '[非文本]' AND m.ts > 0
        ORDER BY m.ts ASC LIMIT ?
        """,
        (GROUP, BATCH),
    ).fetchall()
    conn.close()

    first_ts = rows[0][1]
    today = dt.datetime.fromtimestamp(first_ts).strftime("%Y-%m-%d")
    convo = "\n".join(f"[{mid}] {sender}: {content}" for mid, ts, content, sender in rows)

    print(f"模型: {model}")
    print(f"批次: {len(rows)} 条真实消息（{today} 起）")
    print("-" * 70)
    print("【送入的原文】")
    for mid, _ts, content, sender in rows:
        print(f"  [{mid}] {sender}: {content[:70]}")
    print("-" * 70)

    try:
        payload, _ = call(key, model, convo, today)
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}\n{exc.read().decode('utf-8', 'replace')[:600]}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"请求失败: {type(exc).__name__}: {exc}")
        return 1

    usage = payload.get("usage", {})
    print(f"用量: 输入 {usage.get('prompt_tokens')} / 输出 {usage.get('completion_tokens')} tokens")

    content = payload["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        print(f"JSON 解析失败: {exc}\n原始内容:\n{content[:800]}")
        return 1

    items = parsed.get("items", parsed if isinstance(parsed, list) else [])
    print(f"顶层键: {list(parsed.keys()) if isinstance(parsed, dict) else '数组'}")
    print(f"产出条目: {len(items)} / 送入消息 {len(rows)}")
    print("-" * 70)
    for i in items:
        print(f"  [{i.get('kind')}] {i.get('title')}")
        extra = {k: v for k, v in i.items() if k in ("deadline", "place", "amount") and v}
        if extra:
            print(f"        {extra}")
        print(f"        msg_id={i.get('msg_id')} conf={i.get('confidence')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
