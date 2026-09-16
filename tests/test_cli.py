"""CLI 层的退出码与接线。

⚠️ 退出码是 M4 的**核心交付**：任务计划就只能看见这一个数。所以这里
每一条都在钉「什么时候返回几」，而不是钉输出文字。

范式抄 `tests/test_digest.py::cli_env`（那一段守的是同一个契约的 digest 分支）：
用 `cli.main([...])` 驱动，把 `_load_config_only` / `_require_export_db` /
`load_llm_key` 换成替身，**一件都不许落到真实环境**（真库、真日志目录、真的锁）。

⚠️ `load_llm_key` 在 `cmd_refine` / `cmd_digest` 里是**函数体内** import 的，
所以只能打在 `vigil.config` 上，打在 `vigil.cli` 上不生效；`cmd_daily` 用的是
模块级名字，两处都要接（见 `daily_env`）。
"""

from __future__ import annotations

import pytest

from vigil import cli


class _null_ctx:
    """假上下文管理器：`with` 进去什么都不做、什么都不锁。"""

    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return None


def _exit_code_of(argv: list[str]) -> int | str:
    """跑一次 CLI，把「异常上抛」折算成退出码。

    ⚠️ 这里**只折算、不吞**：未捕获的异常本身就是「非零退出」的一种形态
    （`__main__` 走 `sys.exit(main())`，解释器对未捕获异常一律非零退出），
    与 `return 1` 是同一个契约的两种实现（计划 §8.5 第 3 条）。
    唯一被这条判据拒绝的是「抛了却仍然报成功」。
    """
    try:
        return cli.main(argv)
    except SystemExit as exc:
        return exc.code if exc.code is not None else 0
    except Exception:  # noqa: BLE001 — 见 docstring：上抛 == 非零退出
        return 1


def _config(tmp_path):
    from vigil.config import Config, Group

    return Config(
        qq_db_dir=tmp_path / "qq",
        output_db=tmp_path / "export.db",
        groups=(Group(id=100, name="班级群"), Group(id=200, name="新生群")),
    )


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    """把 export / refine / digest 的外部依赖全接上（不含 `daily`，见 `daily_env`）。

    ⚠️ **锁的路径由 `conftest.py` 的 autouse 夹具统一挪到 `tmp_path`**
    （三个 `cmd_*` 现在各上一次锁，见 M4 审 F4）。本夹具不再自己换一次——
    换的是**路径**不是锁本身，真 `SingleInstance` 的拿锁/放锁逻辑照跑。
    """
    cfg = _config(tmp_path)
    monkeypatch.setattr(cli, "_load_or_die", lambda: (cfg, "k-db"))
    monkeypatch.setattr(cli, "_load_config_only", lambda: cfg)
    monkeypatch.setattr(cli, "_require_export_db", lambda config: tmp_path / "export.db")
    monkeypatch.setattr("vigil.config.load_llm_key", lambda *a, **k: "k-llm")
    return tmp_path


@pytest.fixture
def daily_env(monkeypatch, tmp_path):
    """把 `cmd_daily` 的外部依赖全接上——**不碰真实日志目录、不真加锁**。

    ⚠️ 配置与两个密钥**都要接**：`cmd_daily` 在加锁**之前**就要它们齐备，
    缺一个就会提前 `return 1`——于是那两条锁/失败的用例测到的其实是
    「没有密钥」，而不是它名字里说的那件事（而这台机器上 `.env` 恰好齐备时，
    测试又会悄悄地变成依赖真实环境）。
    """
    monkeypatch.setattr(cli, "load_config", lambda *a, **k: _config(tmp_path))
    monkeypatch.setattr(cli, "load_key", lambda *a, **k: "k-db")
    monkeypatch.setattr(cli, "load_llm_key", lambda *a, **k: "k-llm")
    monkeypatch.setattr("vigil.config.load_llm_key", lambda *a, **k: "k-llm")
    monkeypatch.setattr(cli.logs, "setup", lambda **kw: None)
    monkeypatch.setattr(cli.logs, "clear_last_error", lambda: None)
    monkeypatch.setattr(cli.logs, "prune_old_logs", lambda **kw: [])
    monkeypatch.setattr(cli.logs, "write_last_error", lambda *a, **kw: None)
    monkeypatch.setattr(cli.lock, "SingleInstance", _null_ctx)
    return tmp_path


# ── export：整群读不到 ⇒ 非零 ────────────────────────────────────


def test_export_returns_nonzero_when_a_group_could_not_be_read(cli_env, monkeypatch,
                                                               capsys):
    """⭐ export 有整群读不到 ⇒ 非零。

    实测旧实现（M4 规划期）：`cmd_export` 结尾无条件 `return 0`，
    即使它自己刚打了 `[失败] N 个群整群读不到`。任务计划看到的是成功。

    变异 M1（删掉 `if stats.failed_groups: return 1`）→ 本条红。
    """
    from vigil.export import ExportStats

    stats = ExportStats(
        per_group=[(100, "班级群", 12)],
        failed_groups=[(200, "新生群")],
    )
    monkeypatch.setattr("vigil.export.export", lambda *a, **kw: stats)

    rc = cli.main(["export"])

    assert rc != 0
    assert "失败" in capsys.readouterr().out


