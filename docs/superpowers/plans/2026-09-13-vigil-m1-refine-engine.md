# VIGIL M1「抽取引擎」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `data/vigil.db` 里 47,719 条非结构化群消息，变成可检索、可回溯的结构化条目表 `items`。

**Architecture:** 一条抽取管线，两个下游视图（日报 / Web）。管线是：取待处理消息 → 本地规则预筛（零 API 成本地砍量）→ 按群聚批并带上下文 → 脱敏 → 批量调 SiliconFlow → 落 `items` 表 + `refine_runs` 记账（保证幂等与增量）。

**Tech Stack:** Python 3.13 / SQLite（stdlib）/ `urllib.request`（stdlib，**不引入新依赖**）/ pytest / SiliconFlow OpenAI 兼容接口

**Spec:** [`docs/superpowers/specs/2026-09-13-vigil-product-layer-design.md`](../specs/2026-09-13-vigil-product-layer-design.md)

---

## Global Constraints

以下约束适用于**每一个**任务，不再逐任务重复。

1. **禁止引入新的运行时依赖。** `pyproject.toml` 的 `dependencies` 保持 `["sqlcipher3>=0.6.2"]`。HTTP 用 stdlib `urllib.request`，JSON 用 stdlib `json`，日期用 stdlib `datetime`。测试依赖 `pytest` 放 `[dependency-groups]`。
2. **所有源码文件用 `from __future__ import annotations` 开头**（跟随 `vigil/` 现有 8 个模块的既有风格）。
3. **所有文件编码 UTF-8**，注释与文档字符串一律中文（跟随现有风格）。
4. **数字列名在 SQL 里必须加双引号**（`"40027"`）。`vigil/` 现有代码已遵守；新代码若碰加密库也必须遵守。⚠️ 实测过：不加引号会被解析成整数字面量，静默返回错数据。
5. **不写 `IN (...)` 查加密库**。新代码只查明文的 `data/vigil.db`，不受此限，但不得在 `vigil/qqdb.py` / `vigil/export.py` 里新增 `IN`。
6. **错误处理策略：配置错 → 快速失败**（抛 `RuntimeError` 子类）；**外部环境错 → 降级并报告**（沿用 `export.py` 里 `senders`/`media` 的既有取舍）。
7. **测试绝不联网、绝不碰真实 QQ 加密库、绝不碰 `data/vigil.db`**。用 `sqlite3.connect(":memory:")` 与构造样本。
8. **任务 4 修改 `tests/conftest.py` 时必须追加而非覆盖**——它已由任务 1 建立。
9. **每个任务一个独立 commit**，消息格式 `feat: ...` / `test: ...` / `chore: ...`。
10. **测试要逐条详情时用 `-vv` 而不是 `-v`**。`pyproject.toml` 里设了 `addopts = "-q"`，而 `-q` 与 `-v` 是互斥的计数器，命令行给一个 `-v` 只够抵消它、看不到逐条结果。`-vv` 才能压过 `-q`。（这是 Task 2 实测踩到的：brief 写 `-v`，实际无逐条输出。）

### 逃逸舱（wave 模式：收紧版）

计划里若出现与实现不符的断言/命令/顺序：

- **pipeline 模式**：按实际情况修正并继续，**无需请示**，但必须在报告里写明偏差。
- **wave 模式（本里程碑）**：**只允许在你自己 `Touches:` 声明的文件范围内修正**。一旦发现需要改动 `Touches:` 之外的文件——**停下，报告 controller，等裁决**。不要用"就改一个文件而已"说服自己越界：同波其它 implementer 可能正在写同一个文件，越界是波内打架的头号入口。

  若某一步**根本走不通**，同样停下报告，不要硬凑一个"看起来通过"的结果。

---

## 与 spec 的四点偏差（实施时按本计划，勿按 spec）

写计划期间用真实数据做了 API 探针（`_probe_refine.py`），实测结果要求对 spec 做四处修正。**执行时以本计划为准。**

| # | spec 原文 | 本计划 | 依据 |
|---|---|---|---|
| 偏差 1 | `items` 表有 `actor_label` 列 | **删除该列** | 代号（`U7`）是 run 内临时映射，落库无意义；原始 `actor_uid` 已在表里，姓名可 JOIN `sender_names` 取回 |
| 偏差 2 | §4.4「高价值群里**全部**消息都进候选」 | 改为「高价值群**不受关键词过滤**，但硬丢弃仍生效」 | 实测班级群 15 条里有 8 条是「已完成」，全喂 LLM 纯属浪费 |
| 偏差 3 | 无 | **新增硬丢弃规则：纯应答**（`已完成`/`收到`/`好的` 整条即此） | 同上，探针实测这 8 条正是「已完成」 |
| 偏差 4 | §4.2 建 `digests` / `digest_items` 表 | **M1 不建这两张表** | 它们属于 M2；M1 建了也没有写入方，违反 YAGNI |

---

## 文件结构

**新建：**

| 文件 | 职责 |
|---|---|
| `vigil/categories.py` | 类目加载与校验；提示词里的类目表由此渲染 |
| `vigil/redact.py` | 发送前脱敏（保姓名、抹号码） + 代号映射器 |
| `vigil/store.py` | 抽取层持久化：建表、取待处理、写 items、记账 |
| `vigil/prefilter.py` | 规则预筛 + 上下文展开 + 切批 |
| `vigil/llm.py` | SiliconFlow 客户端（stdlib urllib，含重试） |
| `vigil/refine.py` | 抽取编排（流水线主入口） |
| `config/categories.toml` | 七个类目的定义（用户已裁定） |
| `tests/conftest.py` | 共享夹具 |
| `tests/test_smoke.py`、`test_categories.py`、`test_redact.py`、`test_store.py`、`test_prefilter.py`、`test_llm.py`、`test_refine.py` | 逐模块测试 |

**修改：**

| 文件 | 改什么 |
|---|---|
| `pyproject.toml` | 加 `[build-system]`、`[project.scripts]`、`[tool.pytest.ini_options]`、`[dependency-groups]` |
| `vigil/config.py` | 加 `tier` 字段 + `load_llm_key()`；抽 `_read_env()` 复用 |
| `vigil/cli.py` | 加 `refine` 子命令 |

**不改：** `export.py` / `reader.py` / `qqdb.py` / `text.py` / `senders.py` / `media.py`。M1 是**新增**，不重构接入层。

---

## 任务依赖

```
Task 1 (骨架)
Task 2 (类目)     ─┐
Task 3 (脱敏)      │
Task 4 (持久化) ───┼─→ Task 7 (编排+CLI) ─→ Task 8 (冒烟验收)
Task 5 (预筛) ←────┤
Task 6 (LLM)  ─────┘
```

Task 4 → Task 5 有依赖（`prefilter` 用 `store.PendingMessage`）。其余 2–6 互不依赖，可并行——但它们都改 `pyproject.toml` 之外的独立文件，**默认走 pipeline 顺序执行**。

---

### Task 1: 测试骨架 + 可执行入口

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/conftest.py`

**Dependencies:** 无

**Touches:** `pyproject.toml`, `tests/conftest.py`, `tests/test_smoke.py`, `uv.lock`

**Interfaces:**
- Consumes: 无
- Produces:
  - pytest 可跑（`tests/` 已配置）
  - 控制台命令 `vigil <子命令>`（替代 `python -m vigil`）
  - `tests/conftest.py` 的 `memdb` 夹具（内存 SQLite）

> **不含日志模块**。spec §4.8 把「日志落文件」归在 M4（自动化的前提），
> M1 阶段 `on_progress` 回调就是进度通道，现在建 `log.py` 没有消费者，
> 是悬空工件。

- [ ] **Step 1: 先跑一次确认现在没有测试设施**

Run: `.venv/Scripts/python.exe -m pytest --version`
Expected: FAIL —— `No module named pytest`（或命令不存在）

- [ ] **Step 2: 配置 pyproject**

修改 `pyproject.toml` 为完整内容：

```toml
[project]
name = "vigil"
version = "0.1.0"
description = "VIGIL 守夜人 —— QQ 群信息聚合器（路线 C：本地数据库旁路）"
requires-python = ">=3.11"
dependencies = ["sqlcipher3>=0.6.2"]

[project.scripts]
vigil = "vigil.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["vigil*"]

[dependency-groups]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

安装：

```bash
uv sync --group dev
uv pip install -e .
```

- [ ] **Step 3: 建 conftest.py**

创建 `tests/conftest.py`：

```python
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


@pytest.fixture
def memdb():
    """内存库。用完即弃，不污染任何真实文件。"""
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()
```

- [ ] **Step 4: 写一个冒烟测试，证明设施真的通了**

创建 `tests/test_smoke.py`：

```python
"""测试设施自检。这个文件本身没有业务价值，
但它让「pytest 能不能跑」这件事有个明确的判据。"""

from __future__ import annotations


def test_pytest_runs():
    assert True


def test_memdb_fixture_works(memdb):
    memdb.execute("CREATE TABLE t (x INTEGER)")
    memdb.execute("INSERT INTO t VALUES (1)")
    assert memdb.execute("SELECT x FROM t").fetchone() == (1,)


def test_vigil_package_is_importable():
    import vigil

    assert vigil.__version__ == "0.1.0"
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 3 passed

- [ ] **Step 6: 验证可执行入口**

Run: `.venv/Scripts/vigil.exe --help`
Expected: 打印 usage，列出 `{groups,export,who,read,media}`

若 `vigil.exe` 不存在，说明 `uv pip install -e .` 没跑成功，回到 Step 2。

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml tests/ uv.lock
git commit -m "chore: 加测试骨架与 vigil 可执行入口"
```

---

### Task 2: 类目体系

**Files:**
- Create: `config/categories.toml`, `vigil/categories.py`, `tests/test_categories.py`

**Dependencies:** [Task 1]

**Touches:** `config/categories.toml`, `vigil/categories.py`, `tests/test_categories.py`

**Interfaces:**
- Consumes: `vigil.config.REPO_ROOT`
- Produces:
  - `vigil.categories.DISCARD: str = "discard"`
  - `vigil.categories.CategoryError(RuntimeError)`
  - `vigil.categories.Category` — frozen dataclass，字段 `slug: str`, `label: str`, `desc: str`, `icon: str`
  - `vigil.categories.load_categories(path: pathlib.Path | None = None) -> tuple[Category, ...]`
  - `vigil.categories.prompt_block(cats: tuple[Category, ...]) -> str`

**为什么做成配置而非硬编码常量**：类目是产品决策，用户已经改过一次（把「二手」「失物招领」从「生活」里拆出来）。写死在代码里，每次调整都要改代码、改测试、重发版。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_categories.py`：

```python
"""类目配置的测试。重点是校验失败路径——配置错要快速失败。"""

from __future__ import annotations

import pytest

from vigil import categories
from vigil.categories import Category, CategoryError


def _write(tmp_path, body: str):
    p = tmp_path / "categories.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_loads_real_project_config():
    """真实配置文件必须能加载，且正是用户裁定的七类。"""
    cats = categories.load_categories()
    assert [c.slug for c in cats] == [
        "notice",
        "academic",
        "activity",
        "life",
        "secondhand",
        "lostfound",
        "job",
    ]
    assert all(c.label and c.desc for c in cats)


def test_rejects_duplicate_slug(tmp_path):
    p = _write(
        tmp_path,
        """
[[categories]]
slug = "notice"
label = "通知"
desc = "正式通知"

[[categories]]
slug = "notice"
label = "重复"
desc = "重复了"
""",
    )
    with pytest.raises(CategoryError, match="重复"):
        categories.load_categories(p)


@pytest.mark.parametrize(
    "bad", ["Notice", "NOTICE", "通知", "2notice", "no-tice", "no.tice", "", "notice "]
)
def test_rejects_non_lowercase_ascii_slug(tmp_path, bad):
    """slug 会进 items.kind 列、提示词、前端筛选键——必须是小写英文标识符。

    `str.isidentifier()` 不够：它放行 `Notice` 与 `通知`（W1 审查实测）。
    """
    p = _write(
        tmp_path,
        f"""
[[categories]]
slug = "{bad}"
label = "x"
desc = "y"
""",
    )
    with pytest.raises(CategoryError):
        categories.load_categories(p)


def test_accepts_underscore_and_digits_after_first_letter(tmp_path):
    p = _write(
        tmp_path,
        """
[[categories]]
slug = "part_time_job2"
label = "x"
desc = "y"
""",
    )
    assert categories.load_categories(p)[0].slug == "part_time_job2"


def test_rejects_discard_as_slug(tmp_path):
    """discard 是保留字（表示「丢弃」），不能当类目名。"""
    p = _write(
        tmp_path,
        """
[[categories]]
slug = "discard"
label = "丢弃"
desc = "假装是个类目"
""",
    )
    with pytest.raises(CategoryError, match="保留字"):
        categories.load_categories(p)


def test_rejects_missing_desc(tmp_path):
    """desc 不是可选的——提示词靠它告诉模型这一类收什么。"""
    p = _write(
        tmp_path,
        """
[[categories]]
slug = "notice"
label = "通知"
""",
    )
    with pytest.raises(CategoryError, match="desc"):
        categories.load_categories(p)


def test_rejects_slug_with_trailing_newline(tmp_path):
    """`^[a-z][a-z0-9_]*$` 的 `$` 允许结尾一个换行，所以 `"notice\\n"` 会被旧正则放行。

    ⚠️ 这里**必须用 TOML 多行字符串**把真换行喂进去：写成单行基本串里的
    `\\n` 转义会被 tomllib 判为非法字符（单行串不允许裸换行），
    测试就会绕过正则、在 TOML 解析层失败——**假绿**。
    所以本用例与下面的 `test_rejects_malformed_toml` 必须分开，
    各自只测一件事。
    """
    p = _write(
        tmp_path,
        '[[categories]]\nslug = """notice\n"""\nlabel = "x"\ndesc = "y"\n',
    )
    with pytest.raises(CategoryError, match="slug 必须匹配"):
        categories.load_categories(p)


@pytest.mark.parametrize(
    "body",
    [
        "[categories]\nslug = 'notice'\nlabel = 'x'\ndesc = 'y'\n",  # 单层方括号（常见笔误）
        "categories = 'oops'\n",  # 字符串
        "categories = [1, 2]\n",  # 是数组，但元素不是表
    ],
)
def test_rejects_wrong_shape_with_category_error(tmp_path, body):
    """配置形状写错也要走 CategoryError，不能甩 AttributeError。

    `[categories]` 与 `[[categories]]` 在 TOML 里只差一层方括号——最常见的笔误。
    不挡的话会去迭代 dict 的键（字符串），下一行 `.get()` 抛 AttributeError，
    同样绕过 cli 只捕 CategoryError 的契约。
    """
    p = _write(tmp_path, body)
    with pytest.raises(CategoryError, match="categories"):
        categories.load_categories(p)


def test_rejects_malformed_toml(tmp_path):
    """TOML 语法错也必须走 CategoryError，而不是甩原始 traceback。

    `tomllib.TOMLDecodeError` 继承自 ValueError 而非 RuntimeError——
    不包的话会绕过 cli 的错误处理契约（cli 只捕 CategoryError）。
    这条是 fix 审查实测抓出来的。
    """
    p = _write(tmp_path, '[[categories]]\nslug = "unclosed\n')
    with pytest.raises(CategoryError, match="TOML"):
        categories.load_categories(p)


def test_rejects_empty_config(tmp_path):
    p = _write(tmp_path, "[settings]\n")
    with pytest.raises(CategoryError, match="空"):
        categories.load_categories(p)


def test_prompt_block_lists_every_slug():
    cats = categories.load_categories()
    block = categories.prompt_block(cats)
    for c in cats:
        assert c.slug in block
        assert c.desc in block
    # 一行一个类目
    assert len(block.splitlines()) == len(cats)


def test_category_is_frozen():
    c = Category(slug="a", label="b", desc="c")
    with pytest.raises(Exception):
        c.slug = "x"  # type: ignore[misc]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_categories.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'vigil.categories'`

- [ ] **Step 3: 写类目配置**

创建 `config/categories.toml`：

