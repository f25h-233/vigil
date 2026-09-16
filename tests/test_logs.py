"""日志模块的测试。

⚠️ 每一条都 monkeypatch `logs.LOG_DIR`，绝不写仓库的 `data/logs/`。
`LOG_DIR` **必须在函数体里现读**，不能在 import 时算好冻进默认参数——
否则 monkeypatch 换不掉它，这些测试就会去写真实目录（而且是**静默地**写）。
"""

from __future__ import annotations

import datetime as dt
import logging
import pathlib

import pytest

from vigil import logs


@pytest.fixture
def logdir(tmp_path, monkeypatch):
    """把日志目录换到临时目录，并复位幂等标志。"""
    d = tmp_path / "logs"
    monkeypatch.setattr(logs, "LOG_DIR", d)
    logs.reset()
    yield d
    logs.reset()


def test_setup_creates_dir_and_writes_a_line(logdir):
    logs.setup()
    logs.emit("你好")
    # emit 会真的写文件——必须 flush 过，所以不 close 也读得到
    text = logs.log_path().read_text(encoding="utf-8")
    assert "你好" in text


def test_setup_is_idempotent_no_duplicate_lines(logdir):
    """⭐ 重复 setup 不许叠加 handler。

    叠了的话同一行会出现两遍——而「日志里同一句话出现三次」会让人
    以为跑了三次。这是幂等的硬理由，不是洁癖。
    """
    logs.setup()
    logs.setup()
    logs.setup()
    logs.emit("只此一行")
    text = logs.log_path().read_text(encoding="utf-8")
    assert text.count("只此一行") == 1


def test_emit_prints_verbatim_without_timestamp(logdir, capsys):
    """⭐ stdout 上是**一字不改的原文**。

    这是与既有 capsys 测试的契约：`tests/test_digest.py` 里约 10 处
    用 `capsys.readouterr().out` 读 CLI 输出。加时间戳前缀会让它们集体变红。
    """
    logs.setup()
    logs.emit("完成：扫描 3 条")
    out = capsys.readouterr().out
    assert out == "完成：扫描 3 条\n", "stdout 必须是原文，不许有时间戳/级别前缀"


def test_file_line_has_timestamp_and_level(logdir):
    logs.setup()
    logs.emit("有事发生")
    line = logs.log_path().read_text(encoding="utf-8").strip()
    assert line.endswith("INFO  有事发生"), line
    # 前缀是 "YYYY-MM-DD HH:MM:SS "
    assert len(line) > 19 and line[4] == "-" and line[13] == ":", line


def test_every_record_is_flushed_immediately(logdir):
    """⭐ 每条记录都落盘，不靠 close。

    无人值守下进程被强杀时，还留在缓冲区里的恰好是唯一能解释崩溃的那几行。
    ⚠️ 这条测的是 `logging.FileHandler` 继承自 `StreamHandler.emit` 的行为
    （它末尾调 `self.flush()`）——**不是**我们自己写的逻辑。所以它是一条
    「换 handler 类型会红」的哨兵：哪天有人把 DailyFileHandler 换成
    BufferingHandler 之类，这条必须红。
    """
    logs.setup()
    logs.emit("崩前最后一句")
    # 注意：没有 close()、没有 shutdown()
    assert "崩前最后一句" in logs.log_path().read_text(encoding="utf-8")


def test_log_path_uses_the_day(logdir):
    d = dt.date(2026, 9, 17)
    assert logs.log_path(d).name == "vigil-2026-09-17.log"


def test_clear_then_write_last_error(logdir):
    logs.clear_last_error()
    assert not (logdir / logs.LAST_ERROR_NAME).exists()
    logs.setup()
    logs.emit("出事了")
    p = logs.write_last_error("refine 第 3 批失败")
    assert p == logdir / logs.LAST_ERROR_NAME
    body = p.read_text(encoding="utf-8")
    assert "refine 第 3 批失败" in body
    assert "出事了" in body, "spec §4.8 要求的是「日志尾部」——尾部要真的在"


def test_write_last_error_survives_missing_log_file(logdir):
    """当天日志不存在时也必须写得出 LAST-ERROR.txt。

    这是 .cmd 兜底路径的形状：Python 在写日志之前就失败了。
    """
    logs.clear_last_error()
    p = logs.write_last_error("启动即失败")
    assert "启动即失败" in p.read_text(encoding="utf-8")


def test_prune_only_deletes_our_own_filename_shape(logdir):
    """⭐ 轮转只认 `vigil-YYYY-MM-DD.log`。

    用宽 glob（`*.log` / `*`）的话，日后往这个目录放任何东西都会被无声吃掉
    ——而「日志轮转把别的东西删了」是最难查的一类事故。
    """
    logdir.mkdir(parents=True, exist_ok=True)
    today = dt.date(2026, 9, 17)
    old = logs.log_path(today - dt.timedelta(days=40))
    keep = logs.log_path(today - dt.timedelta(days=3))
    foreign = logdir / "important.log"
    errfile = logdir / logs.LAST_ERROR_NAME
    for f in (old, keep, foreign, errfile):
        f.write_text("x", encoding="utf-8")

    deleted = logs.prune_old_logs(today=today)

    assert deleted == [old.name]
    assert not old.exists()
    assert keep.exists() and foreign.exists() and errfile.exists()


def test_prune_keeps_files_at_the_boundary(logdir):
    logdir.mkdir(parents=True, exist_ok=True)
    today = dt.date(2026, 9, 17)
    edge = logs.log_path(today - dt.timedelta(days=logs.KEEP_DAYS))
    edge.write_text("x", encoding="utf-8")
    assert logs.prune_old_logs(today=today) == [], "恰好第 KEEP_DAYS 天的不该删"
    assert edge.exists()


def test_prune_tolerates_missing_dir(logdir):
    assert logs.prune_old_logs() == []      # logdir 还没建
