"""共享测试夹具。

原则：测试不碰真实的 QQ 加密库、不碰 data/vigil.db、不联网。
全部用内存 SQLite 与构造出来的样本数据。
"""

from __future__ import annotations

import pathlib
import sqlite3
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ⚠️ 这个 import 是**安全**的：`vigil.config` 在模块级只算路径常量
# （`REPO_ROOT` / `LOCK_PATH`），不读文件也不建目录——真正读 `.env`、读
# `groups.toml` 的都在函数里。所以 import 它不会碰到真实的 `data/`。
from vigil import lock  # noqa: E402

# 同理安全：`vigil.overrides` 模块级只算 `OVERRIDES_DB` 路径常量与几张 DDL 字符串，
# **不建目录、不连库**（真正建库的 `ensure_schema()` 在函数里）。所以 import 它不会
# 碰真实的 `data/`。
from vigil import overrides  # noqa: E402

# 同理安全：`vigil.config` 模块级只算路径常量（`REPO_ROOT` / `DEFAULT_*`），
# 读文件全在函数里（`load_llm_settings` / `load_config` 都是被调用时才 open）。
from vigil import config  # noqa: E402


# 隔离根里那份最小类目表（M6 T5）。形状与内容都**自带**，不抄仓库里真实的
# `config/categories.toml`：抄一份等于把「测试红绿取决于用户的类目配置」留着，
# 而 M6 的整个卖点就是把那份文件交给用户在网页上编辑。
#
# ⚠️ 七个 slug 与**顺序**（`notice` 在第一个）是 `tests/test_api.py` 里
# `test_categories_carry_counts` 断言的东西；`academic` 的中文名是
# `test_items_returns_the_frozen_field_set` 断言 `kind_label == "学业"` 要的。
# 改这里之前先看那两条——它们会红，而且是**响亮**地红。
_ISOLATED_CATEGORIES_TOML = """\
[[categories]]
slug = "notice"
label = "通知公告"
desc = "隔离用类目：通知公告"

[[categories]]
slug = "academic"
label = "学业"
desc = "隔离用类目：学业"

[[categories]]
slug = "activity"
label = "活动"
desc = "隔离用类目：活动"

[[categories]]
slug = "life"
label = "生活"
desc = "隔离用类目：生活"

[[categories]]
slug = "secondhand"
label = "二手"
desc = "隔离用类目：二手"

[[categories]]
slug = "lostfound"
label = "失物招领"
desc = "隔离用类目：失物招领"

[[categories]]
slug = "job"
label = "兼职招聘"
desc = "隔离用类目：兼职招聘"
"""


# ── 默认路径 / REPO_ROOT 的隔离（autouse）─────────────────────────────
#
# ⚠️ **约定（M6 T4 复审 ⚠️-2，对 T5–T9 都成立）：测试里凡是要落到临时根的
#    路径，一律写绝对路径（`pathlib.Path(...).as_posix()`）**——不许在临时配置
#    里写相对路径、指望被测代码去拼 `REPO_ROOT`。三条理由：
#
#      · `config.REPO_ROOT` 与 `api.REPO_ROOT` 是**两个模块全局**
#        （`config.py` / `api.py` 各一个），下面的夹具只挪得动其中一个；
#      · `validate_config_raw` 对**相对** `output_db` 的解析基准是
#        `config.REPO_ROOT`——那是 import 期算好的常量，`monkeypatch` 够不着；
#      · 于是「只挪了 `api.REPO_ROOT`，而临时 `groups.toml` 里写的是相对
#        `output_db`」会把产物**指回真实仓库的 `data/`**：快照路径
#        （`groups_snapshot.default_path` = `output_db.parent / …`）正是从它推出来的。
#        而外部断言全都在看 tmp 根 ⇒ **空守卫**（评审已复现这条链）。
#
#   同理一律 `.as_posix()`：反斜杠在 TOML 基本字符串里是转义字符。