```toml
# VIGIL 信息类目
#
# ── 怎么改 ─────────────────────────────────────────────
#   desc 不是注释，它会被逐字渲染进 LLM 的提示词里。
#   想让模型把某类信息分对，就把判据说清楚——写得含糊会导致误分类。
#   改完不需要动代码，下次 vigil refine 即生效。
#
# ── 怎么加类目 ─────────────────────────────────────────
#   复制一段 [[categories]]，slug 用小写英文标识符（唯一、不能是 discard）。
#   加完要重跑 vigil refine --redo 才能对历史消息生效。

[[categories]]
slug = "notice"
label = "通知公告"
icon = "📋"
desc = "辅导员/班主任/班助/老师/管理部门发布的正式通知：办事流程、缴费、体检、材料提交、纪律要求、系统填报、名单统计"

[[categories]]
slug = "academic"
label = "学业"
icon = "📚"
desc = "作业布置与截止、考试安排、课程调整、选课退课、成绩发布、补考重修、四六级、竞赛报名"

[[categories]]
slug = "activity"
label = "活动"
icon = "🎤"
desc = "讲座、社团招新、比赛、晚会、志愿服务、报名征集、参观接待、文体活动"

[[categories]]
slug = "life"
label = "生活"
icon = "🏠"
desc = "食堂、宿舍、水电、校园卡、校车、快递、门禁、维修、医疗、校园周边服务"

[[categories]]
slug = "secondhand"
label = "二手"
icon = "🛒"
desc = "转让、出售、求购物品（教材、电器、自行车、生活用品等），含价格与联系方式求购意向"

[[categories]]
slug = "lostfound"
label = "失物招领"
icon = "🔍"
desc = "寻物启事、失物认领、捡到东西找人、走失找寻（证件、校园卡、钥匙、电子产品等）"

[[categories]]
slug = "job"
label = "兼职招聘"
icon = "💼"
desc = "兼职、实习、校招、家教、勤工助学、课题组招人，含薪酬与联系方式"
```

- [ ] **Step 4: 实现 categories.py**

创建 `vigil/categories.py`：

```python
"""类目配置：从 config/categories.toml 读，校验后供预筛与提示词共用。

为什么不硬编码成常量：类目是产品决策，用户已经改过一次
（把「二手」「失物招领」从「生活」里拆出来）。写死在代码里，
每次调整都要改代码、改测试、重发版。
"""

from __future__ import annotations

import pathlib
import re
import tomllib
from dataclasses import dataclass

from .config import REPO_ROOT

DEFAULT_CATEGORIES = REPO_ROOT / "config" / "categories.toml"

# 保留字：被丢弃的消息在 refine_runs 里记这个值，所以不能用作类目名
DISCARD = "discard"

# slug 会被写进 items.kind 列、渲染进提示词、当作 CLI 与前端的筛选键，
# 所以必须是小写英文标识符。
# ⚠️ 只查 str.isidentifier() 不够——它放行 'Notice' 和 '通知'，
# 而两者都会在下游造成麻烦（W1 审查实测）。用正则收紧。
# ⚠️ 用 \Z 而不是 $：Python 里 $ 允许结尾有一个换行，
# 于是 "notice\n" 会被放行（fix 审查实测）。
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*\Z")


class CategoryError(RuntimeError):
    """类目配置有问题——快速失败。"""


@dataclass(frozen=True)
class Category:
    slug: str
    label: str
    desc: str
    icon: str = ""


def load_categories(path: pathlib.Path | None = None) -> tuple[Category, ...]:
    path = path or DEFAULT_CATEGORIES
    if not path.is_file():
        raise CategoryError(f"找不到类目配置: {path}")

    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        # 必须包成 CategoryError：TOMLDecodeError 继承自 ValueError 而不是
        # RuntimeError，不包的话会绕过 cli 的错误处理契约，用户看到的是
        # 原始 traceback 而不是一行可读的配置错误。
        raise CategoryError(f"{path}: TOML 语法错误——{exc}") from exc

    entries = raw.get("categories")
    # ⚠️ 三个分支不能合并。`[categories]`（单层方括号）与 `[[categories]]` 在 TOML 里
    # 只差一层括号，是极常见的笔误，但解析结果一个是 dict、一个是 list。
    # 不挡的话 `for entry in entries` 会去迭代 dict 的键（字符串），
    # 下一行 `entry.get(...)` 抛 AttributeError——**同样绕过 cli 只捕
    # CategoryError 的契约**，用户看到的是原始 traceback。
    # ⚠️ 顺序也不能反：先判 None 再判类型。反过来的话「根本没写」会被
    # 归到「类型不对」，把「段为空」的专用报错变成不可达代码。
    if entries is None:
        raise CategoryError(f"{path}: [[categories]] 段为空（根本没写）")
    if not isinstance(entries, list):
        raise CategoryError(
            f"{path}: 需要 [[categories]] 数组段（注意是双层方括号），"
            f"实际是 {type(entries).__name__}"
        )
    if not entries:
        raise CategoryError(f"{path}: [[categories]] 段为空（写了个空数组）")

    out: list[Category] = []
    seen: set[str] = set()

    for entry in entries:
        if not isinstance(entry, dict):
            raise CategoryError(
                f"{path}: 每个 [[categories]] 段都必须是键值表，"
                f"实际是 {type(entry).__name__}"
            )
        slug = str(entry.get("slug", ""))
        if not _SLUG_RE.match(slug):
            raise CategoryError(
                f"{path}: slug 必须匹配 {_SLUG_RE.pattern}，实际是 {slug!r}"
            )
        if slug in seen:
            raise CategoryError(f"{path}: slug 重复: {slug}")
        if slug == DISCARD:
            raise CategoryError(f"{path}: {DISCARD!r} 是保留字，不能作类目")
        seen.add(slug)

        desc = str(entry.get("desc", "")).strip()
        if not desc:
            raise CategoryError(f"{path}: 类目 {slug} 缺少 desc（提示词要用它）")

        out.append(
            Category(
                slug=slug,
                label=str(entry.get("label", slug)),
                desc=desc,
                icon=str(entry.get("icon", "")),
            )
        )

    return tuple(out)


def prompt_block(cats: tuple[Category, ...]) -> str:
    """渲染成提示词里的类目表——改 categories.toml 即改提示词。"""
    width = max(len(c.slug) for c in cats)
    return "\n".join(f"{c.slug.ljust(width)}  {c.label}：{c.desc}" for c in cats)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_categories.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add config/categories.toml vigil/categories.py tests/test_categories.py
git commit -m "feat: 加类目配置与校验（七个类目，配置驱动）"
```

---

### Task 3: 脱敏

**Files:**
- Create: `vigil/redact.py`, `tests/test_redact.py`

**Dependencies:** [Task 1]

**Touches:** `vigil/redact.py`, `tests/test_redact.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `vigil.redact.PLACEHOLDER: str = "<号码>"`
  - `vigil.redact.redact_text(text: str) -> str`
  - `vigil.redact.Redactor` — `.group(gid: int) -> str` / `.actor(uid: str) -> str` / `.text(s: str) -> str`

**设计依据（实测）**：真实群昵称形如 `2600090309张韩18368500707`（学号+姓名+手机号）。所以**发信人标签和正文一样需要脱敏**。

**保留姓名是刻意的**：群昵称直接编码了角色（`储运263班主任助理卞雨琦19551968610`），这是判断「谁发的、是不是官方」最可靠的信号，剥掉等于废掉抽取层。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_redact.py`：

```python
"""脱敏的测试。

**样本来源要说清楚**（早期版本的本文件曾声称"全部取自真实数据"，那是错的）：
群昵称样本确实取自本机真实数据（`2600090309张韩18368500707` 一类），
但**正文样本多是构造的**——真实语料里没有恰好可用的例子。
比如 `13812345678` 这个手机号在全库 0 命中，它只是形态正确。
"""

from __future__ import annotations

import pytest

from vigil.redact import PLACEHOLDER, Redactor, redact_text


@pytest.mark.parametrize(
    "raw,expected",
    [
        # 真实群昵称：学号 + 姓名 + 手机号（实测样本）
        ("2600090309张韩18368500707", f"{PLACEHOLDER}张韩{PLACEHOLDER}"),
        ("2600090304杜欣格19850212122", f"{PLACEHOLDER}杜欣格{PLACEHOLDER}"),
        # 姓名保留是关键：它是判断「谁发的」的信号
        ("西太湖新媒体杨馨雅", "西太湖新媒体杨馨雅"),
        # 带角色的昵称，号码抹掉、角色留下
        (
            "储运263班主任助理卞雨琦19551968610",
            f"储运263班主任助理卞雨琦{PLACEHOLDER}",
        ),
        # 只带学号
        ("2600090319储运263林子哲", f"{PLACEHOLDER}储运263林子哲"),
        # 正文里的手机号
        ("有问题打我电话13812345678", f"有问题打我电话{PLACEHOLDER}"),
    ],
)
def test_redacts_numbers_keeps_names(raw, expected):
    assert redact_text(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "截止日期是2026-10-08",
        "9月15日24:00截止",
        "作业截止9月7号",
        "学费4800元",
        "明天下午3点到4点",
        "2026级新生",
    ],
)
def test_does_not_touch_dates_or_amounts(raw):
    """日期与金额必须毫发无伤——打坏了 prompt 就抽不出 deadline。

    连字符与中文让它们不命中 \\d{10,}，这是设计如此，不是巧合。
    """
    assert redact_text(raw) == raw


# ── URL 豁免 ──────────────────────────────────────────────────────
# W1 审查实测：不豁免时全库 34 条链接有 2 条被打烂，
# 都是 B 站分享链的 32 位 hex vd_source。


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.bilibili.com/video/BV1GH4y1H75S/?vd_source=1a2b3c4d5e6f7a8b",
        "报名 https://www.wjx.cn/vm/1788234567890.aspx",
        "https://docs.qq.com/sheet/DR0p1b2M3d4567890123",
        "https://qr.qq.com/q/1234567890123",
        "https://example.com/activity?id=1788234567890&t=1",
    ],
)
def test_urls_are_left_intact(raw):
    """链接必须原样保留——`links` 是 item schema 的一等字段。

    链接里的文档 ID / 分享 token 是结构化标识符，不是手机号或学号；
    抹掉会产出**残废 URL 且是静默的**——没有报错，只是数据错了。
    """
    assert redact_text(raw) == raw


def test_url_exemption_is_scoped():
    """豁免只针对 URL 段——同一行里 URL 之外的号码仍要抹掉。"""
    text = "联系13812345678 报名 https://www.wjx.cn/vm/1788234567890.aspx"
    out = redact_text(text)
    assert "13812345678" not in out
    assert "https://www.wjx.cn/vm/1788234567890.aspx" in out


# ── 身份短号 ──────────────────────────────────────────────────────
# W1 审查实测：QQ 号常见 8 位、群号 9 位，而 LONGNUM 阈值是 10 位
# → 81464214 / 421632774 会原样出网。阈值又不能下调（8 位会打死 20261008），
# 所以只能靠上下文标签。


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("QQ：81464214", f"QQ：{PLACEHOLDER}"),
        ("加我qq 81464214", f"加我qq {PLACEHOLDER}"),
        ("群号 421632774", f"群号 {PLACEHOLDER}"),
        # ↓ 下面四条来自真实语料（fix 审查捞出来的）——第一版规则**全部漏掉**，
        #   因为第一版只枚举了 `QQ|群号|微信` 这类字面标签，而中文写法太散。
        ("加qq群 831560802", f"加qq群 {PLACEHOLDER}"),
        ("QQ通知群：421632774", f"QQ通知群：{PLACEHOLDER}"),
        ("交流群548412164", f"交流群{PLACEHOLDER}"),
        ("q群967911480", f"q群{PLACEHOLDER}"),
        ("微信号：abc123456", "微信号：abc123456"),  # 非纯数字，不该动
    ],
)
def test_redacts_identity_numbers_after_label(raw, expected):
    """**「群」字本身就是标签**——这是第二版修法的核心。"""
    assert redact_text(raw) == expected


def test_identity_rule_leaves_no_residue():
    """12 位数字不该被 `\\d{5,12}` 咬掉一段、留下尾巴。"""
    out = redact_text("群号 123456789012")
    assert "123456789012" not in out
    assert out == f"群号 {PLACEHOLDER}"


@pytest.mark.parametrize("raw", ["第 3 教学楼", "下午 4 点 30 分", "2026 级", "共 12345 人"])
def test_identity_rule_does_not_eat_ordinary_numbers(raw):
    """没有身份标签的普通数字不能被误伤——否则日期地点全毁。"""
    assert redact_text(raw) == raw


@pytest.mark.parametrize("raw", ["第3群有20人", "群里有300多人", "群里一共 120 人"])
def test_group_label_rule_needs_enough_digits(raw):
    """把「群」当标签后，后面的位数必须够长才抹——否则人数、楼号全毁。

    这也是为什么下限是 5 位：队里 3 个人、第 2 群、300 多人，都远短于 5 位。
    """
    assert redact_text(raw) == raw


def test_phone_does_not_leave_residue_in_long_digits():
    """缺数字边界时，13 位数字会被咬掉前 11 位、留下 `90` 的残渣。"""
    out = redact_text("订单号6217001381234567890")
    assert "567890" not in out, "不该留下残渣"
    assert out == f"订单号{PLACEHOLDER}"


# ── 匿名者 ────────────────────────────────────────────────────────


def test_actor_rejects_empty_uid():
    """匿名者没有身份——静默返回共享代号会让模型把不同人当成同一人。"""
    with pytest.raises(ValueError, match="匿名"):
        Redactor().actor("")


def test_actor_rejection_does_not_shift_real_codes():
    """一次误调用不该影响真实 uid 的代号分配（W1 审查实测的隐患）。"""
    r = Redactor()
    with pytest.raises(ValueError):
        r.actor("")
    assert r.actor("u_a") == "U1"
    assert r.actor("u_b") == "U2"


def test_redactor_is_stable_within_run():
    """同一 uid 必须一直拿到同一个代号，否则模型看不出「同一人说了两次」。"""
    r = Redactor()
    assert r.actor("u_a") == r.actor("u_a")
    assert r.actor("u_a") != r.actor("u_b")
    assert r.group(100) == r.group(100)
    assert r.group(100) != r.group(200)


def test_redactor_codes_are_short():
    """代号要短——它们会出现在每一条发给模型的记录里。"""
    r = Redactor()
    assert r.actor("u_first") == "U1"
    assert r.actor("u_second") == "U2"
    assert r.group(999) == "G1"


def test_redactor_text_delegates():
    r = Redactor()
    assert r.text("电话13812345678") == f"电话{PLACEHOLDER}"


def test_handles_empty_and_none_like():
    assert redact_text("") == ""
    assert redact_text("无号码") == "无号码"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_redact.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'vigil.redact'`

- [ ] **Step 3: 实现 redact.py**

创建 `vigil/redact.py`：