def test_export_returns_zero_when_every_group_was_read(cli_env, monkeypatch):
    """阳性对照：全都读到了就必须是 0。

    没有这一条的话，「无条件 `return 1`」也能让上面那条全绿——而它意味着
    每次成功导出都在报警，报警器很快就会被无视。
    """
    from vigil.export import ExportStats

    stats = ExportStats(per_group=[(100, "班级群", 12), (200, "新生群", 8)])
    monkeypatch.setattr("vigil.export.export", lambda *a, **kw: stats)

    assert cli.main(["export"]) == 0


def test_export_returns_zero_when_only_bad_pages(cli_env, monkeypatch):
    """坏页（`skipped_by_group`）**不算失败**——别把它并进失败里。

    那是 QQ 库的物理损坏：已知、非致命、同群其余消息不受影响，输出里
    已经照实报了。把它算成失败，等于让每一天都是"失败"。
    """
    from vigil.export import ExportStats

    stats = ExportStats(
        per_group=[(100, "班级群", 12)],
        skipped_by_group=[(200, "新生群", 3)],
    )
    monkeypatch.setattr("vigil.export.export", lambda *a, **kw: stats)

    assert cli.main(["export"]) == 0


def test_export_output_goes_through_logs_emit(cli_env, monkeypatch):
    """管线输出必须走 `logs.emit`（T1 契约：先 print 原文、再写日志）。

    变异「`logs.emit(` → `print(`」会让本条红——而现实中它意味着这几行只到
    stdout：任务计划下 stdout **没有落点**，跑完一夜等于什么都没说过。
    """
    from vigil.export import ExportStats

    seen: list[str] = []
    monkeypatch.setattr(cli.logs, "emit", seen.append)
    monkeypatch.setattr(
        "vigil.export.export",
        lambda *a, **kw: ExportStats(per_group=[(100, "班级群", 12)]),
    )

    cli.main(["export"])

    assert any("完成：1 个群，共 12 条消息" in m for m in seen)


# ── refine：有批次出错 ⇒ 非零（且汇总行仍在）────────────────────


def _refine_stats(**kw):
    from vigil.refine import RefineStats

    base = dict(
        scanned=100, discarded_local=60, candidates=44, sent_messages=40,
        batches_planned=2, batches=2, items_saved=7,
    )
    base.update(kw)
    return RefineStats(**base)


def test_refine_returns_nonzero_when_batches_errored(cli_env, monkeypatch):
    """⭐ refine 有批次出错 ⇒ 非零。

    变异 M2（`return 1 if stats.errors else 0` → `return 0`）→ 本条红。
    """
    stats = _refine_stats(errors=["批 1：HTTP 503", "批 2：超时"])
    monkeypatch.setattr("vigil.refine.refine", lambda *a, **kw: stats)

    assert cli.main(["refine"]) != 0


def test_refine_returns_zero_when_no_batch_errored(cli_env, monkeypatch):
    """阳性对照：一批都没错 ⇒ 0（挡「无条件 return 1」）。"""
    monkeypatch.setattr("vigil.refine.refine", lambda *a, **kw: _refine_stats())

    assert cli.main(["refine"]) == 0


def test_refine_still_prints_summary_before_returning_nonzero(cli_env, monkeypatch,
                                                              capsys):
    """汇总行必须在 `return` 之前——否则失败时日志里没有本次的计数。

    只断言汇总段的**稳定前缀**，不碰词表：词表的判据在别处（见 brief 的
    M5 阳性对照——那句文案目前零覆盖）。
    """
    stats = _refine_stats(errors=["批 1：HTTP 503"])
    monkeypatch.setattr("vigil.refine.refine", lambda *a, **kw: stats)

    rc = cli.main(["refine"])

    out = capsys.readouterr().out
    assert rc != 0
    assert "完成：扫描" in out      # 汇总行仍在
    assert "产出条目" in out        # 汇总段确实走完了，不是半路 return
    assert "[失败] 1 批出错" in out


def test_refine_summary_states_the_discard_counts_as_peers_not_a_subset(
    cli_env, monkeypatch, capsys
):
    """⭐⭐ 汇总行里「本地筛掉」与「规则硬丢弃」是**并列**关系，不许写成包含（「其中」）。

    计划 §三 3.6 的第 2 条禁令。M2-4 修的正是这句假话：`prefilter.expand_context`
    取 ±2 邻居时**不看**那条消息有没有被硬规则判死，所以被判死的消息照样可能作为
    上下文出网——「本地筛掉」里**不包含**「规则硬丢弃」，写成「（其中硬规则丢弃 N 条）」
    就是在说两者是父集/子集，在真库上是假话。

    ⚠️ M4 把它改对了，却**没给「它不再回来」上保险**：终审复核实测，把汇总行改回
    「（其中硬规则丢弃 N 条）」→ **原 404 条测试全绿**。这条断言就是那个保险。

    ⚠️ 断言**只落在 refine 的汇总行上**，不全局搜「其中」——`cli.py` 别处另有一处
    **合法**的「其中 N 行是程序补的」（digest 的补行计数，那是真的包含关系），
    全局搜会误伤它。

    变异「`（候选 … 条；规则硬丢弃 … 条）` → `（其中硬规则丢弃 … 条）`」→ 本条红。
    """
    monkeypatch.setattr("vigil.refine.refine", lambda *a, **kw: _refine_stats())

    assert cli.main(["refine"]) == 0

    lines = [ln for ln in capsys.readouterr().out.splitlines()
             if ln.startswith("完成：扫描")]
    assert len(lines) == 1, f"refine 的汇总行应当恰好一行，实际：{lines!r}"
    summary = lines[0]
    assert "本地筛掉" in summary, summary
    assert "其中" not in summary, (
        "「其中」把「规则硬丢弃」说成了「本地筛掉」的子集——那不是实情："
        f"{summary}"
    )


