"""每日管线的编排测试。

⚠️ 三个阶段全部被 monkeypatch 成假的——本文件**不调模型、不碰真库**。
测的是编排语义：失败判据、跳过规则、最坏状态、账目。
"""

from __future__ import annotations

import pathlib

import pytest

from vigil import daily


class _FakeConfig:
    """一个只带 ``output_db`` 的假配置。

    ⚠️ **偏离 brief（见报告 §偏差 D1）**：brief 的测试里写的是
    ``config=object()``，那样**一条都跑不过**——`daily.run()` 要读
    ``config.output_db``（进度文案一处、refine/digest 的 ``db_path`` 两处），
    而 `object()` 没有这个属性；进度文案那一处还在 `try` **外面**，会直接
    AttributeError 掀掉整轮（不是被记成阶段失败）。反过来，用真的 `Config`
    会去读 ``config/*.toml``——那是「测试不碰真库/真配置」要避免的。
    所以用这个两行替身：它证明的是「config 只是被原样传递的道具」。
    """

    output_db = pathlib.Path("unused.db")


def _export_stats(**over):
    from vigil.export import ExportStats

    s = ExportStats()
    s.per_group = over.get("per_group", [(1, "群甲", 10)])
    s.failed_groups = over.get("failed_groups", [])
    return s


def _refine_stats(**over):
    from vigil.refine import RefineStats

    s = RefineStats()
    s.scanned = over.get("scanned", 100)
    s.sent_messages = over.get("sent", 10)
    s.candidates = over.get("candidates", 10)
    s.errors = over.get("errors", [])
    return s


def _digest_stats(**over):
    from vigil.digest import DigestStats

    s = DigestStats(day="2026-09-16", window_from=0, window_to=1)
    s.errors = over.get("errors", [])
    return s


@pytest.fixture
def wired(monkeypatch):
    """把三阶段换成可编程的假的，并记录调用顺序。"""
    calls: list[str] = []
    plan: dict[str, object] = {}

    def fake_export(config, key, *, on_progress=print):
        calls.append("export")
        r = plan.get("export")
        if isinstance(r, BaseException):
            raise r
        return r if r is not None else _export_stats()

    def fake_refine(config, **kw):
        calls.append("refine")
        r = plan.get("refine")
        if isinstance(r, BaseException):
            raise r
        return r if r is not None else _refine_stats()

    def fake_digest(config, **kw):
        calls.append("digest")
        r = plan.get("digest")
        if isinstance(r, BaseException):
            raise r
        return r if r is not None else _digest_stats()

    monkeypatch.setattr(daily.export_mod, "export", fake_export)
    monkeypatch.setattr(daily.refine_mod, "refine", fake_refine)
    monkeypatch.setattr(daily.digest_mod, "digest", fake_digest)
    return calls, plan


def test_happy_path_runs_all_three_in_order(wired):
    calls, _ = wired
    report = daily.run(config=_FakeConfig(), key="k", llm_key="l",
                       day="2026-09-16", on_progress=lambda *_: None)
    assert calls == ["export", "refine", "digest"]
    assert report.ok
    assert report.last_error == ""
    assert report.deadline == "2026-09-16"


def test_export_failure_skips_digest_but_still_refines(wired):
    """⭐ export 失败 ⇒ **跳过 digest**，但 refine 照跑。

    为什么跳过 digest：export 失败意味着 `messages` 不完整，于是日报那句
    「当天 N 条消息」可能读起来像"这天很安静"，而其实是"没读进来"——
    那是这个项目反复抓到的同一句假话。refine 照跑是因为存量消息仍值得抽。
    """
    calls, plan = wired
    plan["export"] = _export_stats(failed_groups=[(7, "读不到")])
    report = daily.run(config=_FakeConfig(), key="k", llm_key="l",
                       day="2026-09-16", on_progress=lambda *_: None)

    assert calls == ["export", "refine"], "digest 必须被跳过"
    assert not report.ok
    assert "export" in report.last_error
    skipped = [s for s in report.stages if s.name == "digest"]
    assert skipped and not skipped[0].ok and skipped[0].skipped_reason


def test_export_raises_is_also_a_failure(wired):
    calls, plan = wired
    plan["export"] = RuntimeError("QQ 库路径没了")
    report = daily.run(config=_FakeConfig(), key="k", llm_key="l",
                       day="2026-09-16", on_progress=lambda *_: None)
    assert calls == ["export", "refine"]
    assert not report.ok
    assert "QQ 库路径没了" in report.last_error


def test_refine_failure_does_not_skip_digest(wired):
    """⭐ refine 有错 ⇒ digest **照跑**。

    日报自己的覆盖率检查会说出「仅抽取了 X/Y」——那是它在说自己有资格说的话。
    替它跳过，等于把一个它本来能诚实表达的部分结果也丢掉。
    """
    calls, plan = wired
    plan["refine"] = _refine_stats(errors=["第 2 批失败: 429"])
    report = daily.run(config=_FakeConfig(), key="k", llm_key="l",
                       day="2026-09-16", on_progress=lambda *_: None)
    assert calls == ["export", "refine", "digest"]
    assert not report.ok
    assert "429" in report.last_error


def test_digest_failure_is_reported(wired):
    _, plan = wired
    plan["digest"] = _digest_stats(errors=["模型调用失败: 超时"])
    report = daily.run(config=_FakeConfig(), key="k", llm_key="l",
                       day="2026-09-16", on_progress=lambda *_: None)
    assert not report.ok
    assert "超时" in report.last_error