```python
"""发送前的脱敏：把能指到具体人的东西挡在本机。

**保留姓名是刻意的**——实测的群昵称直接编码了角色
（「储运263班主任助理卞雨琦19551968610」），这是判断「谁发的、
是不是官方」最可靠的信号，剥掉等于废掉抽取层。

四层遮蔽，各挡一类东西：

1. **URL 段整体豁免**（见 ``redact_text``）——链接里的文档 ID / 分享 token
   是结构化标识符，不是身份号；抹掉会把链接打烂，而 ``links`` 是 item
   schema 的一等字段。**实测依据**：不豁免时全库 34 条链接有 2 条被打烂
   （B 站分享链的 32 位 hex ``vd_source``）。
2. **手机号** —— 两侧带数字边界，不在更长的数字串内部匹配。缺了边界，
   ``1788234567890`` 的前 11 位会被咬掉、留下 ``90`` 的残渣。
3. **长数字串（≥10 位）** —— 学号、订单号一类。
4. **身份标签后的短数字** —— QQ 号常见 8 位、群号 9 位，**位数阈值够不着**，
   只能靠上下文。**实测依据**：不加这条时 ``81464214``（QQ）、
   ``421632774``（群号）会原样出网。

为什么不会误伤日期：``2026-10-08`` 中间的连字符让它不命中 ``\\d{10,}``，
``9月15日`` 同理；身份标签规则要求前面必须有 ``QQ``/``群号`` 之类的词，
所以 ``第 3 教学楼`` 不会被误伤。两条边界都有测试守着。
"""

from __future__ import annotations

import re

PLACEHOLDER = "<号码>"

# 链接：整段豁免。\S+ 是刻意的——QQ 消息里的链接后面常紧跟中文标点。
URL = re.compile(r"https?://\S+|www\.\S+")

# 手机号：11 位、1 开头、第二位 3-9。
# 两侧的数字边界不能省：没有它，13 位的 1788234567890 会被咬掉前 11 位、
# 留下 "90" 这样的残渣（W1 审查实测）。
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

# 学号/订单号一类。10 位是下限：日期与金额远短于此，不会误伤。
LONGNUM = re.compile(r"\d{10,}")

# 身份标签后的短数字。QQ 号/群号常见 5-9 位，位数阈值挡不住，只能靠上下文。
#
# ⚠️ 第一版只枚举了 `QQ|群号|微信` 一类字面标签——**实测几乎没起作用**：
# 真实语料里 5-11 位泄漏只从 107 降到 100。中文写法太散，枚举是打地鼠。
# 关键修法是把 **「群」字本身** 当标签（`交流群548412164`、`QQ通知群：421632774`、
# `加qq群 831560802` 全都以它收口），并加 IGNORECASE 覆盖 qq/Qq/QQ 大小写。
# `(?!\d)` 是防残渣：12 位数字若被 `\d{5,12}` 咬掉前 12 位会留下一位尾巴。
IDENTITY_NUM = re.compile(
    r"((?:qq|Q号|企鹅|群号|学号|工号|微信号|微信|wx|vx|群)\s*[:：]?\s*)"
    r"(\d{5,12})(?!\d)",
    re.IGNORECASE,
)

# ⚠️ `群号` 与 `群` 两个备选**都必须留**，不能只留 `群`：
# 「群号 421632774」里 群 后面跟的是「号」不是数字，光靠 `群` 匹配不上。
# （这条是 controller 誊写计划时删错备选、被自测抓回来的。）


def _redact_segment(text: str) -> str:
    """对**不含 URL** 的片段做遮蔽。"""
    text = IDENTITY_NUM.sub(lambda m: m.group(1) + PLACEHOLDER, text)
    text = PHONE.sub(PLACEHOLDER, text)
    return LONGNUM.sub(PLACEHOLDER, text)


def redact_text(text: str) -> str:
    """抹掉可识别到个人的号码，保留其余一切（含姓名）。

    URL 段**整体豁免**：链接里的文档 ID / 分享 token 是结构化标识符，
    抹掉会把链接打烂，而报名链接正是本项目最想抽出来的东西。
    代价是 URL 里若嵌了手机号会一并放行——这个取舍是刻意的：
    打在链接上的损失是确定的（实测 2/34），而手机号出现在 URL 里极罕见。
    """
    parts: list[str] = []
    last = 0
    for match in URL.finditer(text):
        parts.append(_redact_segment(text[last : match.start()]))
        parts.append(match.group(0))  # URL 原样保留
        last = match.end()
    parts.append(_redact_segment(text[last:]))
    return "".join(parts)


class Redactor:
    """一次 run 内保持代号稳定的映射器。

    映射只活在内存里：`items` 表存的是原始 `group_id` 与 `sender_uid`，
    回填时不需要从代号反解，所以这套映射不落盘——落盘反而是多余的泄漏面。

    ⚠️ ``actor('')`` 会抛 ``ValueError``，这是刻意的。匿名发送者
    （实测全库 1,218 条 = 2.55%）**没有身份可言**：给它们一个共享代号，
    模型就会把互不相识的人当成同一个人。调用方必须对空 uid 特判、
    逐条区分（见 ``refine.build_user_prompt``）。

    至于为什么用 fail-fast 而不是静默返回一个占位符：静默的话，
    一次误调用就会把后续**所有真实 uid 的代号整体错位**（W1 审查实测），
    而错误要到产出质量变差时才被发现——那时已经烧掉一整轮 token 了。
    """

    def __init__(self) -> None:
        self._groups: dict[int, str] = {}
        self._actors: dict[str, str] = {}

    def group(self, gid: int) -> str:
        if gid not in self._groups:
            self._groups[gid] = f"G{len(self._groups) + 1}"
        return self._groups[gid]

    def actor(self, uid: str) -> str:
        if not uid:
            raise ValueError(
                "actor() 不接受空 uid——匿名发送者没有身份，"
                "必须由调用方逐条区分（见 refine.build_user_prompt）"
            )
        if uid not in self._actors:
            self._actors[uid] = f"U{len(self._actors) + 1}"
        return self._actors[uid]

    def text(self, s: str) -> str:
        return redact_text(s)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_redact.py -vv`
Expected: 33 passed

> 数从 16 涨到 33，是 W1 审查后补的覆盖：URL 豁免 6 条、身份短号 8 条、
> 残渣 1 条、匿名者守卫 2 条。原先的 16 条对这三类**零覆盖**。

- [ ] **Step 5: Commit**

```bash
git add vigil/redact.py tests/test_redact.py
git commit -m "feat: 加发送前脱敏（保姓名、抹号码，数字遮蔽不误伤日期）"
```

---

### Task 4: 持久化层

**Files:**
- Create: `vigil/store.py`, `tests/test_store.py`
- Modify: `tests/conftest.py`（追加 `msg_factory` 夹具）

**Dependencies:** [Task 1]

**Touches:** `vigil/store.py`, `tests/test_store.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `vigil.store.STATUS_OK = "ok"` / `STATUS_DISCARDED = "discarded"` / `STATUS_ERROR = "error"`
  - `vigil.store.PendingMessage` — frozen dataclass，字段 `msg_id: int`, `group_id: int`, `ts: int`, `sender_uid: str`, `sender: str`, `content: str`
  - `vigil.store.ExtractedItem` — frozen dataclass，字段 `kind: str`, `title: str`, `detail: str | None`, `event_ts: int`, `deadline_ts: int | None`, `group_id: int`, `actor_uid: str | None`, `place: str | None`, `links: tuple[str, ...]`, `amount: str | None`, `confidence: float`, `src_msg_ids: tuple[int, ...]`
  - `vigil.store.ensure_schema(conn: sqlite3.Connection) -> None`
  - `vigil.store.pending_messages(conn, *, since=None, until=None, limit=None, redo=False) -> list[PendingMessage]`
  - `vigil.store.save_items(conn, items, *, model, prompt_ver, now=None) -> int`
  - `vigil.store.record_run(conn, msg_ids, *, status, prompt_ver, item_count=0, err=None, now=None) -> None`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_store.py`：

```python
"""持久化层的测试。全部用内存库，不碰 data/vigil.db。"""

from __future__ import annotations

import sqlite3

import pytest

from vigil import store
from vigil.store import ExtractedItem, PendingMessage


def _seed_messages(conn: sqlite3.Connection) -> None:
    """造一张最小的 messages + sender_names，形状与 export.py 产出的完全一致。"""
    conn.executescript(
        """
        CREATE TABLE messages (
            msg_id     INTEGER PRIMARY KEY,
            group_id   INTEGER NOT NULL,
            ts         INTEGER NOT NULL,
            sender_uid TEXT,
            content    TEXT NOT NULL
        );
        CREATE TABLE sender_names (
            group_id   INTEGER NOT NULL,
            uid        TEXT    NOT NULL,
            group_nick TEXT,
            qq_nick    TEXT,
            uin        INTEGER,
            in_group   INTEGER,
            PRIMARY KEY (group_id, uid)
        );
        """
    )
    conn.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        [
            (1, 100, 1000, "u_a", "明天有讲座"),
            (2, 100, 2000, "u_b", "收到"),
            (3, 200, 3000, "u_a", "二手自行车出"),
        ],
    )
    conn.executemany(
        "INSERT INTO sender_names VALUES (?,?,?,?,?,?)",
        [
            (100, "u_a", "张三", "三三", 111, 0),
            (100, "u_b", None, "李四", 222, 0),
            (200, "u_a", "张三", "三三", 111, 0),
        ],
    )
    conn.commit()


def test_ensure_schema_is_idempotent(memdb):
    store.ensure_schema(memdb)
    store.ensure_schema(memdb)
    names = {
        r[0]
        for r in memdb.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"items", "item_sources", "refine_runs"} <= names


def test_pending_messages_resolves_sender_name(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    pending = store.pending_messages(memdb)
    assert len(pending) == 3
    # 群昵称优先于 QQ 昵称
    assert pending[0].sender == "张三"
    # 群昵称为空时退回 QQ 昵称
    assert pending[1].sender == "李四"


def test_pending_messages_orders_by_time(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    assert [m.msg_id for m in store.pending_messages(memdb)] == [1, 2, 3]


def test_pending_messages_skips_already_run(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    store.record_run(memdb, [1], status=store.STATUS_OK, prompt_ver="v1")
    assert [m.msg_id for m in store.pending_messages(memdb)] == [2, 3]


def test_pending_messages_retries_error_rows(memdb):
    """⚠️ error 行必须被重试，不能当成「已处理」（Task 7 审查实测抓出）。

    写成 `NOT IN (SELECT msg_id FROM refine_runs)` 的话，一次网络抖动
    （429/超时）就会把那批消息**永久跳过**，且没有任何自动重试机制——
    静默的永久数据丢失。error 的语义是「试过但没成功」，不是「已处理」。
    """
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    store.record_run(memdb, [1], status=store.STATUS_OK, prompt_ver="v1")
    store.record_run(memdb, [2], status=store.STATUS_ERROR, prompt_ver="v1", err="429")
    store.record_run(memdb, [3], status=store.STATUS_DISCARDED, prompt_ver="v1")

    # 只有 error 那条会被重新取出——ok 与 discarded 都算真处理过了
    assert [m.msg_id for m in store.pending_messages(memdb)] == [2]


def test_redo_returns_everything(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    store.record_run(memdb, [1, 2, 3], status=store.STATUS_OK, prompt_ver="v1")
    assert len(store.pending_messages(memdb, redo=True)) == 3


def test_pending_messages_respects_window_and_limit(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    assert [m.msg_id for m in store.pending_messages(memdb, since=2000)] == [2, 3]
    assert [m.msg_id for m in store.pending_messages(memdb, until=2000)] == [1]
    assert len(store.pending_messages(memdb, limit=2)) == 2


def test_save_items_writes_sources(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    item = ExtractedItem(
        kind="activity",
        title="西太湖报告厅有讲座",
        detail=None,
        event_ts=1000,
        deadline_ts=None,
        group_id=100,
        actor_uid="u_a",
        place="西太湖报告厅",
        links=(),
        amount=None,
        confidence=0.9,
        src_msg_ids=(1,),
    )
    assert store.save_items(memdb, [item], model="m", prompt_ver="v1", now=42) == 1

    row = memdb.execute(
        "SELECT kind, title, deadline_ts, actor_uid, created_at FROM items"
    ).fetchone()
    assert row == ("activity", "西太湖报告厅有讲座", None, "u_a", 42)
    assert memdb.execute("SELECT item_id, msg_id FROM item_sources").fetchall() == [(1, 1)]


def test_save_items_roundtrips_links(memdb):
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    item = ExtractedItem(
        kind="notice", title="报名", detail=None, event_ts=1000, deadline_ts=None,
        group_id=100, actor_uid=None, place=None,
        links=("https://example.com/a", "https://example.com/b"),
        amount=None, confidence=0.5, src_msg_ids=(1,),
    )
    store.save_items(memdb, [item], model="m", prompt_ver="v1")
    raw = memdb.execute("SELECT links FROM items").fetchone()[0]
    assert "example.com/a" in raw and "example.com/b" in raw


def test_record_run_is_idempotent(memdb):
    store.ensure_schema(memdb)
    store.record_run(memdb, [7], status=store.STATUS_OK, prompt_ver="v1", item_count=2)
    store.record_run(memdb, [7], status=store.STATUS_DISCARDED, prompt_ver="v2")
    rows = memdb.execute("SELECT msg_id, status, prompt_ver FROM refine_runs").fetchall()
    assert rows == [(7, "discarded", "v2")]


def test_item_sources_supports_reverse_lookup(memdb):
    """『这条消息产出了哪条 item』必须可查——避免重复抽取靠它。"""
    _seed_messages(memdb)
    store.ensure_schema(memdb)
    item = ExtractedItem(
        kind="notice", title="t", detail=None, event_ts=1000, deadline_ts=None,
        group_id=100, actor_uid=None, place=None, links=(), amount=None,
        confidence=0.5, src_msg_ids=(1, 2),
    )
    store.save_items(memdb, [item], model="m", prompt_ver="v1")
    by_msg = memdb.execute(
        "SELECT item_id FROM item_sources WHERE msg_id = ?", (2,)
    ).fetchall()
    assert by_msg == [(1,)]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_store.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'vigil.store'`

- [ ] **Step 3: 给 conftest 追加夹具**

在 `tests/conftest.py` **末尾追加**（不要覆盖已有内容）：

```python
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
```

- [ ] **Step 4: 实现 store.py**

创建 `vigil/store.py`：