def test_refine_dry_run_returns_zero(cli_env, monkeypatch):
    """`--dry-run` 仍然是 0：它本来就不该有错误，且明确标注了没调模型。"""
    monkeypatch.setattr("vigil.refine.refine", lambda *a, **kw: _refine_stats())

    assert cli.main(["refine", "--dry-run"]) == 0


def test_pipeline_stages_receive_logs_emit_as_on_progress(cli_env, monkeypatch):
    """三个阶段的进度回调必须是 `logs.emit`。

    阶段内部那些进度行（每群几行、每批几行）默认走内建 `print`——只到
    stdout。`daily` 跑完后排障时要靠日志回答"跑到哪了、哪个群卡住了"，
    回调没接上，日志里就是一段空白。
    """
    from vigil.digest import DigestStats
    from vigil.export import ExportStats

    got: dict[str, object] = {}

    def fake_export(config, key, *, on_progress=print):
        got["export"] = on_progress
        return ExportStats()

    def fake_refine(config, **kw):
        got["refine"] = kw.get("on_progress")
        return _refine_stats()

    def fake_digest(config, **kw):
        got["digest"] = kw.get("on_progress")
        return DigestStats(day="2026-09-13")

    monkeypatch.setattr("vigil.export.export", fake_export)
    monkeypatch.setattr("vigil.refine.refine", fake_refine)
    monkeypatch.setattr("vigil.digest.digest", fake_digest)

    assert cli.main(["export"]) == 0
    assert cli.main(["refine"]) == 0
    assert cli.main(["digest", "--date", "2026-09-13"]) == 0

    assert got["export"] is cli.logs.emit
    assert got["refine"] is cli.logs.emit
    assert got["digest"] is cli.logs.emit


# ── digest：失败也要走完汇总 ───────────────────────────────────


def test_digest_prints_summary_when_a_batch_failed(cli_env, monkeypatch, capsys):
    """⚠️ 失败**不再提前 return**：提前返回会让日志里只有一句「[失败]」，
    而没有本次的计数——事后根本判断不出这轮跑到哪、抓到几条。

    变异「把 `return 1` 挪回汇总行之前」会让本条红。
    """
    from vigil.digest import DigestStats

    stats = DigestStats(
        day="2026-09-13", groups=2, messages=30, items=5, lines=4,
        errors=["批 1：HTTP 503"],
    )
    monkeypatch.setattr("vigil.digest.digest", lambda *a, **kw: stats)

    rc = cli.main(["digest", "--date", "2026-09-13"])

    out = capsys.readouterr().out
    assert rc == 1
    assert "[失败] 批 1：HTTP 503" in out
    assert "完成：2026-09-13 窗口内 2 个群 30 条消息" in out


# ── daily：退出码 0 / 1 / 2 ────────────────────────────────────


def test_daily_returns_2_when_another_instance_holds_the_lock(daily_env, monkeypatch):
    """⭐ 已有实例在跑 ⇒ 退出码 **2**（§三 3.4 冻结）。

    2 不是 1：无人值守下「上一次还没跑完」只要等着就行，「这次跑失败了」
    要人来看。用同一个码会把这两件事混成一件。

    变异 M3（`return 2` → `return 1`）→ 本条红。
    """
    from vigil import lock

    def boom(*a, **kw):
        raise lock.AlreadyRunning("已有实例在跑（锁：x；上次写入：pid=123）")

    monkeypatch.setattr(cli.lock, "SingleInstance", boom)

    assert cli.main(["daily"]) == 2


def test_daily_writes_last_error_and_returns_1_on_failure(daily_env, monkeypatch):
    """⭐ 有阶段失败 ⇒ 写 LAST-ERROR.txt + 退出码 1。

    变异 M4（删掉 `logs.write_last_error(report.last_error)`）→ 本条红。
    """
    written: dict[str, str] = {}
    monkeypatch.setattr(
        cli.logs, "write_last_error",
        lambda msg, **kw: written.setdefault("msg", msg),
    )

    from vigil.daily import RunReport, StageResult

    monkeypatch.setattr(
        "vigil.daily.run",
        lambda **kw: RunReport(
            stages=(StageResult("export", False, "2 个群整群读不到"),),
            last_error="export: 2 个群整群读不到",
            deadline="2026-09-16",
        ),
    )

    rc = cli.main(["daily"])

    assert rc == 1
    assert "2 个群整群读不到" in written["msg"]


def test_daily_returns_0_on_success(daily_env, monkeypatch):
    """成功 ⇒ 0。也是 `RunReport.ok` 这条契约在 CLI 侧的锚点。"""
    from vigil.daily import RunReport

    monkeypatch.setattr(
        "vigil.daily.run", lambda **kw: RunReport(deadline="2026-09-16")
    )

    assert cli.main(["daily"]) == 0


def test_daily_clears_last_error_before_running(daily_env, monkeypatch):
    """开跑先清 LAST-ERROR ⇒ 「文件存在」⟺「本次跑失败过」（T1 的语义）。

    顺序也要紧：清了之后再跑，跑失败时写进去的就是**本次**的错误。
    """
    calls: list[str] = []
    monkeypatch.setattr(cli.logs, "clear_last_error", lambda: calls.append("clear"))

    from vigil.daily import RunReport

    def fake_run(**kw):
        calls.append("run")
        return RunReport()

    monkeypatch.setattr("vigil.daily.run", fake_run)

    assert cli.main(["daily"]) == 0
    assert calls == ["clear", "run"]


