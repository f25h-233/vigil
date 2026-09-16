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

    ⚠️ **锁的路径也要接到 tmp_path**：三个 `cmd_*` 现在各上一次锁（M4 审 F4），
    不接的话每次测试都会去动仓库里**真实的** `data/vigil.lock`——测试污染工作区，
    而且一旦用户那边真有实例在跑，这些测试会莫名其妙地拿到退出码 2。
    注意这里换的是**路径**不是锁本身：真 `SingleInstance` 的拿锁/放锁逻辑照跑。
    """
    cfg = _config(tmp_path)
    monkeypatch.setattr(cli, "_load_or_die", lambda: (cfg, "k-db"))
    monkeypatch.setattr(cli, "_load_config_only", lambda: cfg)
    monkeypatch.setattr(cli, "_require_export_db", lambda config: tmp_path / "export.db")
    monkeypatch.setattr("vigil.config.load_llm_key", lambda *a, **k: "k-llm")
    monkeypatch.setattr("vigil.lock.LOCK_PATH", tmp_path / "vigil.lock")
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

    with lock.SingleInstance(cli_env / "vigil.lock"):      # 「另一个实例」持着锁
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

    with lock.SingleInstance(cli_env / "vigil.lock"):
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

    with lock.SingleInstance(cli_env / "vigil.lock"):
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