def test_default_day_is_yesterday(wired):
    from vigil.digest import yesterday

    report = daily.run(config=_FakeConfig(), key="k", llm_key="l",
                       on_progress=lambda *_: None)
    assert report.deadline == yesterday()


def test_progress_goes_through_the_given_sink(wired):
    lines: list[str] = []
    daily.run(config=_FakeConfig(), key="k", llm_key="l",
              day="2026-09-16", on_progress=lines.append)
    text = "\n".join(lines)
    assert "export" in text and "refine" in text and "digest" in text
    assert "2026-09-16" in text


# ─────────────────────────────────────────────────────────────────────────
# 以下四条是**补的**（偏离 brief，见报告 §偏差 D2）。
#
# 理由：brief 的 Step 5 变异表 M2 说「把 refine 阶段的 try/except 去掉会
# 变红」，但 brief 的测试文件里**没有任何一条**把 `plan["refine"]` 设成异常
# （只设过 `plan["export"]` 与 `plan["digest"]`）——按 M2 变异，整份测试**全绿**，
# 那是一条会假绿的"反证"。同理 digest 抛异常的路径也没被覆盖。
# 另外 T1 把 `logs.emit` 钉成「写不进去就抛 OSError」，那条契约在编排层
# 的行为也必须钉住（§8.5）。
# ─────────────────────────────────────────────────────────────────────────


def test_refine_raises_is_recorded_and_digest_still_runs(wired):
    """refine **抛异常**（不只是 errors 非空）⇒ 记成阶段失败，digest 照跑。"""
    calls, plan = wired
    plan["refine"] = RuntimeError("预算护栏崩了")
    report = daily.run(config=_FakeConfig(), key="k", llm_key="l",
                       day="2026-09-16", on_progress=lambda *_: None)
    assert calls == ["export", "refine", "digest"], "refine 抛异常不该拦下 digest"
    assert not report.ok
    assert "预算护栏崩了" in report.last_error
    stage = [s for s in report.stages if s.name == "refine"]
    assert stage and not stage[0].ok and "预算护栏崩了" in stage[0].detail


def test_digest_raises_is_recorded(wired):
    """digest 抛异常（不只是 errors 非空）⇒ 记成阶段失败，不掀掉 run()。"""
    _, plan = wired
    plan["digest"] = RuntimeError("落文件失败：磁盘满")
    report = daily.run(config=_FakeConfig(), key="k", llm_key="l",
                       day="2026-09-16", on_progress=lambda *_: None)
    assert not report.ok
    assert "磁盘满" in report.last_error


def test_emit_failure_inside_a_stage_is_a_stage_failure(wired, monkeypatch):
    """§8.5：`emit` 在阶段内部炸 ⇒ 那个阶段记成**失败**，绝不被吞成成功。

    `emit`（= on_progress 或 `logs.emit`）写不进日志时抛 OSError 是 Task 1
    钉死的契约：无人值守下退出码是唯一还活着的信号，「日志有洞但 exit 0」
    正是 M4 要消灭的形状。所以这条测试要证明的是：OSError 传到 `run()`
    的阶段级 `except Exception` 后，`RunReport.ok` 必须为假。
    """
    calls, plan = wired
    boom = "[probe] 这次写日志会炸"

    def exploding_export(config, key, *, on_progress=print):
        calls.append("export")
        on_progress(boom)          # ← 模拟 export 内部的一次 emit
        return _export_stats()

    monkeypatch.setattr(daily.export_mod, "export", exploding_export)

    def flaky(msg: str) -> None:
        if msg == boom:
            raise OSError("日志盘满")
        # 其余的 emit 照常——否则阶段失败话术自己也会炸，测试就测不到"记账"

    report = daily.run(config=_FakeConfig(), key="k", llm_key="l",
                       day="2026-09-16", on_progress=flaky)

    assert not report.ok, "emit 抛 OSError 被吞成了成功——正是 §8.5 禁止的形状"
    export_stage = [s for s in report.stages if s.name == "export"]
    assert export_stage and not export_stage[0].ok
    assert "日志盘满" in export_stage[0].detail
    assert "日志盘满" in report.last_error, "失败必须留在账上"
    assert calls == ["export", "refine"], "export 失败 ⇒ digest 跳过（与 M1 同一判据）"


def test_broken_emit_never_returns_a_success_report(wired):
    """§8.5：日志从第一行就写不进去 ⇒ `run()` **直接抛**，绝不返回成功账目。

    这是 `run()` docstring 里"任何阶段失败都不抛"的**唯一例外**：emit 坏掉
    不是阶段失败，是"本次运行的记录没了"。这里不许吞（吞掉的话调用方会拿到
    一份 `ok=True` 的账目去写"全部成功"，而磁盘上一个字都没有）——抛出去由
    `cmd_daily` 的顶层兜底变成**非零退出码**，那是无人值守下唯一还活着的信号。
    """
    calls, plan = wired

    def dead_emit(msg: str) -> None:
        raise OSError("日志目录没了")

    with pytest.raises(OSError):
        daily.run(config=_FakeConfig(), key="k", llm_key="l",
                  day="2026-09-16", on_progress=dead_emit)
    assert calls == [], "第一行 emit 就炸了，不该有任何阶段开跑"