# ── F4：人工命令也要上锁（M4 独立审查）─────────────────────────
#
# 审查 AST 核过：全文件此前**只有 `cmd_daily` 引用 `lock`** ⇒ 人工跑
# `export`/`refine`/`digest` 与任务计划撞车时完全不受保护。而
# `docs/SETUP-自动化.md` §七 给退出码 2 写的理由**正是**这个场景
# （「用户手动又跑一次」），spec §4.8 的「幂等可重入」也只堵了一半：
# 两个 refine 并发会各读同一批待处理消息 ⇒ 抽两遍、烧两份 token。


def test_export_returns_2_when_another_instance_holds_the_lock(cli_env, monkeypatch):
    """⭐ 人工 `export` 撞上正在跑的实例 ⇒ **2**，且管线一行没跑。

    变异「去掉 `cmd_export` 的 `with lock.SingleInstance():`」→ 本条红。
    """
    from vigil import lock
    from vigil.export import ExportStats

    ran: list[str] = []
    monkeypatch.setattr(
        "vigil.export.export",
        lambda *a, **kw: ran.append("export") or ExportStats(),
    )

    with lock.SingleInstance(lock.LOCK_PATH):   # 「另一个实例」持着同一把锁
        assert cli.main(["export"]) == 2
    assert ran == []                                      # 没真的跑管线
    assert cli.main(["export"]) == 0                      # 锁放掉后照常


def test_refine_returns_2_when_another_instance_holds_the_lock(cli_env, monkeypatch):
    """⭐ 人工 `refine` 撞车 ⇒ **2**，且没调模型、没写库。

    变异「去掉 `cmd_refine` 的 `with lock.SingleInstance():`」→ 本条红。
    """
    from vigil import lock

    ran: list[str] = []
    monkeypatch.setattr(
        "vigil.refine.refine",
        lambda *a, **kw: ran.append("refine") or _refine_stats(),
    )

    with lock.SingleInstance(lock.LOCK_PATH):   # 与代码**同一把锁**
        assert cli.main(["refine"]) == 2
    assert ran == []
    assert cli.main(["refine"]) == 0


def test_digest_returns_2_when_another_instance_holds_the_lock(cli_env, monkeypatch):
    """⭐ 人工 `digest` 撞车 ⇒ **2**，且没生成日报。

    变异「去掉 `cmd_digest` 的 `with lock.SingleInstance():`」→ 本条红。
    """
    from vigil import lock
    from vigil.digest import DigestStats

    ran: list[str] = []
    monkeypatch.setattr(
        "vigil.digest.digest",
        lambda *a, **kw: ran.append("digest") or DigestStats(day="2026-09-13"),
    )

    with lock.SingleInstance(lock.LOCK_PATH):   # 与代码**同一把锁**
        assert cli.main(["digest", "--date", "2026-09-13"]) == 2
    assert ran == []
    assert cli.main(["digest", "--date", "2026-09-13"]) == 0


def test_lock_is_released_when_a_locked_command_exits_via_sys_exit(cli_env, monkeypatch,
                                                                   capsys):
    """`sys.exit`（**SystemExit**）也必须释放锁。

    三个 `cmd_*` 的配置/参数错误分支都是 `sys.exit(...)`，而它们现在都在
    `with lock.SingleInstance():` 里面。**SystemExit 不是 Exception 是
    BaseException**——`with` 仍会调 `__exit__`，但这条链必须实测：判错了就是
    「一次参数错误把锁永远攥在自己手里」，此后所有人工命令与任务计划
    全会拿到 2，而原因完全看不出来。

    变异「`__exit__` 里不解锁 / 只在 `except Exception` 上解锁」→ 本条红。
    """
    # `--since` 非法 ⇒ `reader._to_epoch` 抛 ValueError ⇒ `cmd_refine` 的 sys.exit
    with pytest.raises(SystemExit):
        cli.main(["refine", "--since", "2026-13-45"])

    monkeypatch.setattr("vigil.refine.refine", lambda *a, **kw: _refine_stats())
    assert cli.main(["refine"]) == 0        # 锁已放掉：能跑进管线（0），不是 2


# ── §8.5：能吞异常的只有「打扫类」失败 ─────────────────────────


def test_daily_unexpected_exception_returns_nonzero(daily_env, monkeypatch):
    """§8.5 第 2 条：`cmd_daily` 的顶层 `except Exception` **必须返回非零**。

    绝对不许写成 `except Exception: logs.emit(...); return 0` 之类的
    「降级成功」——现实里它意味着「daily 崩了，任务计划看到成功」。
    """
    def boom(**kw):
        raise RuntimeError("daily 内部炸了")

    monkeypatch.setattr("vigil.daily.run", boom)

    assert _exit_code_of(["daily"]) != 0


