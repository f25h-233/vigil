"""漏天补跑：把最近 N 天里缺的日报补出来。由 vigil-daily.cmd 在 daily 成功后调用。

为什么需要（真事，2026-09-21）：Windows 任务计划的补跑（StartWhenAvailable）
  只补**最近一次错过的**触发。机器连关几天再开，中间那些天的窗口就直接
  跳过——2026-09-19 的日报就是这么永久缺掉的，而它那天的 125 条消息一直
  躺在库里（digests 表从 09-18 直接跳到 09-20，中间空了一格）。

为什么放在脚本层而不是 `vigil daily` 里：daily 那条链被测试锁住
  （tests/test_daily.py 等）；补漏是一层运维兜底，不该改变已测行为。

口径：
  · 只看「昨天」往前数 LOOKBACK_DAYS 天——今天不做（窗口还没走完，
    由明天的 daily 负责）；
  · 「缺」= docs/digests/<日期>.md 不存在。文件集合与库里 digests 表的
    窗口集合相等是本项目的既成不变量（别在这里记条数，记关系式）；
  · 补一天 = `vigil digest --date <日期>`——export/refine 刚在同一个 .cmd
    里跑过，数据已就位，不需要重跑；空白日不调模型，约 0 成本；
  · 幂等：已有日报的那天永远跳过；补过的天再跑一遍什么都不会发生。

退出码：0 = 全部补齐或本来就齐；1 = 有真失败（已写 LAST-ERROR.txt）。
  子进程退出码 2（锁被占）不算失败——那是「另一个实例在跑」的既有语义
  （见 docs/SETUP-自动化.md 的退出码表），跳过继续。
"""

from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIGESTS = REPO / "docs" / "digests"

# 往回看几天。「会关机的笔记本」与「补跑烧模型调用」之间的折中；
# 改这一个常量即可。
LOOKBACK_DAYS = 7


def missing_days(today: dt.date, lookback: int = LOOKBACK_DAYS) -> list[dt.date]:
    """从昨天往前数 lookback 天里没有日报文件的那些天（按时间正序）。"""
    days = [today - dt.timedelta(days=i) for i in range(1, lookback + 1)]
    return [d for d in reversed(days) if not (DIGESTS / f"{d:%Y-%m-%d}.md").is_file()]


def main() -> int:
    from vigil import logs

    logs.setup()
    todo = missing_days(dt.date.today())
    if not todo:
        logs.emit(f"[补漏] 最近 {LOOKBACK_DAYS} 天无缺档")
        return 0

    stamps = "、".join(f"{d:%Y-%m-%d}" for d in todo)
    logs.emit(f"[补漏] 发现 {len(todo)} 天缺日报，开始补：{stamps}")
    for day in todo:
        stamp = f"{day:%Y-%m-%d}"
        rc = subprocess.run(
            ["uv", "run", "vigil", "digest", "--date", stamp],
            cwd=REPO,
        ).returncode
        if rc == 2:
            logs.emit(f"[补漏] {stamp} 跳过：有另一个实例在跑（退出码 2）")
            continue
        if rc != 0:
            logs.write_last_error(
                f"漏天补跑失败：{stamp} 的日报没补出来（vigil digest 退出码 {rc}）。"
                f" 手动复现：cd {REPO} && uv run vigil digest --date {stamp}"
            )
            return 1
        logs.emit(f"[补漏] {stamp} 已补出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