@pytest.fixture(autouse=True)
def _isolate_overrides_path(tmp_path_factory, monkeypatch):
    """把人工干预层的默认路径挪出仓库——**否则写路径会建真实的 `data/overrides.db`**。

    ⚠️ `store.ensure_schema()` 现在会调 `overrides.ensure_schema()`（M5 Task 4 Step 5），
    而它**每次 refine / digest 都跑**（测试里有 5 个文件、几十处在调它）。
    没有这个夹具，跑一次全量就在真实的 `data/` 里留下一个干预层库；更糟的是：

      ① **污染**：将来有用例往里面写了事件（改分类 / 软删 / 撤销），那些就是
         **用户真实的人工修改数据**被测试改写——而 `data/` 不入 git，
         **没有任何东西能把它还原**；
      ② **假红**：与 `data/vigil.lock` 同族的形态——只在"真库恰好有状态"时出现，
         看着像产品缺陷、其实是测试污染。

    ⚠️ **不能用 `tmp_path`**（本夹具初版就踩了）：有些用例把 `tmp_path` 当**产品
    目录**用，并按**文件集合**断言。`tests/test_digest.py` 的两条持久化用例就是
    `sorted(p.name for p in tmp_path.iterdir()) == ["2026-09-13.md"]`——
    overlay 库一旦落在 `tmp_path` 里，它们会**变成红的，而红的原因与它们要守的
    不变量毫无关系**（实测：2 failed / 459 passed）。
    所以这里用 `tmp_path_factory.mktemp()` 另开一个**每次调用唯一**的目录：
    它不在被测代码会去列目录的那些路径下。

    ⚠️ 用 autouse：漏掉一个测试文件就退化为上面两条。
    ⚠️ 只换路径、**不建文件**：建库仍然是 `ensure_schema()` 的职责
    （读路径不建库是刻意的设计，夹具不该替它把文件先造出来）。
    """
    monkeypatch.setattr(
        overrides, "OVERRIDES_DB", tmp_path_factory.mktemp("overrides") / "overrides.db"
    )


@pytest.fixture(autouse=True)
def _isolate_lock_path(tmp_path, monkeypatch):
    """把单实例锁的默认路径挪到 tmp——**否则跑测试会碰真实的 `data/vigil.lock`**。

    ⚠️ 两个后果，第二个比第一个严重得多：

      ① **污染**：跑一次全量就在 `data/` 里造一个 `vigil.lock`（虽然 `data/`
         不入库）；
      ② **假红**：F4 之后 `cmd_export`/`cmd_refine`/`cmd_digest` 都加锁，
         而 `cli_env` 那批用例**不换锁路径**。于是**若真有实例在跑**
         （比如 M4 冒烟的短触发器正好在跑 `vigil daily`），那些测试会拿到
         退出码 **2** 而**莫名变红**——**看着像产品缺陷，其实是测试污染**。

    ⚠️ 用 autouse：漏掉一个测试文件就退化为上面第 ② 条，而它是**环境相关的**
    ——只在"恰好有实例在跑"时出现，最难查。
    """
    monkeypatch.setattr(lock, "LOCK_PATH", tmp_path / "vigil.lock")


@pytest.fixture(autouse=True)
def _isolate_llm_toml_path(tmp_path_factory, monkeypatch):
    """把 LLM 端点配置的默认路径挪出仓库（M6 T3，勘误 E6）。

    ⚠️ **不隔离的后果是"环境相关的绿"，不是"写脏仓库"**——与上两条夹具的
    形态不同，值得单独说清楚：`load_llm_settings` 是**读**，不会写 `config/`。
    真正的问题是**测试的行为取决于仓库里那份文件的当前内容**：

      `cmd_refine` / `cmd_digest` / `cmd_repass` / `daily.run()` 都读它
      （T3 之后），于是 `test_daily.py::test_stage_arguments_are_wired_from_
      the_day_window` 与 `test_refine.py::test_cli_refine_model_falls_back_to_
      default` 这两条**与 LLM 配置无关**的用例，会因为「有人在网页上换了
      模型」而变红——**而那正是 M6 邀请用户做的事**。

    ⚠️ **实测过**（2026-09-17，T3）：把 `config/llm.toml` 的 `model` 改成一个
    别的值 ⇒ 上面两条**同时变红**（`2 failed, 636 passed`）；改回来 ⇒ 全绿。
    它们今天绿**只是因为出厂文件恰好等于内置默认**——这叫假绿。

    ⚠️ **指向一个不存在的路径**，不是 `tmp_path` 下的空文件：
    `load_llm_settings` 对「文件不存在」返回内置默认（+ `on_warn`），
    那正是这些用例期望的基线；而**空文件**会抛「缺少 [llm] 段」⇒ 全部变红。

    ⚠️ 用 `mktemp` 而不是 `tmp_path`（理由与 `_isolate_overrides_path` 一字不差）：
    有些用例把 `tmp_path` 当**产品目录**用并按**文件集合**断言
    （`tests/test_digest.py` 就是 `sorted(p.name for p in tmp_path.iterdir())`）。

    ⚠️ 用 autouse：漏掉一个测试文件，那个文件里的用例就退回"看仓库文件脸色"。
    """
    monkeypatch.setattr(
        config, "DEFAULT_LLM_TOML", tmp_path_factory.mktemp("llm") / "llm.toml"
    )