def test_daily_log_write_failure_never_ends_in_success(daily_env, monkeypatch):
    """§8.5 第 1/4 条：从 `logs.emit` 冒出来的异常**不许被记成成功**。

    ⚠️ 这里钉的是「**冒出来的异常不许被降级成 exit 0**」这条契约，
    **不是**在模拟真实磁盘满（计划 §8.5 第 4 条明说它不证明那件事）。

    ⚠️ 而且「日志写失败」并**不是**一条能到得了本层的事件：`logs.emit` 的
    「写不进就抛」只对**跨零点换文件**那一段成立；普通写失败（磁盘满）被
    `logging.StreamHandler.emit` 自带的 `try/except` 吞掉、只调
    `handleError` 往 stderr 打一份——而任务计划**丢弃 stderr**。
    ⇒ 那条路径要靠在 `logs.py` 的 `handleError` 上兜（T1 的文件，由 controller
    另行处置），**不是**本条能覆盖的。本条只保证：万一异常真的冒上来了，
    `cmd_daily` 不会把它变成成功。
    """
    from vigil.config import ConfigError

    seen: list[str] = []

    def boom(msg):
        seen.append(msg)
        raise OSError("日志写不进去")

    def config_dies(*a, **kw):
        raise ConfigError("配置读不出来")

    monkeypatch.setattr(cli.logs, "emit", boom)
    # 用一个**必然经过 emit** 的失败分支（配置错误）把 emit 推到台前：
    # 否则 emit 根本没被调用，这条测试看起来绿、其实什么都没测。
    monkeypatch.setattr(cli, "load_config", config_dies)

    assert _exit_code_of(["daily"]) != 0
    # ⚠️ 这两半都要钉（M4 审 F2）。只断言「抛了不报成功」是不够的：把该分支的
    # `logs.emit(...)` 换成 `pass`，那条断言**照样全绿**——它对这个分支到底有没有
    # 留痕不敏感。所以这里同时断言 emit 真的被调用过、且带的是配置错误那句话。
    assert seen, "该失败分支必须经过 logs.emit"
    assert "配置" in seen[0]


def test_daily_last_error_write_failure_never_ends_in_success(daily_env, monkeypatch):
    """§8.5 第 3 条：`write_last_error` 在磁盘满时**自己也会抛**。

    那条链可以断（异常继续往上走 ⇒ 退出码仍非零），但**不许断在"成功"上**：
    要么不包，要么包了之后仍然返回非零。
    """
    from vigil.daily import RunReport, StageResult

    def boom(*a, **kw):
        raise OSError("磁盘满")

    monkeypatch.setattr(cli.logs, "write_last_error", boom)
    monkeypatch.setattr(
        "vigil.daily.run",
        lambda **kw: RunReport(
            stages=(StageResult("export", False, "整群读不到"),),
            last_error="export: 整群读不到",
        ),
    )

    assert _exit_code_of(["daily"]) != 0


# ── 边界：改动的分界线（人工查询命令不进日志）───────────────────


@pytest.mark.parametrize(
    "argv, reader_func",
    [
        (["read"], "read_messages"),
        (["who"], "sender_stats"),
        (["media"], "local_images"),
    ],
)
def test_query_commands_do_not_write_to_the_log(monkeypatch, tmp_path, argv,
                                                reader_func):
    """`read` / `who` / `media`（以及 `groups` / `deadline-audit` / `serve`）
    是**人工即时查询**，永不无人值守。

    它们往日志里灌只会把日志淹掉——本任务只把四个管线命令接上 `logs.emit`。
    变异「顺手把查询命令也换掉」会让本条红。
    """
    from vigil import reader

    monkeypatch.setattr(cli, "_load_config_only", lambda: _config(tmp_path))
    monkeypatch.setattr(cli, "_require_export_db", lambda config: tmp_path / "export.db")
    monkeypatch.setattr(reader, reader_func, lambda *a, **kw: [])

    def boom(*a, **kw):
        raise AssertionError("人工查询命令不该写日志")

    monkeypatch.setattr(cli.logs, "emit", boom)

    assert cli.main(argv) == 0


# ── C-1：真的 `export()` 读不到群 ⇒ 真的 `cmd_export` 非零（M4 终审）────
#
# ⚠️ 上面那些 export 判据（`:98` 起）用的全是**手造的 `ExportStats`**：它们
# 证明的是「`failed_groups` 非空 ⇒ 退 1」，**证明不了**「读不到的群会进
# `failed_groups`」。而终审 C-1 的洞恰恰在后者——`_read_group` 在分块回退里
# 那条索引查询失败时 `return GroupRead([], [])`，与「这个群本来就没消息」
# **完全同形** ⇒ 一个群整群读不到时 `cmd_export` 退 0、`daily` 照写日报。
# 所以这一条必须跑**真的** `export_mod.export`。


def _fake_source_db(path) -> None:
    """真 `nt_msg.db` 的最小同形替身：38 列、列名是纯数字、明文 sqlite。

    ⚠️ 明文：`open_encrypted` 会被换成直连（真实现走 sqlcipher3，对明文库
    必然解密失败）——本文件测的不是解密。
    """
    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    cols = ", ".join(f'"400{i:02d}"' for i in range(1, 39))
    conn.execute(f"CREATE TABLE group_msg_table ({cols})")
    # 这两张表在真源库里本来就有：`dataline_msg_table` 是 qqcli 兼容层要写的
    # 目标（同列结构），`c2c_msg_table` 是 qqcli 打开库时会校验的
    conn.execute(f"CREATE TABLE dataline_msg_table ({cols})")
    conn.execute("CREATE TABLE c2c_msg_table (x)")
    conn.execute(
        f"INSERT INTO group_msg_table VALUES ({','.join(['NULL'] * 38)})"
    )
    conn.commit()
    conn.close()


