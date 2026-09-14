"""变异反证：验证思考开关相关的测试真的会红。

教训（本文件存在的理由，写在这里免得下次再犯）：上一版用 shell 写
`cp A /tmp/x || cp A ./x` 做备份，git bash 下 /tmp 存在，`||` 分支没跑，
还原时 `cp ./x` 直接失败——**源码被留在变异状态**。所以改成 Python 的
try/finally，还原不靠运气。

不是产品代码。跑法：
    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe _probe_mutation.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# (文件, 变异说明, 原文, 变异后, 期望变红的测试名)
MUTATIONS = [
    (
        "vigil/llm.py",
        "永远发送 enable_thinking",
        "    if cfg.enable_thinking is not None:",
        "    if True:",
        "test_omits_thinking_field_by_default",
    ),
    (
        "vigil/llm.py",
        "永不发送 enable_thinking",
        "    if cfg.enable_thinking is not None:",
        "    if False:",
        "test_sends_thinking_false_when_configured",
    ),
    (
        "vigil/refine.py",
        "参数接了但没通电（丢掉 enable_thinking）",
        "            api_key=api_key, model=model, enable_thinking=enable_thinking",
        "            api_key=api_key, model=model",
        "test_refine_passes_thinking_switch_to_llm",
    ),
]


def run_tests() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q", "--no-header"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    originals = {f: Path(f).read_text(encoding="utf-8") for f, *_ in MUTATIONS}
    failures = 0
    try:
        for path, label, old, new, expect_red in MUTATIONS:
            if old not in originals[path]:
                print(f"✗ [{path}] 变异点没找到：{old!r} —— 测试无效，先修脚本")
                failures += 1
                continue
            Path(path).write_text(originals[path].replace(old, new), encoding="utf-8")
            code, out = run_tests()
            red = [ln for ln in out.splitlines() if ln.startswith("FAILED")]
            caught = code != 0 and any(expect_red in ln for ln in red)
            print(f"{'✓' if caught else '✗ 没抓到（假绿！）'} {label} → 期望 {expect_red} 变红")
            if not caught:
                failures += 1
                print(f"      实际输出：\n{out[-500:]}")
    finally:
        for path, text in originals.items():
            Path(path).write_text(text, encoding="utf-8")
        print("已还原全部源文件（finally 保证）")

    code, out = run_tests()
    print(f"还原后测试：{'全过' if code == 0 else '仍失败！'}")
    if code != 0:
        print(out[-800:])
        failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