@pytest.fixture(autouse=True)
def _isolate_api_repo_root(tmp_path_factory, monkeypatch):
    """把 `api.config_path()`（Web 侧**现读**的 `groups.toml`）的解析根挪出仓库。

    ⚠️ 与 `_isolate_llm_toml_path` 是**同一族**（M6 T4）；形态更险一点：
    那边只是读文件，这边除了读，`load_config` 还要 `qq_db_dir.is_dir()`——
    那是个**外部**目录（QQ 的安装位置），换台机器、换个盘就没有。

    ⚠️ **不隔离的后果是「一批无关用例跟着用户改配置红绿」**：M6 T4 起
    `/api/items`、`/api/items/{id}`、`/api/digests/{id}` 经 `item_out` 现读
    `groups.toml` 取群名（`api.current_config()`，也正是 `test_api._config_for`
    的 docstring 早就点过的那个「假红来源」）。而那份文件**正是 M6 邀请用户
    在网页上改的东西**：用户在「配置」页改个群名或停用群，就会让一批与群配置
    毫无关系的用例变红。

    ⚠️ **只挪根、不写文件**也不行：`load_config` 读不到文件抛 `ConfigError`
    ⇒ 每个走 `/api/*` 的用例都变 500。所以这里在根下写一份**能读通的**最小配置。

    ⚠️ 数据根（`output_db`）同样落在这个 tmp 根下：`groups_snapshot.default_path`
    由它推出来（`output_db.parent / "groups-snapshot.json"`），
    于是「快照会被写到哪里」也一并隔离，不会碰到仓库里真实的 `data/`。

    ⚠️ 路径写**绝对 + posix**：相对路径的解析基准是 `config.REPO_ROOT`
    （**那个**全局没被挪走），而反斜杠是 TOML 基本字符串里的转义字符。

    ⚠️ 用 `mktemp` 而不是 `tmp_path`（理由与上面两道一字不差）：
    有些用例把 `tmp_path` 当**产品目录**用并按**文件集合**断言
    （`tests/test_digest.py` 就是 `sorted(p.name for p in tmp_path.iterdir())`）。

    ⚠️ **M6 T5 起还要写一份 `config/categories.toml`**：`api.categories_path()`
    与 `config_path()` 是**同一个根**，而 `api_categories` / `item_out` 从 T5 起
    都**现读**它。这与 E6（`DEFAULT_LLM_TOML`）是同一族：
    **新增的默认路径常量必须被夹具隔离**，否则测试要么写进真仓库、
    要么跟着用户的配置红绿。
    """
    from vigil import api as _api

    root = tmp_path_factory.mktemp("api_root")
    (root / "config").mkdir()
    (root / "data").mkdir()
    (root / "qqdb").mkdir()
    (root / "config" / "groups.toml").write_text(
        "[settings]\n"
        f'qq_db_dir = "{(root / "qqdb").as_posix()}"\n'
        f'output_db = "{(root / "data" / "vigil.db").as_posix()}"\n'
        "\n"
        "[[groups]]\n"
        "id = 111\n"
        'name = "隔离用群"\n'
        "enabled = true\n",
        encoding="utf-8",
    )
    # ⚠️ M6 T5 起 `api.categories_path()` 也在这个根下现读
    # （`categories_path()` = `REPO_ROOT / "config" / "categories.toml"`），
    # 而它**正是 M6 邀请用户在网页上改的那份文件**（T5 的类目编辑 + T10 的设置页）。
    # 不写这一份的话：`load_categories` 抛"找不到类目配置"⇒ 每个走
    # `/api/categories` 或 `item_out`（它要 `kind_label`）的用例都变 500。
    #
    # ⚠️ **内容自带、不抄仓库里那份真文件**：抄一份等于把「测试红绿取决于用户
    # 的类目配置」这件事留着——用户删掉一个类目，一批无关用例跟着红
    # （与上面 `_isolate_llm_toml_path` 记的假绿是同一族）。这里要的只是
    # 「有一份能读通的类目表」，所以用一份最小的。
    (root / "config" / "categories.toml").write_text(
        _ISOLATED_CATEGORIES_TOML, encoding="utf-8"
    )
    monkeypatch.setattr(_api, "REPO_ROOT", root)