class _UnreadableGroup:
    """只让**群 100** 的查询抛（真 sqlite 连接的替身），其余照常。

    ⚠️ 群号必须参与判定：群 200 要**一切正常**（源库里它一条消息都没有），
    否则「读不到」与「本来就没有」就分不开了——而那正是这条要钉的区别。
    """

    def __init__(self, conn, gid: int) -> None:
        self._conn, self._gid = conn, gid

    def execute(self, sql, params=(), *rest):
        import sqlite3

        if "FROM group_msg_table " in sql and params and params[0] == self._gid:
            raise sqlite3.OperationalError("database disk image is malformed")
        return self._conn.execute(sql, params, *rest)

    def close(self) -> None:
        self._conn.close()


def test_export_returns_nonzero_when_the_real_export_cannot_read_a_group(
    cli_env, monkeypatch, capsys
):
    """⭐⭐ 真的 `export()` 读不到一个群 ⇒ 真的 `cmd_export` 退 **1**。

    终审 C-1 的完整链路是「整群读不到 ⇒ `failed_groups` 里没有它 ⇒ 退 0 ⇒
    `daily` 照写日报」。本条的判据一路从 `_read_group` 走到退出码，中间**不许
    有任何替身**（除了「打开加密库」那一步）。

    对照组（同一份源库、同一个替身，只是不抛）：退 **0**。没有这一半，
    「任何情况都退 1」也能让第一条绿。

    变异「`export.py` 的 `raise` 改回 `return GroupRead([], [])`」→ 第一条红。
    """
    import sqlite3

    from vigil import lock  # noqa: F401  —— 只为与下面那条用例同款地说明锁

    _fake_source_db(cli_env / "qq" / "nt_msg.db")
    monkeypatch.setattr(
        "vigil.export.qqdb.open_encrypted",
        lambda path, key: _UnreadableGroup(sqlite3.connect(str(path)), 100),
    )

    assert cli.main(["export"]) == 1, (
        "整群读不到的 export 报了成功——任务计划看到 exit 0，而那个群一条都没读进来"
    )
    assert "[失败] 1 个群整群读不到" in capsys.readouterr().out

    # ── 对照组：同一个替身不抛 ⇒ 退 0，两个群都在 per_group 里 ──────
    monkeypatch.setattr(
        "vigil.export.qqdb.open_encrypted",
        lambda path, key: sqlite3.connect(str(path)),
    )
    assert cli.main(["export"]) == 0


# ── F4 的第四条写库命令：`deadline-audit --apply` 也要上锁（终审 U-3/M-1）──
#
# F4 的裁定是「人工命令也要上锁」（R71），但实现的是**按名字枚举**的三个
# （export/refine/digest）。写库路径还有**第四条**：`cmd_deadline_audit` →
# `store.clear_deadlines`（它自己 commit）。终审实测（锁被持有时）：
# `export` rc=2（被保护），`deadline-audit --apply` rc=**0** 且库**仍被改**。


def _seed_unverifiable_deadline(db) -> int:
    """造一个导出库，里面有一条「截止日在源文里找不到依据」的 item。

    返回那个 `deadline_ts`——「库被改没被改」就靠它判。
    """
    import datetime as dt
    import sqlite3

    from vigil import store
    from vigil.store import ExtractedItem

    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    store.ensure_schema(conn)
    # `messages` 表按 web/export 产出的形状建（ensure_schema 不管它）
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS messages (msg_id INTEGER PRIMARY KEY,"
        " group_id INTEGER NOT NULL, ts INTEGER NOT NULL, sender_uid TEXT,"
        " content TEXT NOT NULL);"
    )
    ts = int(dt.datetime(2026, 9, 26).timestamp())
    with store.transaction(conn):
        store.save_items(
            conn,
            [ExtractedItem(
                kind="notice", title="某通知", detail=None, event_ts=ts,
                deadline_ts=ts, group_id=100, actor_uid=None, place=None,
                links=(), amount=None, confidence=0.9, src_msg_ids=(1,),
            )],
            model="m", prompt_ver="v2", commit=False,
        )
        conn.execute(
            "INSERT INTO messages (msg_id, group_id, ts, sender_uid, content)"
            " VALUES (1, 100, ?, 'u1', '这条正文里没有任何日期')",
            (ts,),
        )
    conn.close()
    return ts