```python
"""抽取层的持久化：建表、取待处理消息、写 items、记账。

表建在 data/vigil.db（与 messages 同库），这样「条目 → 源消息」
可以纯 SQL JOIN，不需要跨库。

`digests` / `digest_items` 属于 M2，本模块不建——M1 建了也没有写入方。
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass

STATUS_OK = "ok"
STATUS_DISCARDED = "discarded"
STATUS_ERROR = "error"

# items：结构化条目，日报与 Web 都是它的视图
_ITEMS_DDL = """
CREATE TABLE IF NOT EXISTS items (
    item_id     INTEGER PRIMARY KEY,
    kind        TEXT    NOT NULL,
    title       TEXT    NOT NULL,
    detail      TEXT,
    event_ts    INTEGER NOT NULL,
    deadline_ts INTEGER,
    group_id    INTEGER NOT NULL,
    actor_uid   TEXT,
    place       TEXT,
    links       TEXT,
    amount      TEXT,
    confidence  REAL    NOT NULL,
    model       TEXT    NOT NULL,
    prompt_ver  TEXT    NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS items_kind_ts  ON items(kind,     event_ts DESC);
CREATE INDEX IF NOT EXISTS items_group_ts ON items(group_id, event_ts DESC);
CREATE INDEX IF NOT EXISTS items_deadline ON items(deadline_ts)
    WHERE deadline_ts IS NOT NULL;
"""

# item_sources：可回溯。独立成表而非 JSON 数组，因为要双向查——
# 「这条 item 来自哪几条消息」和「这条消息产出了哪条 item」都要快。
_SOURCES_DDL = """
CREATE TABLE IF NOT EXISTS item_sources (
    item_id INTEGER NOT NULL,
    msg_id  INTEGER NOT NULL,
    PRIMARY KEY (item_id, msg_id)
);
CREATE INDEX IF NOT EXISTS item_sources_msg ON item_sources(msg_id);
"""

# refine_runs：幂等与增量的依据。一条消息一行，重跑跳过已处理的。
_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS refine_runs (
    msg_id     INTEGER PRIMARY KEY,
    refined_at INTEGER NOT NULL,
    status     TEXT    NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    prompt_ver TEXT    NOT NULL,
    err        TEXT
);
"""

SCHEMA_DDL = _ITEMS_DDL + _SOURCES_DDL + _RUNS_DDL


@dataclass(frozen=True)
class PendingMessage:
    """待抽取的一条消息，姓名已解析好。"""

    msg_id: int
    group_id: int
    ts: int
    sender_uid: str
    sender: str
    content: str


@dataclass(frozen=True)
class ExtractedItem:
    """一条结构化条目。src_msg_ids 让它可回溯到原文。"""

    kind: str
    title: str
    detail: str | None
    event_ts: int
    deadline_ts: int | None
    group_id: int
    actor_uid: str | None
    place: str | None
    links: tuple[str, ...]
    amount: str | None
    confidence: float
    src_msg_ids: tuple[int, ...]


def ensure_schema(conn: sqlite3.Connection) -> None:
    """建表。幂等——每次 refine 都调，不靠外部迁移工具。"""
    conn.executescript(SCHEMA_DDL)
    conn.commit()


def pending_messages(
    conn: sqlite3.Connection,
    *,
    since: int | None = None,
    until: int | None = None,
    limit: int | None = None,
    redo: bool = False,
) -> list[PendingMessage]:
    """取待抽取的消息，按时间升序（时间序是上下文与切批的前提）。

    不在这里过滤 `[非文本]`——硬丢弃是预筛层的职责，
    这样 refine_runs 才能覆盖全部消息（M1 出口标准要求无遗漏）。
    """
    sql = """
        SELECT m.msg_id, m.group_id, m.ts,
               COALESCE(m.sender_uid, '') AS uid,
               COALESCE(NULLIF(s.group_nick, ''), NULLIF(s.qq_nick, ''), '') AS sender,
               m.content
        FROM messages m
        LEFT JOIN sender_names s
               ON s.group_id = m.group_id AND s.uid = m.sender_uid
    """
    where: list[str] = []
    params: list[object] = []

    if not redo:
        # ⚠️ 必须排除 error 行重试，不能把它们当成「已处理」。
        # 写成 `NOT IN (SELECT msg_id FROM refine_runs)` 的话，一次网络抖动
        # （429/超时）就会把那批消息**永久跳过**，且没有任何自动重试机制——
        # 静默的永久数据丢失。error 行是「试过但没成功」，不是「已处理」。
        where.append(
            "m.msg_id NOT IN (SELECT msg_id FROM refine_runs WHERE status != ?)"
        )
        params.append(STATUS_ERROR)
    if since is not None:
        where.append("m.ts >= ?")
        params.append(since)
    if until is not None:
        where.append("m.ts < ?")
        params.append(until)

    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY m.ts ASC, m.msg_id ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)

    return [PendingMessage(*row) for row in conn.execute(sql, params)]


def save_items(
    conn: sqlite3.Connection,
    items: list[ExtractedItem],
    *,
    model: str,
    prompt_ver: str,
    now: int | None = None,
) -> int:
    """写 items 与它们的来源，返回写入条数。"""
    stamp = int(time.time()) if now is None else now
    for item in items:
        cur = conn.execute(
            "INSERT INTO items (kind, title, detail, event_ts, deadline_ts,"
            " group_id, actor_uid, place, links, amount, confidence,"
            " model, prompt_ver, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item.kind,
                item.title,
                item.detail,
                item.event_ts,
                item.deadline_ts,
                item.group_id,
                item.actor_uid,
                item.place,
                json.dumps(list(item.links), ensure_ascii=False),
                item.amount,
                item.confidence,
                model,
                prompt_ver,
                stamp,
            ),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO item_sources (item_id, msg_id) VALUES (?, ?)",
            [(cur.lastrowid, mid) for mid in item.src_msg_ids],
        )
    conn.commit()
    return len(items)


def record_run(
    conn: sqlite3.Connection,
    msg_ids: list[int] | tuple[int, ...],
    *,
    status: str,
    prompt_ver: str,
    item_count: int = 0,
    err: str | None = None,
    now: int | None = None,
) -> None:
    """记账。用 REPLACE 保证重跑时是更新而非重复插入。"""
    if not msg_ids:
        return
    stamp = int(time.time()) if now is None else now
    conn.executemany(
        "INSERT OR REPLACE INTO refine_runs"
        " (msg_id, refined_at, status, item_count, prompt_ver, err)"
        " VALUES (?,?,?,?,?,?)",
        [(mid, stamp, status, item_count, prompt_ver, err) for mid in msg_ids],
    )
    conn.commit()
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_store.py -v`
Expected: 10 passed

- [ ] **Step 6: Commit**

```bash
git add vigil/store.py tests/test_store.py tests/conftest.py
git commit -m "feat: 加抽取层持久化（items/item_sources/refine_runs 三表）"
```

---

### Task 5: 规则预筛与切批

**Files:**
- Create: `vigil/prefilter.py`, `tests/test_prefilter.py`
- Modify: `vigil/config.py`（加 `Group.tier` 字段）

**Dependencies:** [Task 1, Task 4]

**Touches:** `vigil/prefilter.py`, `tests/test_prefilter.py`, `vigil/config.py`, `config/groups.toml`

**Interfaces:**
- Consumes: `vigil.store.PendingMessage`（Task 4）、`vigil.text.NON_TEXT`
- Produces:
  - `vigil.config.Group.tier: str`（默认 `"normal"`）；`Config.tier_of(gid: int) -> str`
  - `vigil.prefilter.DEFAULT_KEYWORDS: frozenset[str]`
  - `vigil.prefilter.ROLE_PATTERN: re.Pattern[str]`
  - `vigil.prefilter.MIN_BYTES: int = 4`
  - `vigil.prefilter.Candidate` — frozen dataclass，字段 `msg_id, group_id, ts, sender, content, reason: str`
  - `vigil.prefilter.ScreenStats` — 可变 dataclass，计数字段见下
  - `vigil.prefilter.screen(messages, *, tier_of, keywords=DEFAULT_KEYWORDS) -> tuple[list[Candidate], ScreenStats]`
  - `vigil.prefilter.expand_context(messages, candidates, *, context=2) -> list[PendingMessage]`
  - `vigil.prefilter.make_batches(messages, *, max_batch=30) -> list[list[PendingMessage]]`

**这是省钱的地方**：全量直喂 LLM 按探针实测约 3.7M 输入 token，预筛能再降一个数量级。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_prefilter.py`：

```python
"""规则预筛的测试。

用例尽量取自探针实跑到的真实消息——尤其那 8 条「已完成」，
它们正是「纯应答」规则的由来。
"""

from __future__ import annotations

import pytest

from vigil import prefilter
from vigil.prefilter import Candidate, screen, expand_context, make_batches

HIGH = lambda gid: "high"    # noqa: E731
NORMAL = lambda gid: "normal"  # noqa: E731


def _keep_ids(cands):
    return {c.msg_id for c in cands}


# ── 硬丢弃 ────────────────────────────────────────────


def test_drops_non_text(msg_factory):
    msgs = [msg_factory(1, "[非文本]")]
    kept, stats = screen(msgs, tier_of=HIGH)
    assert kept == []
    assert stats.dropped_empty == 1


def test_drops_too_short(msg_factory):
    msgs = [msg_factory(1, "1"), msg_factory(2, "dd"), msg_factory(3, "好")]
    kept, stats = screen(msgs, tier_of=HIGH)
    assert kept == []
    assert stats.dropped_short == 3


def test_drops_bad_timestamp(msg_factory):
    """1970-01-01 的脏数据（实测存在于多个群）。"""
    msgs = [msg_factory(1, "这里有通知请查收", ts=0)]
    kept, stats = screen(msgs, tier_of=HIGH)
    assert kept == []
    assert stats.dropped_bad_time == 1


@pytest.mark.parametrize("text", ["已完成", "收到", "好的", "好的！", "嗯嗯", "OK", "知道了"])
def test_drops_bare_acknowledgements(msg_factory, text):
    """探针实测：班级群 15 条里 8 条是「已完成」，纯噪声。"""
    kept, stats = screen([msg_factory(1, text)], tier_of=HIGH)
    assert kept == []
    assert stats.dropped_ack == 1


def test_keeps_ack_with_substance(msg_factory):
    """「收到」后面跟真东西的不能丢。"""
    kept, _ = screen([msg_factory(1, "收到，明天9点在西太湖集合")], tier_of=HIGH)
    assert _keep_ids(kept) == {1}


def test_drops_flood(msg_factory):
    """同一人 60 秒内连发 3 条一样的——广告号刷屏的形态。"""
    msgs = [
        msg_factory(i, "校园卡办理 联系QQ123", ts=1000 + i, uid="spammer")
        for i in range(3)
    ]
    kept, stats = screen(msgs, tier_of=NORMAL)
    assert kept == []
    assert stats.dropped_flood == 3


def test_flood_does_not_catch_different_people(msg_factory):
    """不同人各说一次「已完成」不是刷屏（实测的班级群就是这形态）。"""
    msgs = [
        msg_factory(i, "已完成", ts=1000 + i, uid=f"u{i}")
        for i in range(8)
    ]
    kept, stats = screen(msgs, tier_of=HIGH)
    # 被「纯应答」挡掉，而不是被刷屏挡掉
    assert stats.dropped_ack == 8
    assert stats.dropped_flood == 0


def test_flood_does_not_cross_groups(msg_factory):
    """**同一个人**在不同群转发同一条通知，不该被判刷屏。

    ⚠️ uid 必须是**非空**的。写成匿名者的话，消息会被 `_flood_ids` 开头的
    「跳过匿名者」分支先拦下，测试就退化成**空守卫**——把 `group_id` 从桶键里
    删掉也照样绿（W2 审查用变异测试实测抓出：29 条测试全绿）。

    这条守的是「**桶键必须含 group_id**」。
    """
    msgs = [
        msg_factory(
            i, "转发通知：明天停课", ts=1000 + i, group_id=gid, uid="u_forwarder"
        )
        for i, gid in enumerate([100, 200, 300], start=1)
    ]
    kept, stats = screen(msgs, tier_of=NORMAL)
    assert stats.dropped_flood == 0, "同人跨群的同内容不该判为刷屏"
    assert _keep_ids(kept) == {1, 2, 3}


def test_flood_does_not_catch_anonymous_across_groups(msg_factory):
    """匿名者在不同群发同样的话，不该被判刷屏。

    ⚠️ 这条与上一条守的是**不同**的规则：这条守「**跳过匿名者**」，
    上一条守「桶键含 group_id」。

    两者**必须分开写**。合成一条的话，「跳过匿名者」分支会先命中，
    从而把 `group_id` 的缺失整个掩盖掉——这正是第一条测试最初的写法错误。
    """
    msgs = [
        msg_factory(i, "转发通知：明天停课", ts=1000 + i, group_id=gid, uid="")
        for i, gid in enumerate([100, 200, 300], start=1)
    ]
    kept, stats = screen(msgs, tier_of=NORMAL)
    assert stats.dropped_flood == 0, "匿名者的同内容不该判为刷屏"
    assert _keep_ids(kept) == {1, 2, 3}


def test_flood_ignores_anonymous_senders(msg_factory):
    """匿名者（uid 为空串）不参与刷屏判定——**空串不是身份**。

    实测全库 1,218 条（2.55%）匿名消息；把空串当桶键等于把互不相识的人
    当成同一个人。
    """
    msgs = [
        msg_factory(i, "校园卡办理联系我", ts=1000 + i, group_id=100, uid="")
        for i in range(3)
    ]
    _, stats = screen(msgs, tier_of=NORMAL)
    assert stats.dropped_flood == 0


def test_flood_still_catches_same_group_spammer(msg_factory):
    """收紧之后，真正的同群刷屏仍必须被抓住——别把修复做成功能阉割。"""
    msgs = [
        msg_factory(i, "校园卡办理 联系QQ123", ts=1000 + i, group_id=100, uid="spammer")
        for i in range(3)
    ]
    kept, stats = screen(msgs, tier_of=NORMAL)
    assert kept == []
    assert stats.dropped_flood == 3


# ── 保留 ──────────────────────────────────────────────


def test_high_tier_keeps_non_keyword_messages(msg_factory):
    """班级群里「看着像闲聊」的往往是真通知，不敢用关键词过滤。"""
    kept, _ = screen([msg_factory(1, "大家记得把那个表弄一下")], tier_of=HIGH)
    assert _keep_ids(kept) == {1}
    assert kept[0].reason == "high_tier"


def test_normal_tier_needs_keyword(msg_factory):
    kept, _ = screen([msg_factory(1, "大家记得把那个表弄一下")], tier_of=NORMAL)
    assert kept == []


def test_normal_tier_keeps_keyword_hit(msg_factory):
    kept, _ = screen([msg_factory(1, "明天讲座地点改到报告厅")], tier_of=NORMAL)
    assert _keep_ids(kept) == {1}
    assert kept[0].reason == "keyword"


def test_normal_tier_keeps_role_sender(msg_factory):
    """辅导员/班助发的，即使不含关键词也要留。"""
    msgs = [msg_factory(1, "大家把那个弄一下", sender="储运263班主任助理卞雨琦")]
    kept, _ = screen(msgs, tier_of=NORMAL)
    assert _keep_ids(kept) == {1}
    assert kept[0].reason == "role"


def test_stats_counts_everything(msg_factory):
    msgs = [
        msg_factory(1, "[非文本]"),
        msg_factory(2, "1"),
        msg_factory(3, "明天讲座在报告厅"),
    ]
    _, stats = screen(msgs, tier_of=NORMAL)
    assert stats.total == 3
    assert stats.kept == 1
    assert stats.dropped_empty == 1
    assert stats.dropped_short == 1


# ── 上下文展开 ────────────────────────────────────────


def test_expand_context_includes_neighbours(msg_factory):
    """单条消息常常没头没尾（「明天记得带」），邻居能救回这类。"""
    msgs = [msg_factory(i, f"第{i}条", ts=1000 + i) for i in range(1, 8)]
    cands = [Candidate(msg_id=4, group_id=100, ts=1004, sender="x",
                       content="第4条", reason="keyword")]
    out = expand_context(msgs, cands, context=2)
    assert [m.msg_id for m in out] == [2, 3, 4, 5, 6]


def test_expand_context_clamps_at_edges(msg_factory):
    msgs = [msg_factory(i, f"第{i}条", ts=1000 + i) for i in range(1, 4)]
    cands = [Candidate(msg_id=1, group_id=100, ts=1001, sender="x",
                       content="第1条", reason="keyword")]
    out = expand_context(msgs, cands, context=2)
    assert [m.msg_id for m in out] == [1, 2, 3]


def test_expand_context_does_not_cross_groups(msg_factory):
    """邻居必须是同群的——跨群拼接会让上下文完全错位。"""
    msgs = [
        msg_factory(1, "群A第1条", group_id=100, ts=1000),
        msg_factory(2, "群A第2条", group_id=100, ts=1001),
        msg_factory(3, "群B第1条", group_id=200, ts=1002),
        msg_factory(4, "群B第2条", group_id=200, ts=1003),
    ]
    cands = [Candidate(msg_id=2, group_id=100, ts=1001, sender="x",
                       content="群A第2条", reason="keyword")]
    out = expand_context(msgs, cands, context=5)
    assert [m.msg_id for m in out] == [1, 2]


def test_expand_context_zero_is_passthrough(msg_factory):
    msgs = [msg_factory(i, f"第{i}条", ts=1000 + i) for i in range(1, 4)]
    cands = [Candidate(msg_id=2, group_id=100, ts=1002, sender="x",
                       content="第2条", reason="keyword")]
    assert [m.msg_id for m in expand_context(msgs, cands, context=0)] == [2]


def test_expand_context_dedupes_overlapping_windows(msg_factory):
    msgs = [msg_factory(i, f"第{i}条", ts=1000 + i) for i in range(1, 6)]
    cands = [
        Candidate(msg_id=2, group_id=100, ts=1002, sender="x", content="第2条", reason="k"),
        Candidate(msg_id=3, group_id=100, ts=1003, sender="x", content="第3条", reason="k"),
    ]
    out = expand_context(msgs, cands, context=1)
    assert [m.msg_id for m in out] == [1, 2, 3, 4]


# ── 切批 ──────────────────────────────────────────────


def test_make_batches_splits_by_group(msg_factory):
    msgs = [
        msg_factory(1, "a", group_id=100),
        msg_factory(2, "b", group_id=100),
        msg_factory(3, "c", group_id=200),
    ]
    batches = make_batches(msgs, max_batch=30)
    assert [[m.msg_id for m in b] for b in batches] == [[1, 2], [3]]


def test_make_batches_respects_max(msg_factory):
    msgs = [msg_factory(i, f"第{i}条", group_id=100) for i in range(1, 8)]
    batches = make_batches(msgs, max_batch=3)
    assert [len(b) for b in batches] == [3, 3, 1]


def test_make_batches_empty():
    assert make_batches([]) == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prefilter.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'vigil.prefilter'`

- [ ] **Step 3: 给 config.py 加 tier 字段**

修改 `vigil/config.py`。把 `Group` 定义（第 23–27 行附近）改为：

```python
# 群分级：high = 不受关键词过滤（班级群/课程群/部门群里的
# 「闲聊」往往是真通知）；normal = 需要关键词或角色昵称命中。
TIER_HIGH = "high"
TIER_NORMAL = "normal"
VALID_TIERS = frozenset({TIER_HIGH, TIER_NORMAL})


