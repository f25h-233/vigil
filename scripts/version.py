#!/usr/bin/env python3
"""VIGIL 版本号方案 —— 唯一计算实现（规则见 README「版本号」）。

    base = v2.{全历史 feat 数}.{全历史 fix/test 数}
    锚点 = 最近一条 feat 提交
    后缀 = 锚点之后【非 feat/fix/test、且非发版提交】的提交数 → a=1 … z=26；0 条则无后缀

⚠️ 发版提交（`chore(release): vX`）不计入后缀 —— 否则版本号会追着自己跑。
⚠️ 计数依赖 master 不被改写：发版后不要再 rebase/squash master，否则已发布的号
   会从仓库里数不出来。
⚠️ 溢出兜底：锚点之后杂项 > 26 条时，后缀取 `z{超出部分}`（如第 27 条 → `z1`）。

用法：
    python scripts/version.py            # 打印 tag，如 v2.61.128e
    python scripts/version.py --version  # 打印包内版本串（PEP440），如 2.61.128
    python scripts/version.py --json     # 打 JSON，供脚本消费
    python scripts/version.py --explain  # 打印计算过程
"""

from __future__ import annotations

import json
import re
import string
import subprocess
import sys

MAJOR = 2

# conventional-commit 前缀；要求有冒号（裸 'feat' 这种不算）
RE_CD = re.compile(r"^(feat|fix|test)(\(.*\))?!?:")
# 发版提交：chore(release): v2.61.128e 这种 —— 从计数里排除
RE_RELEASE = re.compile(r"^chore\(release\): v[0-9]")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


def commits() -> list[tuple[str, str]]:
    """HEAD 可达的全部提交 (sha, subject)，旧 → 新。"""
    out = _git("log", "--reverse", "--pretty=%H%x09%s")
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        sha, _, subj = line.partition("\t")
        if sha:
            rows.append((sha, subj))
    return rows


def classify(subject: str) -> str:
    if RE_RELEASE.match(subject):
        return "release"
    m = RE_CD.match(subject)
    return m.group(1) if m else "other"


def compute(rows: list[tuple[str, str]]) -> dict:
    feat = sum(1 for _, s in rows if classify(s) == "feat")
    fixtest = sum(1 for _, s in rows if classify(s) in ("fix", "test"))

    # 锚点 = 最近一条 feat（没有 feat 则视作从根开始）
    anchor_idx = None
    for i in range(len(rows) - 1, -1, -1):
        if classify(rows[i][1]) == "feat":
            anchor_idx = i
            break

    if anchor_idx is None:
        anchor_sha, anchor_subj = "(none)", "(无 feat 提交)"
        span = rows
    else:
        anchor_sha, anchor_subj = rows[anchor_idx]
        span = rows[anchor_idx + 1 :]

    # ⚠️ 后缀只数「非 feat/fix/test」的杂项提交（避免与 base 的 feat / fix+test 重复计数）；
    #    发版提交也排除（否则版本号追着自己跑）。
    counted = [
        (sha, s) for sha, s in span if classify(s) not in ("feat", "fix", "test", "release")
    ]

    n = len(counted)
    if n == 0:
        letter = ""
    elif n <= 26:
        letter = string.ascii_lowercase[n - 1]
    else:  # 溢出兜底
        letter = f"z{n - 26}"

    base = f"{MAJOR}.{feat}.{fixtest}"
    return {
        "major": MAJOR,
        "feat": feat,
        "fixtest": fixtest,
        "base": base,
        "pep440": base,
        "letter": letter,
        "suffix_count": n,
        "tag": f"v{base}{letter}",
        "anchor_sha": anchor_sha[:8] if anchor_sha != "(none)" else anchor_sha,
        "anchor_subject": anchor_subj,
        "after": [s for _, s in counted],
    }


def main() -> int:
    v = compute(commits())
    if "--json" in sys.argv:
        print(json.dumps(v, ensure_ascii=False, indent=2))
    elif "--version" in sys.argv:
        print(v["pep440"])
    elif "--explain" in sys.argv:
        print(f"base           : v{v['base']}   (feat={v['feat']}  fix+test={v['fixtest']})")
        print(f"锚点(最近 feat): {v['anchor_sha']}  {v['anchor_subject']}")
        print(f"锚点后杂项     : {v['suffix_count']} 条 → 后缀 '{v['letter']}'")
        for s in v["after"]:
            print(f"    · {s}")
        print(f"=> tag          : {v['tag']}")
    else:
        print(v["tag"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