def _deadline_ts_of(db, item_id: int = 1):
    import sqlite3

    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(
            "SELECT deadline_ts FROM items WHERE item_id = ?", (item_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def test_deadline_audit_apply_returns_2_and_leaves_the_db_alone_when_locked(
    cli_env, monkeypatch, capsys
):
    """⭐ `deadline-audit --apply` 撞车 ⇒ **2**，且**库一个字没动**。

    终审实测（锁被持有时）：`export` rc=2（被保护），而 `deadline-audit --apply`
    rc=**0** 且 `items.deadline_ts` 被置 NULL——「所有写库命令都上锁」这条 M4
    承诺此前只覆盖**按名字枚举**的三个。而它对库的写**不可逆**（核验判错就
    把真截止日抹了），所以「锁在保护、它照写」是这条里最重的一半。

    变异「去掉 `cmd_deadline_audit` 里的 `with lock.SingleInstance():`」→
    本条红，且报告里**两个数一起现形**（实测 `(0, None) == (2, ts)`）：
    退出码 0 而不是 2，**并且库已经被改了**。
    """
    from vigil import lock

    db = cli_env / "export.db"
    ts = _seed_unverifiable_deadline(db)
    monkeypatch.setattr(cli, "_load_config_only", lambda: _config(cli_env))
    monkeypatch.setattr(cli, "_require_export_db", lambda config: db)

    assert _deadline_ts_of(db) == ts, "造场景失败：这条的截止日一开始就该在"

    with lock.SingleInstance(lock.LOCK_PATH):     # 「另一个实例」持着同一把锁
        rc = cli.main(["deadline-audit", "--apply"])
    after = _deadline_ts_of(db)

    # ⚠️ 两个事实**合成一条断言**：分成两条的话，前一条一红后一条就再也不跑，
    # 而「库被改了没」恰恰是这里最重的一半（deadline_ts 置 NULL 不可逆）。
    assert (rc, after) == (2, ts), (
        f"锁被持有时 rc={rc}（应当是 2），deadline_ts={after}（应当是 {ts}，"
        f"即**一个字都没改**）——退 0 + 库被改说明这把锁根本没保护到它"
    )
    # 退出码是给任务计划的，人还要看得见「为什么没跑」——与其它三个写库
    # 命令同一句话术，且**不许**静默退 2
    assert "[跳过]" in capsys.readouterr().out

    # 锁放掉后照常：真的写，且报出改了几条
    assert cli.main(["deadline-audit", "--apply"]) == 0
    assert _deadline_ts_of(db) is None


def test_deadline_audit_dry_run_is_read_only_so_it_does_not_take_the_lock(
    cli_env, monkeypatch
):
    """默认的 `deadline-audit`（dry-run）**不上锁**——这是判断，不是遗漏。

    它是 `read`/`who`/`media`/`groups` 那一族的**人工即时查询**：只有 SELECT
    和 print。`lock.SingleInstance` 的语义是「同一时刻只许一个**写库**的
    vigil 进程」（见 `lock.py` 的模块 docstring）；给只读检查上锁会凭空造出
    一个**假拒绝**（rc=2），而 2 的约定含义是「已经有实例在写」。

    所以锁**只在 `--apply` 那一刻**取，理由写在 `cmd_deadline_audit` 里。

    变异「把 `with lock.SingleInstance():` 提到函数开头（dry-run 也上锁）」
    → 本条红（rc 会变成 2）。
    """
    from vigil import lock

    db = cli_env / "export.db"
    ts = _seed_unverifiable_deadline(db)
    monkeypatch.setattr(cli, "_load_config_only", lambda: _config(cli_env))
    monkeypatch.setattr(cli, "_require_export_db", lambda config: db)

    with lock.SingleInstance(lock.LOCK_PATH):
        assert cli.main(["deadline-audit"]) == 0, (
            "只读的核验被锁挡住了——那不是「有人在写」，是假拒绝"
        )
    assert _deadline_ts_of(db) == ts, "dry-run 一个字都不许改库"


def test_soft_deleted_item_still_shows_up_in_deadline_audit(cli_env, monkeypatch, capsys):
    """⑤ `deadline-audit` **刻意不接 overlay**——这个决定必须有守卫（T5 审查的结论）。

    它是**对底层数据的核验**（「这条 item 的截止日在源文里有没有依据」），不是视图：
    它就该看真实的 `items`——包括已软删的那些。软删只是「界面上别显示」，
    源文与截止日的矛盾**照样存在**，核验命令看不到它才是错的。

    ⚠️ 这条守卫还替一个**更重的**事实站岗：`cli.py` 里那个
    `SELECT title FROM items WHERE item_id = ?` 后面直接是 `.fetchone()[0]`。
    T5 审查实测：**给 `items_with_deadline` 接上 overlay 反而会崩**——
    （T8 fix loop **复跑确认**了这条：把标题查询接上 overlay 并过滤软删后，
    本条红在 `TypeError: 'NoneType' object is not subscriptable`，
    `vigil/cli.py:525`——就是下面那句 `.fetchone()[0]`。见 task-8-report.md 的 E5。）
    软删之后这条查询返回 `None`，`[0]` 抛 `TypeError`。
    所以「不接」不是遗漏，是判断；而判断需要有东西钉住。

    变异「在 `cmd_deadline_audit` 的查询里过滤软删」→ 本条红
    （标题不再出现在输出里）。
    """
    import sqlite3 as _sq

    from vigil import overrides, store

    db = cli_env / "export.db"
    _seed_unverifiable_deadline(db)
    monkeypatch.setattr(cli, "_load_config_only", lambda: _config(cli_env))
    monkeypatch.setattr(cli, "_require_export_db", lambda config: db)

    overrides.ensure_schema()
    w = overrides.connect()
    try:
        overrides.delete_item(w, item_id=1, msg_id=1, actor="test")
    finally:
        w.close()

    # **效果对照**：软删在视图层确实生效——否则下面那句「照旧出现」证明不了因果。
    # ⚠️ 用 `window_items`（日报的读路径，overlay 感知）而不是 `get_item`：
    # 后者会 JOIN `sender_names`，而 `_seed_unverifiable_deadline` 只建了 `messages`
    # （那是 export.py 的产物）——那会变成一条与本条要守的东西无关的红。
    ro = _sq.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        visible = [w.item_id for w in store.window_items(ro, since=0, until=2**31)]
    finally:
        ro.close()
    assert 1 not in visible, "软删没生效——这条守卫是空的"

    assert cli.main(["deadline-audit"]) == 0
    out = capsys.readouterr().out
    assert "某通知" in out, (
        "deadline-audit 看不到被软删的条目了。它刻意不接 overlay（对底层数据的核验）："
        "软删只是「界面别显示」，源文与截止日的矛盾照样存在"
    )


# ── repass：存量重判（默认只出清单；--apply 才写库）────────────────
#
# ⚠️ 这一组守的是**退出码与锁的契约**，不是重判逻辑本身
# （逻辑在 `tests/test_repass.py`）。理由与 export/refine/digest：退出码是
# 无人值守下唯一还活着的信号，而它是**接线**属性——重判算得再对，
# 命令返回 0 就等于没报警。


def _repass_result(*, errors=(), to_delete=(1, 2), to_keep=(3,)):
    from vigil.repass import RepassPlan, RepassStats

    return (
        RepassPlan(to_delete=list(to_delete), to_keep=list(to_keep)),
        RepassStats(scanned_msgs=10, batches=1, errors=list(errors)),
    )


def test_repass_dry_run_takes_no_lock_and_passes_apply_false(
    cli_env, monkeypatch, capsys
):
    """默认（不 `--apply`）**只出清单**：不上锁，且明确传 `apply=False`。

    ⚠️ 与 `deadline-audit` 的 dry-run 同一取舍：它是人工即时查询那一族的，
    给只读检查上锁会凭空造出一个**假拒绝**（rc=2），而 2 的约定含义是
    「已经有实例在写」。

    变异「把 `with lock.SingleInstance():` 提到函数开头（dry-run 也上锁）」
    → 本条红；变异「默认 `apply=True`」→ 本条红（`seen["apply"]` 是 True）。
    """
    from vigil import lock

    seen: dict = {}

    def fake(config, **kw):
        seen.update(kw)
        return _repass_result()

    monkeypatch.setattr("vigil.repass.repass", fake)

    with lock.SingleInstance(lock.LOCK_PATH):   # 「另一个实例」持着同一把锁
        rc = cli.main(["repass"])

    assert rc == 0, "只出清单的重判被锁挡住了——那不是「有人在写」，是假拒绝"
    assert seen["apply"] is False, "默认必须**只出清单**：存量重判不可逆"
    out = capsys.readouterr().out
    assert "item 1" in out and "item 2" in out, "清单要真的打出来给人看"


def test_repass_apply_returns_2_and_never_runs_when_the_lock_is_held(
    cli_env, monkeypatch, capsys
):
    """⭐ `repass --apply` 撞车 ⇒ **2**，且**根本没有跑**（更别说写库）。

    ⚠️ 「没跑」和「跑了但没写」是两件事：这里是前者——`repass()` 一次都没被调用。
    拿到锁之后再跑一次是**阳性对照**：证明 2 来自锁，不是来自「这个命令永远退 2」。
    """
    from vigil import lock

    calls: list[dict] = []

    def fake(config, **kw):
        calls.append(kw)
        return _repass_result()

    monkeypatch.setattr("vigil.repass.repass", fake)

    with lock.SingleInstance(lock.LOCK_PATH):
        rc = cli.main(["repass", "--apply"])

    assert (rc, calls) == (2, []), (
        f"锁被持有时 rc={rc}（应当是 2）、repass() 调用 {len(calls)} 次"
        f"（应当是 0）——退 0 或照样跑说明这把锁没保护到它"
    )
    assert "[跳过]" in capsys.readouterr().out, "为什么没跑要看得见，不许静默退 2"

    assert cli.main(["repass", "--apply"]) == 0
    assert calls and calls[0]["apply"] is True


def test_repass_returns_nonzero_when_a_batch_failed(cli_env, monkeypatch):
    """⭐ 有批次失败 ⇒ 非零：那一批这一轮**没有取得判定**（勘误 E5），
    清单因此是**不完整**的——这件事需要人来看，不许报成功。

    变异「`return 1 if stats.errors else 0` → `return 0`」→ 本条红。
    """
    monkeypatch.setattr(
        "vigil.repass.repass",
        lambda *a, **kw: _repass_result(errors=["第 1 批失败: HTTP 503"]),
    )
    assert cli.main(["repass"]) != 0


def test_repass_returns_zero_when_no_batch_failed(cli_env, monkeypatch):
    """阳性对照：一批都没错 ⇒ 0（挡「无条件 return 1」——报警器被无视的第一个原因）。"""
    monkeypatch.setattr("vigil.repass.repass", lambda *a, **kw: _repass_result())
    assert cli.main(["repass"]) == 0


def test_repass_plan_reports_the_three_safety_buckets_separately(
    cli_env, monkeypatch, capsys
):
    """三只「不删」的桶必须**分开**报出来。

    混成一句「保留 N 条」，读的人就分不清「判过了、该留」与「根本没判」——
    而后者意味着这次重判的结果**不能全信**（勘误 E5）。

    变异「把 `plan.unjudged` 并进 `to_keep` 的计数里」→ 本条红。
    """
    plan, stats = _repass_result()
    plan.skipped_referenced = [7]
    plan.skipped_soft_deleted = [8]
    plan.unjudged = [9]
    monkeypatch.setattr("vigil.repass.repass", lambda *a, **kw: (plan, stats))

    cli.main(["repass"])

    out = capsys.readouterr().out
    for iid in (7, 8, 9):
        assert f"item {iid}" in out, f"item {iid} 没被单独报出来——三只桶被并了"
    assert "没判成" in out and "软删" in out and "日报引用" in out
