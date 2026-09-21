"""vigil serve 的监督循环：崩了就重启，连续 N 次才放弃。

为什么不在 .cmd 里写重试循环（第一版那么写的，**实测失败**）：
  cmd 的 label/goto 会对**正在执行的文件**逐字节重读——文件被改、或
  多实例叠加时行为无法推理；`>>` 重定向在跨进程争用时打不开文件只会往
  stderr 报一句，而任务计划把 stderr 丢弃 ⇒ 失败无声。2026-09-21 实测：
  重试循环一次都没触发过，而日志里连"exited with"标记都没写。
  这些不是理论，是现场。

为什么不用任务计划自带的 RestartOnFailure：**实测无效**——杀进程后任务
  如实记了失败（结果 1），过了重启间隔的 2.5 倍时间也没有任何重启；旧
  引擎的重启只覆盖"任务起不来"，不覆盖"action 退出非零"。详见
  scripts/register-serve-task.ps1 的 .DESCRIPTION 第 3 条。

口径（与任务计划/`.cmd` 的分工）：
  · 子进程退出码 0 = 服务器正常结束（设计上不该发生）→ 监督器也退 0，
    不再拉起；
  · 非 0 → 记一行、等 WAIT_SECONDS 秒、重启；连续 MAX_RESTARTS 次后放弃，
    以 1 退出（任务计划记为失败，人去读 data/logs/vigil-serve.log）。
  · "连续"是字面义：中间只要有一次活过 RUNNING_GRACE 秒，计数归零——
    否则一台常年开机的机器上，每周崩一次的服务会在第 5 周被放弃。
    ⚠️ 这条是行为的一部分，别当成可以"简化"掉。
  · **不写 LAST-ERROR.txt**：那文件的契约只属 `vigil daily`（见
    docs/SETUP-自动化.md §六）。网页服务的失败记录就是 vigil-serve.log。

只依赖标准库（不需要 import vigil）：监督器是外壳的最外圈，它比包本身
  更早启动、更晚退出，不能反过来依赖包能 import。
"""

from __future__ import annotations

import datetime as dt
import msvcrt
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "data" / "logs" / "vigil-serve.log"
LOCK = REPO / "data" / "logs" / "vigil-serve.lock"

MAX_RESTARTS = 5
WAIT_SECONDS = 60
RUNNING_GRACE = 300  # 活过 5 分钟 = 这一次不算"崩溃循环"

SERVE_CMD = ["uv", "run", "vigil", "serve", "--host", "127.0.0.1", "--port", "8787"]


def acquire_single_instance():
    """拿跨进程单实例锁（Windows 字节范围锁）。拿不到返回 None。

    为什么必须有（实测教训 2026-09-21）：`schtasks /end` 结束任务实例时，
    深层子进程（cmd → uv → python → uv → python）可能变成**孤儿**继续活着。
    现场出现过两条监督链轮流抢 8787：赢的占着端口，输的每 60 秒撞一次
    bind 10048，还会烧光 5 次机会留下一条假的"放弃"记录。

    为什么用字节范围锁而不是"写 PID 文件再探测存活"：操作系统在进程
    死亡时**自动释放**锁 —— 不存在"陈旧锁"这个状态，也就没有清理竞态。
    锁文件里的 PID 只供人看，判断唯一性靠锁本身。

    ⚠️ 返回值必须被调用方持有到进程结束：文件对象一被 GC 关闭，锁就没了。
    """
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = LOCK.open("a+b")
    try:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(f"{os.getpid()}\n".encode("utf-8"))
    fh.flush()
    return fh


def note(line: str) -> None:
    """往 serve 日志追加一行。开-写-关，不长期持句柄。

    ⚠️ 与子进程的 stdout 句柄（`subprocess.run` 期间一直开着）并存是同
    设计的一部分：CPython 的 open 走完整共享模式（FILE_SHARE_READ |
    WRITE | DELETE），两个句柄互不排斥。cmd 的 `>>` 没有这个保证，这正是
    循环从 .cmd 搬到这里的原因之一。
    """
    LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(f"[{stamp}] {line}\n")


def main() -> int:
    lock = acquire_single_instance()
    if lock is None:
        note("另一个监督器已在运行（单实例锁被占），本实例退出")
        return 0
    restarts = 0
    while True:
        started = time.monotonic()
        note("启动 vigil serve（127.0.0.1:8787）")
        with LOG.open("a", encoding="utf-8", newline="\n") as fh:
            rc = subprocess.run(
                SERVE_CMD, cwd=REPO, stdout=fh, stderr=subprocess.STDOUT
            ).returncode
        alive = time.monotonic() - started

        if rc == 0:
            note("serve 正常退出（rc=0），监督器随之结束")
            return 0

        if alive >= RUNNING_GRACE:
            restarts = 0
        restarts += 1
        note(f"serve 退出 rc={rc}，本次存活 {alive:.0f} 秒（连续第 {restarts} 次）")

        if restarts >= MAX_RESTARTS:
            note(
                f"连续 {MAX_RESTARTS} 次崩溃，监督器放弃。手动排查："
                f" cd {REPO} && uv run vigil serve --host 127.0.0.1 --port 8787"
            )
            return 1

        note(f"{WAIT_SECONDS} 秒后重启……")
        time.sleep(WAIT_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
