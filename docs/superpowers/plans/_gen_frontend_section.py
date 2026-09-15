"""把**已验证**的前端源码生成为计划的一个章节。

为什么不手抄：手抄会漂移。这里的每个文件都在探针目录里真装真构建过
（vite 8.3 构建 180 模块通过），生成能保证「计划里写的」与「验证过的」
逐字节相同。

用法：python docs/superpowers/plans/_gen_frontend_section.py
"""

import pathlib

SRC = pathlib.Path("_smoke/m3-frontend-probe")
PLAN = pathlib.Path("docs/superpowers/plans/2026-09-15-vigil-m3-web-pwa.md")

# (探针里的路径, 计划里的路径, 属于哪个任务)
FILES = [
    ("src/types.ts", "web/src/types.ts", "T4"),
    ("src/api.ts", "web/src/api.ts", "T4"),
    ("src/format.ts", "web/src/format.ts", "T4"),
    ("src/index.css", "web/src/index.css", "T4"),
    ("src/main.tsx", "web/src/main.tsx", "T4"),
    ("src/App.tsx", "web/src/App.tsx", "T4"),
    ("src/components/SourceList.tsx", "web/src/components/SourceList.tsx", "T4"),
    ("src/components/ItemCard.tsx", "web/src/components/ItemCard.tsx", "T4"),
    ("index.html", "web/index.html", "T4"),
    ("tsconfig.json", "web/tsconfig.json", "T4"),
    ("vite.config.ts", "web/vite.config.ts", "T4"),
    ("package.json", "web/package.json", "T4"),
    (".gitignore", "web/.gitignore", "T4"),
    ("tools/make_icons.py", "web/tools/make_icons.py", "T4"),
    ("src/views/Feed.tsx", "web/src/views/Feed.tsx", "T5"),
    ("src/views/Categories.tsx", "web/src/views/Categories.tsx", "T6"),
    ("src/views/Digests.tsx", "web/src/views/Digests.tsx", "T6"),
]

LANG = {
    ".ts": "ts", ".tsx": "tsx", ".css": "css", ".json": "json",
    ".html": "html", ".py": "python", "": "text",
}

out: list[str] = [
    "\n---\n",
    "## 附录 A：前端全部文件（**已在探针里真装真构建通过，逐字照抄，不许改写**）\n",
    "本节由 `docs/superpowers/plans/_gen_frontend_section.py` **从验证过的文件生成**，",
    "不是手抄——手抄会漂移，而漂移的后果是 implementer 抄到一个没验证过的版本。\n",
    "生成命令（改完探针文件后重跑）：",
    "```bash\npython docs/superpowers/plans/_gen_frontend_section.py\n```\n",
    "⚠️ 这些文件在 `_smoke/m3-frontend-probe/` 里通过了 `npm run build`（vite 8.3.0，",
    "180 模块，PWA 产物齐全），并用**变异反证**证明过 `tsc` 真的在检查类型。\n",
]

missing: list[str] = []
for rel_probe, rel_plan, task in FILES:
    p = SRC / rel_probe
    if not p.is_file():
        missing.append(rel_probe)
        continue
    body = p.read_text(encoding="utf-8").rstrip("\n")
    lang = LANG.get(p.suffix, "text")
    out.append(f"### A.{len([x for x in out if x.startswith('### A.')]) + 1} `{rel_plan}`"
               f"（{task}）\n")
    out.append(f"````{lang}\n{body}\n````\n")

if missing:
    raise SystemExit(f"探针里缺这些文件，先补齐再生成：{missing}")

section = "\n".join(out)

# ⚠️ 这是一次性播种工具，**不是幂等生成器**。终审（阶段③）点名过这个风险：
# 它用 "a" 追加、编号从 A.1 重数（数的是本次输出的行，不是文件里已存在的），
# 所以在同一个仓库里重跑一次会追加**第二份 A.1–A.17**；而计划里已经写着
# 「A.15 作废并指向 cc6e2c0」这类批注——重复的旧版本会跟着复活，把修好的
# 缺陷重新变成"可照抄的源码"。
# 另一层：它的输入 `_smoke/m3-frontend-probe/` 在 gitignore 里，**干净 clone 下
# 根本跑不起来**——所以它在本仓库里剩下的唯一作用就是"能搞坏计划"。
existing = PLAN.read_text(encoding="utf-8")
if "## 附录 A" in existing:
    raise SystemExit(
        "计划里已经有附录 A 了。本脚本是一次性播种工具，不是幂等生成器：\n"
        "  再跑一次会追加第二份 A.1–A.17，把已作废的旧版本复活。\n"
        "  要重新生成，请先把计划里现有的附录整段删掉。\n"
        "  （T4/T5/T6 落地后，前端文件的权威来源已经是仓库里的 web/src/**，不是本脚本。）"
    )

with PLAN.open("a", encoding="utf-8") as f:
    f.write(section)
print(f"已追加 {len(FILES)} 个文件的完整源码，计划现在 {len(PLAN.read_text(encoding='utf-8').splitlines())} 行")