@dataclass(frozen=True)
class Group:
    id: int
    name: str
    enabled: bool = True
    tier: str = TIER_NORMAL
```

把 `Config` 类改为（加 `tier_of` 方法）：

```python
@dataclass(frozen=True)
class Config:
    qq_db_dir: pathlib.Path
    output_db: pathlib.Path
    groups: tuple[Group, ...]

    @property
    def enabled_groups(self) -> tuple[Group, ...]:
        return tuple(g for g in self.groups if g.enabled)

    def group_name(self, gid: int) -> str:
        for g in self.groups:
            if g.id == gid:
                return g.name
        return ""

    def tier_of(self, gid: int) -> str:
        """未知群的默认档位是 normal——保守，宁可多筛不可漏喂。"""
        for g in self.groups:
            if g.id == gid:
                return g.tier
        return TIER_NORMAL
```

把 `load_config` 里构造 `Group` 的那段（第 76–78 行附近）改为：

```python
        tier = str(entry.get("tier", TIER_NORMAL))
        if tier not in VALID_TIERS:
            raise ConfigError(
                f"{path}: 群 {gid} 的 tier 只能是 {sorted(VALID_TIERS)}，实际是 {tier!r}"
            )
        groups.append(
            Group(
                id=gid,
                name=entry.get("name", ""),
                enabled=entry.get("enabled", True),
                tier=tier,
            )
        )
```

然后在 `config/groups.toml` 里，给班级群/课程群/部门群等加 `tier = "high"`。至少这几条：

```toml
[[groups]]
id = 1074335063
name = "储运263班级群"
enabled = true
tier = "high"

[[groups]]
id = 740631117
name = "2026级石工本科生群"
enabled = true
tier = "high"

[[groups]]
id = 1124073041
name = "26级高数（一）储运"
enabled = true
tier = "high"

[[groups]]
id = 1046517740
name = "2026级储运工程制图"
enabled = true
tier = "high"

[[groups]]
id = 1101855355
name = "26级宿舍长"
enabled = true
tier = "high"

[[groups]]
id = 1055988015
name = "263团员小群"
enabled = true
tier = "high"

[[groups]]
id = 1109468222
name = "求索技术部的小窝"
enabled = true
tier = "high"

[[groups]]
id = 932222509
name = "西太湖新媒体部门招新群"
enabled = true
tier = "high"
```

其余群（新生群 643375490、二手群、跑团群、资料分享群等）保持默认 `normal`——新生群一个群就有 44,935 条，是成本大头，必须靠关键词筛。

- [ ] **Step 4: 实现 prefilter.py**

创建 `vigil/prefilter.py`：

```python
"""规则预筛：先在本机零成本地砍掉大半消息，再交给 LLM。

这是省钱的地方——全量直喂 LLM 按探针实测约 3.7M 输入 token，
预筛能再降一个数量级。

判定顺序是**先丢弃后保留**：硬丢弃规则优先，命中即丢，
不给保留规则翻案的机会。理由——「已完成」这类消息在班级群里
是 tier=high，若让保留规则先跑就会被全部喂给模型（探针实测
15 条里 8 条是「已完成」）。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from .store import PendingMessage
from .text import NON_TEXT

# 短于这个字节数的消息没有信息量。用字节而非字符：
# 「好的」是 6 字节、单字「好」是 3 字节，按字符算会全放进来。
MIN_BYTES = 4

# 关键词表。刻意**不用**「时间」「地点」「收」「出」这类高频词——
# 它们几乎命中一切，等于没筛。
DEFAULT_KEYWORDS = frozenset(
    """
    通知 报名 截止 考试 作业 选课 讲座 招新 面试 成绩 体检 缴费 办理 领取
    登记 补考 四六级 重修 报到 注册 提交 填写 会议 集合 培训 公示 名单
    转让 出售 求购 拼车 租房 兼职 招聘 实习 校招 家教 勤工 日结
    丢失 拾到 捡到 失物 认领 招领 寻物 换 退 补
    """.split()
)

# 群昵称里编码了角色——这是判断发送者是否"官方"的可用信号。
# 实测：'储运263班主任助理卞雨琦'、'西太湖新媒体杨馨雅'。
ROLE_PATTERN = re.compile(
    r"辅导员|班主任|班助|老师|教师|助理|管理员|部长|主席|团长|队长|负责人|学长|学姐"
)

# 整条消息就是一句应答，没有信息量。
# 必须是**全匹配**——「收到，明天9点集合」不能被丢。
BARE_ACK = re.compile(
    r"^(已(完成|收到|填写|填好|交|办|知)|收到|好(的)?|嗯+|哦+|谢谢?|ok|OK|"
    r"知道(了)?|行|1|✓|👌)[!！。.~～、\s]*$"
)


@dataclass(frozen=True)
class Candidate:
    """一条被判定为值得抽取的消息。reason 用于观测与调参。"""

    msg_id: int
    group_id: int
    ts: int
    sender: str
    content: str
    reason: str


@dataclass
class ScreenStats:
    total: int = 0
    kept: int = 0
    dropped_empty: int = 0
    dropped_short: int = 0
    dropped_bad_time: int = 0
    dropped_ack: int = 0
    dropped_flood: int = 0
    kept_high_tier: int = 0
    kept_keyword: int = 0
    kept_role: int = 0

    @property
    def dropped(self) -> int:
        return (
            self.dropped_empty
            + self.dropped_short
            + self.dropped_bad_time
            + self.dropped_ack
            + self.dropped_flood
        )


def _normalized(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _flood_ids(
    messages: Sequence[PendingMessage], *, window: int = 60, threshold: int = 3
) -> set[int]:
    """找出刷屏消息：**同一群内**同一 uid 在 window 秒内发出 threshold 条以上相同内容。

    ⚠️ 两个约束都不能少——W1 波级审查实测抓出的缺陷，改前先读懂为什么：

    * **必须按群分桶**。只按 (uid, 内容) 分桶会让全部 15 个群的匿名者
      共用同一个桶：三个群的匿名者 60 秒内转发同一条通知，就会被误判成
      「刷屏」整批丢掉——而**被转发的通知恰恰是本项目最想保住的东西**。
    * **匿名者（uid 为空串）整体跳过**。实测全库 1,218 条（2.55%）匿名消息；
      `pending_messages` 把 NULL uid 规范化成 `''`，而**空串不是身份**——
      拿它当桶键等于把互不相识的人当成同一个人。
    """
    buckets: dict[tuple[int, str, str], list[PendingMessage]] = {}
    for m in messages:
        if not m.sender_uid:  # 匿名者无法归属身份，不参与刷屏判定
            continue
        body = _normalized(m.content)
        if not body:
            continue
        buckets.setdefault((m.group_id, m.sender_uid, body), []).append(m)

    out: set[int] = set()
    for group in buckets.values():
        if len(group) < threshold:
            continue
        group.sort(key=lambda m: m.ts)
        for i in range(len(group) - threshold + 1):
            if group[i + threshold - 1].ts - group[i].ts <= window:
                out.update(m.msg_id for m in group[i : i + threshold])
    return out


def _drop_reason(m: PendingMessage, *, flood: set[int]) -> str | None:
    """硬丢弃。返回原因码，None 表示没被丢弃。"""
    body = m.content.strip()
    if not body or body == NON_TEXT:
        return "empty"
    # ⚠️ 这里的 `not (...)` 不能省——它是计划自相矛盾被实测逼出来的修补。
    #
    # 原计划把「< MIN_BYTES」直接判 short，但那样 `"OK"`（2 字节）会被
    # 记成 dropped_short，而 test_drops_bare_acknowledgements 要求
    # dropped_ack；两者矛盾，原样实现是 1 failed。
    #
    # 单纯把 BARE_ACK 判定前移也修不好：`"好"`（3 字节）同样命中 `好(的)?`，
    # 会变成 ack，反过来挂掉 test_drops_too_short。两个测试分别锁死两个方向。
    #
    # 出路是**按字符数而非字节数区分**：单字符（"好"、"1"）确实没信息量，
    # 算 short；多字符的纯应答（"OK"、"嗯嗯"）是应答噪声，归 ack。
    # 两者都会被丢，保留集完全不变——只是让计数反映「应答噪声」的真实规模
    # （探针实测班级群 15 条里 8 条是「已完成」）。
    if len(body.encode("utf-8")) < MIN_BYTES and not (
        len(body) > 1 and BARE_ACK.match(body)
    ):
        return "short"
    if m.ts <= 0:
        return "bad_time"
    if m.msg_id in flood:
        return "flood"
    if BARE_ACK.match(body):
        return "ack"
    return None


def _keep_reason(m: PendingMessage, *, tier: str, keywords: frozenset[str]) -> str:
    """保留判定。返回原因，空串表示不保留。"""
    if tier == "high":
        return "high_tier"
    if ROLE_PATTERN.search(m.sender):
        return "role"
    for kw in keywords:
        if kw in m.content:
            return "keyword"
    return ""


def screen(
    messages: Sequence[PendingMessage],
    *,
    tier_of: Callable[[int], str],
    keywords: frozenset[str] = DEFAULT_KEYWORDS,
) -> tuple[list[Candidate], ScreenStats]:
    """把消息分成「值得抽取」与「丢弃」两堆。"""
    stats = ScreenStats(total=len(messages))
    flood = _flood_ids(messages)
    kept: list[Candidate] = []

    for m in messages:
        dropped = _drop_reason(m, flood=flood)
        if dropped is not None:
            setattr(stats, f"dropped_{dropped}", getattr(stats, f"dropped_{dropped}") + 1)
            continue

        reason = _keep_reason(m, tier=tier_of(m.group_id), keywords=keywords)
        if not reason:
            # 既不硬丢弃也没命中保留规则——算作「软丢弃」，不计入硬丢弃计数
            continue

        kept.append(
            Candidate(
                msg_id=m.msg_id,
                group_id=m.group_id,
                ts=m.ts,
                sender=m.sender,
                content=m.content,
                reason=reason,
            )
        )
        stats.kept += 1
        setattr(stats, f"kept_{reason}", getattr(stats, f"kept_{reason}") + 1)

    return kept, stats


def expand_context(
    messages: Sequence[PendingMessage],
    candidates: Sequence[Candidate],
    *,
    context: int = 2,
) -> list[PendingMessage]:
    """把候选连同它们**在同一群内**前后各 context 条邻居一并取回。

    为什么需要：单条消息常常没头没尾（「明天记得带」），
    邻居能救回这类。跨群的「邻居」是毫无意义的，所以按群分组。

    参数 messages 必须已按时间升序（pending_messages 保证了这点）。
    """
    if context <= 0:
        keep = {c.msg_id for c in candidates}
        return [m for m in messages if m.msg_id in keep]

    by_group: dict[int, list[PendingMessage]] = {}
    for m in messages:
        by_group.setdefault(m.group_id, []).append(m)

    positions = {
        gid: {m.msg_id: i for i, m in enumerate(msgs)}
        for gid, msgs in by_group.items()
    }

    in_scope: dict[int, set[int]] = {}
    for c in candidates:
        index = positions.get(c.group_id)
        if not index or c.msg_id not in index:
            continue
        i = index[c.msg_id]
        lo = max(0, i - context)
        hi = min(len(by_group[c.group_id]), i + context + 1)
        in_scope.setdefault(c.group_id, set()).update(range(lo, hi))

    out: list[PendingMessage] = []
    for gid, indexes in in_scope.items():
        msgs = by_group[gid]
        out.extend(msgs[i] for i in sorted(indexes))
    return out


def make_batches(
    messages: Sequence[PendingMessage], *, max_batch: int = 30
) -> list[list[PendingMessage]]:
    """按（群，时间）连续性切批。

    不跨群混批是刻意的：不同群的对话毫无关系，混在一起会让模型
    把 A 群的上下文套到 B 群的消息上。
    """
    out: list[list[PendingMessage]] = []
    current: list[PendingMessage] = []
    last_group: int | None = None

    for m in messages:
        if last_group is not None and (m.group_id != last_group or len(current) >= max_batch):
            out.append(current)
            current = []
        current.append(m)
        last_group = m.group_id

    if current:
        out.append(current)
    return out
```

> ⚠️ **实现提示**：`screen` 里用 `setattr`/`getattr` 动态改计数器，是为了让 `_drop_reason` 返回原因码后映射到 `stats.dropped_<码>` 字段。`ScreenStats` 的字段名必须与 `_drop_reason` 的返回码一一对应（`empty`/`short`/`bad_time`/`flood`/`ack`），`_keep_reason` 的返回码同理（`high_tier`/`keyword`/`role`）。

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_prefilter.py -v`
Expected: 全部 passed

- [ ] **Step 6: 确认没弄坏既有配置加载**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v && .venv/Scripts/vigil.exe groups --only-watched`
Expected: 测试全绿；`groups` 命令正常列出已纳群

- [ ] **Step 7: Commit**

```bash
git add vigil/prefilter.py tests/test_prefilter.py vigil/config.py config/groups.toml
git commit -m "feat: 加规则预筛、上下文展开与切批，并给群加 tier 分级"
```

---

### Task 6: SiliconFlow 客户端

**Files:**
- Create: `vigil/llm.py`, `tests/test_llm.py`

**Dependencies:** [Task 1]

**Touches:** `vigil/llm.py`, `tests/test_llm.py`

**Interfaces:**
- Consumes: 无（只用 stdlib）
- Produces:
  - `vigil.llm.DEFAULT_MODEL: str = "Qwen/Qwen2.5-7B-Instruct"`
  - `vigil.llm.DEFAULT_BASE: str = "https://api.siliconflow.cn/v1/chat/completions"`
  - `vigil.llm.LLMError(RuntimeError)`
  - `vigil.llm.LLMConfig` — frozen dataclass，字段 `api_key: str`, `model: str = DEFAULT_MODEL`, `base_url: str = DEFAULT_BASE`, `timeout: int = 180`, `max_retries: int = 3`, `temperature: float = 0.1`
  - `vigil.llm.LLMResult` — frozen dataclass，字段 `payload: dict`, `input_tokens: int`, `output_tokens: int`
  - `vigil.llm.chat_json(cfg, *, system: str, user: str, sleep=time.sleep) -> LLMResult`

**三处实测易错点（探针 `_probe_refine.py` 抓到的，写进代码注释）**：
1. `response_format={"type":"json_object"}` 会让模型返回**对象**而非裸数组 → 提示词必须要求 `{"items": [...]}` 外层包裹
2. 不给「今天」的日期，模型会把「9月7号」猜成 2023 → 提示词必须注入当前日期
3. 模型倾向只处理第一条就停下 → 提示词必须明确「只输出有价值的信息」

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_llm.py`：

```python
"""LLM 客户端测试。**全部用假 transport，绝不联网。**"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from vigil.llm import LLMConfig, LLMError, chat_json


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _envelope(content: str, *, prompt_tokens=10, completion_tokens=5) -> bytes:
    return json.dumps(
        {
            "model": "fake",
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
        }
    ).encode("utf-8")


@pytest.fixture
def cfg():
    return LLMConfig(api_key="k", max_retries=3)


def test_parses_json_payload(monkeypatch, cfg):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req)
        return FakeResponse(_envelope('{"items": [{"msg_id": 1}]}'))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = chat_json(cfg, system="s", user="u", sleep=lambda _: None)

    assert result.payload == {"items": [{"msg_id": 1}]}
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    assert len(calls) == 1


