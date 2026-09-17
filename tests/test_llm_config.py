"""LLM 端点配置（`config/llm.toml`）—— M6 T3。

⚠️ 本文件**不联网**：所有 `urlopen` 都被换成一个假的响应对象，
但**报文本身是真的**——本文件最值钱的断言恰恰是「实际发出去的 JSON 里
有没有 `enable_thinking` 这个键」。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from vigil import config, llm


def _capture_bodies(monkeypatch) -> list[dict]:
    """把 `chat_json` 真正发出去的请求体抓下来。"""
    sent: list[dict] = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "{}"}}], "usage": {}}
            ).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        sent.append(json.loads(request.data.decode("utf-8")))
        return _Response()

    # ⚠️ 打的是 `urllib.request.urlopen`（`llm.py` 用的是模块级 `urllib.request`）。
    # 不要在这里 `monkeypatch.undo()`——那会连带拆掉 conftest 的 autouse 隔离夹具。
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    return sent


def _patch_existing(monkeypatch, tmp_path, text: str) -> pathlib.Path:
    """让 `load_llm_settings()` 的**默认路径**指向一份临时文件。

    ⚠️ 必须是改 `DEFAULT_LLM_TOML` 而不是传 `path=`：本文件要验的正是
    「CLI / daily 不传 path 时读到什么」，传 path 会把被测的那段绕过去。
    """
    p = tmp_path / "llm.toml"
    p.write_text(text, encoding="utf-8")
    monkeypatch.setattr(config, "DEFAULT_LLM_TOML", p)
    return p


# ── 读取：三态 ──────────────────────────────────────────────────────


def test_missing_file_yields_defaults_and_warns(tmp_path, monkeypatch):
    """⭐ 文件不存在 ⇒ 全内置默认，且**必须出声**。

    ⚠️ 这一声是承重的：默认里 `enable_thinking=None` = **不发该字段**，
    而实测「不发」会让 Qwen3.5-35B-A3B 单批从 2.8s 涨到 **111.5s**
    （11,124 输出 token）。删掉一个配置文件换来 40 倍慢，如果**没有任何提示**，
    那就是本项目反复禁止的「静默退化」。

    ⚠️ 变异反证：把 `on_warn` 那行删掉 ⇒ 本条**必红**。
    """
    # ⚠️ **偏离 brief（见报告 §偏差 D1）**：brief 这里写的是 `tmp_path / "nope.toml"`，
    # 而它下面那条断言要求提示里出现 `llm.toml` —— 二者**不能同时成立**
    # （`"llm.toml" not in "...\\nope.toml"`）。断言才是承重的那条（提示必须点名
    # 那个文件，用户才知道去建哪一个），所以改的是夹具路径：仍然不存在，
    # 但仍叫 `llm.toml`。
    monkeypatch.setattr(config, "DEFAULT_LLM_TOML", tmp_path / "gone" / "llm.toml")
    warnings: list[str] = []
    s = config.load_llm_settings(on_warn=warnings.append)
    assert s.base_url == llm.DEFAULT_BASE
    assert s.model == llm.DEFAULT_MODEL
    assert s.enable_thinking is None
    assert len(warnings) == 1
    assert "llm.toml" in warnings[0]
    assert "enable_thinking" in warnings[0], "提示里必须点名这个字段——它才是慢 40 倍的原因"


def test_file_without_the_key_means_do_not_send(tmp_path, monkeypatch):
    """文件存在但没写 `enable_thinking` ⇒ `None`（= 不发），**且不警告**。

    ⚠️ 不警告是刻意的：用户正在写一份自定义端点配置，他**没提**这个字段。
    这时候的每一个提醒都是噪音，而噪音会让真正的提醒失效。
    """
    _patch_existing(monkeypatch, tmp_path, '[llm]\nbase_url = "https://x/v1/chat/completions"\n')
    warnings: list[str] = []
    s = config.load_llm_settings(on_warn=warnings.append)
    assert s.enable_thinking is None
    assert warnings == []
    assert s.base_url == "https://x/v1/chat/completions"
    assert s.model == llm.DEFAULT_MODEL, "没写的字段逐项回落，不是整段回落"


def test_explicit_false_is_not_collapsed_to_none(tmp_path, monkeypatch):
    """⭐ `= false` 与「没写」必须是**两个不同的值**。

    ⚠️ 这是本任务最容易写错的一行：`section.get("enable_thinking")` 对
    「键不存在」和「值是 false」返回的东西**不同**（`None` vs `False`），
    所以 `if value:` 这种写法会把 `false` 静默吞成"没写" ⇒ 切到自建端点后
    行为**悄悄变了**。必须显式判 `not in`。

    ⚠️ 变异反证：把 `if "enable_thinking" not in section` 改成
    `if not section.get("enable_thinking")` ⇒ 本条**必红**。
    """
    _patch_existing(monkeypatch, tmp_path, "[llm]\nenable_thinking = false\n")
    assert config.load_llm_settings().enable_thinking is False

    _patch_existing(monkeypatch, tmp_path, "[llm]\nenable_thinking = true\n")
    assert config.load_llm_settings().enable_thinking is True


def test_a_non_bool_enable_thinking_is_rejected(tmp_path, monkeypatch):
    """`enable_thinking = "false"`（带引号）必须**响亮报错**，不许静默当真。

    ⚠️ 与本模块的立场一致：「配置写错是我们自己的问题，越早暴露越好。不猜、不兜底」。
    """
    _patch_existing(monkeypatch, tmp_path, '[llm]\nenable_thinking = "false"\n')
    with pytest.raises(config.ConfigError, match="enable_thinking"):
        config.load_llm_settings()


def test_malformed_llm_toml_is_wrapped(tmp_path, monkeypatch):
    _patch_existing(monkeypatch, tmp_path, "[llm\nbase_url = 1\n")
    with pytest.raises(config.ConfigError, match="TOML"):
        config.load_llm_settings()


def test_a_wrong_section_shape_is_rejected(tmp_path, monkeypatch):
    """`[[llm]]`（双层）会读成 list ⇒ 必须响亮（与 `[[person]]` 同一条判据）。"""
    _patch_existing(monkeypatch, tmp_path, '[[llm]]\nbase_url = "x"\n')
    with pytest.raises(config.ConfigError, match="llm"):
        config.load_llm_settings()


# ── 写侧 ────────────────────────────────────────────────────────────


def test_save_then_load_roundtrips(tmp_path, monkeypatch):
    p = tmp_path / "llm.toml"
    s = config.LLMSettings(
        base_url="https://api.deepseek.com/v1/chat/completions",
        model="deepseek-chat",
        enable_thinking=None,
    )
    config.save_llm_settings(s, p)
    assert config.load_llm_settings(p).base_url == s.base_url
    assert config.load_llm_settings(p).model == s.model
    # ⭐ 「不发」这一态必须能穿过一次 round-trip —— 否则界面上选了它、
    # 保存后却变成 false，而用户从响应里看不出区别。
    assert config.load_llm_settings(p).enable_thinking is None


def test_saved_llm_toml_contains_no_key():
    """⭐ **密钥永远不进配置文件**（spec §3.2）。

    ⚠️ 这条不是"检查代码写没写"——它检查的是**产物**：`save_llm_settings`
    接受的 `LLMSettings` 里根本没有放密钥的字段，但这条测试挡的是
    将来有人"顺手"加一个 `api_key` 字段进来。密钥走 `.env`
    （`config.load_llm_key`），落进 `config/*.toml` 就等于**进了 git**。
    """
    import dataclasses
    assert "api_key" not in {f.name for f in dataclasses.fields(config.LLMSettings)}


# ── ⭐ 端到端：从配置文件到真实报文（R12 的全部意义）────────────────


def test_the_end_to_end_wire_format_omits_the_field(tmp_path, monkeypatch):
    """⭐ R12：`enable_thinking` 在通用 OpenAI 端点上**必须真的不发出去**。

    ⚠️ 这条测的是**三层拼起来的结果**：`config/llm.toml` → `LLMSettings`
    → `refine` 内部的 `LLMConfig` → `chat_json` 的请求体。
    只测其中任何一层都不够——`LLMConfig` 今天已经能正确省略这个字段了
    （`llm.py:150-151`），**卡住的是它上面那两层根本没把 `None` 传下来**
    （三个消费函数的默认值是 `False`）。

    ⚠️ **实测修正（M6 T3，见 task-3-report §偏差 D3）**：原稿在这里写的变异反证
    ——「把 `refine.py` 里构造 `LLMConfig` 那行的 `enable_thinking=enable_thinking`
    改成 `enable_thinking=False` ⇒ 本条**必红**」——**不成立**：本条自己用
    `llm.LLMConfig(...)` 手工构造配置，**一次都没调 `refine()`**，所以
    `refine.py` 怎么改都影响不到它（实测：变异后本文件 **10 passed**）。
    「上一层有没有把值传下来」那一半由
    `test_refine_forwards_the_configured_endpoint_to_the_wire` 钉住。
    """
    sent = _capture_bodies(monkeypatch)
    cfg = config.LLMSettings(enable_thinking=None)
    llm_cfg = llm.LLMConfig(api_key="k", base_url=cfg.base_url, model=cfg.model,
                            enable_thinking=cfg.enable_thinking)
    llm.chat_json(llm_cfg, system="s", user="u", sleep=lambda _: None)
    assert "enable_thinking" not in sent[0]

    sent.clear()
    llm_cfg2 = llm.LLMConfig(api_key="k", enable_thinking=False)
    llm.chat_json(llm_cfg2, system="s", user="u", sleep=lambda _: None)
    assert sent[0]["enable_thinking"] is False, (
        "明确关掉时必须**发出去**——否则 Qwen 混合思考模型会退回 111.5s/批"
    )


def test_base_url_reaches_the_request(tmp_path, monkeypatch):
    """⭐ 出口判据 3 的最小机械形式：`base_url` 真的到了 URL 上（不是只存了个字段）。"""
    urls: list[str] = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "{}"}}], "usage": {}}
            ).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        urls.append(request.full_url)
        return _Response()

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)

    _patch_existing(
        monkeypatch, tmp_path,
        '[llm]\nbase_url = "https://my-own-host.example/v1/chat/completions"\n',
    )
    s = config.load_llm_settings()
    llm.chat_json(
        llm.LLMConfig(api_key="k", base_url=s.base_url), system="s", user="u",
        sleep=lambda _: None,
    )
    assert urls == ["https://my-own-host.example/v1/chat/completions"]


def test_the_autouse_fixture_isolates_the_default_llm_toml():
    """⭐ 钉住 `tests/conftest.py::_isolate_llm_toml_path`（勘误 E6）。

    ⚠️ **只写夹具不验夹具 = 空守卫**：夹具写错（名字拼错、忘了 `autouse`、
    指到了仓库内）时它是**静默**的——所有用例照样绿，而地雷原样还在。

    ⚠️ 地雷的实测形态（T3，2026-09-17）：把仓库里 `config/llm.toml` 的
    `model` 改成一个别的值（**那正是 M6 邀请用户做的事**）⇒
    `test_daily.py::test_stage_arguments_are_wired_from_the_day_window` 与
    `test_refine.py::test_cli_refine_model_falls_back_to_default` 两条
    **与 LLM 配置无关**的用例同时变红（`2 failed, 636 passed`）。
    它们绿只是因为出厂文件恰好等于内置默认——那是**环境相关的绿**。

    判据从**被测代码的视角**问（不是问夹具自身写没写对）：
    `load_llm_settings()` **不传 path** 时读的是哪个文件。两条合起来才成立：
    ① 那个路径**不在仓库里**；② 它**真的不存在**（于是读回内置默认，
    那是不关心 LLM 配置的用例所依赖的基线）。
    """
    assert not config.DEFAULT_LLM_TOML.is_relative_to(config.REPO_ROOT), (
        f"默认路径还指着仓库内的 {config.DEFAULT_LLM_TOML}——改那份文件"
        "（T3/M6 的核心用法）会红掉两条无关用例"
    )
    assert not config.DEFAULT_LLM_TOML.is_file(), (
        "隔离路径不该是一个已存在的文件：load_llm_settings 会去解析它，"
        "而空文件会抛「缺少 [llm] 段」（那些用例要的是内置默认）"
    )
    s = config.load_llm_settings()
    assert (s.base_url, s.model, s.enable_thinking) == (
        llm.DEFAULT_BASE, llm.DEFAULT_MODEL, None
    )


# ── ⭐ CLI 的三级优先级：命令行 > `config/llm.toml` > 内置默认（FIX B）──────
#
# ⚠️ 这三条在 T3 首轮里**一条判据都没有**：`cmd_refine` / `cmd_digest` /
# `cmd_repass` 里的 `base_url=args.base_url or llm_settings.base_url` 与
# `model=args.model or llm_settings.model` 全都不在既有用例的断言里
# （`tests/test_cli.py` 里那几个替身只钉 `apply` / `on_progress`）。
# 判据读的是**替身收到的 kwargs**，不是 `cli.py` 的源码文本。


def _wire_cli(monkeypatch, tmp_path, seen: dict) -> None:
    """把 `cli.main` 的外部依赖全接上——**一件都不许落到真实环境**。

    范式照抄 `tests/test_cli.py::cli_env` 与
    `tests/test_refine.py::test_cli_refine_model_falls_back_to_default`：
    `_load_config_only` / `_require_export_db` / `load_llm_key` 换替身，
    三个阶段换假的（只记下它们**收到了什么**）。
    锁不用接：`conftest.py` 的 autouse 夹具已经把锁路径挪到 tmp_path。
    """
    from vigil import cli
    from vigil.digest import DigestStats
    from vigil.refine import RefineStats
    from vigil.repass import RepassPlan, RepassStats

    cfg = type("_Cfg", (), {"output_db": tmp_path / "export.db"})()
    monkeypatch.setattr(cli, "_load_config_only", lambda: cfg)
    monkeypatch.setattr(cli, "_require_export_db", lambda c: tmp_path / "export.db")
    monkeypatch.setattr(config, "load_llm_key", lambda *a, **k: "k-llm")

    def fake_refine(c, **kw):
        seen["refine"] = kw
        return RefineStats()

    def fake_digest(c, **kw):
        seen["digest"] = kw
        return DigestStats()

    def fake_repass(c, **kw):
        seen["repass"] = kw
        return RepassPlan(), RepassStats()

    monkeypatch.setattr("vigil.refine.refine", fake_refine)
    monkeypatch.setattr("vigil.digest.digest", fake_digest)
    monkeypatch.setattr("vigil.repass.repass", fake_repass)


def _run_all_three() -> None:
    """三条命令各跑一次（repass 走默认的"只出清单"那条路，不写库）。"""
    from vigil import cli

    assert cli.main(["refine"]) == 0
    assert cli.main(["digest", "--date", "2026-09-16"]) == 0
    assert cli.main(["repass"]) == 0


def test_cli_reads_the_endpoint_from_the_file(monkeypatch, tmp_path, capsys):
    """⭐⭐ 不给 flag ⇒ **文件里**的 `base_url` / `model` 传下去。

    这条挡的正是 T3 的出口判据 3（「`refine` 与 `digest` 两处都生效」）在
    CLI 这一层的那一半：网页改了端点，命令行跑的那次必须跟着改。
    """
    _patch_existing(
        monkeypatch, tmp_path,
        '[llm]\nbase_url = "https://from-file/v1/chat/completions"\n'
        'model = "file-model"\nenable_thinking = false\n',
    )
    seen: dict = {}
    _wire_cli(monkeypatch, tmp_path, seen)

    _run_all_three()
    capsys.readouterr()

    for stage in ("refine", "digest", "repass"):
        assert seen[stage]["base_url"] == "https://from-file/v1/chat/completions", (
            f"{stage} 没拿到文件里的端点——网页上改了端点，{stage} 还在打老地址"
        )
        assert seen[stage]["model"] == "file-model", f"{stage} 没拿到文件里的模型"


def test_cli_flag_beats_the_file(monkeypatch, tmp_path, capsys):
    """⭐⭐ 给了 `--base-url` / `--model` ⇒ **命令行赢**。

    命令行优先是刻意的：排障要能"先试一下别的端点"而不用动文件。
    ⚠️ 变异「把 `args.base_url or llm_settings.base_url` 改成
    `llm_settings.base_url`（无条件用文件）」⇒ 本条**必红**。
    """
    _patch_existing(
        monkeypatch, tmp_path,
        '[llm]\nbase_url = "https://from-file/v1/chat/completions"\n'
        'model = "file-model"\n',
    )
    seen: dict = {}
    _wire_cli(monkeypatch, tmp_path, seen)
    from vigil import cli

    assert cli.main(["refine", "--base-url", "https://from-flag/v1", "--model", "flag-model"]) == 0
    assert cli.main(["digest", "--date", "2026-09-16", "--base-url", "https://from-flag/v1",
                     "--model", "flag-model"]) == 0
    assert cli.main(["repass", "--base-url", "https://from-flag/v1", "--model", "flag-model"]) == 0
    capsys.readouterr()

    for stage in ("refine", "digest", "repass"):
        assert seen[stage]["base_url"] == "https://from-flag/v1"
        assert seen[stage]["model"] == "flag-model"


def test_cli_falls_back_to_the_builtin_when_the_file_is_missing(monkeypatch, tmp_path, capsys):
    """⭐⭐ 文件不存在 ⇒ **内置默认**（不是 `None`、不是空串）。

    ⚠️ `None` 会一路传到 `LLMConfig`/`httpx`，而空串会变成一个**看起来像
    URL 的东西**去发请求——两条都是静默的坏。判据是逐字段等于 `llm.DEFAULT_*`。
    """
    monkeypatch.setattr(config, "DEFAULT_LLM_TOML", tmp_path / "gone" / "llm.toml")
    seen: dict = {}
    _wire_cli(monkeypatch, tmp_path, seen)

    _run_all_three()
    capsys.readouterr()

    for stage in ("refine", "digest", "repass"):
        assert seen[stage]["base_url"] == llm.DEFAULT_BASE
        assert seen[stage]["model"] == llm.DEFAULT_MODEL


def test_cli_think_flag_never_swallows_the_files_value(monkeypatch, tmp_path, capsys):
    """⭐ 「没给 `--think` 时**文件说了算**」——把 brief 说的"碰巧"钉成判据。

    ⚠️ brief 自己论证过：`args.think or llm_settings.enable_thinking` 在这里
    **碰巧正确**，而它依赖 `args.think` 的默认值是 `False` 而不是 `None`
    （`False or X` 得到 `X`；但若哪天有人把 `store_true` 改成
    `default=None`，同一条式子的**含义就变了**）。实现用的是显式写法
    （`True if args.think else …`），语义与那份论证**不同**——
    所以这里钉的是**要保住的语义**，三种情形一个都不许错：

      ① 文件 `= true`、没给 `--think` ⇒ `True`（**文件说了算**，不是"默认关"）
      ② 文件 `= false`、给了 `--think` ⇒ `True`（命令行赢）
      ③ 文件**没写**、没给 `--think` ⇒ `None`（**不发**，R12）
    """
    from vigil import cli

    seen: dict = {}
    _wire_cli(monkeypatch, tmp_path, seen)

    _patch_existing(monkeypatch, tmp_path, "[llm]\nenable_thinking = true\n")
    assert cli.main(["refine"]) == 0
    assert seen["refine"]["enable_thinking"] is True, (
        "文件里写了 true 却被吞成关闭——`--think` 的默认值一旦变成 None，"
        "`args.think or …` 那类写法就会在这里静默反过来"
    )

    _patch_existing(monkeypatch, tmp_path, "[llm]\nenable_thinking = false\n")
    assert cli.main(["refine", "--think"]) == 0
    assert seen["refine"]["enable_thinking"] is True, "给了 --think 必须赢过文件"

    _patch_existing(monkeypatch, tmp_path, '[llm]\nbase_url = "https://x/v1"\n')
    assert cli.main(["refine"]) == 0
    assert seen["refine"]["enable_thinking"] is None, "文件没写 = 不发这个字段"
    capsys.readouterr()


def test_refine_forwards_the_configured_endpoint_to_the_wire(monkeypatch):
    """⭐ `refine(..., base_url=..., enable_thinking=...)` 必须真的到请求层。

    ⚠️ **补的（偏离 brief，见报告 §偏差 D3）**：brief 给
    `test_the_end_to_end_wire_format_omits_the_field` 写的变异反证是
    「把 `refine.py` 里构造 `LLMConfig` 那行的 `enable_thinking=enable_thinking`
    改成 `enable_thinking=False` ⇒ 本条**必红**」——**实测是假的**：那条测试
    自己 `llm.LLMConfig(...)` 手工构造配置，**一次都没调 `refine()`**
    （实测：变异后 `tests/test_llm_config.py` **10 passed**、全量只红
    `tests/test_refine.py::test_refine_passes_thinking_switch_to_llm`）。
    而它想守的那条线（「上一层有没有把值传下来」）`base_url` 那一半
    **今天没有任何判据**——删掉 `base_url=base_url` 不会让任何用例变红，
    因为 `LLMConfig` 的默认值恰好就是 `DEFAULT_BASE`（空守卫的典型形状）。

    判据是**真正交给 `chat_json` 的那个 cfg**，不是源码文本——
    语料构造照抄 `tests/test_refine.py::seeded` / `StubConfig`。
    """
    import sqlite3

    from vigil import refine, store
    from vigil.llm import LLMResult

    conn = sqlite3.connect(":memory:", uri=True)
    conn.executescript(
        """
        CREATE TABLE messages (
            msg_id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL,
            ts INTEGER NOT NULL, sender_uid TEXT, content TEXT NOT NULL
        );
        CREATE TABLE sender_names (
            group_id INTEGER NOT NULL, uid TEXT NOT NULL, group_nick TEXT,
            qq_nick TEXT, uin INTEGER, in_group INTEGER,
            PRIMARY KEY (group_id, uid)
        );
        """
    )
    conn.execute(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        (1, 100, 1000, "u_a", "明天下午有讲座，地点西太湖报告厅"),
    )
    conn.commit()
    store.ensure_schema(conn)

    class _Cfg:
        """refine 只用到 `tier_of`（`refine.py:464` 是全模块唯一的 `config.`）。"""

        def tier_of(self, gid: int) -> str:
            return "high"

    seen: list[llm.LLMConfig] = []

    def fake_chat_json(cfg, *, system, user, sleep=None):
        seen.append(cfg)
        return LLMResult(payload={"items": []}, input_tokens=1, output_tokens=1)

    monkeypatch.setattr(refine, "chat_json", fake_chat_json)
    quiet = lambda *a, **k: None  # noqa: E731

    refine.refine(
        _Cfg(), api_key="k", conn=conn, batch_size=1, on_progress=quiet,
        base_url="https://my-host/v1/chat/completions", enable_thinking=None,
    )
    assert seen, "一批都没跑，这条测试就没在验证任何东西"
    assert seen[0].base_url == "https://my-host/v1/chat/completions"
    assert seen[0].enable_thinking is None, "「不发」这一态被上一层吞掉了"

    seen.clear()
    refine.refine(
        _Cfg(), api_key="k", conn=conn, batch_size=1, redo=True,
        on_progress=quiet, enable_thinking=False,
    )
    assert seen, "redo 那轮一批都没跑"
    assert seen[0].base_url == llm.DEFAULT_BASE, "不传时应当退回内置端点"
    assert seen[0].enable_thinking is False
