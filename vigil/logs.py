"""日志：控制台原文 + 按日轮转文件 + 失败留痕。

为什么必须有（spec §4.8；Step Zero 0.7 明确移入 M4）：
在此之前全项目**零日志基础设施**——`grep -rn "import logging" vigil/` 零命中，
60 处 `print(` 全在 `cli.py`，三个库模块的进度回调默认值就是内建 `print`。
而 print 到 stdout 在任务计划程序下**没有任何落点**：任务计划不保存任务的
输出，挂机跑一夜，第二天只剩「退出码是多少」这一条信息。

四条设计决定（每条都有代价，写在这里免得日后被当成"可以优化掉"）：

1. **按日一个文件** `vigil-YYYY-MM-DD.log`，不是单文件轮转。按日命名让
   「昨天发生了什么」变成一个**文件名**问题；单文件轮转则要么处理"写到
   一半改名"，要么需要额外的句柄重开逻辑，且昨天的内容会被滚走。

2. **`emit()` 先 print 原文、再写日志**，顺序不能反。stdout 上必须是
   **一字不改的原文**（没有时间戳前缀），因为既有测试用 capsys 读它
   （`tests/test_digest.py` 里约 10 处）。反过来做的代价是 M4 顺带重写
   一整套 CLI 输出测试——那是范围蔓延。

3. **不接管 stderr、不装 excepthook。** Python 未捕获异常的 traceback 由
   解释器直接写 stderr，绕过 logging；硬要接管需要重定向或 excepthook，
   那是另一类脆。所以失败路径**同时**依赖三件东西：`LAST-ERROR.txt`
   （本模块写）、退出码（CLI 返回）、stderr（人工跑时可见，任务计划丢弃）。

4. **文件 handler 每条记录都 flush**——这不是我们写的，是
   `logging.StreamHandler.emit` 自带的行为（它末尾就调 `self.flush()`，
   `FileHandler` 继承它）。所以**不包一层自以为是的子类**，而是写一条
   断言该行为的测试（`test_every_record_is_flushed_immediately`）：
   哪天有人换了 handler 类型，那条测试要能红。为什么在乎——无人值守下
   进程被强杀时，还留在缓冲区里的恰好是唯一能解释崩溃的那几行。

⚠️ `LOG_DIR` 一律**在函数体里现读**，不许在 import 时算好冻进默认参数。
   测试用 `monkeypatch.setattr(logs, "LOG_DIR", tmp_path)` 换掉它；冻住的
   话那些测试会去写**真实的** `data/logs/`，而且是静默地写。
   （`vigil/api.py` 的 `WEB_DIST` 是同一条纪律，那里写着原因。）
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import pathlib
import re

from .config import REPO_ROOT

LOG_DIR = REPO_ROOT / "data" / "logs"
LAST_ERROR_NAME = "LAST-ERROR.txt"

# 日志保留天数。spec §7 R4 记着「磁盘紧张（C: 7.8 GB / D: 29 GB）」，
# 而按当前体量（每天几千行、每行百字节）30 天是几 MB 量级。
KEEP_DAYS = 30

# LAST-ERROR.txt 里附多少行日志尾部。spec §4.8 的原文要求是「日志尾部」——
# 40 行足够覆盖一次 daily 的全部阶段摘要 + 出错前后的上下文。
TAIL_LINES = 40

_LOGGER_NAME = "vigil"
_configured = False

_LOG_NAME_RE = re.compile(r"^vigil-(\d{4})-(\d{2})-(\d{2})\.log$")


def log_path(day: dt.date | None = None) -> pathlib.Path:
    """当天的日志文件路径。`LOG_DIR` 现读（见模块 docstring 末尾）。"""
    day = day or dt.date.today()
    return LOG_DIR / f"vigil-{day:%Y-%m-%d}.log"


class DailyFileHandler(logging.FileHandler):
    """按日命名的文件 handler，**跨零点自动换文件**。

    `logging.FileHandler` 在构造时就把文件名定死了。一个从 23:50 跑到
    00:20 的 `refine` 会把第二天的事件全写进前一天的文件里，于是
    「日志是哪天跑的」这件事就对不上了——而无人值守下日志正是唯一的记录。
    """

    def __init__(self, directory: pathlib.Path) -> None:
        self._dir = directory
        self._day = dt.date.today()
        super().__init__(self._name(), encoding="utf-8", delay=False)

    def _name(self) -> str:
        return str(self._dir / f"vigil-{self._day:%Y-%m-%d}.log")

    def emit(self, record: logging.LogRecord) -> None:
        today = dt.date.today()
        if today != self._day:
            self._day = today
            self.acquire()
            try:
                if self.stream:
                    self.stream.close()
                    self.stream = None
                self.baseFilename = os.path.abspath(self._name())
                self.stream = self._open()
            finally:
                self.release()
        super().emit(record)


def setup(*, level: int = logging.INFO) -> logging.Logger:
    """装好文件 handler，返回 vigil 的 logger。**幂等**。

    幂等的硬理由：`vigil daily` 要先配一次，若它内部调的三个阶段各自再配
    一次，同一行就会在文件里出现三遍——而「日志里同一句话出现三次」会让
    人以为跑了三次。

    只装文件 handler，**不装控制台 handler**：人看的输出归 `emit()` 管
    （见模块 docstring 第 2 条），两条路各写各的才不会有先后与重复问题。
    """
    global _configured

    logger = logging.getLogger(_LOGGER_NAME)
    if _configured:
        return logger

    logger.setLevel(level)
    # 不向 root 冒泡：否则任何第三方库调 basicConfig 都会让我们多印一份。
    logger.propagate = False

    directory = LOG_DIR          # 现读，见模块 docstring 末尾
    directory.mkdir(parents=True, exist_ok=True)

    handler = DailyFileHandler(directory)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-5s %(message)s",
                          datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)

    _configured = True
    return logger


def emit(message: str) -> None:
    """人看的原文走 stdout，日志留一份带时间戳的。CLI 与 daily 的唯一输出口。

    ⚠️ **先 print 再 log，顺序不能反**（模块 docstring 第 2 条）。
    """
    print(message)
    logging.getLogger(_LOGGER_NAME).info(message)


def reset() -> None:
    """拆掉已装的 handler 并复位幂等标志。**只给测试用**。

    生产代码里没有任何调用点，因为没有「该把日志关了」的时刻。
    """
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    _configured = False


def clear_last_error() -> None:
    """开跑前清掉上一次的 LAST-ERROR.txt。

    ⚠️ 必须在**开跑时**清，不是成功时清：成功时才清的话，一个启动即崩
    （连本函数都没跑到）的进程会留下上一次的旧错误，被读成"这次又失败了"。
    开跑时清 ⇒ 「文件存在」⟺「本次运行失败过」。
    """
    try:
        (LOG_DIR / LAST_ERROR_NAME).unlink()
    except FileNotFoundError:
        pass


def _log_tail(lines: int) -> str:
    """当天日志的最后 N 行。读不到就返回空串（不抛）。"""
    try:
        text = log_path().read_text(encoding="utf-8")
    except OSError:
        return ""
    rows = text.splitlines()
    return "\n".join(rows[-lines:])


def write_last_error(message: str, *, tail_lines: int = TAIL_LINES) -> pathlib.Path:
    """把失败摘要 + 日志尾部写进 LAST-ERROR.txt（spec §4.8 的原文要求）。

    ⚠️ 尾部从**当天的日志文件**读，不从内存缓冲读——内存里只有本进程写的行，
    而这条路径**本来就要覆盖"失败发生在别的进程里"**（.cmd 的兜底分支）。
    """
    directory = LOG_DIR          # 现读
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LAST_ERROR_NAME
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = f"[{stamp}] {message}\n"
    tail = _log_tail(tail_lines)
    if tail:
        body += f"\n--- 日志尾部（{pathlib.Path(log_path()).name}）---\n{tail}\n"
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


def prune_old_logs(*, keep_days: int = KEEP_DAYS,
                   today: dt.date | None = None) -> list[str]:
    """删掉 `keep_days` 天前的日志文件，返回被删的文件名。

    ⚠️ **只认 `vigil-YYYY-MM-DD.log` 这个形状**，不用宽 glob。用 `*.log`
    的话，日后往这个目录放任何东西都会被无声吃掉——而「日志轮转把别的
    东西删了」是最难查的一类事故。`LAST-ERROR.txt` 同理，不在删除范围。

    边界取「**严格早于** today - keep_days」：恰好第 keep_days 天的保留。
    """
    directory = LOG_DIR          # 现读
    if not directory.is_dir():
        return []
    cutoff = (today or dt.date.today()) - dt.timedelta(days=keep_days)

    removed: list[str] = []
    for p in sorted(directory.iterdir()):
        m = _LOG_NAME_RE.match(p.name)
        if not m or not p.is_file():
            continue
        try:
            day = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue          # 文件名像但日期非法（如 2026-13-45），不碰它
        if day < cutoff:
            try:
                p.unlink()
            except OSError:
                continue      # 被别的进程占着就跳过，删日志失败不该掀掉整轮
            removed.append(p.name)
    return removed