def test_sends_auth_header_and_model(monkeypatch, cfg):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse(_envelope("{}"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    chat_json(cfg, system="sys", user="usr", sleep=lambda _: None)

    assert captured["headers"]["Authorization"] == "Bearer k"
    assert captured["body"]["model"] == cfg.model
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert captured["body"]["messages"][0] == {"role": "system", "content": "sys"}


def test_tolerates_markdown_fence(monkeypatch, cfg):
    """模型有时会把 JSON 包在 ```json 围栏里。"""
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: FakeResponse(_envelope('```json\n{"a": 1}\n```')),
    )
    assert chat_json(cfg, system="s", user="u", sleep=lambda _: None).payload == {"a": 1}


def test_retries_on_429_then_succeeds(monkeypatch, cfg):
    attempts = {"n": 0}

    def fake_urlopen(req, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise urllib.error.HTTPError(
                "u", 429, "rate limited", {}, io.BytesIO(b"slow down")
            )
        return FakeResponse(_envelope('{"items": []}'))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = chat_json(cfg, system="s", user="u", sleep=lambda _: None)
    assert attempts["n"] == 2
    assert result.payload == {"items": []}


def test_does_not_retry_on_401(monkeypatch, cfg):
    """认证错重试一百次也还是错——白等。"""
    attempts = {"n": 0}

    def fake_urlopen(req, timeout=None):
        attempts["n"] += 1
        raise urllib.error.HTTPError(
            "u", 401, "unauthorized", {}, io.BytesIO(b"bad key")
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(LLMError, match="401"):
        chat_json(cfg, system="s", user="u", sleep=lambda _: None)
    assert attempts["n"] == 1


def test_raises_after_exhausting_retries(monkeypatch, cfg):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: (_ for _ in ()).throw(OSError("network down")),
    )
    with pytest.raises(LLMError, match="3"):
        chat_json(cfg, system="s", user="u", sleep=lambda _: None)


def test_raises_on_unparsable_content(monkeypatch, cfg):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: FakeResponse(_envelope("这不是 JSON")),
    )
    with pytest.raises(LLMError, match="解析"):
        chat_json(cfg, system="s", user="u", sleep=lambda _: None)


@pytest.mark.parametrize(
    "raw_content",
    [
        None,  # 模型返回工具调用 / 被内容过滤时，content 就是 null
        12345,  # 数字
        "[1, 2, 3]",  # 裸数组
    ],
)
def test_rejects_non_object_content(monkeypatch, cfg, raw_content):
    """⚠️ 契约必须挡住非字符串 content 与非对象顶层（W2 审查实测抓出）。

    这两种都会**穿透 `chat_json` 的契约**，而不是变成 LLMError：
    * `content = None` → `None.strip()` 抛 `AttributeError`
    * 裸数组 → `_loads` 返回 list，下游 `payload.get()` 抛 `AttributeError`

    调用方按常理只 `except LLMError`，所以两种都会崩掉整轮 refine。
    """
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: FakeResponse(_envelope(raw_content)),
    )
    with pytest.raises(LLMError, match="解析"):
        chat_json(cfg, system="s", user="u", sleep=lambda _: None)


def test_backoff_is_exponential(monkeypatch, cfg):
    delays = []
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=None: (_ for _ in ()).throw(OSError("x")),
    )
    with pytest.raises(LLMError):
        chat_json(cfg, system="s", user="u", sleep=delays.append)
    assert delays == [1, 2]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'vigil.llm'`

- [ ] **Step 3: 实现 llm.py**

创建 `vigil/llm.py`：

```python
"""SiliconFlow 客户端（OpenAI 兼容接口）。

只用标准库 urllib —— 项目依赖表目前只有 sqlcipher3，
为一个 POST 请求引入 httpx 不划算。

契约由 _probe_refine.py 用真实消息实测确定，三处易错点刻在下面，
改提示词的人务必先读：

  1. ``response_format={"type": "json_object"}`` 会让模型返回**对象**
     而非裸数组。所以提示词必须要求 ``{"items": [...]}`` 这种外层包裹，
     不能要求返回数组。
  2. 不告诉模型「今天」是哪天，它会把「9月7号」猜成过去的年份
     （实测猜成了 2023）。所以 user 消息里必须注入当前日期。
  3. 模型倾向只处理第一条消息就停下（实测输出仅 88 token）。
     所以提示词必须明确「无价值的消息直接不出现在结果里」。
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_BASE = "https://api.siliconflow.cn/v1/chat/completions"

# 实测默认：15 条消息 1170 输入 / 175 输出 token，
# 与 32B 档位在本批样本上质量持平，但便宜约一个数量级。
DEFAULT_MODEL = "Qwen/Qwen2.5-7B-Instruct"

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


class LLMError(RuntimeError):
    """调用失败——重试耗尽，或响应无法解析。"""


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE
    timeout: int = 180
    max_retries: int = 3
    temperature: float = 0.1


@dataclass(frozen=True)
class LLMResult:
    payload: dict
    input_tokens: int
    output_tokens: int


def _loads(text: str) -> dict:
    """稳健解析模型输出：容忍 ``` 围栏与前后缀噪声。

    ⚠️ 两道闸都不能省——W2 审查实测抓出，两者都会**穿透 chat_json 的契约**：

    * **content 可能不是字符串**（`null` 或数字）。模型返回工具调用、或被内容
      过滤时就是 `null`，此时 `None.strip()` 抛 `AttributeError`；
      调用方按常理 `except LLMError`，会被崩掉整轮 refine。
    * **顶层可能是裸数组**。直接返回 list 的话，下游 `payload.get("items")`
      会抛 `AttributeError`——同样穿透契约。本函数声明的是 `-> dict`，
      就必须保证真的是 dict。
    """
    if not isinstance(text, str):
        raise ValueError(f"content 不是字符串，而是 {type(text).__name__}")

    stripped = _FENCE.sub("", text.strip())
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(stripped[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError(f"顶层不是 JSON 对象，而是 {type(parsed).__name__}")
    return parsed


def chat_json(
    cfg: LLMConfig,
    *,
    system: str,
    user: str,
    sleep=time.sleep,
) -> LLMResult:
    """发一次对话请求，返回解析后的 JSON 与 token 用量。

    sleep 可注入，测试里传 ``lambda _: None`` 就能免去真实等待。
    """
    body = json.dumps(
        {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": cfg.temperature,
            "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")

    last_error: Exception | None = None

    for attempt in range(cfg.max_retries):
        request = urllib.request.Request(
            cfg.base_url,
            data=body,
            headers={
                "Authorization": f"Bearer {cfg.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=cfg.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            # 4xx（限流除外）重试不会有不同结果——立刻失败，别白等
            if 400 <= exc.code < 500 and exc.code != 429:
                raise LLMError(f"HTTP {exc.code}: {detail}") from exc
            last_error = LLMError(f"HTTP {exc.code}: {detail}")
        except Exception as exc:  # noqa: BLE001 — 网络层什么都可能抛
            last_error = exc

        if attempt < cfg.max_retries - 1:
            sleep(2**attempt)
    else:
        raise LLMError(f"重试 {cfg.max_retries} 次仍失败: {last_error}")

    try:
        content = raw["choices"][0]["message"]["content"]
        payload = _loads(content)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        # ⚠️ 用 ValueError 而不是 json.JSONDecodeError：_loads 的两道
        # 「类型闸」抛的是 ValueError，而 JSONDecodeError 本就是它的子类，
        # 所以这一条同时覆盖两者。少 Catch 一种就会让它穿透契约。
        raise LLMError(f"响应解析失败: {type(exc).__name__}: {exc}") from exc

    usage = raw.get("usage") or {}
    return LLMResult(
        payload=payload,
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_llm.py -v`
Expected: 8 passed

- [ ] **Step 5: 真实连通性冒烟（唯一一次联网动作）**

Run:
```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
from vigil.llm import LLMConfig, chat_json
import pathlib
key = pathlib.Path(r'C:/Users/qwe13/.claude/toolkit/.cache/siliconflow.key').read_text(encoding='utf-8').strip()
r = chat_json(LLMConfig(api_key=key), system='只输出 JSON。', user='今天的日期是 2026-09-13。输出 {\"items\":[{\"msg_id\":1,\"kind\":\"notice\",\"title\":\"连通性自检\"}]}')
print('payload:', r.payload)
print('tokens:', r.input_tokens, '/', r.output_tokens)
"
```
Expected: 打印出 payload 与 token 用量，无异常

- [ ] **Step 6: Commit**

```bash
git add vigil/llm.py tests/test_llm.py
git commit -m "feat: 加 SiliconFlow 客户端（stdlib 实现，含重试与稳健 JSON 解析）"
```

---

### Task 7: 抽取编排与 CLI

**Files:**
- Create: `vigil/refine.py`, `tests/test_refine.py`
- Modify: `vigil/config.py`（加 `load_llm_key`）、`vigil/cli.py`（加 `refine` 子命令）

**Dependencies:** [Task 1, Task 2, Task 3, Task 4, Task 5, Task 6]

**Touches:** `vigil/refine.py`, `tests/test_refine.py`, `vigil/config.py`, `vigil/cli.py`

**Interfaces:**
- Consumes: Task 2 `categories`、Task 3 `redact`、Task 4 `store`、Task 5 `prefilter` + `config.tier_of`、Task 6 `llm`
- Produces:
  - `vigil.config.load_llm_key(env_path: pathlib.Path | None = None) -> str`
  - `vigil.refine.PROMPT_VERSION: str = "v1"`
  - `vigil.refine.build_system_prompt(cats) -> str`
  - `vigil.refine.build_user_prompt(messages, redactor, *, today) -> str`
  - `vigil.refine.RefineStats` — dataclass，字段 `scanned, discarded_local, sent_messages, batches, items_saved, input_tokens, output_tokens, budget_hit, errors`
  - `vigil.refine.refine(config, *, api_key, db_path=None, conn=None, since=None, until=None, limit=None, redo=False, batch_size=30, context=2, budget_tokens=None, model=DEFAULT_MODEL, prompt_ver=PROMPT_VERSION, dry_run=False, on_progress=print) -> RefineStats`
    - `conn` 与 `db_path` 二选一：CLI 传 `db_path`，测试传内存 `conn`。传了 `conn` 时连接由调用方负责关闭。
  - CLI：`vigil refine [--since D] [--until D] [--limit N] [--redo] [--batch N] [--context N] [--budget N] [--model NAME] [--prompt-ver V] [--dry-run]`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_refine.py`：

```python
"""编排层测试。用假 LLM 与内存库，绝不联网、绝不碰真实数据。"""

from __future__ import annotations

import sqlite3

import pytest

from vigil import refine, store
from vigil.llm import LLMResult
from vigil.store import STATUS_DISCARDED, STATUS_OK


class FakeLLM:
    """记录调用、按脚本返回。用于验证编排逻辑而非模型质量。"""

    def __init__(self, script=None):
        self.calls = []
        self.script = script or (lambda messages: {"items": []})

    def __call__(self, cfg, *, system, user, sleep=None):
        self.calls.append({"system": system, "user": user})
        return LLMResult(
            payload=self.script(user), input_tokens=100, output_tokens=20
        )


