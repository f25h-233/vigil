"""M2 日报合成的提示词探针（写计划期间用，不进产品）。

为什么先探针再写计划：M1 的经验是「计划里嵌的完整代码 + 提示词」有约一半缺陷
必须用真实数据才暴露得出来。日报的提示词尤其如此。

═══ 第 1 轮探针（2026-09-15）确认的事实 ═══

1. **quote 契约成立**：10 条 item 全部被逐字摘录命中，0 处未命中。
2. **合并成立**：模型把「新媒体面试地点变更 / 招新结束 / 录取名单公布」
   3 条并成 1 行，quotes 三条都列上——正是 spec 要的「同一活动只留一条」。
3. ⚠️ **全角引号会让模型退化成无限空格循环**（本次探针最大的发现）：

   | 变体 | 结果 |
   |---|---|
   | 原样发出（detail 含 “风之海310”） | 85s 未收尾，已吐 8,896 字且仍在继续 |
   | 把该处 “ ” 换成 「」 | **6.2s 正常返回** |
   | 全条目的 “ ” 都换掉 | **5.8s 正常返回** |
   | 同上但去掉那条 item | 4.5s 正常返回 |

   实测分布：items 270 条里 4 条命中（1.5%）、messages 47,719 条里 25 条命中。
   → **修法：发前把 “ ” 归一化成 「」。** 另加 max_tokens 兜底。

4. ⚠️ **探针自己踩的坑**：第 1 版把 `group_id` 明文发了出去（违反 spec §4.5）。
   → 改发群名；并对文本字段再过一遍 Redactor（纵深防御）。

5. ⚠️ **短超时会误判**：同一个请求 35s 判 FAIL、换 300s 后 2.0s 就返回。
   中间还混入了我自己的僵尸后台请求（占满 key 的并发，把后续请求一起拖死）。
   → 结论：别用短超时做实验；实验前先确认没有残留进程。

用法：
    python _probe_digest.py 2026-09-13 2026-09-08
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from vigil.config import load_config, load_llm_key  # noqa: E402
from vigil.llm import DEFAULT_MODEL, LLMConfig, LLMError, chat_json  # noqa: E402
from vigil.redact import Redactor  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent
DB = REPO_ROOT / "data" / "vigil.db"

# 模型退化护栏（见文件头第 3 条）
QUOTE_MAP = str.maketrans({"“": "「", "”": "」"})

SYSTEM = """你是校园信息日报的编辑。把当天从各个 QQ 群里提炼出的条目，写成一份给同学看的一页日报。

读者的诉求是：**一眼看完，不漏事**。

规则：

1. **每一条 item 都必须出现在日报里**——不能因为"这条不重要"就省略。
   讲同一件事的多条 item 合并成一行；除此之外，一条都不能少。
2. 每一行给出 `quotes`：逐字摘录你引用的那几条 item 的 title 原文片段。
   程序拿它回连条目，**匹配不上的行会被丢弃**，所以必须逐字照抄，不要改写。
   同一件事的多个 item 合并成一行时，`quotes` 要把每一条都列上。
3. 每行还要给出：
   * `label`：**不超过 12 个字**的短标签，说明这一行讲的是什么
     （例：「体检表」「选课补退选」「卖自行车」）。它会加粗显示在行首，
     所以要短、要能一眼扫到，**不要写成完整句子**。
   * `text`：一句话说清细节，让人不看原文就知道该怎么办；
     没有额外信息时给空串。
4. **不要编造 item 里没有的信息**——时间、地点、部门、人名，宁可不写也不能补。

输出必须是 JSON 对象，形如 {"lines": [{"quotes": ["..."], "label": "...", "text": "..."}]}。"""


def fetch(day: str) -> list[dict]:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM items WHERE event_ts >= strftime('%s', ?)"
        " AND event_ts < strftime('%s', ?, '+1 day') ORDER BY event_ts",
        (day, day),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def build_items(rows: list[dict], names: dict[int, str], red: Redactor) -> list[dict]:
    out = []
    for r in rows:
        # ⚠️ 只发群名，绝不发群号（spec §4.5）。文本字段再过一遍 Redactor + 引号归一化。
        def clean(v):
            return (red.text(v) if v else v) if v else None

        out.append(
            {
                "title": (clean(r["title"]) or "").translate(QUOTE_MAP),
                "detail": (clean(r["detail"]) or "").translate(QUOTE_MAP) or None,
                "kind": r["kind"],
                "time": dt.datetime.fromtimestamp(r["event_ts"]).strftime("%H:%M"),
                "place": clean(r["place"]),
                "amount": clean(r["amount"]),
                "deadline": (
                    dt.datetime.fromtimestamp(r["deadline_ts"]).strftime("%Y-%m-%d")
                    if r["deadline_ts"]
                    else None
                ),
                "group": names.get(r["group_id"], ""),
            }
        )
    return out


def render(day: str, lines: list[dict], n_items: int, groups: int, msgs: int) -> str:
    out = [f"# 守夜人日报 · {day}", "", f"当天 {groups} 个群 {msgs:,} 条消息，提炼出 {n_items} 条。", ""]
    for line in lines:
        label = line.get("label") or (line.get("quotes") or [""])[0]
        text = line.get("text") or ""
        out.append(f"- **{label}** {text}".rstrip())
    return "\n".join(out)


def main() -> int:
    days = sys.argv[1:] or ["2026-09-13"]
    key = load_llm_key()
    cfg = load_config()
    names = {g.id: g.name for g in cfg.groups}

    for day in days:
        rows = fetch(day)
        red = Redactor()
        items = build_items(rows, names, red)
        conn = sqlite3.connect(str(DB))
        msgs, groups = conn.execute(
            "SELECT count(*), count(distinct group_id) FROM messages"
            " WHERE ts >= strftime('%s', ?) AND ts < strftime('%s', ?, '+1 day')",
            (day, day),
        ).fetchone()
        conn.close()

        print(f"\n{'='*72}\n{day}：{len(items)} 条 item / {groups} 群 / {msgs:,} 条消息\n{'='*72}")

        user = (
            f"今天的日期是 {day}。\n\n"
            f"以下是 {day} 这一天提炼出的条目：\n"
            + json.dumps({"items": items}, ensure_ascii=False, indent=1)
        )
        t0 = time.time()
        try:
            result = chat_json(
                LLMConfig(
                    api_key=key,
                    model=DEFAULT_MODEL,
                    enable_thinking=False,
                ),
                system=SYSTEM,
                user=user,
            )
        except LLMError as exc:
            print(f"!! 调用失败 {time.time()-t0:.1f}s: {exc}")
            continue

        lines = [l for l in (result.payload.get("lines") or []) if isinstance(l, dict)]
        covered: set[int] = set()
        misses: list[str] = []
        for line in lines:
            for q in line.get("quotes") or []:
                q = str(q).strip()
                if not q:
                    continue
                hit = False
                for j, it in enumerate(items):
                    if q in f"{it['title']} {it['detail'] or ''}":
                        covered.add(j)
                        hit = True
                if not hit:
                    misses.append(q)

        print(f"--- {time.time()-t0:.1f}s | {result.input_tokens}/{result.output_tokens} tok"
              f" | 覆盖 {len(covered)}/{len(items)} | 未命中 {misses} ---")
        print(render(day, lines, len(items), groups, msgs))
        if len(covered) < len(items):
            print("\n【未覆盖（需程序补行）】")
            for j, it in enumerate(items):
                if j not in covered:
                    print(f"  ✗ {it['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
