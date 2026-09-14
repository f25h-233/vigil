"""M1 出口验收的抽样工具 —— 生成便于人工判读的核对表。

不是产品代码，是验收证据的生成器。输出两样东西：

1. **分类准确率抽验**：随机抽 N 条 item，每条附源消息原文，你逐条判断
   「类别对不对」。这是 spec 定的 M1 出口标准之一。
2. **可回溯性核验**：随机抽 M 条，机械化核对「来源内容里是否真的含有
   item 的依据」，标出可疑项。

跑法（仓库根）：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe vigil_acceptance.py
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe vigil_acceptance.py --n 100 --m 20
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import re
import sqlite3
import sys

DB = "data/vigil.db"
KIND = {
    "notice": "通知公告",
    "academic": "学业",
    "activity": "活动",
    "life": "生活",
    "secondhand": "二手",
    "lostfound": "失物招领",
    "job": "兼职招聘",
}

# 归一化：剥空白与常见中英文标点，用于「标题是否能在来源里找到依据」的机械核对
_PUNCT = re.compile(r"[\s，。！？、：；「」『』【】（）()\[\]…~～\-—]+")


def _norm(s: str) -> str:
    return _PUNCT.sub("", s or "")


def load(db: str):
    conn = sqlite3.connect(db)
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    rows = conn.execute(
        """
        SELECT i.item_id, i.kind, i.title, i.detail, i.deadline_ts,
               i.place, i.amount, i.confidence, i.group_id, m.content, m.ts
        FROM items i
        JOIN item_sources s ON s.item_id = i.item_id
        JOIN messages   m ON m.msg_id  = s.msg_id
        ORDER BY i.item_id
        """
    ).fetchall()
    conn.close()
    return rows


def overlap(title: str, src: str) -> float:
    """标题字符有多大比例能在来源里找到（粗指标，仅供标可疑，不作判据）。"""
    t = _norm(title)
    if not t:
        return 0.0
    s = _norm(src)
    return sum(1 for ch in t if ch in s) / len(t)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100, help="分类抽验条数")
    ap.add_argument("--m", type=int, default=20, help="可回溯核验条数")
    ap.add_argument("--seed", type=int, default=20260914, help="随机种子（可复现）")
    args = ap.parse_args()

    rows = load(DB)
    if not rows:
        print("items 表为空——先跑 vigil refine")
        return 1

    random.seed(args.seed)
    total = len(rows)
    print("=" * 92)
    print(f"M1 出口验收抽样　｜　items 共 {total:,} 条　｜　种子 {args.seed}")
    print("=" * 92)

    # ── 第一部分：分类准确率抽验 ──
    n = min(args.n, total)
    print(f"\n【一】分类准确率抽验　随机 {n} 条")
    print("请逐条判断：**【】里的类别对不对**（对 = ✓，错 = 写下应该是什么类）")
    print("-" * 92)
    for idx, r in enumerate(random.sample(rows, n), 1):
        iid, kind, title, detail, dl, place, amount, conf, gid, src, ts = r
        when = dt.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "-"
        dls = dt.datetime.fromtimestamp(dl).strftime("%Y-%m-%d") if dl else "—"
        print(f"\n{idx:>3}. 【{KIND.get(kind, kind)}】{title}")
        extra = []
        if detail:
            extra.append(f"细节={detail}")
        if place:
            extra.append(f"地点={place}")
        if amount:
            extra.append(f"金额={amount}")
        if dl:
            extra.append(f"截止={dls}")
        if extra:
            print(f"     {' | '.join(extra)[:110]}")
        print(f"     {when}　群{gid}　置信{conf}")
        print(f"     来源: {src[:104]}")

    # ── 第二部分：可回溯性核验（机械化）──
    m = min(args.m, total)
    print("\n\n" + "=" * 92)
    print(f"【二】可回溯性核验　随机 {m} 条（机械核对：标题能否在来源里找到依据）")
    print("=" * 92)
    judged = []
    for r in random.sample(rows, m):
        iid, kind, title, _, _, _, _, _, _, src, _ = r
        judged.append((iid, title, src, overlap(title, src)))
    bad = [j for j in judged if j[3] < 0.45]
    for iid, title, src, ratio in sorted(judged, key=lambda x: x[3]):
        flag = "✓" if ratio >= 0.45 else "⚠️"
        print(f"  {flag} #{iid:<4} 重合 {ratio:>4.0%}　{title[:44]}")
        if ratio < 0.45:
            print(f"           来源: {src[:80]}")
    print(f"\n  ⚠️ 重合 <45% 的：{len(bad)} / {m}（该指标偏保守，需人工确认是否为真错配）")

    # ── 汇总 ──
    print("\n\n" + "=" * 92)
    print("【三】M1 出口标准对照")
    print("=" * 92)
    print(f"  1. 分类准确率 ≥ 80%　　　　→ 由第一部分人工判定：____ / {n}")
    print(f"  2. 可回溯且内容对得上　　　→ 由第二部分核验：{m - len(bad)} / {m} 机械通过")
    print(f"  3. items 条数　　　　　　　→ {total:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