@pytest.fixture
def seeded(memdb):
    memdb.executescript(
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
    memdb.executemany(
        "INSERT INTO messages VALUES (?,?,?,?,?)",
        [
            (1, 100, 1000, "u_a", "明天下午有讲座，地点西太湖报告厅"),
            (2, 100, 1001, "u_b", "已完成"),
            (3, 100, 1002, "u_a", "数学作业截止到9月7号"),
        ],
    )
    memdb.executemany(
        "INSERT INTO sender_names VALUES (?,?,?,?,?,?)",
        [(100, "u_a", "班长小王", "小王", 111, 0), (100, "u_b", "李四", "李四", 222, 0)],
    )
    memdb.commit()
    store.ensure_schema(memdb)
    return memdb


class StubConfig:
    """refine 只用到 tier_of 与群名，不需要真实配置文件。"""

    def tier_of(self, gid: int) -> str:
        return "high"

    def group_name(self, gid: int) -> str:
        return "测试群"


def test_build_system_prompt_contains_categories():
    from vigil.categories import load_categories

    prompt = refine.build_system_prompt(load_categories())
    assert "notice" in prompt and "secondhand" in prompt
    assert "items" in prompt, "必须要求 items 外层包裹（探针实测）"


def test_build_user_prompt_injects_today():
    """不给今天，模型会把「9月7号」猜成 2023（探针实测）。"""
    from vigil.redact import Redactor
    from vigil.store import PendingMessage

    msgs = [
        PendingMessage(
            msg_id=1, group_id=100, ts=1000, sender_uid="u_a",
            sender="班长小王", content="作业截止9月7号",
        )
    ]
    text = refine.build_user_prompt(msgs, Redactor(), today="2026-09-13")
    assert "2026-09-13" in text
    assert "[1]" in text
    assert "班长小王" in text


def test_build_user_prompt_redacts_numbers():
    from vigil.redact import Redactor
    from vigil.store import PendingMessage

    msgs = [
        PendingMessage(
            msg_id=1, group_id=100, ts=1000, sender_uid="u_a",
            sender="2600090309张韩18368500707", content="打我电话13812345678",
        )
    ]
    text = refine.build_user_prompt(msgs, Redactor(), today="2026-09-13")
    assert "18368500707" not in text
    assert "13812345678" not in text
    assert "张韩" in text, "姓名要保留——它是判断发送者身份的信号"


def test_build_user_prompt_distinguishes_anonymous_senders():
    """⚠️ 匿名发送者必须**逐条区分**。

    本条的存在本身就是审查的产物：Task 7 审查实测「**删掉这个特判，128 条
    测试全绿**」——实现是对的，但零守护。这是「空守卫」在同一里程碑里的
    第四次重现，所以补上。

    为什么重要：W1 波级审查实测全库 1,218 条匿名消息里 **1,196 条是实质正文**，
    含班主任助理张皓宇、卞雨琦各 11 条。若全归一个代号，模型会把互不相识的
    人当成同一个人，并把这个错误认知写进 title/detail。
    """
    from vigil.redact import Redactor
    from vigil.store import PendingMessage

    msgs = [
        PendingMessage(
            msg_id=1, group_id=100, ts=1000, sender_uid="",
            sender="", content="转发通知：明天停课",
        ),
        PendingMessage(
            msg_id=2, group_id=200, ts=1001, sender_uid="",
            sender="", content="转发通知：明天停课",
        ),
    ]
    text = refine.build_user_prompt(msgs, Redactor(), today="2026-09-13")
    assert "匿名1" in text, "第一条匿名消息要有自己的标记"
    assert "匿名2" in text, "第二条必须是**不同**的标记"
    assert text.count("匿名") == 2


def test_build_user_prompt_keeps_named_senders_stable():
    """有 uid 的仍走稳定代号——同一人两次发言必须看得出是同一人。

    与上一条互补：匿名者**逐条区分**，有身份者**稳定复用**。两条一起才
    完整描述 `build_user_prompt` 的发信人标记规则。
    """
    from vigil.redact import Redactor
    from vigil.store import PendingMessage

    msgs = [
        PendingMessage(msg_id=1, group_id=100, ts=1000, sender_uid="u_a",
                       sender="班长小王", content="第一句"),
        PendingMessage(msg_id=2, group_id=100, ts=1001, sender_uid="u_a",
                       sender="班长小王", content="第二句"),
    ]
    text = refine.build_user_prompt(msgs, Redactor(), today="2026-09-13")
    assert text.count("U1") == 2, "同一人的两条消息应共用一个代号"


def test_prompt_uses_sequential_indices_not_msg_ids():
    """⚠️ 必须用**批内序号**而不是 msg_id——Task 8 冒烟实测逼出的关键改动。

    msg_id 是 19 位雪花号，同一批 30 条只有末 3 位不同。实测模型在
    「抄 30 个几乎相同的长数字」上**系统性**出错：对照实验里 msg_id 版
    命中 0/2，返回的都是「在批内但不对应」的 ID，错归因被静默接受，
    可回溯性直接失效。换 1-2 位序号后命中 1/1，输入 token 还降 43%。

    这条测试守两件事：**长 ID 不出现在提示词里** + **序号从 1 起连续**。
    """
    from vigil.redact import Redactor
    from vigil.store import PendingMessage

    msgs = [
        PendingMessage(msg_id=7685024133064673881, group_id=100, ts=1000,
                       sender_uid="u_a", sender="甲", content="第一条"),
        PendingMessage(msg_id=7685024133064673978, group_id=100, ts=1001,
                       sender_uid="", sender="", content="第二条"),
        PendingMessage(msg_id=7685024133064673918, group_id=100, ts=1002,
                       sender_uid="u_b", sender="乙", content="第三条"),
    ]
    text = refine.build_user_prompt(msgs, Redactor(), today="2026-09-13")

    # 19 位 msg_id 一个都不许出现
    for mid in (7685024133064673881, 7685024133064673978, 7685024133064673918):
        assert str(mid) not in text, f"提示词里不该出现长 msg_id: {mid}"
    # 序号从 1 起、连续
    for i in (1, 2, 3):
        assert f"\n{i}. " in text, f"缺序号 {i}"
    # 匿名者的标记也走序号（不再用 msg_id）
    assert "匿名2" in text


def test_cli_refine_model_falls_back_to_default(monkeypatch, tmp_path):
    """⚠️ argparse 不给 `--model` 时传的是 `None`，而 `None` 会**绕过**
    `refine()` 的默认参数值（默认值只在「未传参」时生效）。

    CLI 不自己兜底的话，会把 `None` 当模型名发给 SiliconFlow。
    """
    from vigil import cli, refine as refine_mod

    captured = {}

    def fake_refine(config, **kwargs):
        captured.update(kwargs)
        return refine_mod.RefineStats()

    monkeypatch.setattr(refine_mod, "refine", fake_refine)
    monkeypatch.setattr(cli, "_load_config_only", lambda: object())
    monkeypatch.setattr(cli, "_require_export_db", lambda c: tmp_path / "x.db")

    assert cli.main(["refine", "--dry-run"]) == 0
    assert captured["model"] == refine_mod.DEFAULT_MODEL
    assert captured["dry_run"] is True


def test_load_llm_key_prefers_env_over_file(monkeypatch, tmp_path):
    """密钥读取：环境变量优先于 `.env`；都没有时返回空串而不是抛错。"""
    from vigil.config import load_llm_key

    env = tmp_path / ".env"
    env.write_text("SILICONFLOW_API_KEY=sk-from-file\n", encoding="utf-8")

    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    assert load_llm_key(env) == "sk-from-file"

    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-from-env")
    assert load_llm_key(env) == "sk-from-env", "环境变量应优先于 .env"

    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    assert load_llm_key(tmp_path / "nonexistent.env") == "", "文件不存在不该崩"


def test_refine_saves_items(seeded, monkeypatch):
    """一条消息产出条目 → 落库 → 记账。"""
    fake = FakeLLM(
        lambda user: {
            "items": [
                {
                    "idx": 1, "kind": "activity", "title": "西太湖报告厅有讲座",
                    "detail": None, "deadline": None, "place": "西太湖报告厅",
                    "amount": None, "confidence": 0.9,
                }
            ]
        }
    )
    monkeypatch.setattr(refine, "chat_json", fake)

    stats = refine.refine(
        StubConfig(), api_key="k", db_path=None, conn=seeded,
        on_progress=lambda *a, **k: None,
    )

    assert stats.items_saved == 1
    assert seeded.execute("SELECT kind, title FROM items").fetchone() == (
        "activity", "西太湖报告厅有讲座",
    )
    assert seeded.execute("SELECT item_id, msg_id FROM item_sources").fetchall() == [(1, 1)]


def test_refine_records_discarded_for_noise(seeded, monkeypatch):
    """硬丢弃的消息也要记账——M1 出口要求 refine_runs 无遗漏。"""
    monkeypatch.setattr(refine, "chat_json", FakeLLM())
    refine.refine(StubConfig(), api_key="k", conn=seeded, on_progress=lambda *a, **k: None)

    row = seeded.execute(
        "SELECT status FROM refine_runs WHERE msg_id = 2"
    ).fetchone()
    assert row == (STATUS_DISCARDED,)


def test_refine_is_idempotent(seeded, monkeypatch):
    """跑两次，第二次不该重复调模型、不该重复写条目。"""
    fake = FakeLLM(
        lambda user: {
            "items": [
                {"idx": 1, "kind": "activity", "title": "讲座", "detail": None,
                 "deadline": None, "place": None, "amount": None, "confidence": 0.9}
            ]
        }
    )
    monkeypatch.setattr(refine, "chat_json", fake)

    refine.refine(StubConfig(), api_key="k", conn=seeded, on_progress=lambda *a, **k: None)
    first_calls = len(fake.calls)
    refine.refine(StubConfig(), api_key="k", conn=seeded, on_progress=lambda *a, **k: None)

    assert len(fake.calls) == first_calls, "第二次不该再调模型"
    assert seeded.execute("SELECT count(*) FROM items").fetchone()[0] == 1


def test_refine_parses_deadline(seeded, monkeypatch):
    fake = FakeLLM(
        lambda user: {
            "items": [
                {"idx": 3, "kind": "academic", "title": "数学作业截止",
                 "detail": None, "deadline": "2026-09-07", "place": None,
                 "amount": None, "confidence": 0.9}
            ]
        }
    )
    monkeypatch.setattr(refine, "chat_json", fake)
    refine.refine(StubConfig(), api_key="k", conn=seeded, on_progress=lambda *a, **k: None)

    deadline = seeded.execute(
        "SELECT deadline_ts FROM items WHERE title = '数学作业截止'"
    ).fetchone()[0]
    import datetime as dt
    assert dt.datetime.fromtimestamp(deadline).strftime("%Y-%m-%d") == "2026-09-07"


def test_refine_ignores_out_of_range_idx(seeded, monkeypatch):
    """模型可能编出越界的序号——必须丢弃而不是崩溃。

    越界即丢不只是防御：**宁可少一条，也不能把条目挂到错误的消息上**，
    那会让「可回溯」变成假的（M1 出口标准要求能跳回原文且内容对得上）。
    """
    fake = FakeLLM(
        lambda user: {
            "items": [
                {"idx": 999, "kind": "notice", "title": "编的",
                 "detail": None, "deadline": None, "place": None,
                 "amount": None, "confidence": 0.9}
            ]
        }
    )
    monkeypatch.setattr(refine, "chat_json", fake)
    stats = refine.refine(StubConfig(), api_key="k", conn=seeded,
                          on_progress=lambda *a, **k: None)
    assert stats.items_saved == 0
    assert seeded.execute("SELECT count(*) FROM items").fetchone()[0] == 0


def test_refine_respects_budget(seeded, monkeypatch):
    """预算护栏必须在超限时停下并如实报告。

    batch_size=1 是必须的：护栏在**每批开始前**检查，样本只有 3 条消息，
    默认 batch_size=30 会全挤进一批，护栏根本没机会触发。
    """
    monkeypatch.setattr(
        refine, "chat_json",
        lambda cfg, *, system, user, sleep=None: LLMResult(
            payload={"items": []}, input_tokens=10_000, output_tokens=10_000
        ),
    )
    stats = refine.refine(
        StubConfig(), api_key="k", conn=seeded, budget_tokens=5_000, batch_size=1,
        on_progress=lambda *a, **k: None,
    )
    assert stats.budget_hit is True
    # ⚠️ 这里必须同时钉住两个数：`batches_planned` 是"切成几批"，
    # `batches` 是"实际跑了几批"。只断言后者的话，把 planned 算错也发现不了；
    # 只断言前者的话，护栏没生效也发现不了。
    # （controller 改 `batches` 语义时漏改过这条断言，照抄计划会红 `assert 1 == 3`——
    #   由 fix 审查实测抓出。）
    assert stats.batches_planned == 3, "样本应被切成 3 批"
    assert stats.batches == 1, "只跑了 1 批就撞上预算闸"
    assert stats.batches < stats.batches_planned, "实际必须少于计划，否则这条没验到东西"
    assert len(seeded.execute(
        "SELECT 1 FROM refine_runs WHERE status = 'ok'"
    ).fetchall()) < 3


def test_refine_survives_llm_error(seeded, monkeypatch):
    """单批失败不该让整轮崩掉——降级并记录，沿用 export.py 的既有取舍。"""
    from vigil.llm import LLMError

    def boom(cfg, *, system, user, sleep=None):
        raise LLMError("模拟失败")

    monkeypatch.setattr(refine, "chat_json", boom)
    stats = refine.refine(StubConfig(), api_key="k", conn=seeded,
                          on_progress=lambda *a, **k: None)
    assert stats.errors, "失败要如实记录"
    assert seeded.execute(
        "SELECT count(*) FROM refine_runs WHERE status = 'error'"
    ).fetchone()[0] > 0


def test_refine_rejects_redo_with_limit(seeded):
    """redo + limit 会重复产出 items 并白烧 token——必须快速失败挡住。

    W1 Task 4 审查实测：`pending_messages(redo=True, limit=2)` 返回 [1,2,3,4,5]
    里含已处理的；CLI 上 `--redo --limit N` 是个安静的烧钱陷阱。
    """
    with pytest.raises(ValueError, match="redo"):
        refine.refine(
            StubConfig(), api_key="k", conn=seeded, redo=True, limit=2,
            on_progress=lambda *a, **k: None,
        )


def test_dry_run_makes_no_calls(seeded, monkeypatch):
    """--dry-run 只报告不调模型、不写库。"""
    fake = FakeLLM()
    monkeypatch.setattr(refine, "chat_json", fake)
    stats = refine.refine(StubConfig(), api_key="k", conn=seeded, dry_run=True,
                          on_progress=lambda *a, **k: None)
    assert fake.calls == []
    assert stats.items_saved == 0
    assert seeded.execute("SELECT count(*) FROM refine_runs").fetchone()[0] == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_refine.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'vigil.refine'`

- [ ] **Step 3: 给 config.py 加 LLM 密钥读取**

修改 `vigil/config.py`。把 `load_key` 的**函数体**重构为共用一个私有 helper，并新增 `load_llm_key`：

```python
def _read_env(name: str, env_path: pathlib.Path | None = None) -> str:
    """先读同名环境变量，再读仓库根的 .env。找不到返回空串。"""
    value = os.environ.get(name, "").strip()
    if value:
        return value

    path = env_path or DEFAULT_ENV
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        if key.strip() == name:
            return raw.strip().strip("'\"")
    return ""


def load_key(env_path: pathlib.Path | None = None) -> str:
    """读取数据库密钥：优先环境变量 VIGIL_DB_KEY，其次仓库根的 .env。"""
    return _read_env("VIGIL_DB_KEY", env_path)


def load_llm_key(env_path: pathlib.Path | None = None) -> str:
    """读取 LLM 密钥：优先环境变量 SILICONFLOW_API_KEY，其次 .env。

    与数据库密钥分开取名，是因为它们是完全不同的凭证——
    混用会让「换模型」变成一件危险的事。
    """
    return _read_env("SILICONFLOW_API_KEY", env_path)
```

同时，在 `.env` 里追加一行（**不要提交 `.env`**）：

```
SILICONFLOW_API_KEY=sk-...（从 toolkit/.cache/siliconflow.key 取）
```

- [ ] **Step 4: 实现 refine.py**

创建 `vigil/refine.py`：

```python
"""抽取引擎：messages → items。

流水线：
    取待处理 → 规则预筛 → 按群切批 → 展开上下文 → 脱敏 → 批量调 LLM
    → 落 items + item_sources → 记账 refine_runs

设计的两个关键取舍：
  * **丢掉的消息也要记账**。refine_runs 必须覆盖全部消息，
    否则「哪些看过、哪些没看过」分不清，增量就无从谈起。
  * **单批失败不中断整轮**。沿用 export.py 对 senders/media 的既有取舍：
    外部环境的问题降级并记录，不拖垮主流程。
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from . import prefilter, store
from .categories import Category, prompt_block
from .config import Config
from .llm import DEFAULT_MODEL, LLMConfig, LLMError, chat_json
from .redact import Redactor
from .store import PendingMessage

PROMPT_VERSION = "v1"

# 输出 token 的上限估计，用于把「输出」也算进预算
_BATCH_TITLE_MAX = 40


@dataclass
class RefineStats:
    """如实报告——失败与跳过都要看得见。"""

    scanned: int = 0
    discarded_local: int = 0
    sent_messages: int = 0
    batches_planned: int = 0  # 计划要跑多少批
    batches: int = 0  # **实际**跑了几批——预算 break 之后会小于 planned
    items_saved: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    budget_hit: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def build_system_prompt(cats: tuple[Category, ...]) -> str:
    """系统提示词。类目表从配置渲染，改 categories.toml 即改提示词。"""
    return f"""你是校园 QQ 群的信息提炼助手。从群聊消息里挑出对大学生真正有价值的信息。

类目（只能选这些）：
{prompt_block(cats)}

闲聊、纯表情、无信息量的发言**直接不出现在结果里**——不要为它们输出任何占位元素。

输出必须是 JSON 对象，形如 {{"items": [...]}}，其中 items 是数组。
每个元素的结构：
{{"idx": 29, "kind": "notice", "title": "一句话摘要（≤{_BATCH_TITLE_MAX}字）",
 "detail": "补充细节或null", "deadline": "YYYY-MM-DD 或 null",
 "place": "地点或null", "amount": "金额或null", "confidence": 0.9}}

⚠️ `idx` 是下面消息列表里的**序号**（从 1 开始），**不是消息 ID**。

死线日期必须结合下面提供的「今天」推算正确年份。没有死线的填 null。"""


def build_user_prompt(
    messages: list[PendingMessage], redactor: Redactor, *, today: str
) -> str:
    """用户提示词。**脱敏在这一步完成**——所有离开本机的内容都经过这里。

    形如 ``29. U3 昵称: 内容``：**序号让模型能指回来源**，代号（姓名保留、
    号码已抹）让模型能看出「同一人说了两次」。

    ⚠️ 用**批内序号**而不是 msg_id——这是 Task 8 冒烟实测逼出来的关键改动：

    msg_id 是 19 位雪花号，同一批 30 条的 ID 只有末 3 位不同
    （`…673881` / `…673929` / `…673918`）。实测模型在这种「抄 30 个几乎相同的
    长数字」上的错误是**系统性**的：对照实验里 msg_id 版**命中 0/2**，且返回的
    都是「在批内但不对应」的 ID——错归因被静默接受，可回溯性直接失效。

    换成 1-2 位序号后**命中 1/1**，输入 token 还从 1424 降到 819（**-43%**）。

    ⚠️ 匿名发送者（uid 为空串）**必须逐条区分**。实测全库 1,218 条（2.55%）
    匿名消息；若一律走 ``redactor.actor('')``，它们会全部拿到同一个代号
    （W1 波级审查实测：两个不同群的匿名者都是 ``U1``），模型便会把互不相识
    的人当成同一个人。**匿名者没有身份可言，所以给每条一个互不相同的标记。**
    """
    lines = []
    for index, m in enumerate(messages, start=1):
        body = redactor.text(m.content)
        if m.sender_uid:
            name = redactor.text(m.sender) or "未知"
            who = f"{redactor.actor(m.sender_uid)} {name}"
        else:
            who = f"匿名{index}"  # 逐条唯一——避免把不同人当成同一人
        lines.append(f"{index}. {who}: {body}")
    return f"今天的日期是 {today}。\n\n消息如下：\n" + "\n".join(lines)


def _parse_deadline(value: object) -> int | None:
    """把 'YYYY-MM-DD' 转成 unix 秒。解析不了就当没有——不猜。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return int(dt.datetime.strptime(value.strip(), "%Y-%m-%d").timestamp())
    except ValueError:
        return None


def _to_item(
    raw: dict, batch: list[PendingMessage], *, known_kinds: frozenset[str]
) -> store.ExtractedItem | None:
    """把模型返回的一条 JSON 转成 ExtractedItem。

    任何不合法（idx 越界、类目不在表里、缺 title）都返回 None——
    模型会编，宁可不入库也不入脏数据。

    ⚠️ `idx` 是**批内序号**（1 基），与 `build_user_prompt` 的编号一一对应。
    越界即丢弃：宁可少一条，也不能把条目挂到错误的消息上——那会让
    「可回溯」变成假的（M1 出口标准要求能跳回原文**且内容对得上**）。
    """
    try:
        idx = int(raw["idx"])
    except (KeyError, TypeError, ValueError):
        return None

    if not 1 <= idx <= len(batch):
        return None
    source = batch[idx - 1]

    kind = str(raw.get("kind", "")).strip()
    if kind not in known_kinds:
        return None

    title = str(raw.get("title") or "").strip()
    if not title:
        return None

    links_raw = raw.get("links") or []
    links = tuple(str(x) for x in links_raw) if isinstance(links_raw, list) else ()

    try:
        confidence = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    def _text(key: str) -> str | None:
        value = raw.get(key)
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    return store.ExtractedItem(
        kind=kind,
        title=title,
        detail=_text("detail"),
        event_ts=source.ts,
        deadline_ts=_parse_deadline(raw.get("deadline")),
        group_id=source.group_id,
        actor_uid=source.sender_uid or None,
        place=_text("place"),
        links=links,
        amount=_text("amount"),
        confidence=max(0.0, min(1.0, confidence)),
        src_msg_ids=(source.msg_id,),
    )


def refine(
    config: Config,
    *,
    api_key: str,
    db_path: Path | None = None,
    conn: sqlite3.Connection | None = None,
    since: int | None = None,
    until: int | None = None,
    limit: int | None = None,
    redo: bool = False,
    batch_size: int = 30,
    context: int = 2,
    budget_tokens: int | None = None,
    model: str = DEFAULT_MODEL,
    prompt_ver: str = PROMPT_VERSION,
    dry_run: bool = False,
    on_progress=print,
) -> RefineStats:
    """跑一轮抽取。幂等——已处理的消息会被跳过，除非 redo=True。

    连接由调用方持有：CLI 传 db_path，测试传内存 conn。
    """
    from .categories import load_categories

    cats = load_categories()
    known_kinds = frozenset(c.slug for c in cats)
    stats = RefineStats()

    # redo + limit 叠加是有害组合（W1 Task 4 审查实测）：
    # redo 把已抽过的消息重新抽一遍，limit 又只取最早的 N 条——
    # 结果是重复产出 items、白烧 token。快速失败挡住它，别让它静默发生。
    if redo and limit is not None:
        raise ValueError(
            "redo 与 limit 不能同时用：redo 会重抽已处理的消息，"
            "limit 又只取最早的 N 条，两者叠加会重复产出 items 并白烧 token。"
            "要限量重抽，请用 since/until 圈定时间窗。"
        )

    owns_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(str(db_path))
    try:
        store.ensure_schema(conn)

        messages = store.pending_messages(
            conn, since=since, until=until, limit=limit, redo=redo
        )
        stats.scanned = len(messages)
        if not messages:
            on_progress("[refine] 没有待处理的消息")
            return stats

        candidates, screen_stats = prefilter.screen(
            messages, tier_of=config.tier_of
        )
        stats.discarded_local = screen_stats.dropped
        on_progress(
            f"[refine] 扫描 {screen_stats.total:,} 条 → 规则保留 {screen_stats.kept:,} 条"
            f"（本地丢弃 {screen_stats.dropped:,}）"
        )

        # 没进候选的一律记账为 discarded，其中既含硬丢弃也含「没命中保留规则」。
        # 记账必须做全：refine_runs 覆盖不到的消息会让增量同步永远重扫它们。
        # 集合先建好——47k 条消息下逐条重建集合是 O(n²)。
        candidate_ids = {c.msg_id for c in candidates}
        not_candidate_ids = [m.msg_id for m in messages if m.msg_id not in candidate_ids]
        if not dry_run and not_candidate_ids:
            store.record_run(
                conn, not_candidate_ids, status=store.STATUS_DISCARDED,
                prompt_ver=prompt_ver,
            )

        if not candidates:
            on_progress("[refine] 预筛后没有候选，结束")
            return stats

        in_scope = prefilter.expand_context(messages, candidates, context=context)
        batches = prefilter.make_batches(in_scope, max_batch=batch_size)
        stats.sent_messages = len(in_scope)
        stats.batches_planned = len(batches)

        if dry_run:
            on_progress(
                f"[refine] --dry-run：将发送 {len(in_scope):,} 条、分 {len(batches)} 批，"
                f"不调用模型、不写库"
            )
            return stats

        system = build_system_prompt(cats)
        today = dt.date.today().isoformat()
        llm_cfg = LLMConfig(api_key=api_key, model=model)

        for index, batch in enumerate(batches, start=1):
            if budget_tokens is not None and stats.total_tokens >= budget_tokens:
                stats.budget_hit = True
                on_progress(
                    f"[refine] 已达预算上限 {budget_tokens:,} token，提前停止"
                    f"（已完成 {index - 1}/{len(batches)} 批）"
                )
                break

            stats.batches += 1  # 实际跑了——放在预算闸之后，break 的那批不算跑过
            redactor = Redactor()
            user = build_user_prompt(batch, redactor, today=today)
            batch_ids = [m.msg_id for m in batch]

            try:
                result = chat_json(llm_cfg, system=system, user=user)
            except LLMError as exc:
                msg = f"第 {index} 批失败: {exc}"
                stats.errors.append(msg)
                on_progress(f"[refine] {msg}")
                store.record_run(
                    conn, batch_ids, status=store.STATUS_ERROR,
                    prompt_ver=prompt_ver, err=str(exc)[:200],
                )
                continue

            stats.input_tokens += result.input_tokens
            stats.output_tokens += result.output_tokens

            raw_items = result.payload.get("items")
            if not isinstance(raw_items, list):
                raw_items = []

            produced: list[store.ExtractedItem] = []
            hit_ids: set[int] = set()
            for raw in raw_items:
                if not isinstance(raw, dict):
                    continue
                item = _to_item(raw, batch, known_kinds=known_kinds)
                if item is None:
                    continue
                produced.append(item)
                hit_ids.update(item.src_msg_ids)

            if produced:
                stats.items_saved += store.save_items(
                    conn, produced, model=model, prompt_ver=prompt_ver
                )

            store.record_run(
                conn, batch_ids, status=store.STATUS_DISCARDED,
                prompt_ver=prompt_ver,
            )
            if hit_ids:
                store.record_run(
                    conn, sorted(hit_ids), status=store.STATUS_OK,
                    prompt_ver=prompt_ver, item_count=len(produced),
                )

            on_progress(
                f"[refine] 批次 {index}/{len(batches)}：{len(batch)} 条 → "
                f"{len(produced)} 条 item"
            )

        return stats
    finally:
        if owns_conn and conn is not None:
            conn.close()
```

- [ ] **Step 5: 给 cli.py 加 refine 子命令**

修改 `vigil/cli.py`：在 `cmd_media` 之后加 `cmd_refine`，在 `main()` 里注册子命令。

```python
def cmd_refine(args) -> int:
    """抽取：把消息变成结构化条目。"""
    from . import refine as refine_mod
    from .config import load_llm_key

    config = _load_config_only()
    db = _require_export_db(config)

    api_key = load_llm_key()
    if not api_key and not args.dry_run:
        sys.exit(
            "[配置错误] 没有 LLM 密钥。\n"
            "  请在仓库根目录的 .env 里写入：SILICONFLOW_API_KEY=sk-...\n"
            "  （--dry-run 不需要密钥）"
        )

    try:
        since_ts = reader._to_epoch(args.since)
        until_ts = reader._to_epoch(args.until)
    except ValueError as exc:
        sys.exit(f"[参数错误] {exc}")

    # refine() 会对 --redo/--limit 的非法组合抛 ValueError。不接的话用户看到的是
    # 裸 traceback，而不是一行可读的参数错误——与 other 子命令的既有风格不一致。
    try:
        stats = refine_mod.refine(
            config,
            api_key=api_key,
            db_path=db,
            since=since_ts,
            until=until_ts,
            limit=args.limit,
            redo=args.redo,
            batch_size=args.batch,
            context=args.context,
            budget_tokens=args.budget,
            # --model 不给时是 None，而 None 会绕过 refine() 的默认值，所以这里兜底
            model=args.model or refine_mod.DEFAULT_MODEL,
            prompt_ver=args.prompt_ver,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        sys.exit(f"[参数错误] {exc}")

    print("-" * 60)
    # ⚠️ 账目必须自洽：只报「硬丢弃」的话，用户会拿 scanned − discarded_local
    # 去对 sent_messages，然后发现差了三万多条不知道去哪了（Task 7 审查实测）。
    # 所以主数字用「本地筛掉」（= scanned − sent），硬丢弃作为其中一项列出。
    #
    # dry-run 时要报**计划**批数：实际批数必然是 0，显示「0 批」会让人
    # 以为什么都没准备好（Task 7 fix 实测指出）。
    shown_batches = stats.batches_planned if args.dry_run else stats.batches
    print(
        f"完成：扫描 {stats.scanned:,} 条 → 本地筛掉 "
        f"{stats.scanned - stats.sent_messages:,} 条"
        f"（其中硬丢弃 {stats.discarded_local:,} 条）"
        f" → 送模型 {stats.sent_messages:,} 条（{shown_batches:,} 批）"
    )
    print(f"产出条目：{stats.items_saved:,} 条")
    if not args.dry_run:
        print(f"token 用量：输入 {stats.input_tokens:,} / 输出 {stats.output_tokens:,}")
    if stats.budget_hit:
        # 报「实际跑了多少」而不是计划数——预算 break 后两者会差很多
        print(
            f"[注意] 达到预算上限提前停止：实际跑了 {stats.batches} 批，"
            f"计划 {stats.batches_planned} 批。剩余消息留待下次（或调大 --budget）"
        )
    if stats.errors:
        print(f"\n[失败] {len(stats.errors)} 批出错：")
        for e in stats.errors[:5]:
            print(f"  {e}")
    if args.dry_run:
        print("（--dry-run：未调用模型、未写库）")
    return 0
```

在 `main()` 里，`p_media` 那段之后加：

```python
    p_refine = sub.add_parser("refine", help="抽取：把消息提炼成结构化条目")
    p_refine.add_argument("--since", help="起始日期 YYYY-MM-DD")
    p_refine.add_argument("--until", help="结束日期 YYYY-MM-DD")
    p_refine.add_argument("--limit", type=int, help="最多处理多少条")
    p_refine.add_argument("--redo", action="store_true", help="重抽已处理过的消息")
    p_refine.add_argument("--batch", type=int, default=30, help="每批消息数")
    p_refine.add_argument("--context", type=int, default=2, help="候选各带几条上下文")
    p_refine.add_argument("--budget", type=int, help="token 预算上限")
    p_refine.add_argument("--model", default=None, help="覆盖默认模型")
    p_refine.add_argument(
        "--prompt-ver", default=refine_mod.PROMPT_VERSION,
        help="提示词版本号；改了提示词就换个号，便于区分与重跑",
    )
    p_refine.add_argument("--dry-run", action="store_true", help="只报告不调用模型")
    p_refine.set_defaults(func=cmd_refine)
```

`cmd_refine` 里已经用 `refine_mod.DEFAULT_MODEL` 与 `args.prompt_ver` 兜底，无需额外处理——`refine.py` 顶部的 `from .llm import DEFAULT_MODEL, ...` 已经把常量带进来了。

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/ -v`
Expected: 全部 passed

- [ ] **Step 7: 验证 CLI 接线**

Run: `.venv/Scripts/vigil.exe refine --dry-run`
Expected: 打印「将发送 N 条、分 M 批」，退出码 0，**不调用模型**

- [ ] **Step 8: Commit**

```bash
git add vigil/refine.py tests/test_refine.py vigil/config.py vigil/cli.py
git commit -m "feat: 加抽取编排与 vigil refine 命令"
```

---

### Task 8: 冒烟验收（M1 出口）

**Files:**
- Modify: `_probe_refine.py`（改造成可复用的验收脚本，或删除）
- 无源码改动（除非冒烟抓到 bug，那时走 scoped fix）

**Dependencies:** [Task 1–7 全部]

**Touches:** `docs/DATA-NOTES.md`, `_probe_refine.py`

**这是 M1 的出口证据，不是可选项。**

- [ ] **Step 1: 小样本试跑（先花小钱验质量）**

Run:
```bash
.venv/Scripts/vigil.exe refine --since 2026-09-12
```
Expected: 产出十几到几十条 items，输入 token 在万级

> ⚠️ **必须用 `--since` 不能用 `--limit`**——这是实测踩出来的：
> `pending_messages` 按 `ts ASC` 排序，`--limit` 取的是**最旧**的消息。
> 而这个语料最早那批恰好是**群刚建时玩互动功能**产生的
> （`戳了戳` / `的头，要长不高了` / `加入了群聊。`），里面没有任何有价值信息。
> 实测 `--limit 150` 只得 1 条 item，且那 150 条里有 14 条是 `ts=0` 脏数据。
> 换成时间窗才有代表性内容（失物招领、通知、二手都有）。

- [ ] **Step 2: 人工抽验分类准确率** ⚠️ **需用户本人参与**

Run:
```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import sqlite3
conn = sqlite3.connect('data/vigil.db')
rows = conn.execute('''
  SELECT i.kind, i.title, i.deadline_ts, s.content
  FROM items i
  JOIN item_sources src ON src.item_id = i.item_id
  JOIN messages s ON s.msg_id = src.msg_id
  ORDER BY random() LIMIT 25
''').fetchall()
for kind, title, dl, src in rows:
    print(f'[{kind}] {title}')
    print(f'   来源: {src[:90]}')
"
```

请用户逐条判断：**类目分对了吗？有没有该进 items 却被漏掉的？**

出口标准：**分类准确率 ≥ 80%**。不达标 → 改 `config/categories.toml` 的 `desc` 或提示词，重跑，重验。

- [ ] **Step 3: 验证可回溯**

Run:
```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import sqlite3
conn = sqlite3.connect('data/vigil.db')
n = conn.execute('SELECT count(*) FROM items').fetchone()[0]
orphan = conn.execute('''
  SELECT count(*) FROM items i
  WHERE NOT EXISTS (SELECT 1 FROM item_sources s WHERE s.item_id = i.item_id)
''').fetchone()[0]
broken = conn.execute('''
  SELECT count(*) FROM item_sources src
  WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.msg_id = src.msg_id)
''').fetchone()[0]
print(f'items 总数: {n}')
print(f'无来源的 items（必须为 0）: {orphan}')
print(f'指向不存在消息的来源（必须为 0）: {broken}')
"
```
Expected: 两个「必须为 0」都是 0

- [ ] **Step 4: 验证幂等**

Run:
```bash
.venv/Scripts/vigil.exe refine --limit 150
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import sqlite3
conn = sqlite3.connect('data/vigil.db')
print('items 总数:', conn.execute('SELECT count(*) FROM items').fetchone()[0])
"
```
Expected: 第二次运行报告「没有待处理的消息」，**items 总数不变**

- [ ] **Step 5: 验证预算护栏**

Run:
```bash
.venv/Scripts/vigil.exe refine --limit 200 --budget 500
```
Expected: 打印「已达预算上限…提前停止」，退出码 0，`refine_runs` 只覆盖部分消息

- [ ] **Step 6: 全量跑**

Run:
```bash
.venv/Scripts/vigil.exe refine
```
Expected: 跑完不崩；`refine_runs` 覆盖全部 47,719 条

- [ ] **Step 7: 验证 refine_runs 无遗漏**

Run:
```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe -c "
import sqlite3
conn = sqlite3.connect('data/vigil.db')
total = conn.execute('SELECT count(*) FROM messages').fetchone()[0]
run = conn.execute('SELECT count(*) FROM refine_runs').fetchone()[0]
print(f'messages: {total:,}   refine_runs: {run:,}   差: {total - run:,}')
for status, n in conn.execute('SELECT status, count(*) FROM refine_runs GROUP BY status'):
    print(f'  {status}: {n:,}')
print('items:', conn.execute('SELECT count(*) FROM items').fetchone()[0])
"
```
Expected: 「差」为 0（或仅剩 `--budget` 那一轮之后新增的少量）

- [ ] **Step 8: 记录实测数字**

把结果写进 `docs/DATA-NOTES.md` 的新章节「七、抽取层实测」，至少包含：总条数、items 条数、各 status 分布、token 用量、实际花费、分类准确率抽验结论。

- [ ] **Step 9: Commit**

```bash
git add docs/DATA-NOTES.md
git commit -m "docs: 记录 M1 抽取层的实测数字与验收结论"
```

---

## 完成标准（M1 出口）

全部满足才算 M1 收工：

- [ ] `vigil refine` 跑完 47,719 条无异常退出
- [ ] `refine_runs` 覆盖全部消息，无遗漏
- [ ] `items` 表有数据，每条都有 `item_sources` 可回溯，且指回真实存在的消息
- [ ] **抽样 100 条人工验收分类准确率 ≥ 80%**（用户参与）
- [ ] 重跑幂等：第二次不调模型、不增加 items
- [ ] 预算护栏可触发且如实报告
- [ ] `docs/DATA-NOTES.md` 记录了实测数字