@pytest.fixture(autouse=True)
def _isolate_jobs_registry(monkeypatch):
    """每个用例一份**全新的**后台 job 注册表（M6 T6；勘误 E6 点名要一并考虑的那件）。

    ⚠️ `jobs.registry` 是**模块级单例**（`api.py` 用它），而「同一时刻只许一个
    job」这条守卫（`JobBusy` → 409）看的是**那个进程**里有没有 running 的 job
    ⇒ job 的**残留**天然跨用例可见：`slow_llm` 那类夹具就是**故意**留一个
    running job 的（`test_api_reorder_refuses_a_second_job_while_one_runs`），
    而它的线程要等夹具 teardown 置了那个 Event 之后才把 state 改成 `failed`
    ——**那一步是异步的**，下一个用例若跑在它前面，POST 就会撞 409。

    ⚠️ **实测（T6，2026-09-17）：把这个夹具改成空转，连跑 5 次
    （`tests/test_api.py tests/test_jobs.py tests/test_reorder.py`），
    每次都是 `108 passed`。** 也就是说它今天**不是**一条被逼出来的守卫，
    而是一道**防御**——上面那个竞态窗口确实存在（异步），但 teardown 的
    `gate.set()` 几乎总是先落地。这里**刻意不写「不换就会红」**：那是编的，
    而本项目最贵的一课是**错的论证比没有论证更危险**（勘误 E4/E7）。
    留着它的理由只有一条：这类竞态的失败形态是**环境相关的假红**
    ——只在"恰好来不及"时出现，最难查；而它的代价只是一个 `JobRegistry()`。

    ⚠️ 用 autouse（与上面四道同形）：漏掉一个测试文件就退回"看残留脸色"。
    ⚠️ 造新实例、**不清空旧实例**：旧实例可能正被一个 daemon 线程改着，
    清空它等于让那个线程往一个没人看的对象上写（无害，而且是真实发生的事）。
    """
    from vigil import jobs as _jobs

    monkeypatch.setattr(_jobs, "registry", _jobs.JobRegistry())


@pytest.fixture
def memdb():
    """内存库。用完即弃，不污染任何真实文件。

    ⚠️ `uri=True` 是 Task 5 加的，**必须**：查询层入口会
    `ATTACH 'file:...?mode=ro'`，而 URI 形式**只在连接带 `SQLITE_OPEN_URI`
    时才被解析**（Task 4 实测、T5 复核）。不带这个标志，每条走查询层的用例都会抛
    `OverlayError`——而那不是产品缺陷。对 `:memory:` 而言这个标志
    **不影响任何行为**（路径不以 `file:` 开头时它就是个空开关），
    与生产侧三处连接的补齐（`cli.py` / `digest.py` / `refine.py`，裁决 R4）是同一件事。
    """
    conn = sqlite3.connect(":memory:", uri=True)
    yield conn
    conn.close()


@pytest.fixture
def msg_factory():
    """快速造 PendingMessage。Task 5 的预筛测试要用。"""
    from vigil.store import PendingMessage

    def make(
        msg_id: int,
        content: str,
        *,
        group_id: int = 100,
        ts: int = 1_700_000_000,
        sender: str = "某同学",
        uid: str = "u_x",
    ) -> PendingMessage:
        return PendingMessage(
            msg_id=msg_id,
            group_id=group_id,
            ts=ts,
            sender_uid=uid,
            sender=sender,
            content=content,
        )

    return make
