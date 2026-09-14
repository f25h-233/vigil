"""诊断：4 个候选模型的「思考开关」在 SiliconFlow 上到底怎么工作。

回答问题（不猜，实测）：
  1. 不传 enable_thinking 时，模型是否默认思考？（看响应有没有 reasoning_content、
     输出 token 是不是远大于答案本身）
  2. 传 enable_thinking=false 是否被接受？（HTTP 200 还是 400）
  3. 思考关掉后，json_object 是否仍然可用？
  4. 各模型的延迟量级——这直接决定全量跑一轮要多久。

不是产品代码。跑法（仓库根）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe _probe_think.py
"""

from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from vigil import prefilter, reader, refine
from vigil.categories import load_categories
from vigil.config import load_llm_key
from vigil.redact import Redactor
from vigil.store import PendingMessage

MODELS = [
    "Qwen/Qwen3.5-35B-A3B",
    "Qwen/Qwen3.5-27B",
    "Qwen/Qwen3-32B",
    "Qwen/Qwen3-14B",
]
URL = "https://api.siliconflow.cn/v1/chat/completions"
TIMEOUT = 300


def build_batch() -> tuple[str, list[PendingMessage]]:
    """复现真实管线的第一批（与 refine() 同一条路径）。

    固定 --since 2026-09-12 的窗口——这与历史上三次模型测试的窗口一致
    （09-12 + 09-13 共 1,050 条），保证新数据和旧数据可比。
    """
    since = reader._to_epoch("2026-09-12")
    conn = sqlite3.connect("data/vigil.db")
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    rows = conn.execute(
        """
        SELECT msg_id, group_id, ts, COALESCE(sender_uid,''), content
        FROM messages WHERE ts >= ? AND ts > 0
        ORDER BY ts, msg_id
        """,
        (since,),
    ).fetchall()
    conn.close()
    print(f"窗口内消息 {len(rows)} 条（历史基准窗口）")

    msgs = [
        PendingMessage(
            msg_id=r[0], group_id=r[1], ts=r[2], sender_uid=r[3], sender="", content=r[4]
        )
        for r in rows
    ]

    def tier_of(_gid: int) -> str:
        return "normal"

    candidates, _ = prefilter.screen(msgs, tier_of=tier_of)
    in_scope = prefilter.expand_context(msgs, candidates, context=2)
    batches = prefilter.make_batches(in_scope, max_batch=30)
    return refine.build_user_prompt(
        batches[0], Redactor(), today="2026-09-14"
    ), batches[0]


def call(model: str, system: str, user: str, *, thinking: bool | None, key: str) -> dict:
    """发一次请求。thinking=None 表示**完全不传**该字段（测默认行为）。"""
    payload: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    if thinking is not None:
        payload["enable_thinking"] = thinking

    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = json.loads(response.read().decode("utf-8"))
        elapsed = time.monotonic() - started
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:220]
        return {
            "ok": False,
            "secs": time.monotonic() - started,
            "err": f"HTTP {exc.code}: {detail}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "secs": time.monotonic() - started,
            "err": f"{type(exc).__name__}: {exc}",
        }

    message = raw["choices"][0]["message"]
    content = message.get("content")
    usage = raw.get("usage") or {}
    items = None
    if isinstance(content, str):
        try:
            items = len(json.loads(content.strip().strip("`").removeprefix("json")).get("items") or [])
        except Exception:  # noqa: BLE001
            items = -1  # 不是合法 JSON

    return {
        "ok": True,
        "secs": elapsed,
        "reasoning": bool(message.get("reasoning_content")),
        "content_type": type(content).__name__,
        "chars": len(content) if isinstance(content, str) else 0,
        "items": items,
        "in_tok": usage.get("prompt_tokens"),
        "out_tok": usage.get("completion_tokens"),
        "reason_tok": (usage.get("completion_tokens_details") or {}).get(
            "reasoning_tokens"
        ),
    }


def main() -> int:
    key = load_llm_key()
    system = refine.build_system_prompt(load_categories())
    user, batch = build_batch()
    print(f"批次：{len(batch)} 条消息，提示词 {len(user)} 字符\n", flush=True)

    header = f"{'模型':<22}{'thinking':<12}{'秒':>7}{'入':>7}{'出':>7}{'思维':>6}{'items':>6}  备注"
    print(header, flush=True)
    print("-" * 118, flush=True)

    # 8 次调用彼此独立 —— 并行发，谁先回来谁先打印
    jobs = [
        (model, label, thinking)
        for model in MODELS
        for label, thinking in (("默认(不传)", None), ("false", False))
    ]
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {
            pool.submit(call, m, system, user, thinking=t, key=key): (m, label)
            for m, label, t in jobs
        }
        for future in as_completed(futures):
            model, label = futures[future]
            r = future.result()
            short = model.split("/")[-1]
            if not r["ok"]:
                print(
                    f"{short:<22}{label:<12}{r['secs']:>7.1f}{'-':>7}{'-':>7}{'-':>6}{'-':>6}"
                    f"  ✗ {r['err'][:70]}",
                    flush=True,
                )
                continue
            print(
                f"{short:<22}{label:<12}{r['secs']:>7.1f}"
                f"{r['in_tok'] or 0:>7}{r['out_tok'] or 0:>7}"
                f"{'有' if r['reasoning'] else '无':>6}"
                f"{r['items'] if r['items'] is not None else '?':>6}"
                f"  content={r['content_type']}/{r['chars']}字",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
