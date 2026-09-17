# VIGIL M6「配置从文件走到界面」实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `config/*.toml` 从「手工编辑的文件」变成「网页上可增删改的配置」——统一 load/save/validate、原子写、导入导出、LLM 配置、群号管理、类目编辑与重排，同时清掉 M5 遗留的 U-4 与那批 deferred。

**Architecture:** 三件事构成全部骨架——
① **配置是唯一真相源**：`config/*.toml` 由程序原子写出，数据库是派生物（spec §3.2）。
② **Web 的写边界钉在具体文件上**：Web 可写 `config/` 与 `data/overrides.db`，**不可写 `data/vigil.db`**，**也不写 `data/cache/`**（后者是 U-4 的落点）。
③ **一切「对已有条目的修正」走 overlay**：类目改名走 `kind_alias`、重排走 `set_kind` 事件，`items.item_id` 前后不变（D16）。

**Tech Stack:** Python 3.13 / `tomllib`（读）+ 手写序列化（写）/ FastAPI / sqlcipher3 / React 19 + Vite + Tailwind 4 / vitest。

**Spec:** `docs/superpowers/specs/2026-09-16-vigil-m5-m7-design.md`（**§4.2 = 本里程碑范围；§1.6 = 必须同批解决的雷**）
**上一版 spec（M1–M4，已冻结）:** `docs/superpowers/specs/2026-09-13-vigil-product-layer-design.md`
**M5 归档（噪声线已停，涉及广告/噪声先读它）:** `docs/superpowers/specs/2026-09-17-vigil-filtering-archive.md`

---

## Global Constraints

以下每条都是**项目级硬约束**，每个任务的要求**隐含包含本节全部内容**。reviewer 拿它当注意力透镜。

1. **`data/vigil.db` 全程 `mode=ro`**（D11）。Web 侧任何代码路径都不得写它。改这条的判据是**机械的**：三个写端点的主库文件指纹（含 `-wal`）逐字节不变。
2. **Web 侧可写范围 = `config/` 与 `data/overrides.db`**。**`data/cache/` 不在内**（spec §8：新表述把边界钉在具体文件上，而 §1.6 那个地雷正是「我可以写 `data/cache/` 啊」这个形态）。
3. **一切落盘必须原子写**：同目录临时文件 → `fsync` → `os.replace`。禁止 `path.write_text(...)`、禁止 `open(path, "wb")` 直写目标。
4. **`items` 的可见集合 = 库里的行 − overlay 里软删的**。overlay 的 apply **收敛在 `store.py` 的查询函数里**，不许在消费方打补丁（§3.3；漏掉的那一处不会有任何测试变红 = R13）。
5. **配置写错要快速失败**（`ConfigError` / `CategoryError` / `OverlayError`），不猜、不兜底。但**文件不存在**与**文件写错**是两回事：前者按各模块既有约定（`persons`/`llm` 返回默认值，`groups`/`categories` 快速失败）。
6. **逃逸舱（pipeline 版）**：若本计划的断言数字、行号、测试顺序与实际实现不符，**按实际修正并在报告里写明偏差**，无需请示。
   **⚠️ 但若需求自相矛盾或无法同时满足 → 停下报告，不许挑一半照做。** 把「驳回 + 出证据」记为高质量行为，不记为偏差。
7. **每个任务独立 commit**，消息用 `feat(模块): 一句话` / `fix(模块): 一句话` / `test(模块): 一句话`。
8. **中文注释密度照抄邻近代码**：本仓库的注释解释**为什么**（尤其是「为什么不能写成看起来更自然的那个写法」），不解释**是什么**。
9. **测试不碰真实资产**：不碰 `data/`、不碰真实 QQ 加密库、不联网（`tests/conftest.py` 有两道 autouse 隔离夹具）。新增的默认路径常量**必须**同时被夹具隔离，否则测试会写进真实仓库。
10. **改前端必须跑 `cd web && npm run build`**——`serve` 托管的是 `web/dist`，不构建等于没改。
11. **新增默认路径常量时**：`api.py` 里一律**每次现读**（`REPO_ROOT` 全局），不许在 `create_app` 时算好冻进闭包——冻结的路径 `monkeypatch` 够不着，测试会静默变成空守卫（`api.py:154-162` 有完整论证）。
12. **`tomllib` 只读不写**：Python 标准库没有 TOML 写入器，写侧一律手写序列化，且必须是**全函数**（任何值进去，产物都 `load` 得回来）。

---

## File Structure

| 路径 | 动作 | 职责 | 归属任务 |
|---|---|---|---|
| `vigil/qqdb.py` | 改 | `strip_fake_header` 原子写（U-4） | T1 |
| `vigil/cli.py` | 改 | `groups` 上锁；新增 `config`/`reorder` 子命令；`--base-url` 参数 | T1/T3/T7/T8 |
| `vigil/config.py` | 改 | 三份 toml 的序列化层：`toml_str`/`toml_int`/`save_config`/`save_persons`；LLM 配置文件读取 | T2/T3 |
| `vigil/categories.py` | 改 | `save_categories` + `slug_alias` 语义 | T2/T6 |
| `vigil/groups_snapshot.py` | **新** | 群清单快照的生成与读取（Web 的只读数据源） | T4 |
| `vigil/export.py` | 改 | export 结束时顺手刷新群清单快照 | T4 |
| `vigil/overrides.py` | 改 | 新增 `config_snapshots` / `kind_alias` 两张表与四个函数 | T5/T6 |
| `vigil/store.py` | 改 | `_EFFECTIVE_KIND` SQL 片段（overlay + alias 的收敛点） | T6 |
| `vigil/jobs.py` | **新** | 内存 job 注册表 + 后台线程 + 进度/取消 | T7 |
| `vigil/reorder.py` | **新** | LLM 重判已有条目的判定核心（不写库，出计划） | T7 |
| `vigil/configpack.py` | **新** | 配置包的导出/导入（单文件 TOML，不含密钥） | T8 |
| `vigil/api.py` | 改 | 群/类目/LLM/配置包/job 端点；写边界守卫扩展 | T4/T5/T6/T7/T8 |
| `config/llm.toml` | **新** | LLM 端点配置（**不含密钥**） | T3 |
| `web/src/test-setup.ts` | **新** | jsdom + testing-library 全局装配 | T9 |
| `web/src/views/Settings.tsx` | **新** | 配置界面（群 / 人 / LLM / 类目 四节） | T10 |
| `web/src/api.ts` / `types.ts` / `App.tsx` | 改 | 新端点契约 + 新 tab | T10 |

**测试文件**（与源码一一对应，不新建重复职责的文件）：

| 测试 | 覆盖 |
|---|---|
| `tests/test_qqdb.py` | **新** — `strip_fake_header` 的原子性 |
| `tests/test_config.py` | 改 — 序列化层 |
| `tests/test_categories.py` | 改 — `save_categories` |
| `tests/test_llm_config.py` | **新** — `config/llm.toml` 的读取与消费 |
| `tests/test_groups_snapshot.py` | **新** — 快照生成/读取 |
| `tests/test_overrides.py` | 改 — 新表与新函数 |
| `tests/test_store.py` | 改 — `_EFFECTIVE_KIND` |
| `tests/test_jobs.py` | **新** — job 生命周期 |
| `tests/test_reorder.py` | **新** — 重判判定核心 |
| `tests/test_configpack.py` | **新** — 导入导出 |
| `tests/test_api.py` | 改 — 新端点 |
| `web/src/__tests__/*.dom.test.tsx` | **新** — 组件层 |

---

---

## ⚠️ 执行期勘误（**读计划正文前先读这一节**）

> 与 M5 计划同形：实施期实测出来的偏差与计划缺陷集中记在这里。

### E1（controller 实测，T1 执行期发现）原子写的**峰值磁盘需求翻倍**，而没有任何测试看得见

**实测数字**（2026-09-17 21:20 前后，真机）：

```
data/cache/nt_msg_clear.db        3,285,852,160 字节  ≈ 3.29 GB
data/cache/group_info_clear.db       50,581,504 字节  ≈ 50 MB
data/cache/ 合计                   ≈ 3.2 GB
D 盘剩余                                      ≈ 24 GB（753 GB 的 97% 已被占用）

源库 nt_msg.db mtime   2026-09-17 21:15:46   （**比缓存新**）
缓存 nt_msg_clear.db mtime  2026-09-17 18:14:30  ⇒ 缓存判据**未命中** ⇒ 下次 strip 必重写
```

**T1 的原子写（`tmp → fsync → os.replace`）要求临时文件与旧文件**同时存在**。**

⇒ **峰值磁盘占用 = 2 × 3.29 GB ≈ 6.6 GB**（旧实现是就地截断，峰值 ≈ 3.3 GB）。
⇒ 而 `tests/test_qqdb.py` 里全部用例用的是**几百字节**的假库 —— **这个数字在测试里完全不可见**。

**判定：修法是对的，不因此改动。** 理由三条：
1. 24 GB > 6.6 GB，当前有足够余量；
2. **失败方向是安全的**：磁盘满时 `except BaseException` 会清掉临时文件、**旧缓存原样保留**，
   然后**响亮地抛错**（而旧实现在同一场景下留下的是一个**半拷贝的缓存**——虽然大小对不上会被下次判为未命中，但那是一个"看起来像数据坏了"的状态）；
3. 这是 T1「主修是锁、加固是原子写」里**加固**那一半的固有代价，而加固本身是 T1 明确要的。

**但要记下来**，因为它是"**反着再问一句**"的又一例：**T1 的全部变异反证都会变红、全部用例都会绿，而这个数字它一个字都说不出。**

⚠️ **M6 冒烟前必须做的一件事**：`data/` 下累积了 M4/M5 时期的备份（含一条 80 MB 的
`vigil.db.bak-before-downgrade-20260917-181505`）与 `data/cache/` 的 3.2 GB。
D 盘 97% 时再叠 6.6 GB 峰值是有风险的。**清理由用户决定，不在本计划范围内**——但
**若冒烟时撞到磁盘错误，先来看这一条**。

### E2（T1 implementer 实测）共用缓存文件是**两个**，不是计划正文说的一个

| 文件 | 谁写 | 大小 |
|---|---|---|
| `data/cache/nt_msg_clear.db` | `cli.py:92` / `export.py:330` | 3.29 GB |
| `data/cache/group_info_clear.db` | `cli.py:102` / `export.py:345` | 50 MB |

**计划 §T1 与 spec §1.6 都只提了第一个。** reviewer 已独立核实。
**判定：文档不全（Minor），不是修复不全**——T1 的锁包住 `_cmd_groups_locked` 的**整个函数体**，
两个文件都在保护范围内（`cli.py:75-82` 实测）。
**但 §1.6 的框架受到一处修正**：那个雷的筹码是「**两个**共用文件，合计 3.34 GB」，不是一个。

### E3（T1 implementer 报，controller 采信；**⚠️ 本节经 T1 reviewer 修订**）
`except BaseException` 清不掉 SIGKILL 留下的 `.tmp<pid>`

`strip_fake_header` 的失败清理只在 Python 能把异常接住时生效。**进程被硬杀（或断电）时，
临时文件会留在 `data/cache/` 里**——一个 3.29 GB 的垃圾。

**⚠️ 但 reason 必须改正（T1 reviewer 独立核实，controller 原写法是错的）**：

原写「`data/cache/` 会被 `strip_fake_header` **反复扫到**、残留只会越积越多」——
**这是事实错误**：该函数**从不列目录**（只对 `dst` 做 `is_file` / `stat` / `open`），
全仓也没有任何东西扫 `data/cache/`（唯二扫目录的是 `logs.prune_old_logs` 的 `LOG_DIR`
与 `media.index_cache` 的 `Pic`）。

⇒ **正确的理由只有一条、但它足够硬**：残留是**占盘** —— 一次硬杀留下 **3.29 GB**，
而 E1 已经算出 D 盘只剩 24 GB。**「越积越多」是假的；「一次就够疼」是真的。**

⇒ **判定：Minor，入延迟清单。** 最小修法（留给 triage）：

① **把 docstring 的范围说准**（推荐）：明说「本清理只覆盖 Python 能接住的失败路径；
   SIGKILL / 断电留下的临时文件**是知情接受的**，后果是占盘（3.29 GB 量级/次）」。
   —— 这与本项目「只说自己有资格说的话」是同一条判据：**一个说多了的理由，比没有理由更糟**，
   因为它会让后来者以为自己理解了，从而不去查真实的范围。

② **⚠️ 不要用「glob 全删 `dst.name + ".tmp*"`」**（**controller 原稿提过这条，已撤销**）：
   那会**误删一个并发写者的活临时文件**——而 **pid 后缀正是为并发准备的**
   （`strip_fake_header` 的 docstring 自己论证过：固定名只对单写者成立）。
   若确实要做清理，**必须同时限定「非本进程」与「足够旧」**两个条件，
   而"足够旧"需要一个阈值——那就是一个新参数、一份新语义，**不该顺手加在一个已闭环的任务里**。


---

### E4（T2 implementer 实测，**controller 已独立复跑确认**）⚠️ **计划对 TOML 段序的论证是事实错误**

**计划正文至少 5 处**（`600` / `622` / `852` / `910` / `1019-1020` / `1062` / `4880`）写着同一句话：

> 「TOML 里，一个 `[table]` 出现在 `[[array_of_tables]]` 之后，会被解析成**最后一个数组元素下的子表**（`groups[-1].settings`）」

**这是错的。** controller 用 `uv run python` + `tomllib` 独立复跑（2026-09-17）：

```python
tomllib.loads("[[groups]]
id = 111

[settings]
qq_db_dir = 'x'
")
# ⇒ 顶层键 = ['groups', 'settings']；raw.get("settings") == {'qq_db_dir': 'x'}
# ⇒ **没有嵌套**

tomllib.loads("[[groups]]
id = 111

[groups.settings]
x = 1
")
# ⇒ 顶层键 = ['groups']；raw['groups'][-1] == {'id': 111, 'settings': {'x': 1}}
# ⇒ **只有显式写全路径才嵌套**
```

**正确的事实**：TOML 的 `[header]` 是**从根算的绝对路径**。`[settings]` 无论写在哪里，
定义的都是**顶层** `settings`。会嵌套的只有 `[groups.settings]` 这种**显式带前缀**的写法。
（数组表之后的**裸键值对**——比如 `[[groups]]` 后直接写 `name = "x"`——确实落入 `groups[-1]`；
但那是裸键，不是 `[header]`。本计划把两者混为一谈了。）

**影响面（逐条判定）**：

| 处 | 原论证的作用 | 判定 |
|---|---|---|
| `_GROUPS_HEADER` / `configpack._HEADER` 的段序**要求** | 决定 `[settings]` 写在哪 | ✅ **要求保留**（与现有手写文件的形状一致、人读着自然），**依据作废** |
| `save_config` 落盘前的 `validate_config_raw` 自校 | 曾被说成"段序陷阱的**唯一**兜底" | ⚠️ **它仍然有价值**（挡零群、挡缺 `[settings]`、挡类型错），但**不挡段序**——段序根本不需要挡 |
| `test_save_config_writes_settings_before_groups` 的**变异反证** | 声称「挪到后面 ⇒ `load_config` 抛 `ConfigError`」 | ❌ **该变异根本不会红**——它是一段**错的变异反证**，比没有反证更危险 |
| `configpack.build`（`plan:4880`） | 同上 | 同上 |

**⭐ 这条修正的要点不是"改个说法"，而是它示范了本项目最贵的那条陈规**：

> **错的论证比没有论证更危险。** 一个写错的理由会让后来者**以为自己理解了**，于是不去验证——
> 而他会照着那个错理由去"修"一个不存在的问题（这正是 E1 说的「假红比假绿更贵」的同族）。

**⇒ 对已完成的 T2 的处理**：implementer 已把 4 处依据改成实测事实并标记「实测修正」，**判定采信**。
但 `test_save_config_writes_settings_before_groups` **那条测试本身要重新评估**（见下）。

**⇒ 对未执行的 T4/T7/T8 的要求**：`configpack.build`（T7）与任何新写的 `[settings]` 序列化，
**照旧把 `[settings]` 写在前面**（保持形状一致），但**注释里不许再写那个嵌套的理由**。
写一句实话即可：「与现有 `groups.toml` 的段序一致，便于人读与 diff」。

**⇒ 那条测试该怎么办（留给 T2 的 reviewer 裁决，这里是 controller 的倾向）**：
把断言从"段序"换成**真正该钉的不变量**——**产物的顶层键恰好是 `{settings, groups}`**：

```python
    import tomllib
    assert set(tomllib.loads(text)) == {"settings", "groups"}, (
        "生成的配置有预期外的顶层键——最常见的成因是 `[settings]` 被写成了 "
        "`[groups.settings]`（那才会嵌套），或者 [[groups]] 少了一层方括号"
    )
```

这条**有牙**（写错任何一个段头都会红），而"先后顺序"那一条**没有**。

---

## Task 1: U-4 —— `strip_fake_header` 原子写 + `groups` 上锁

**为什么要做（spec §1.6）**：`vigil groups` 列群列表靠 `strip_fake_header(...)`，它**就地截断重写** `data/cache/nt_msg_clear.db`，而 `export` 用的是**同一个文件**（`export._clear_db_path`）。并发时正在跑的 export 会读到半个文件，SQLite 报坏页 —— 于是「消息静默消失」被报告成「QQ 库物理坏页」，一个**指向错误方向**的诊断。

**⚠️ 本任务的修法有两半，主次必须说清**（如实标注，别粉饰）：

| 半 | 内容 | 它到底解决了什么 |
|---|---|---|
| **主** | `cmd_groups` 上锁（Step 5） | **消除并发本身**。这是真正的修复：`groups` 与 `export` 从此互斥，抢不到文件就不可能发生。 |
| **加固** | `strip_fake_header` 原子写（Step 3） | **不是**本任务的主要防线。在锁存在的前提下，生产里那条并发路径已经不可达 ⇒ 它今天**防的是一个将来**：任何新的 `strip_fake_header` 调用方都会自动继承「不会造出半个文件」这个性质，而不用记得再去加锁。 |

⚠️ **不要把它们说反**。若实测「去掉锁、只留原子写，并发实验仍然通过」，那是**正常的**（原子写确实能让读者看到完整内容），**不构成「锁可以省掉」的证据**——省掉锁之后两个进程仍会各自剥一次头、各自覆盖一次，而缓存判据（size + mtime）在两者之间抖动，**谁赢是随机的**；且 `os.replace` 在 Windows 上遇到被打开的 dst 会直接 `PermissionError`（见下面 Step 3 的 ⚠️）。

本任务只修 **CLI 侧**。Web 侧**永不接触 QQ 库**（T4 用快照绕开），所以 Web 不在这条并发里。

**Files:**
- Modify: `vigil/qqdb.py:11-12`（加 `import os`）、`vigil/qqdb.py:63-68`（写路径）
- Modify: `vigil/cli.py:61-103`（`cmd_groups` 上锁 + AlreadyRunning → 2）
- Create: `tests/test_qqdb.py`

**Interfaces:**
- Consumes: 无（本任务是最底层）
- Produces:
  - `qqdb.strip_fake_header(src: pathlib.Path, dst: pathlib.Path) -> pathlib.Path` —— **签名与返回值不变**，只有写路径变原子
  - `qqdb.QQDBError`（既有）
  - `cli.cmd_groups(args) -> int` —— 新增退出码 **2**（已有实例在跑）

---

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_qqdb.py`：

```python
"""`strip_fake_header` 的原子性 —— M6 T1（U-4）。

⚠️ 本文件**不需要**真实 QQ 加密库：`strip_fake_header` 只做字节搬运，
不解析、不解密。造一个「带假头的文件」就能完整覆盖它。

⚠️ 也不能用 sqlcipher：那是 `open_encrypted` 的事，本文件不碰它。
"""

from __future__ import annotations

import os
import pathlib
import threading

import pytest

from vigil import qqdb


def _make_fake_header_src(path: pathlib.Path, body: bytes) -> pathlib.Path:
    """造一个「带 1024 字节假头」的源库。"""
    path.write_bytes(qqdb._FAKE_HEADER_MAGIC + b"\x00" * (
        qqdb.FAKE_HEADER_SIZE - len(qqdb._FAKE_HEADER_MAGIC)
    ) + body)
    return path


def test_strips_the_fake_header(tmp_path):
    src = _make_fake_header_src(tmp_path / "nt_msg.db", b"BODY" * 100)
    dst = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")
    assert dst.read_bytes() == b"BODY" * 100


def test_plain_sqlite_is_copied_verbatim(tmp_path):
    """源文件已是明文 SQLite 结构 ⇒ 不偏移、原样复制。"""
    body = b"SQLite format 3\x00" + b"X" * 500
    src = tmp_path / "plain.db"
    src.write_bytes(body)
    dst = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")
    assert dst.read_bytes() == body


def test_cache_hit_does_not_rewrite(tmp_path):
    """大小对且不比源旧 ⇒ 直接返回，**不重写**（identity 不变）。"""
    src = _make_fake_header_src(tmp_path / "nt_msg.db", b"BODY" * 100)
    dst = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")
    before = dst.stat().st_ino
    dst2 = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")
    assert dst2 == dst
    assert dst.stat().st_ino == before, "缓存命中路径不该重写文件"


def test_rewrite_replaces_the_file_rather_than_truncating_it(tmp_path):
    """⭐ 本任务的核心断言（U-4 的机械判据）。

    **原子替换 ⇒ 文件身份变了**（新 inode 顶替旧的）。
    **截断重写 ⇒ 文件身份不变**（还是同一个文件，只是内容被从 0 字节重写）。

    所以 `st_ino` 的变化是原子性的**必要条件**，且它**确定、无计时依赖**——
    比「起两个线程赛跑」可靠得多（那种测试会 flaky，而 flaky 的守卫最终
    会被注释掉）。

    ⚠️ 变异反证：把 `os.replace(tmp, dst)` 换回
    `with open(dst, "wb") as out: ...` ⇒ 本条**必红**。
    """
    src = _make_fake_header_src(tmp_path / "nt_msg.db", b"OLD" * 200)
    dst = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")
    # ⚠️ 先响亮地确认度量工具本身可用：FAT 之类的文件系统上 `st_ino` 恒为 0，
    # 那种环境下本条会**恒真**（0 != 0 不成立 ⇒ 其实恒红，但红的原因与 U-4 无关）。
    # 与其留一个「在别的机器上意义不明」的守卫，不如让它在测量工具不可用时
    # **明说**。NTFS 上 `st_ino` 是有效的（CPython 走 GetFileInformationByHandle）。
    assert dst.stat().st_ino != 0, "本机的 st_ino 不可用，本条判据失效——请改用别的度量"
    old_ino = dst.stat().st_ino

    # 让源变新 ⇒ 必然走重写分支（缓存判据是 size + mtime）
    _make_fake_header_src(tmp_path / "nt_msg.db", b"NEW" * 200)
    os.utime(src, (src.stat().st_atime + 10, src.stat().st_mtime + 10))

    qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")
    assert dst.read_bytes() == b"NEW" * 200
    assert dst.stat().st_ino != old_ino, (
        "重写必须走 os.replace（新文件顶替），不能就地截断重写——"
        "后者会让并发读者看到半个文件，而 SQLite 把它报成「坏页」"
    )


def test_a_reader_never_sees_a_partial_file(tmp_path, monkeypatch):
    """并发读者看到的内容，**要么全旧、要么全新**（没有第三种状态）。

    ⚠️ 这条与上一条是**两个不同的判据**：上一条看「文件身份换没换」，
    这一条看「读者实际看到了什么」。前者是机制，后者是后果——
    只钉机制的话，将来有人把 `os.replace` 换成「先删后建」仍会绿，
    而那同样会给读者一个「文件不存在」的窗口。

    做法：把 `shutil.copyfileobj` 换成一个**边拷边读**的版本，
    在拷贝**中途**去读 dst——此刻 dst 必须是**完整的旧内容**。
    """
    src = _make_fake_header_src(tmp_path / "nt_msg.db", b"OLD" * 200)
    dst = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")

    _make_fake_header_src(tmp_path / "nt_msg.db", b"NEW" * 200)
    os.utime(src, (src.stat().st_atime + 10, src.stat().st_mtime + 10))

    seen: list[bytes] = []
    real_copyfileobj = qqdb.shutil.copyfileobj

    def spy(fsrc, fdst, length=0):
        real_copyfileobj(fsrc, fdst, length)
        # 拷完了才读一次 —— 此刻目标还没被 replace，读者应该看到**完整的旧内容**
        seen.append(dst.read_bytes())

    # ⚠️ **绝不要在这里写 `monkeypatch.undo()`**（M5 终审实测的坑）：pytest 的
    # `monkeypatch` 是**函数级单例**，`conftest.py` 那两个 autouse 隔离夹具用的是
    # **同一个实例** —— 一次 `undo()` 会把它们一起拆掉，于是本用例之后的代码
    # 会往**真实的** `data/overrides.db` 写字，而**没有任何断言变红**。
    # 补丁在测试结束时由 pytest 自动还原，本来就不需要手动 undo。
    monkeypatch.setattr(qqdb.shutil, "copyfileobj", spy)
    qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")

    assert seen == [b"OLD" * 200], (
        f"重写中途读到的必须是完整的旧文件，实际读到 {len(seen[0]) if seen else 0} 字节"
    )
    assert dst.read_bytes() == b"NEW" * 200


def test_failure_leaves_the_original_intact_and_no_temp_file(tmp_path, monkeypatch):
    """中途失败 ⇒ 原文件原样、且**不留临时文件**。

    ⚠️ 不留临时文件是承重的：`data/cache/` 会被 `strip_fake_header` 反复扫到，
    残留的 `.tmp<pid>` 会被后来的 cache 判据当成无关文件，越积越多。
    """
    src = _make_fake_header_src(tmp_path / "nt_msg.db", b"OLD" * 200)
    dst = qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")

    _make_fake_header_src(tmp_path / "nt_msg.db", b"NEW" * 200)
    os.utime(src, (src.stat().st_atime + 10, src.stat().st_mtime + 10))

    def boom(*a, **kw):
        raise OSError("磁盘满了")

    # ⚠️ 同样**不要** `monkeypatch.undo()`（理由见上一条用例）。
    monkeypatch.setattr(qqdb.shutil, "copyfileobj", boom)
    with pytest.raises(OSError):
        qqdb.strip_fake_header(src, tmp_path / "cache" / "clear.db")

    assert dst.read_bytes() == b"OLD" * 200, "失败不该动到已存在的目标文件"
    leftovers = [p.name for p in dst.parent.iterdir() if ".tmp" in p.name]
    assert leftovers == [], f"失败路径必须清掉临时文件，残留：{leftovers}"


def test_temp_file_name_is_unique_per_process(tmp_path, monkeypatch):
    """临时文件名必须**带 pid**：两个进程同时剥同一个 dst 时用同一个临时名会互踩。

    ⚠️ 这条不是"防御性编程"：`vigil groups` 与 `vigil export` 确实会并发
    （前者是人工命令、后者由任务计划在 08:00 触发），而 T1 的锁只挡住
    **同一个 dst 的两次 strip 同时发生**——它挡不住「两个进程在**同一时刻**
    各自往 `dst.tmp` 里写」这个形状，因为锁是在 `cmd_groups` 里加的，
    而 `strip_fake_header` 是公共函数，将来可能被别处调用。

    ⚠️ 且不管有没有锁：**用同一个临时名是错的**，修法不该依赖调用方的纪律。
    """
    src = _make_fake_header_src(tmp_path / "nt_msg.db", b"BODY" * 100)
    dst = tmp_path / "cache" / "clear.db"

    names: list[str] = []
    real_replace = qqdb.os.replace

    def spy_replace(a, b):
        names.append(pathlib.Path(a).name)
        return real_replace(a, b)

    # ⚠️ 同样**不要** `monkeypatch.undo()`（理由见上文）。
    monkeypatch.setattr(qqdb.os, "replace", spy_replace)
    qqdb.strip_fake_header(src, dst)

    assert len(names) == 1
    assert str(os.getpid()) in names[0], (
        f"临时文件名 {names[0]!r} 里没有 pid——固定名 `dst.tmp` 在并发下会互踩"
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_qqdb.py -v`
Expected: `test_strips_the_fake_header` / `test_plain_sqlite_...` / `test_cache_hit_...` **PASS**（这三条钉的是既有行为，先绿是对的）；`test_rewrite_replaces_the_file_rather_than_truncating_it` / `test_a_reader_never_sees_a_partial_file` / `test_failure_leaves_the_original_intact_and_no_temp_file` / `test_temp_file_name_is_unique_per_process` **FAIL**（当前实现是就地截断，`st_ino` 不变、中途读到新内容、失败会留半个文件）。

- [ ] **Step 3: 改 `vigil/qqdb.py`**

先加 `import os`（第 13 行附近，`import pathlib` 之后）：

```python
import os
import pathlib
import shutil
```

再把 `strip_fake_header` 的实现换掉（保留它原有的 docstring 开头两句，替换后半段与函数体）：

```python
def strip_fake_header(src: pathlib.Path, dst: pathlib.Path) -> pathlib.Path:
    """把 QQ 的加密库（带假头）复制成可被 SQLCipher 直接打开的形式。

    若源文件已是明文 SQLite 结构则原样复制。已存在且大小正确则跳过。

    ⚠️ **写 dst 必须原子**（U-4，M6 T1）。原实现是
    ``open(dst, "wb")`` —— 那是「**先截断、再拷**」，而 dst 与 `export`
    **共用同一个文件**（`export.py:329` 与 `cli.py:66` 指向同一个路径，
    由 `export._clear_db_path` 定义）。并发时
    （用户手跑 ``vigil groups`` 而任务计划正在跑 ``vigil export``）：

      1. 后者把这个文件**从 0 字节重新写**；
      2. 正在读它的 export 于是读到**半个文件 / 空洞**；
      3. SQLite 报的是**坏页** —— 于是「消息静默消失」被报告成
         「QQ 库物理坏页」，一个**指向错误方向**的诊断（spec §1.6）。

    ⇒ 改成「同目录临时文件 → fsync → ``os.replace``」：读者要么看到
    完整的旧版、要么看到完整的新版，**没有第三种状态**。
    ``os.replace`` 在同一文件系统上是原子的，Windows 上也成立。

    ⚠️ 临时文件名带 **pid**。固定名 ``dst.tmp`` 只对「单写者」成立，
    而这里恰恰是并发场景；用同一个临时名会让两个进程互相写坏对方正在拷的
    临时文件 —— 而那只会在 replace 之后才现形，**长得像数据损坏**。
    ⚠️ 临时文件必须与目标**同目录**（``os.replace`` 不跨卷）。
    ⚠️ 失败路径要清掉临时文件：`data/cache/` 会被本函数反复扫到，
    残留的 `.tmp<pid>` 只会越积越多。
    """
    if not src.is_file():
        raise QQDBError(f"库文件不存在: {src}")

    with open(src, "rb") as f:
        head = f.read(len(_REAL_HEADER_MAGIC))

    has_fake_header = head.startswith(_FAKE_HEADER_MAGIC[: len(head)]) and not head.startswith(
        _REAL_HEADER_MAGIC
    )
    offset = FAKE_HEADER_SIZE if has_fake_header else 0
    expected_size = src.stat().st_size - offset

    # 缓存命中：大小对且不比源旧。比 mtime 是必须的——QQ 一旦写入新消息，
    # 源库就变新了，此时必须重新剥头，否则会读到过期快照。
    if dst.is_file() and dst.stat().st_size == expected_size:
        if dst.stat().st_mtime >= src.stat().st_mtime:
            return dst

    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f"{dst.name}.tmp{os.getpid()}")
    try:
        with open(src, "rb") as f:
            f.seek(offset)
            with open(tmp, "wb") as out:
                shutil.copyfileobj(f, out, 64 << 20)
                # ⚠️ fsync 必须在 replace **之前**：否则断电时可能留下一个
                # 「名字已就位、内容还在页缓存里」的空文件——那比旧版本更糟，
                # 因为它**看起来是有效的**（大小对得上时连缓存判据都会放行）。
                out.flush()
                os.fsync(out.fileno())
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dst
```

⚠️ **Windows 上 `os.replace` 的一个已知行为，实施者必须知道**：若目标文件正被
另一个句柄打开（Python 的 `open()` 不带 `FILE_SHARE_DELETE`），`os.replace` 会抛
**`PermissionError`**，而不是静默降级。

这**正是**「主修是锁、不是原子写」的原因，也是那条「不要把它们说反」的实证：
单靠原子写的话，`vigil groups` 撞上正在读缓存文件的 `export` 会**直接报错**
（响亮，好过静默损坏，但不可用）；加上锁之后这条路径根本不会进入。

⚠️ 因此**不要**为了"让 `os.replace` 更宽容"而去catch `PermissionError` 然后退回
直写——那等于把 U-4 原样请回来，而且这次它藏在一个 `except` 后面，**更难被发现**。
失败就让它失败（`data/cache/` 是缓存，下次跑会重建）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_qqdb.py -v`
Expected: **7 passed**

- [ ] **Step 5: 给 `cmd_groups` 上锁**

`cmd_groups` 现在是同步函数体，直接改写成「薄壳 + 内部函数」的形状（**保持它原有的全部打印逻辑一字不动**，只把 `_load_or_die()` 那一段挪进 `_cmd_groups_locked`）：

```python
def cmd_groups(args) -> int:
    """列出 QQ 本地库里的群。

    ⚠️ **必须上锁**（M6 T1，U-4 的另一半）。本命令会经 `strip_fake_header`
    **写** `data/cache/nt_msg_clear.db`，而那个文件与 `vigil export` **共用**
    （`export._clear_db_path`）。不加锁时，用户手跑本命令会与任务计划正在跑的
    `vigil export` 并发访问同一个缓存文件。

    ⚠️ 原子写（Step 3）解决的是「读者不会看到半个文件」，**不解决并发本身**：
    两个进程各自剥一次头、各自覆盖一次是白费的重复劳动，而缓存判据
    （size + mtime）在两者之间抖动，谁赢是随机的。上锁之后本命令的语义与
    `export` / `refine` / `digest` **完全一致**：撞车时报「已有实例在跑」
    并给退出码 2，**响亮地失败**，而不是静默地互相踩。
    """
    try:
        with lock.SingleInstance():
            return _cmd_groups_locked(args)
    except lock.AlreadyRunning as exc:
        # 与 `cmd_daily` / `cmd_export` 同一语义：2 不是 1——「上一次还没跑完」
        # 等着就行，「这次跑失败了」才要人来看。
        logs.emit(f"[跳过] {exc}")
        return 2


def _cmd_groups_locked(args) -> int:
    config, key = _load_or_die()
    # ……（此处**逐字保留**原 `cmd_groups` 从 `counts = qqdb.list_group_message_counts(` 
    #     到 `return 0` 的全部内容，一行不改）
```

⚠️ **`_cmd_groups_locked` 的函数体就是原 `cmd_groups` 的 body**（`config, key = _load_or_die()` 起，到 `return 0` 止）。**不要顺手改任何一个 `print` 的字面量**——它们被 `tests/test_cli.py` 逐字断言。

- [ ] **Step 6: 写「上锁」的失败测试**

在 `tests/test_cli.py` 末尾追加（**放在该文件已有的 `cli_env` 风格夹具附近**；如果该文件用的是 `capsys` + `monkeypatch.setattr(lock, "LOCK_PATH", ...)` 的既有套路，照抄那个套路）：

```python
def test_groups_refuses_to_run_while_another_instance_holds_the_lock(cli_env, monkeypatch):
    """⭐ U-4 的另一半：`groups` 撞上正在跑的 export 时**响亮失败**，不静默并发。

    ⚠️ 变异反证：把 `cmd_groups` 里的 `with lock.SingleInstance():` 去掉
    ⇒ 本条**必红**（会真的去读 QQ 库并返回 0）。

    ⚠️ 判据必须是「退出码 2」而不是「抛了 AlreadyRunning」：退出码是
    任务计划与用户唯一能看的东西（`cmd_daily` / `cmd_export` 都是这个契约）。
    """
    def boom(self):
        raise lock.AlreadyRunning("已有实例在跑（锁：x；上次写入：pid=123）")

    monkeypatch.setattr(lock.SingleInstance, "__enter__", boom)
    rc = cli.main(["groups"])
    assert rc == 2
```

⚠️ 若 `tests/test_cli.py` 里没有名为 `cli_env` 的夹具，**去掉该参数**并改用该文件里既有的配置夹具（`grep -n "def cli_env\|@pytest.fixture" tests/test_cli.py` 先看清）。**不要新建一套与既有风格不同的夹具。**

- [ ] **Step 7: 跑测试确认通过**

Run: `uv run pytest tests/test_cli.py -v -k groups`
Expected: 全部 PASS（含新加的那条）

- [ ] **Step 8: 全量回归**

Run: `uv run pytest`
Expected: **612 passed**（605 基线 + 本任务新增 7 条 `test_qqdb.py`）。
⚠️ 数字以实际为准；**若与 612 不符，在报告里写明实际数字与差异原因**，不要改断言去凑。

- [ ] **Step 9: Commit**

```bash
git add vigil/qqdb.py vigil/cli.py tests/test_qqdb.py tests/test_cli.py
git commit -m "fix(qqdb,cli): strip_fake_header 改原子写 + groups 上锁（U-4 的一半）"
```

---

## Task 2: 配置序列化层 —— 三份 toml 的写侧

**为什么放在最前面**：T4（加群）、T6（类目编辑）、T8（导入导出）都要写 `config/*.toml`。写侧必须先有一个**被验证过是全函数**的实现，否则后面三个任务各自手搓一份 f-string 拼接，就会长出三套会漂移的序列化。

**本任务同时收掉 M5 遗留清单的三条**：
- **#19** `config.py:229` 的 `uin = {p.uin}` 是**裸 f-string ⇒ 可注入 TOML**（已复现：能写出第二个 `[[persons]]` 段头，并让整份文件 `TOMLDecodeError` 报废）。终审原话：**M6 做批量导入前必须收**——而 T8 正是批量导入。
- **#22** `uin = true` 被接受（`bool` ⊂ `int`）⇒ 建出一个 uin=1 的人。
- **#20** `uid` 不落配置**无用例** → 本任务补一行。

**⚠️ 本任务还会修一个既有缺陷（实施前请先读）**：`load_config` **没有把 `tomllib.TOMLDecodeError` 包成 `ConfigError`**，而 `load_categories` 包了（`categories.py:51-55` 有完整论证：「TOMLDecodeError 继承自 ValueError 而不是 RuntimeError，不包的话会绕过 cli 的错误处理契约，用户看到的是原始 traceback」）。今天 `groups.toml` 只由人手编辑，撞上的概率低；**M6 之后 Web 会写它**，一个序列化缺陷就会以「裸 traceback」而不是「一行可读的配置错误」收场。Step 1 有一条测试钉它。

**Files:**
- Modify: `vigil/config.py`（`toml_str` 公开化、新增 `toml_int`/`_toml_path`/`_validate_config_raw`/`save_config`、`load_config` 包 TOMLDecodeError、`save_persons` 加固）
- Modify: `vigil/categories.py`（抽出 `validate_categories`、新增 `save_categories`、头部注释常量）
- Modify: `vigil/api.py:99`（docstring 里的 `config._toml_str` 改名引用）
- Modify: `tests/test_config.py`, `tests/test_categories.py`

**Interfaces:**
- Consumes: T1 的 `qqdb` 改动（无直接依赖）；既有的 `config.atomic_write_text` / `config.REPO_ROOT` / `config.ConfigError`
- Produces（**后续任务照这些签名调用，不要另起名字**）：
  - `config.toml_str(value: str) -> str` —— TOML 基本字符串，**全函数**（原 `_toml_str`，只是去掉下划线）
  - `config.toml_int(value: object, field: str) -> int` —— 拒绝 `bool` 与非 int
  - `config.save_config(config: Config, path: pathlib.Path | None = None) -> None`
  - `config.save_persons(persons: Sequence[Person], path: pathlib.Path | None = None) -> None`（签名不变）
  - `config.load_config(path: pathlib.Path | None = None) -> Config`（签名不变，新增把语法错误包成 `ConfigError`）
  - `config.validate_config_raw(raw: dict, path: pathlib.Path) -> Config` —— 消费方：`save_config` 自己（落盘前自校）、T8 的 `configpack.py`（导入时校一份**尚未落盘**的字典）
  - `categories.validate_categories(entries: object, path: pathlib.Path) -> tuple[Category, ...]` —— 消费方：`load_categories`、`save_categories`、T8
  - `categories.save_categories(cats: Sequence[Category], path: pathlib.Path | None = None) -> None`

---

- [ ] **Step 1: 写失败的测试**

在 `tests/test_config.py` **末尾追加**：

```python
# ── M6 T2：写侧序列化层 ──────────────────────────────────────────────


def test_save_config_roundtrips(tmp_path):
    """`save_config` 的产物必须被 `load_config` 原样读回来。

    ⚠️ 这条钉的是「**全函数**」那一半：任何 `Config` 进去，产物都读得回来。
    但它**钉不住段序**——见下一条。
    """
    p = tmp_path / "groups.toml"
    cfg = config.Config(
        qq_db_dir=tmp_path / "qqdb",
        output_db=config.REPO_ROOT / "data" / "vigil.db",
        groups=(
            config.Group(id=111, name="甲群", enabled=True, tier="high"),
            config.Group(id=222, name="乙群", enabled=False),
        ),
    )
    (tmp_path / "qqdb").mkdir()
    config.save_config(cfg, p)
    back = config.load_config(p)
    assert back.groups == cfg.groups
    assert back.output_db == cfg.output_db


def test_save_config_writes_settings_before_groups(tmp_path):
    """⭐ `[settings]` 必须在 `[[groups]]` **之前**。

    TOML 里，一个 `[table]` 出现在 `[[array_of_tables]]` **之后**，
    会被解析成**最后一个数组元素下的子表**（`groups[-1].settings`）。
    文件看着没坏，而 `raw.get("settings")` 变成 `None` ⇒ 下一次
    `load_config` 报「缺少 [settings] 段」，**整个程序起不来**。

    ⚠️ 变异反证：把 `save_config` 里的 `lines = [HEADER, "", "[settings]"]`
    挪到 `for g in config.groups` 之后 ⇒ 本条**必红**（`load_config` 会抛
    `ConfigError`，因为顶层只剩 `groups`）。
    """
    p = tmp_path / "groups.toml"
    (tmp_path / "qqdb").mkdir()
    cfg = config.Config(
        qq_db_dir=tmp_path / "qqdb",
        output_db=config.REPO_ROOT / "data" / "vigil.db",
        groups=(config.Group(id=111, name="甲群"),),
    )
    config.save_config(cfg, p)
    text = p.read_text(encoding="utf-8")
    assert text.index("[settings]") < text.index("[[groups]]")
    # 再机械确认一次：解析出来的顶层键就是那两个
    import tomllib
    assert set(tomllib.loads(text)) == {"settings", "groups"}


def test_save_config_refuses_zero_groups(tmp_path):
    """⚠️ 拒绝写出零个群。

    不是洁癖：`load_config` 把「一个群都没配」当成配置错误（`[[]] 段为空`），
    所以写出一份零群的配置 = **把程序改成起不来**——而且下一次启动才现形，
    那时用户已经在网页上点过保存、拿到了「成功」。

    ⚠️ 这同时**否掉了一个看起来更自然的设计**：「删掉最后一个群」。
    要退掉最后一个群，正确动作是 `enabled = false`（保留配置、保留历史）。
    """
    p = tmp_path / "groups.toml"
    (tmp_path / "qqdb").mkdir()
    cfg = config.Config(
        qq_db_dir=tmp_path / "qqdb", output_db=config.REPO_ROOT / "data" / "vigil.db",
        groups=(),
    )
    with pytest.raises(config.ConfigError, match="零个群"):
        config.save_config(cfg, p)
    assert not p.exists(), "拒绝之后不许留下文件"


def test_save_config_keeps_repo_relative_paths_relative(tmp_path):
    """仓库内的路径写**相对**、仓库外的写**绝对**（`_toml_path` 的契约）。

    两个方向各有一个具体的坏法：
      · 全写绝对 ⇒ 配置搬到别的目录时仍指回原仓库（T8 的导入导出就废了）；
      · 全写相对 ⇒ `C:/Users/...` 的 QQ 库路径会被 `load_config` 拼成
        `REPO_ROOT / "C:/Users/..."`，一个不存在的路径。
    """
    p = tmp_path / "groups.toml"
    (tmp_path / "qqdb").mkdir()
    cfg = config.Config(
        qq_db_dir=pathlib.Path("C:/somewhere/nt_db"),
        output_db=config.REPO_ROOT / "data" / "vigil.db",
        groups=(config.Group(id=111, name="甲群"),),
    )
    config.save_config(cfg, p)
    text = p.read_text(encoding="utf-8")
    assert 'output_db = "data/vigil.db"' in text
    assert 'qq_db_dir = "C:/somewhere/nt_db"' in text


def test_save_persons_rejects_a_non_int_uin(tmp_path):
    """⭐ M5 遗留 #19 + #22：`uin` 必须是**真正的整数**，且**拒绝 bool**。

    ⚠️ 旧实现是裸 f-string `f"uin = {p.uin}"`，两个坏法：
      · `uin="1\\n[[persons]]\\nlabel=\\"注入\\""` ⇒ 写出**第二个段头**，
        整份文件结构被改写（已复现）；
      · `uin=True` ⇒ 写出 `uin = true`，读回来是 `uin = 1`（`bool` ⊂ `int`）。

    ⚠️ `Person` 是 frozen dataclass，**不强制类型** ⇒ 产品路径今天够不到它。
    但 T8 的批量导入会让它够到，所以必须在此之前收掉（终审原话）。

    ⚠️ 变异反证：把 `save_persons` 里那行换回 `f"uin = {p.uin}"`
    ⇒ 本条**必红**。
    """
    for bad in ("1\n[[persons]]\nlabel=\"注入\"", True, 1.5, "100000001"):
        with pytest.raises(config.ConfigError, match="uin"):
            config.save_persons(
                [config.Person(uin=bad, label="甲")], tmp_path / "persons.toml"  # type: ignore[arg-type]
            )
    assert not (tmp_path / "persons.toml").exists()


def test_saved_persons_never_contain_a_uid_key(tmp_path):
    """M5 遗留 #20：`uid` **不落配置**——`config/*.toml` 里不许出现它。

    ⚠️ 为什么要有这条：`Person` 的键是 `uin`，`uid` 只在**查询时**由
    `sender_names` 反查（spec §3.1：uid 与 uin 会脱节，落盘就等于把一份
    会过期的映射冻进配置）。今天靠「代码里没写 uid」保证，而
    **没有任何测试挡着后来者顺手加一列**。
    """
    p = tmp_path / "persons.toml"
    config.save_persons([config.Person(uin=100000001, label="甲")], p)
    assert "uid" not in p.read_text(encoding="utf-8")


def test_load_config_wraps_a_toml_syntax_error(tmp_path):
    """⚠️ 本任务修掉的既有缺陷：语法错误必须包成 `ConfigError`。

    不包的话 `tomllib.TOMLDecodeError`（继承自 **ValueError**，不是
    RuntimeError）会**绕过 `cli._load_config_only` 的 `except ConfigError`**，
    用户看到的是**裸 traceback** 而不是一行可读的配置错误。
    `load_categories` 早就这么做了（`categories.py:51-55` 有完整论证），
    `load_config` 没有——M6 之后 Web 会写这份文件，撞上的概率从
    「人手打错字」升到「一次序列化缺陷」。

    ⚠️ 变异反证：去掉 `load_config` 里那个 `try/except tomllib.TOMLDecodeError`
    ⇒ 本条**必红**（抛的是 TOMLDecodeError）。
    """
    p = tmp_path / "groups.toml"
    p.write_text("[settings\nqq_db_dir = 1\n", encoding="utf-8")
    with pytest.raises(config.ConfigError, match="TOML"):
        config.load_config(p)


def test_toml_str_is_reachable_under_its_public_name():
    """`_toml_str` → `toml_str` 的改名必须真的发生（`categories.py` 要 import 它）。

    ⚠️ 这条看着像废话，但它挡的是一个具体的形状：改名改了一半——
    留个 `_toml_str = toml_str` 的兼容别名。别名会让两处引用**看起来都在用
    `toml_str`**，而实际上 `save_persons` 走的是别名那条路，于是
    「谁在调用它」这个问题永远数不清（本项目反复吃「看起来有、其实没人看」
    那个形状的亏，见 `daily.RunReport.counters` 的墓碑）。
    """
    assert hasattr(config, "toml_str")
    assert not hasattr(config, "_toml_str"), "别留兼容别名"
```

在 `tests/test_categories.py` **末尾追加**：

```python
# ── M6 T2：写侧 ──────────────────────────────────────────────────────


def test_save_categories_roundtrips(tmp_path):
    p = tmp_path / "categories.toml"
    cats = (
        categories.Category(slug="notice", label="通知", desc="正式通知", icon="📋"),
        categories.Category(slug="life", label="生活", desc="吃住行"),
    )
    categories.save_categories(cats, p)
    assert categories.load_categories(p) == cats


def test_save_categories_rejects_an_invalid_slug(tmp_path):
    """⭐ 写路径必须复用**读路径的同一个校验函数**。

    ⚠️ 变异反证：把 `save_categories` 里那句 `validate_categories(...)` 删掉
    ⇒ 本条**必红**（会静默写出一个 `load_categories` 拒绝的文件）。

    ⚠️ 后果为什么特别重：`categories.py` 是 **refine 与 api 的硬依赖**，
    一份校验不过的 `categories.toml` 会让**整个程序起不来**——
    而它是原子写的，**没有任何自动回滚**。
    """
    p = tmp_path / "categories.toml"
    with pytest.raises(categories.CategoryError):
        categories.save_categories(
            [categories.Category(slug="Notice", label="大写", desc="slug 不合法")], p
        )
    assert not p.exists(), "校验不过就不许落盘"


def test_save_categories_rejects_discard_as_slug(tmp_path):
    """`discard` 是保留字（`refine_runs` 用它记「这条消息被丢了」），写侧也要挡。"""
    p = tmp_path / "categories.toml"
    with pytest.raises(categories.CategoryError):
        categories.save_categories(
            [categories.Category(slug="discard", label="丢弃", desc="保留字")], p
        )


def test_save_categories_refuses_zero(tmp_path):
    """⚠️ 零个类目会被 `load_categories` 判为配置错误 ⇒ 拒绝写出（与 `save_config` 同理）。"""
    p = tmp_path / "categories.toml"
    with pytest.raises(categories.CategoryError, match="零个类目"):
        categories.save_categories((), p)
    assert not p.exists()


def test_save_categories_escapes_a_quote_in_desc(tmp_path):
    """`desc` 里带引号/换行也必须写出可解析的 TOML（`toml_str` 的全函数性）。"""
    p = tmp_path / "categories.toml"
    cats = (categories.Category(slug="x", label='带"引号"', desc="第一行\n第二行"),)
    categories.save_categories(cats, p)
    assert categories.load_categories(p) == cats
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_config.py tests/test_categories.py -v`
Expected: 上面 12 条**全部 FAIL**（`save_config` / `toml_int` / `save_categories` / `validate_categories` 都还不存在；`load_config` 的语法错误仍抛 `TOMLDecodeError`）。

- [ ] **Step 3: 改 `vigil/config.py`**

**3a. `load_config` 拆成「读文件」+「校验」，并把语法错误包成 `ConfigError`。** 把现有的 `load_config` 整体替换为：

```python
def load_config(path: pathlib.Path | None = None) -> Config:
    path = path or DEFAULT_CONFIG
    if not path.is_file():
        raise ConfigError(f"找不到配置文件: {path}")

    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        # ⚠️ 必须包成 ConfigError（M6 T2 修）。`TOMLDecodeError` 继承自
        # **ValueError** 而不是 RuntimeError，不包的话会绕过
        # `cli._load_config_only` 的 `except ConfigError`，用户看到的是
        # **裸 traceback** 而不是一行可读的配置错误。
        # ⚠️ `load_categories` 从 M5 起就是这么做的（那里有完整论证），
        # 而本函数一直没跟上——今天 `groups.toml` 只由人手编辑、撞上的概率低，
        # **M6 之后 Web 会写它** ⇒ 一次序列化缺陷就会以 traceback 收场。
        raise ConfigError(f"{path}: TOML 语法错误——{exc}") from exc

    return validate_config_raw(raw, path)


def validate_config_raw(raw: dict, path: pathlib.Path) -> Config:
    """把**已解析**的 TOML 校验成 `Config`。

    ⚠️ **读路径与写路径共用这一个函数**（M6 T2）。写路径若另写一套校验，
    两份会漂移——而漂移的后果在这里尤其重：`save_config` 能写出
    `load_config` 拒绝的文件 ⇒ 一份配置永久落盘（原子写、无回滚）
    ⇒ **整个程序起不来**（`config.py` 是所有入口的硬依赖）。

    ⚠️ 它同时是 `[settings]` 段序陷阱的**唯一**兜底：段序写反时
    `raw` 的顶层只有 `groups`，`settings = raw.get("settings")` 得到 `None`
    ⇒ 直接报「缺少 [settings] 段」。写路径因此在落盘前就能自己发现。
    """
    # ↓↓↓ 以下为原 `load_config` 从 `settings = raw.get("settings")`
    #     到 `return Config(...)` 的**逐字搬移**，一行不改 ↓↓↓
    settings = raw.get("settings")
    if not isinstance(settings, dict):
        raise ConfigError(f"{path}: 缺少 [settings] 段")

    for field in ("qq_db_dir", "output_db"):
        if not settings.get(field):
            raise ConfigError(f"{path}: [settings] 缺少 {field}")

    qq_db_dir = pathlib.Path(settings["qq_db_dir"])
    if not qq_db_dir.is_dir():
        raise ConfigError(f"QQ 数据库目录不存在: {qq_db_dir}")

    output_db = pathlib.Path(settings["output_db"])
    if not output_db.is_absolute():
        output_db = REPO_ROOT / output_db

    groups: list[Group] = []
    for entry in raw.get("groups", []):
        gid = entry.get("id")
        if not isinstance(gid, int) or gid <= 0:
            raise ConfigError(f"{path}: 群号必须为正整数，实际是 {gid!r}")
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

    if not groups:
        raise ConfigError(f"{path}: 一个群都没配（[[groups]] 段为空）")

    return Config(qq_db_dir=qq_db_dir, output_db=output_db, groups=tuple(groups))
```

**3b. 把 `_TOML_ESCAPES` / `_toml_str` 改名并公开，同时新增 `toml_int` 与 `_toml_path`。** 在 `atomic_write_text` 之后插入：

```python
# ── 写侧序列化（M6 T2）──────────────────────────────────────────────
#
# ⚠️ Python 标准库**只有 `tomllib`（读）**，没有写入器。本仓库的依赖表只有
# sqlcipher3，不为写 TOML 引第三方库。所以写侧是手写的，而手写序列化
# **唯一的正确性判据是「全函数」**：
#
#     任何合法的值进去，产出的文本都要能被 `tomllib` 读回**同一个值**。
#
# ⚠️ 光有「全函数」还不够：它只覆盖**值**，不覆盖**段序**（`[settings]` 掉到
# `[[groups]]` 后面）与**键名**。那两样由各自的 `save_*` 用「先解析、再喂给
# 读路径的同一个校验函数」挡住（见 `save_config` / `save_categories`）。


def toml_str(value: str) -> str:
    """TOML 基本字符串——**全函数**：任何字符串进去，`save` 的产物都 `load` 得回来。

    ⚠️ 只转义反斜杠与双引号是**不够**的：一个带换行的 label 会写出**解析不了**的 toml，
    而原子写会让它**永久落盘**——`save` 成功返回、`load` 从此抛 `TOMLDecodeError`，
    整份文件连读都读不出来（M5 T7 实测，见 task-7-report.md）。

    ⚠️ 这里只是**转义**那一半；「名字里不许有换行」的**拒绝**在 API 层——
    `config/*.toml` 是人手输的，把一个换行静默存进"名字"里、再在界面上错乱显示，
    比直接报错更不诚实。

    ⚠️ 原名为 `_toml_str`，M6 T2 去掉下划线：`categories.py` 的写侧要用它，
    而跨模块 import 一个下划线名字是在制造「这是私有的、但谁都在用」的假象。
    """
    out: list[str] = []
    for ch in value:
        esc = TOML_ESCAPES.get(ch)
        if esc is not None:
            out.append(esc)
        elif ch < " " or ch == "\x7f":
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def toml_int(value: object, field: str) -> int:
    """把值当整数写出——**拒绝 bool，也拒绝「能转成整数的字符串」**。

    ⚠️ `bool` 是 `int` 的子类（`True == 1`），所以裸的 `isinstance(x, int)`
    会放行 `True` ⇒ 写出 `uin = true`，读回来是 `uin = 1`（M5 遗留 #22，已复现）。

    ⚠️ 也不接受 `"100000001"` 这类字符串：给「静默转一下」留口子，就等于把
    `api._edit_id_of` 那个 `int("abc")` → 500、`1.9` → 静默截断成 1 的缺陷
    换个形状请回来（那里已有完整论证）。**契约是「整数」而不是「能转成整数的东西」。**

    ⚠️ 它同时是 M5 遗留 #19 的落点：旧代码是裸 f-string `f"uin = {p.uin}"`，
    一个非 int 的值可以**注入 TOML**（已复现：写出第二个 `[[persons]]` 段头，
    并让整份文件 `TOMLDecodeError` 报废）。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f"{field} 必须是整数（**拒绝 bool**：True 是 int 的子类，会静默变成 1；"
            f"也拒绝字符串：静默转换会把「1.9 截断」那类缺陷请回来），"
            f"实际是 {value!r}（{type(value).__name__}）"
        )
    return value


def _toml_path(value: pathlib.Path) -> str:
    """把路径写成 TOML 字符串：**能在仓库内相对表达就相对**，否则写绝对。

    ⚠️ 不统一成绝对、也不统一成相对——两个方向各有一个具体的坏法：

      · **全写绝对** ⇒ 配置文件搬到别的目录时仍指回原仓库。T8 的「配置包
        在另一个目录导入并生效」会因此**静默指向旧库**（判据 4 直接失败）。
      · **全写相对** ⇒ `REPO_ROOT` 之外的路径（QQ 库在 `C:/Users/...`）
        会被 `validate_config_raw` 拼成 `REPO_ROOT / "C:/Users/..."`
        —— 一个不存在的路径，`qq_db_dir` 的存在性检查立刻报错
        （响亮，但那句话对用户毫无意义）。
    """
    try:
        return toml_str(value.relative_to(REPO_ROOT).as_posix())
    except ValueError:
        return toml_str(value.as_posix())
```

然后把 `_TOML_ESCAPES` 改名成 `TOML_ESCAPES`（连同它上面那段注释里的引号），并删掉旧位置的 `_toml_str`。

**3c. 新增 `save_config`。** 在 `save_persons` 之前插入：

```python
_GROUPS_HEADER = """\
# VIGIL 监听群配置
#
# ── 怎么加群 ───────────────────────────────────────────────
#   1. 跑 `vigil groups`，它会列出 QQ 本地库里所有群
#      （含群号、群名、消息数，以及「是否已纳入」）
#   2. 把新群的 id 按下面格式加一段 [[groups]]
#   3. 重跑 `vigil export`。**每次都是全量重读所有已纳群**（不做增量记账，
#      实测 4.7 万条几秒），写入用 INSERT OR REPLACE，所以重跑不会产生重复行。
#      新群加进来后第一次 export 就会拉到它的全部历史。
#
# ── 怎么退群 ───────────────────────────────────────────────
#   把 enabled 改成 false（保留配置便于回看），或整段删掉。
#   已导出的历史数据留在库里不动——那是你的记录。
#
# ⚠️ **本文件由程序整体重写**（网页「配置」页保存时会覆盖它）：
#    手工改也行，但**手工加的注释会在下一次网页保存时消失**。
#
# 注意：刚加入的新群，QQ 需要先把它同步到本地库
#      （group_info.db 出现群名、nt_msg.db 开始落消息），
#      之后 `vigil groups` 才看得见。刚加完立刻查可能是空的。
"""


def save_config(config: Config, path: pathlib.Path | None = None) -> None:
    """整体替换写出群配置（原子）。

    ⚠️ 是**整体替换**不是追加：追加语义下「删掉一个群」永远做不到
    （与 `save_persons` 同一条理由）。

    ⚠️ **`[settings]` 必须写在 `[[groups]]` 之前**，且这一点由
    `validate_config_raw` 兜底：TOML 里一个 `[table]` 出现在
    `[[array_of_tables]]` 之后，会被解析成**最后一个数组元素下的子表**
    （`groups[-1].settings`）。文件看着没坏，而 `raw.get("settings")` 变成
    `None` ⇒ 下一次 `load_config` 报「缺少 [settings] 段」，**程序起不来**。
    本函数**在落盘之前**把这句校验收于一步（见末尾）。

    ⚠️ 路径走 `_toml_path`（仓库内相对、仓库外绝对），不要图省事写绝对。
    """
    target = path or DEFAULT_CONFIG

    # ⚠️ 拒绝零个群**不是洁癖**：`validate_config_raw` 把「一个群都没配」
    # 当成配置错误，所以写出一份零群的配置 = **把程序改成起不来**——
    # 而且下一次启动才现形，那时用户已经在网页上点过保存、拿到了「成功」。
    # ⚠️ 这同时**否掉了一个看起来更自然的设计**：网页上「删掉最后一个群」。
    # 正确动作是 `enabled = false`（保留配置、保留历史）。
    if not config.groups:
        raise ConfigError(
            "拒绝写出零个群的配置：读回来会被判成「一个群都没配」的配置错误，"
            "整个程序起不来。要退掉最后一个群，请改成 `enabled = false`"
            "（保留配置、保留已导出的历史）。"
        )

    lines = [
        _GROUPS_HEADER,
        "",
        "[settings]",
        f"qq_db_dir = {_toml_path(config.qq_db_dir)}",
        f"output_db = {_toml_path(config.output_db)}",
        "",
    ]
    for g in config.groups:
        lines.append("[[groups]]")
        lines.append(f"id = {toml_int(g.id, '群号')}")
        lines.append(f"name = {toml_str(g.name)}")
        lines.append(f"enabled = {'true' if g.enabled else 'false'}")
        lines.append(f"tier = {toml_str(g.tier)}")
        lines.append("")

    text = "\n".join(lines)

    # ⚠️ **顺序是承重的：先自己解析+校验，再落盘**。反过来的话，一份不合法的
    # 配置已经落盘了才发现不对——而 `atomic_write_text` 是原子写，
    # **没有任何自动回滚**，那份坏配置会一直躺在那里直到有人手动修。
    # ⚠️ 校验的是**最终文本**（而不是内存里的 `Config`）：只有这样才能抓到
    # 序列化本身的缺陷（漏转义的引号、写反的段序），而不只是数据的问题。
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"内部错误：为 {target} 生成的 TOML 解析不了——{exc}") from exc
    validate_config_raw(raw, target)

    atomic_write_text(target, text)
```

**3d. 加固 `save_persons`。** 把写 `uin` 那行换掉（**其余一字不动**）：

```python
    for p in persons:
        lines.append("[[persons]]")
        # ⚠️ 走 `toml_int` 而不是裸 f-string（M5 遗留 #19/#22）：
        # 裸 f-string 让一个非 int 的值**可注入 TOML**（已复现：能写出第二个
        # `[[persons]]` 段头，并让整份文件 `TOMLDecodeError` 报废），
        # 而 `uin = true` 会被接受（bool ⊂ int）⇒ 建出一个 uin=1 的人。
        # `Person` 是 frozen dataclass 但**不强制类型**，所以产品路径今天
        # 够不到它——T8 的批量导入会让它够到，故必须在此之前收掉。
        lines.append(f"uin = {toml_int(p.uin, 'uin')}")
        lines.append(f"label = {toml_str(p.label)}")
        if p.note:
            lines.append(f"note = {toml_str(p.note)}")
        lines.append("")
```

**3e. 更新 `vigil/api.py:99` 的 docstring 引用**：`config._toml_str` → `config.toml_str`。

- [ ] **Step 4: 改 `vigil/categories.py`**

**4a. 从 `load_categories` 里抽出 `validate_categories`**，并把 `load_categories` 改成薄壳：

```python
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

    return validate_categories(raw.get("categories"), path)


def validate_categories(entries: object, path: pathlib.Path) -> tuple[Category, ...]:
    """把**已解析**的 `categories` 段校验成 `Category` 元组。

    ⚠️ **读路径与写路径共用这一个函数**（M6 T2 抽出来的）。写路径若另写一套
    校验，两份会漂移——而漂移的后果在这里尤其重：`save_categories` 能写出
    `load_categories` 拒绝的文件 ⇒ 一份校验不过的 `categories.toml` 永久落盘
    ⇒ **整个程序起不来**（本模块是 refine 与 api 的硬依赖）。

    ⚠️ 参数是 `entries` **而不是 `raw`**：段序/键名的问题在上游（`raw.get`），
    本函数只管这一段里面的形状。把两件事混在一个签名里，会让写路径
    不得不伪造一个 `raw` 字典才能调用它。
    """
    # ↓↓↓ 以下为原 `load_categories` 从 `if entries is None:`
    #     到 `return tuple(out)` 的**逐字搬移**，一行不改 ↓↓↓
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
```

**4b. 新增 `save_categories`。** 在文件末尾（`prompt_block` 之后）追加：

```python
_CATEGORIES_HEADER = """\
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
#
# ⚠️ **本文件由程序整体重写**（网页「配置」页保存时会覆盖它）：
#    手工改也行，但**手工加的注释会在下一次网页保存时消失**。
"""


def save_categories(cats: Sequence[Category], path: pathlib.Path | None = None) -> None:
    """整体替换写出类目配置（原子）。

    ⚠️ **在落盘之前**先自己解析、再喂给 `validate_categories`。顺序是承重的：
    反过来的话，一份不合法的配置已经原子落盘了才发现不对，
    **没有任何自动回滚**，而 `categories.toml` 是 refine 与 api 的硬依赖
    ⇒ 整个程序起不来。

    ⚠️ 校验的是**最终文本**（而不是内存里的 `Category`）：只有这样才能抓到
    序列化本身的缺陷（漏转义的引号），而不只是数据的问题。
    """
    target = path or DEFAULT_CATEGORIES

    if not cats:
        raise CategoryError(
            "拒绝写出零个类目：读回来会被判成「[[categories]] 段为空」的配置错误，"
            "而 refine 的提示词要用它渲染类目表 ⇒ 整个程序起不来。"
            "确实一个类目都不想要时，请手工编辑本文件并自行承担后果。"
        )

    lines = [_CATEGORIES_HEADER, ""]
    for c in cats:
        lines.append("[[categories]]")
        lines.append(f"slug = {toml_str(c.slug)}")
        lines.append(f"label = {toml_str(c.label)}")
        if c.icon:
            lines.append(f"icon = {toml_str(c.icon)}")
        lines.append(f"desc = {toml_str(c.desc)}")
        lines.append("")

    text = "\n".join(lines)
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CategoryError(f"内部错误：为 {target} 生成的 TOML 解析不了——{exc}") from exc
    validate_categories(raw.get("categories"), target)

    atomic_write_text(target, text)
```

**4c. 改 import**（文件顶部）：

```python
from collections.abc import Sequence

from .config import REPO_ROOT, atomic_write_text, toml_str
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_config.py tests/test_categories.py -v`
Expected: 全部 PASS（含新增 12 条）

- [ ] **Step 6: 全量回归**

Run: `uv run pytest`
Expected: 与 T1 结束时的数字相比 **+12**。
⚠️ 若 `test_load_config_wraps_a_toml_syntax_error` 之外有**既有**用例变红，**先查是不是改名 `_toml_str`→`toml_str` 漏改了引用**（`grep -rn "_toml_str" vigil/ tests/ --include=*.py` 应当**零命中**）。

- [ ] **Step 7: Commit**

```bash
git add vigil/config.py vigil/categories.py vigil/api.py tests/test_config.py tests/test_categories.py
git commit -m "feat(config,categories): 配置写侧序列化层 + TOML 语法错误包成 ConfigError（M5 遗留 #19/#20/#22）"
```

---

## Task 3: LLM 配置（spec §4.2 ②，#5）

**目标**：`base_url` / `model` 从文件读，`refine` **与** `digest` **两处都生效**（出口判据 3），且 `enable_thinking` 这个 SiliconFlow/Qwen 的**扩展字段**可以被「不发」（R12）。

**⚠️ 实施前必须先理解的一个既有事实**（读代码时实测，不是猜测）：

```
refine.py:393    enable_thinking: bool | None = False
digest.py:558    enable_thinking: bool | None = False
repass.py:591    enable_thinking: bool | None = False
```

**默认是 `False` 而不是 `None` ⇒ 今天这个字段是「总是发出去」的**，只是值恰好为 `false`。而 `cmd_refine` / `cmd_digest` 的 `--think` 是 `store_true`（默认 `False`），`daily.py` 更是**根本不传** `enable_thinking`（用默认 `False`）。

⇒ 所以「切到自建 base_url 就 400」这条 R12 风险**今天是活的**：换端点的人拿不到「不发」这个形状。本任务要做的不是"加一个开关"，而是**让「不发」成为一种可达状态**。

**⚠️ 由此推出本任务唯一的设计难点，以及它的答案**：`LLMSettings.enable_thinking` 的默认值选错，会造成**静默的 40 倍慢**（实测：不传该字段，Qwen3.5-35B-A3B 单批 111.5s / 11,124 输出 token；传 `false` 只要 2.8s / 220 token）。规则必须**只有一条**，且"文件缺失"这件事必须**被说出来**：

| `config/llm.toml` 的状态 | `enable_thinking` 的值 | 报文里 | 为什么 |
|---|---|---|---|
| **文件不存在** | `None` | **不发** | 单一规则：没写 = 不发。**但这一支会 `on_warn` 报一声**（见下），否则「删了个文件就慢 40 倍」是静默的 |
| 存在，**没写该键** | `None` | **不发** | 同上——用户正在写一份自定义端点配置，他没提这个字段，最安全的形状是不发 |
| 存在，`= false` | `False` | 发 `false` | 出厂文件就是这个值，保持今天的行为 |
| 存在，`= true` | `True` | 发 `true` | |

⇒ **出厂就带 `config/llm.toml`，内容含 `enable_thinking = false`**，所以默认路线上表第三行命中，行为与今天**一字不差**。表第一行只在「用户主动删掉那个文件」时出现，且它**会说话**。

**Files:**
- Create: `config/llm.toml`
- Modify: `vigil/config.py`（`LLMSettings` / `DEFAULT_LLM_TOML` / `load_llm_settings` / `save_llm_settings`）
- Modify: `vigil/refine.py:385-400`（签名加 `base_url`）、`vigil/refine.py:522-524`（构造点）
- Modify: `vigil/digest.py:548-562`（签名）、`vigil/digest.py:660-668`（构造点）
- Modify: `vigil/repass.py:586-600`（签名）、`vigil/repass.py:647-650`（构造点）
- Modify: `vigil/cli.py`（`cmd_refine` / `cmd_digest` / `cmd_repass` 读设置 + 新增 `--base-url`）
- Modify: `vigil/daily.py:186-247`（读设置并传给两处）
- Create: `tests/test_llm_config.py`

**Interfaces:**
- Consumes: T2 的 `config.toml_str` / `atomic_write_text` / `ConfigError`
- Produces:
  - `config.LLMSettings` —— frozen dataclass，字段 `base_url: str` / `model: str` / `enable_thinking: bool | None`
  - `config.DEFAULT_LLM_TOML: pathlib.Path` = `REPO_ROOT / "config" / "llm.toml"`
  - `config.load_llm_settings(path: pathlib.Path | None = None, *, on_warn: Callable[[str], None] | None = None) -> LLMSettings`
  - `config.save_llm_settings(settings: LLMSettings, path: pathlib.Path | None = None) -> None`
  - `refine.refine(..., base_url: str = DEFAULT_BASE, ...)` / `digest.digest(..., base_url: str = DEFAULT_BASE, ...)` / `repass.repass(..., base_url: str = DEFAULT_BASE, ...)` —— **只增不改**，`enable_thinking` 的默认值**保持 `False` 不动**

---

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_llm_config.py`：

```python
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
    monkeypatch.setattr(config, "DEFAULT_LLM_TOML", tmp_path / "nope.toml")
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

    ⚠️ 变异反证：把 `refine.py` 里构造 `LLMConfig` 那行的
    `enable_thinking=enable_thinking` 改成 `enable_thinking=False`
    ⇒ 本条**必红**。
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_llm_config.py -v`
Expected: 全部 FAIL（`config.LLMSettings` / `load_llm_settings` / `save_llm_settings` / `DEFAULT_LLM_TOML` 都不存在）。
⚠️ `test_the_end_to_end_wire_format_omits_the_field` 与 `test_base_url_reaches_the_request` 里**用到了 `llm.LLMConfig` 的既有能力**（它今天已经能省略字段）——这两条会在 `LLMSettings` 存在之后才开始真正约束"上层有没有把值传下来"。

- [ ] **Step 3: 建 `config/llm.toml`**

```toml
# VIGIL 的 LLM 端点配置
#
# ⚠️ **本文件里永远不放密钥。** 密钥走仓库根的 `.env`（`SILICONFLOW_API_KEY`），
#    因为 `config/*.toml` 是**要进 git** 的（spec §3.2 / D11）。
#
# ⚠️ **本文件由程序整体重写**（网页「配置」页保存时会覆盖它）：
#    手工改也行，但**手工加的注释会在下一次网页保存时消失**。
#
# 改完不需要重启服务：`vigil refine` / `vigil digest` 每次运行都会重新读它。

[llm]

# OpenAI 兼容的 chat completions 端点（**要写到 /chat/completions 为止**）。
base_url = "https://api.siliconflow.cn/v1/chat/completions"

# 模型名。换模型前先读 `docs/M1-模型评估.md`：
# 2026-09-14 六模型对照实测，Qwen/Qwen3.5-35B-A3B 总延迟 64s，
# 其余模型 179–259s，快 3–4 倍，且引用匹配率并列最好。
model = "Qwen/Qwen3.5-35B-A3B"

# ── enable_thinking：三态，**别删这一行** ──────────────────────────
#
#   不写这一行        → **不发这个字段**（通用 OpenAI 端点最安全的形状）
#   = false           → 发 false  ← 出厂值，硅基流动 / Qwen 用这个
#   = true            → 发 true
#
# ⚠️ 它是 **SiliconFlow / Qwen 的扩展字段**：通用 OpenAI 端点不认它，
#    会直接 400（spec §6 R12）。所以换到自建端点时把它**删掉**，
#    而不是改成别的值。
#
# ⚠️ 反过来，用 Qwen3/Qwen3.5 这类**混合思考模型**时**必须**保持 false：
#    实测 Qwen3.5-35B-A3B 不传该字段要 111.5s / 11,124 输出 token，
#    传 false 只要 2.8s / 220 token —— **40 倍差距**。
enable_thinking = false
```

- [ ] **Step 4: 在 `vigil/config.py` 里加读取与写出**

在文件顶部常量区加（`DEFAULT_PERSONS` 之后）：

```python
DEFAULT_LLM_TOML = REPO_ROOT / "config" / "llm.toml"
```

在 `save_persons` 之后加：

```python
@dataclass(frozen=True)
class LLMSettings:
    """LLM 端点配置（`config/llm.toml`）。**这里没有密钥，也不许加**（spec §3.2）。

    ⚠️ `enable_thinking` 是**三态**，不是布尔：

    | 值 | 报文里 | 什么时候用它 |
    |---|---|---|
    | `None` | **不发这个键** | 通用 OpenAI 端点（SiliconFlow/Qwen 的扩展字段它们不认，会 400） |
    | `False` | 发 `false` | Qwen3/Qwen3.5 这类混合思考模型（不发会慢 **40 倍**，实测） |
    | `True` | 发 `true` | 显式要思考 |

    ⚠️ **默认是 `None` 而不是 `False`**——这与 `llm.LLMConfig` 的默认一致
    （那里有完整论证：「留 None 而不是 False 做默认：老模型不一定认这个字段，
    不发才是对它们最安全的形状」）。而"出厂路线上会不会变慢"由
    **`config/llm.toml` 里显式写着 `enable_thinking = false`** 保证，
    不由这个 dataclass 的默认值保证。
    """

    base_url: str = llm.DEFAULT_BASE
    model: str = llm.DEFAULT_MODEL
    enable_thinking: bool | None = None


def load_llm_settings(
    path: pathlib.Path | None = None,
    *,
    on_warn: Callable[[str], None] | None = None,
) -> LLMSettings:
    """读 LLM 端点配置。

    ⚠️ **文件不存在返回内置默认**（与 `load_persons` 同形，与 `load_config`
    的快速失败不同）：没写这份文件是**合法的**——内置默认就是硅基流动那一套。

    ⚠️ **但这一支必须出声**（`on_warn`）。默认里 `enable_thinking=None`
    ⇒ **不发该字段**，而实测那会让 Qwen3.5-35B-A3B 单批从 2.8s 涨到
    **111.5s**。「删掉一个配置文件换来 40 倍慢、且没有任何提示」正是本项目
    反复禁止的静默退化。传 `on_warn=logs.emit` 就把这句话说出来；
    测试里不传就是安静的。

    ⚠️ `enable_thinking` 的缺省判定**必须是 `not in` 而不是 falsy 检查**：
    `section.get("enable_thinking")` 对「键不存在」（`None`）与「值是
    `false`」（`False`）返回**不同的东西**，而 `if value:` 会把后者静默吞成
    "没写" ⇒ 切到自建端点后行为悄悄变了。
    """
    target = path or DEFAULT_LLM_TOML
    if not target.is_file():
        if on_warn is not None:
            on_warn(
                f"[注意] 没有 {target}，用内置默认端点（{llm.DEFAULT_BASE}）。"
                "⚠️ 该默认**不发 enable_thinking 字段**，而混合思考模型"
                "（Qwen3/Qwen3.5）不收到它时会**慢 40 倍**（实测 111.5s vs 2.8s/批）。"
                "要恢复原速，请建这个文件并写 `enable_thinking = false`。"
            )
        return LLMSettings()

    try:
        with open(target, "rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{target}: TOML 语法错误——{exc}") from exc

    section = raw.get("llm")
    if section is None:
        raise ConfigError(
            f"{target}: 缺少 [llm] 段（注意是**单层**方括号；`[[llm]]` 会读成一个数组）"
        )
    if not isinstance(section, dict):
        raise ConfigError(
            f"{target}: `llm` 必须是**一张表**（`[llm]`），"
            f"实际是 {type(section).__name__}——写成 `[[llm]]`（双层方括号）时"
            "读出来的是一串表。"
        )

    base_url = str(section.get("base_url", "")).strip() or llm.DEFAULT_BASE
    model = str(section.get("model", "")).strip() or llm.DEFAULT_MODEL

    if "enable_thinking" not in section:
        thinking: bool | None = None
    else:
        raw_thinking = section["enable_thinking"]
        if not isinstance(raw_thinking, bool):
            raise ConfigError(
                f"{target}: enable_thinking 只能是 true / false，或**整行删掉**"
                f"（删掉 = 不发这个字段）。实际是 {raw_thinking!r}"
                f"（{type(raw_thinking).__name__}）——"
                '写成 `"false"`（带引号）是字符串，不是布尔。'
            )
        thinking = raw_thinking

    return LLMSettings(base_url=base_url, model=model, enable_thinking=thinking)


_LLM_HEADER = """\
# VIGIL 的 LLM 端点配置
#
# ⚠️ **本文件里永远不放密钥。** 密钥走仓库根的 `.env`（`SILICONFLOW_API_KEY`），
#    因为 `config/*.toml` 是**要进 git** 的（spec §3.2 / D11）。
#
# ⚠️ **本文件由程序整体重写**（网页「配置」页保存时会覆盖它）：
#    手工改也行，但**手工加的注释会在下一次网页保存时消失**。
#
# 改完不需要重启服务：`vigil refine` / `vigil digest` 每次运行都会重新读它。
"""


def save_llm_settings(
    settings: LLMSettings, path: pathlib.Path | None = None
) -> None:
    """整体替换写出 LLM 配置（原子）。

    ⚠️ `enable_thinking is None` 时**整行不写**——那是"不发这个字段"的
    唯一表达方式。写成 `enable_thinking = null` 的话，读回来是 Python 的
    `None` 但通过的是 **TOML 里不存在的 null 语法**（TOML 根本没有 null），
    文件直接解析不了。
    """
    target = path or DEFAULT_LLM_TOML
    lines = [_LLM_HEADER, "", "[llm]", ""]
    lines.append(f"base_url = {toml_str(settings.base_url)}")
    lines.append(f"model = {toml_str(settings.model)}")
    if settings.enable_thinking is not None:
        lines.append(
            f"enable_thinking = {'true' if settings.enable_thinking else 'false'}"
        )
    lines.append("")

    text = "\n".join(lines)
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"内部错误：为 {target} 生成的 TOML 解析不了——{exc}") from exc
    if not isinstance(raw.get("llm"), dict):
        raise ConfigError(f"内部错误：为 {target} 生成的 TOML 里没有 [llm] 表")

    atomic_write_text(target, text)
```

并把顶部 import 补成：

```python
from collections.abc import Callable, Sequence

from . import llm
```

（`from . import llm` 安全：`llm.py` 只 import 标准库，不成环。）

- [ ] **Step 5: 三个消费函数加 `base_url` 并把它传下去**

**`vigil/refine.py`** —— 签名（`refine.py:391` 附近）加一行：

```python
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE,
    enable_thinking: bool | None = False,
```

import 补 `DEFAULT_BASE`：

```python
from .llm import DEFAULT_BASE, DEFAULT_MODEL, LLMConfig, LLMError, chat_json, sanitize_for_llm
```

构造点（`refine.py:522-524`）：

```python
        llm_cfg = LLMConfig(
            api_key=api_key, model=model, base_url=base_url,
            enable_thinking=enable_thinking,
        )
```

**`vigil/digest.py`** —— 同样三处：签名加 `base_url: str = DEFAULT_BASE`；import 补 `DEFAULT_BASE`；构造点：

```python
                LLMConfig(
                    api_key=api_key, model=model, base_url=base_url,
                    enable_thinking=enable_thinking, max_tokens=MAX_TOKENS,
                ),
```

**`vigil/repass.py`** —— 同样三处；构造点：

```python
        llm_cfg = LLMConfig(
            api_key=api_key, model=model, base_url=base_url,
            enable_thinking=enable_thinking,
        )
```

⚠️ **不要动 `enable_thinking` 的默认值 `False`**。改它会影响所有没显式传参的调用方（包括 `daily.py` 与两百多条既有测试），而且是**静默**的。本任务只加"能传 `None`"这条路，不改默认。

- [ ] **Step 6: CLI 与 `daily` 接上**

**`vigil/cli.py`** —— 三个子命令的 argparse 各加一行（放在 `--model` 之后）：

```python
    p_refine.add_argument("--base-url", default=None, help="覆盖 LLM 端点（默认读 config/llm.toml）")
```

（`p_repass` / `p_digest` 同形，注意各自的变量名是 `p_repass` / `p_digest`。）

**`cmd_refine`** 里，把 `api_key = load_llm_key()` 之后补上设置读取，并把三处参数换掉：

```python
            api_key = load_llm_key()
            if not api_key and not args.dry_run:
                sys.exit(
                    "[配置错误] 没有 LLM 密钥。\n"
                    "  请在仓库根目录的 .env 里写入：SILICONFLOW_API_KEY=sk-...\n"
                    "  （--dry-run 不需要密钥）"
                )

            # ⚠️ 设置的**解析顺序**固定是：命令行 > config/llm.toml > 内置默认。
            # 命令行优先是为了让排障能"先试一下别的端点"而不用改文件。
            llm_settings = load_llm_settings(on_warn=logs.emit)
```

然后把 `refine_mod.refine(...)` 调用里的两行换成：

```python
                    # --model/--base-url 不给时是 None，而 None 会绕过 refine() 的默认值，
                    # 所以这里按「命令行 > 文件 > 内置默认」兜底
                    model=args.model or llm_settings.model,
                    base_url=args.base_url or llm_settings.base_url,
                    enable_thinking=(
                        True if args.think else llm_settings.enable_thinking
                    ),
```

⚠️ `enable_thinking` 那一行**不能写成 `args.think or llm_settings.enable_thinking`**：`--think` 是 `store_true`，没给时是 `False`，而 `False or X` 得到 `X` —— 于是「文件里写了 `true`、命令行没给 `--think`」时**拿到 `True`（文件说了算）**，这**恰好是对的**；但「文件里没写（`None`）、命令行也没给」时得到 `None`（不发），也是对的；而「命令行给了 `--think`」时得到 `True`，也对。**所以 `or` 在这里碰巧正确——但碰巧正确不是正确**：它依赖 `args.think` 的默认值是 `False` 而不是 `None`。用显式写法把这个依赖去掉。

**`cmd_digest`** 同样：加 `llm_settings = load_llm_settings(on_warn=logs.emit)`，并把

```python
                model=args.model or digest_mod.DEFAULT_MODEL,
                enable_thinking=args.think,
```

换成

```python
                model=args.model or llm_settings.model,
                base_url=args.base_url or llm_settings.base_url,
                enable_thinking=(True if args.think else llm_settings.enable_thinking),
```

**`cmd_repass`** 同样（它的 `--think` 也是 `store_true`）。

**`vigil/daily.py`** —— 这是**无人值守**的那条路，它不接 argparse，必须自己读文件。在 `run()` 签名里加参数并在函数体开头解析：

```python
def run(
    *,
    config: Config,
    key: str,
    llm_key: str,
    day: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> RunReport:
```

在 `emit = on_progress or logs.emit` **之后**加：

```python
    # ⚠️ 无人值守这条路**必须自己读** `config/llm.toml`（没有命令行可接）。
    # ⚠️ `on_warn=emit`：文件缺失时那句「会慢 40 倍」必须进日志——
    # 任务计划不保存 stdout，而 `LAST-ERROR.txt` 只在**阶段失败**时才写。
    from .config import load_llm_settings

    llm_settings = load_llm_settings(on_warn=emit)
    emit(
        f"[daily] LLM 端点：{llm_settings.base_url} · 模型 {llm_settings.model} · "
        f"思考={'不发该字段' if llm_settings.enable_thinking is None else llm_settings.enable_thinking}"
    )
```

然后把 refine 与 digest 两处调用改成：

```python
            model=llm_settings.model,
            base_url=llm_settings.base_url,
            enable_thinking=llm_settings.enable_thinking,
```

（digest 那处同理。）

⚠️ **`daily.py` 是本次改动里唯一一处「行为真的变了」的地方**（它以前固定发 `enable_thinking=false`，现在跟着文件走）。所以 Step 7 里有一条**专门钉它**的测试。

- [ ] **Step 7: 补一条钉住 `daily` 的测试**

在 `tests/test_daily.py` 末尾追加：

```python
def test_daily_passes_the_configured_llm_endpoint(monkeypatch, tmp_path):
    """⭐ `daily` 必须把 `config/llm.toml` 里的端点**真的传下去**。

    ⚠️ 这条挡的是一个具体的形状：`daily` 是**无人值守**路径，没有命令行
    可接，很容易在改造时被漏掉——而它漏掉的后果是"网页上改了端点、
    日报却还在打老地址"，且**只有等到有人看日志才发现**。

    ⚠️ 变异反证：把 `daily.run` 里 refine 调用那三行换回
    `model=refine_mod.DEFAULT_MODEL` ⇒ 本条**必红**。
    """
    from vigil import config

    monkeypatch.setattr(
        config, "DEFAULT_LLM_TOML",
        tmp_path / "llm.toml",
    )
    (tmp_path / "llm.toml").write_text(
        '[llm]\nbase_url = "https://my-host/v1/chat/completions"\n'
        'model = "my-model"\nenable_thinking = false\n',
        encoding="utf-8",
    )

    seen: dict[str, object] = {}

    def fake_export(config, key, *, on_progress=print):
        return export_mod.ExportStats(per_group=[(1, "群", 0)])

    def fake_refine(cfg, **kw):
        seen["refine"] = kw
        return refine_mod.RefineStats()

    def fake_digest(cfg, **kw):
        seen["digest"] = kw
        return digest_mod.DigestStats()

    monkeypatch.setattr(daily.export_mod, "export", fake_export)
    monkeypatch.setattr(daily.refine_mod, "refine", fake_refine)
    monkeypatch.setattr(daily.digest_mod, "digest", fake_digest)
    monkeypatch.setattr(daily.digest_mod, "day_window", lambda day: (0, 1))

    daily.run(config=..., key="k", llm_key="lk", day="2026-09-16", on_progress=lambda _: None)

    assert seen["refine"]["base_url"] == "https://my-host/v1/chat/completions"
    assert seen["refine"]["model"] == "my-model"
    assert seen["refine"]["enable_thinking"] is False
    assert seen["digest"]["base_url"] == "https://my-host/v1/chat/completions"
```

⚠️ **`config=...` 那一处**：照抄 `tests/test_daily.py` 里**既有用例**构造 `Config` 的写法（`grep -n "Config(" tests/test_daily.py | head`），不要另造一个。同理，`ExportStats` / `RefineStats` / `DigestStats` 的构造参数也照抄该文件既有用例。**本计划不猜这些夹具的形状**——照抄是最省事也最不会漂的做法。

- [ ] **Step 8: 跑测试确认通过**

Run: `uv run pytest tests/test_llm_config.py tests/test_daily.py tests/test_llm.py -v`
Expected: 全部 PASS

- [ ] **Step 9: 全量回归**

Run: `uv run pytest`
Expected: 与 T2 结束时相比 **+9**（`test_llm_config.py` 的 8 条 + `test_daily.py` 新增 1 条）。
⚠️ **`daily` 的行为改动若让某条既有用例变红，先读那条用例在钉什么**——它可能在钉「daily 恒发 enable_thinking=false」，那是一条**过期的契约**，按勘误方式改它并在报告里写明。

- [ ] **Step 10: Commit**

```bash
git add config/llm.toml vigil/config.py vigil/refine.py vigil/digest.py vigil/repass.py vigil/cli.py vigil/daily.py tests/test_llm_config.py tests/test_daily.py
git commit -m "feat(config,llm): config/llm.toml 端点配置 —— base_url/model/enable_thinking 三态（spec §4.2 ②，R12）"
```

---

## Task 4: 群清单快照（#3 的只读路径）+ 加群/改群/退群端点

**这是 spec §1.6 那个雷的正面解法。** 回头看它为什么是雷：

```python
# cli.py:64-72（今天）
counts = qqdb.list_group_message_counts(
    qqdb.open_encrypted(
        qqdb.strip_fake_header(          # ← 就地重写 data/cache/nt_msg_clear.db
            config.qq_db_dir / "nt_msg.db",
            config.output_db.parent / "cache" / "nt_msg_clear.db",
        ), key))
```

Web 端点若直接复用它，会有两个**互相独立**的问题：
1. 从后门打破「Web 不写 `data/`」（`data/cache/` 也是 `data/`，spec §8 明说新表述就是为了堵这个形状）；
2. 它需要 **`VIGIL_DB_KEY`**——而 `create_app(config)` 今天**只拿 `Config`、不拿密钥**。把 DB 密钥交给 Web 进程 = 让它能解密整个 QQ 库，这是一次**权限扩大**，而且是为了渲染一个下拉框。

⇒ **裁定（用户 2026-09-17 已选）**：群清单由 **CLI 预生成为 JSON 快照**，Web 只读产物。Web 侧零写入 `data/`、零密钥。

**Files:**
- Create: `vigil/groups_snapshot.py`
- Modify: `vigil/cli.py`（`_cmd_groups_locked` 末尾写快照）
- Modify: `vigil/export.py`（`export()` 末尾刷新快照）
- Modify: `vigil/api.py`（`GET/POST /api/groups`、`PATCH/DELETE /api/groups/{gid}`、`current_config()` 现读）
- Create: `tests/test_groups_snapshot.py`
- Modify: `tests/test_api.py`, `tests/test_export.py`

**Interfaces:**
- Consumes: T1 的 `qqdb.strip_fake_header`（原子写版）、T2 的 `config.save_config` / `config.validate_config_raw`
- Produces:
  - `groups_snapshot.SCHEMA_VERSION: int`（= 1）
  - `groups_snapshot.GroupInfo` —— frozen dataclass：`id: int` / `name: str` / `messages: int` / `last_ts: int`
  - `groups_snapshot.Snapshot` —— frozen dataclass：`generated_at: int` / `groups: tuple[GroupInfo, ...]`
  - `groups_snapshot.default_path(config: Config) -> pathlib.Path`
  - `groups_snapshot.collect(counts, names) -> tuple[GroupInfo, ...]`
  - `groups_snapshot.write(groups, path, *, now: int | None = None) -> pathlib.Path`
  - `groups_snapshot.load(path) -> Snapshot | None` —— **不抛异常**：坏快照 / 版本不符一律返回 `None`（它是增强项，坏掉不该让整个页面 500）
  - `api.create_app` 内新增闭包 `current_config() -> Config`（**现读** groups.toml）

---

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_groups_snapshot.py`：

```python
"""群清单快照 —— M6 T4（spec §1.6 的只读路径）。"""

from __future__ import annotations

import json
import pathlib

from vigil import config, groups_snapshot


def _cfg(tmp_path) -> config.Config:
    (tmp_path / "qqdb").mkdir(exist_ok=True)
    return config.Config(
        qq_db_dir=tmp_path / "qqdb",
        output_db=tmp_path / "data" / "vigil.db",
        groups=(config.Group(id=111, name="甲群"),),
    )


def test_default_path_sits_next_to_the_main_db(tmp_path):
    """快照与主库同目录（`data/`）——它们是同一份「导出产物」的两个视角。"""
    p = groups_snapshot.default_path(_cfg(tmp_path))
    assert p.parent == tmp_path / "data"
    assert p.name == "groups-snapshot.json"


def test_write_then_load_roundtrips(tmp_path):
    groups = (
        groups_snapshot.GroupInfo(id=111, name="甲群", messages=10, last_ts=1700000000),
        groups_snapshot.GroupInfo(id=222, name="乙群", messages=0, last_ts=0),
    )
    p = groups_snapshot.write(groups, tmp_path / "s.json", now=1700000001)
    snap = groups_snapshot.load(p)
    assert snap is not None
    assert snap.generated_at == 1700000001
    assert snap.groups == groups


def test_load_returns_none_for_a_missing_file(tmp_path):
    """⚠️ **不抛异常**：快照是增强项（Web 的群下拉框），没有它时接口应该
    回一句「还没有快照，请先跑 vigil export」，而不是 500。"""
    assert groups_snapshot.load(tmp_path / "nope.json") is None


def test_load_returns_none_for_a_corrupt_file(tmp_path):
    """坏 JSON / 坏结构一律 `None`——同一条理由：它是增强项。

    ⚠️ 与 `load_config` 的「快速失败」**不矛盾**：`groups.toml` 是**必需**的
    配置，写错了要立刻死；而快照是**派生物**，它坏了只意味着"该重跑一次
    export"，把整个服务拖死是过度反应。
    """
    p = tmp_path / "s.json"
    p.write_text("{not json", encoding="utf-8")
    assert groups_snapshot.load(p) is None
    p.write_text('{"generated_at": 1}', encoding="utf-8")
    assert groups_snapshot.load(p) is None
    p.write_text('{"generated_at": 1, "groups": [{"id": "x"}]}', encoding="utf-8")
    assert groups_snapshot.load(p) is None


def test_load_refuses_a_future_schema_version(tmp_path):
    """⭐ 版本闸：将来改了快照形状时，**旧代码必须拒绝读新文件**。

    ⚠️ 没有这道闸的话，加字段的那天会得到一个静默的错读（新文件里的某个
    字段被旧代码当成别的意思）——而快照恰恰是「用户看着它决定加不加群」
    的东西，错读的代价是**加错群**。宁可返回 `None`（界面说「快照过期，
    请重跑 export」）。
    """
    p = tmp_path / "s.json"
    p.write_text(
        json.dumps(
            {"schema": groups_snapshot.SCHEMA_VERSION + 1, "generated_at": 1, "groups": []}
        ),
        encoding="utf-8",
    )
    assert groups_snapshot.load(p) is None


def test_write_is_atomic(tmp_path):
    """快照必须原子写（与全项目同一条规矩）。

    ⚠️ Web 每个请求都可能读它，而它由 CLI 在另一个进程里写 ——
    正是「读者可能看到半个文件」的经典场景。
    """
    p = tmp_path / "s.json"
    groups_snapshot.write(
        (groups_snapshot.GroupInfo(id=111, name="甲群", messages=1, last_ts=2),), p
    )
    body = p.read_text(encoding="utf-8")
    assert json.loads(body)["schema"] == groups_snapshot.SCHEMA_VERSION
    leftovers = [q.name for q in p.parent.iterdir() if ".tmp" in q.name]
    assert leftovers == []


def test_collect_merges_counts_and_names():
    """`collect` 把 `[(群号, 消息数, 最新ts)]` 与 `{群号: 群名}` 拼成 `GroupInfo`。

    ⚠️ 群名取不到时**留空串而不是 `"?"`**：`"?"` 是一个看起来像名字的
    占位符，而界面上「(无名)」与「?」给人的判断完全不同。名字缺失是
    正常状态（`group_info.db` 可能落后于 `nt_msg.db`）。
    """
    counts = [(111, 10, 1700000000), (222, 3, 1700000001)]
    names = {"111": "甲群"}
    out = groups_snapshot.collect(counts, names)
    assert out[0] == groups_snapshot.GroupInfo(
        id=111, name="甲群", messages=10, last_ts=1700000000
    )
    assert out[1].name == ""
```

在 `tests/test_api.py` 末尾追加：

```python
# ── M6 T4：群清单（只读快照）+ 加群/改群/退群 ──────────────────────


def test_api_groups_says_so_when_there_is_no_snapshot(client_no_snapshot):
    """⭐ 没有快照时**明说**，不许回一个空列表。

    ⚠️ 空列表会被读成「你的 QQ 库里一个群都没有」——一句**假话**，
    而且是最容易让人不再信任这个页面的那种假话（本项目的
    「只说自己有资格说的话」判据，M2 起立下的规矩）。
    """
    r = client_no_snapshot.get("/api/groups")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "export" in body["reason"]


def test_api_groups_reads_the_snapshot_and_marks_watched(client_with_snapshot):
    body = client_with_snapshot.get("/api/groups").json()
    assert body["available"] is True
    by_id = {g["id"]: g for g in body["groups"]}
    assert by_id[111]["watched"] is True
    assert by_id[222]["watched"] is False
    assert by_id[111]["messages"] == 10
    assert body["generated_at"] > 0


def test_api_add_group_persists_and_is_visible_after_reload(tmp_path, client_factory):
    """⭐ **出口判据 1 的机械形式**：网页上加一个群 ⇒ 落盘 ⇒ **重读仍在**。

    ⚠️ 「重读仍在」是判据的全部意义所在：只断言响应体的话，
    一个"内存里加了、磁盘上没写"的实现照样绿——而它在重启后**静默消失**，
    用户要到下次开机才发现。
    """
    c = client_factory()
    r = c.post("/api/groups", json={"id": 333, "name": "丙群", "tier": "high"})
    assert r.status_code == 201
    # 换一个**全新的 app**（等价于重启）后再读
    c2 = client_factory()
    body = c2.get("/api/groups").json()
    assert any(g["id"] == 333 for g in body["watched"])


def test_api_add_group_rejects_a_duplicate(client_factory):
    c = client_factory()
    assert c.post("/api/groups", json={"id": 111, "name": "重复"}).status_code == 409


def test_api_add_group_rejects_a_bad_tier(client_factory):
    c = client_factory()
    assert c.post("/api/groups", json={"id": 444, "name": "群", "tier": "boss"}).status_code == 400


def test_api_add_group_rejects_a_bool_id(client_factory):
    """`true` 是 `int` 的子类 ⇒ `isinstance(True, int)` 为真。

    ⚠️ 不挡的话会建出一个群号为 1 的条目——与 M5 终审 #22 是同一个形状，
    而这里连 `toml_int` 都拦不住（它在 `save_config` 里，那时 id 已经是
    `True`、写出去是 `true`）。**闸必须在入口。**
    """
    c = client_factory()
    assert c.post("/api/groups", json={"id": True, "name": "群"}).status_code == 400


def test_api_delete_group_refuses_the_last_one(client_factory):
    """⚠️ 退掉最后一个群 = 把程序改成起不来（`load_config` 判「一个群都没配」）。

    ⚠️ 正确动作是 `enabled = false`，接口要在 detail 里**说清这一点**。
    """
    c = client_factory()  # 夹具只配了一个群
    r = c.delete("/api/groups/111")
    assert r.status_code == 409
    assert "enabled" in r.json()["detail"]


def test_api_patch_group_disables_without_deleting(client_factory):
    c = client_factory()
    assert c.patch("/api/groups/111", json={"enabled": False}).status_code == 200
    body = c.get("/api/groups").json()
    assert all(not g["watched"] for g in body["groups"])
    assert any(g["id"] == 111 for g in body["groups"]), "停用不是删除——条目还在"
```

⚠️ **夹具** `client_no_snapshot` / `client_with_snapshot` / `client_factory`：照抄 `tests/test_api.py` **既有**的 client 夹具构造方式（`grep -n "def client_\|TestClient" tests/test_api.py | head`），只改数据根与快照文件。**不要新造一套风格不同的夹具。**

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_groups_snapshot.py -v`
Expected: 全部 FAIL（模块不存在）

- [ ] **Step 3: 写 `vigil/groups_snapshot.py`**

```python
"""群清单快照 —— Web 侧的「可选群」数据源（M6 T4，spec §1.6 的裁定）。

**为什么要有这个模块**：Web 端点需要一份「QQ 库里有哪些群」的清单，
而现成的实现（`cli.cmd_groups`）靠 `strip_fake_header` **写**
`data/cache/nt_msg_clear.db`。直接复用会有两个**互相独立**的问题：

1. 从后门打破「Web 不写 `data/`」（`data/cache/` 也是 `data/`）；
2. 它需要 **`VIGIL_DB_KEY`** ⇒ 把整个 QQ 库的解密能力交给 Web 进程，
   而 `create_app(config)` 今天**只拿 `Config`、不拿密钥**。

⇒ 群清单由 **CLI 预生成**成 JSON，Web 只读产物。Web 侧零写入 `data/`、零密钥。

**失败策略与 `config.py` 相反，且这是刻意的**：
本模块是**派生物**（`groups.toml` 才是真相源，这里是它的一个视图）。
快照读不出来只意味着「该重跑一次 export」，把整个服务拖死是过度反应——
所以 `load()` 一律返回 `None`，由调用方回一句人话。
"""

from __future__ import annotations

import json
import pathlib
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .config import Config, atomic_write_text

# ⚠️ 加字段就要**加版本号**。`load()` 会拒绝版本不符的文件——没有这道闸的话，
# 加字段那天旧代码会静默错读新文件，而快照恰恰是「用户看着它决定加不加群」
# 的东西，错读的代价是**加错群**。宁可让界面说「快照过期，请重跑 export」。
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GroupInfo:
    """QQ 本地库里的一个群。`messages` / `last_ts` 是该群的**全量**历史统计。"""

    id: int
    name: str
    messages: int
    last_ts: int


@dataclass(frozen=True)
class Snapshot:
    generated_at: int
    groups: tuple[GroupInfo, ...]


def default_path(config: Config) -> pathlib.Path:
    """快照与主库同目录（`data/`）——它们是同一份「导出产物」的两个视角。"""
    return config.output_db.parent / "groups-snapshot.json"


def collect(
    counts: Sequence[tuple[int, int, int]], names: dict[str, str]
) -> tuple[GroupInfo, ...]:
    """把 `qqdb.list_group_message_counts` 的输出与 `qqdb.group_names` 的结果拼起来。

    ⚠️ 群名取不到时**留空串而不是 `"?"`**：`"?"` 是一个看起来像名字的占位符，
    而界面上「(无名)」与「?」给用户的判断完全不同。名字缺失是**正常状态**
    （`group_info.db` 可能落后于 `nt_msg.db`）。
    """
    return tuple(
        GroupInfo(
            id=int(gid),
            name=names.get(str(gid), ""),
            messages=int(n),
            last_ts=int(t or 0),
        )
        for gid, n, t in counts
    )


def write(
    groups: Sequence[GroupInfo],
    path: pathlib.Path,
    *,
    now: int | None = None,
) -> pathlib.Path:
    """原子写出快照。

    ⚠️ **必须原子**（`atomic_write_text`）：Web 每个请求都可能读它，
    而它由 CLI 在**另一个进程**里写 —— 正是「读者可能看到半个文件」的
    经典场景。写一半的 JSON 会让界面变成「快照坏了」而不是「快照旧了」。
    """
    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "generated_at": int(time.time()) if now is None else int(now),
        "groups": [asdict(g) for g in groups],
    }
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=1))
    return path


def load(path: pathlib.Path) -> Snapshot | None:
    """读快照。**任何问题都返回 `None`，绝不抛异常**（见模块 docstring）。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("schema") != SCHEMA_VERSION:
        return None

    generated_at = raw.get("generated_at")
    entries = raw.get("groups")
    if not isinstance(generated_at, int) or not isinstance(entries, list):
        return None

    out: list[GroupInfo] = []
    for e in entries:
        if not isinstance(e, dict):
            return None
        try:
            out.append(
                GroupInfo(
                    id=int(e["id"]),
                    name=str(e["name"]),
                    messages=int(e["messages"]),
                    last_ts=int(e["last_ts"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            return None
    return Snapshot(generated_at=int(generated_at), groups=tuple(out))
```

- [ ] **Step 4: 让 CLI 与 `export` 写快照**

**`vigil/cli.py`**：在 `_cmd_groups_locked` 的 `counts = ...` 之后、`names` 算好之后（即 `print` 表格之前）插入：

```python
    # ⚠️ 顺手写快照（M6 T4）：Web 的「配置」页只读这个文件，永远不碰 QQ 库。
    # ⚠️ 失败**只警告不中断**：快照是增强项，而 `vigil groups` 的主业是
    # 把那张家底表打到屏幕上（人工排障时最需要的东西）。
    try:
        snap_path = groups_snapshot.write(
            groups_snapshot.collect(counts, names),
            groups_snapshot.default_path(config),
        )
        print(f"[快照] 已写 {snap_path}", file=sys.stderr)
    except OSError as exc:
        print(f"[警告] 群清单快照写不出去（不影响上面的列表）：{exc}", file=sys.stderr)
```

顶部 import 补：`from . import groups_snapshot`。

**`vigil/export.py`**：在 `export()` 的 `try:` 块内、`for group in config.enabled_groups:` **之前**插入：

```python
        # ⚠️ 顺手刷新群清单快照（M6 T4）。**必须查全库**而不是只列已纳群：
        # 那个页面的用途正是「从库里挑一个还没纳的群加进来」，只列已纳的
        # 等于把功能砍掉。
        # ⚠️ 走 `list_group_message_counts` 的索引查询，实测**不触发表扫描**、
        # 不受坏页影响（`qqdb.py:94-99` 的 docstring 记着这件事）。
        # ⚠️ 失败只警告不中断：快照是增强项，export 的主业是把消息导出来。
        try:
            counts = qqdb.list_group_message_counts(src)
            names: dict[str, str] = {}
            try:
                names = qqdb.group_names(qqdb.open_group_info(gi_clear, key))
            except Exception:  # noqa: BLE001 — 群名是锦上添花
                pass
            groups_snapshot.write(
                groups_snapshot.collect(counts, names),
                groups_snapshot.default_path(config),
            )
            on_progress(f"群清单快照：{len(counts)} 个群")
        except Exception as exc:  # noqa: BLE001 — 增强项，不该拖垮导出
            on_progress(f"[警告] 群清单快照写不出去：{str(exc)[:80]}")
```

⚠️ **`gi_clear` 可能未定义**，这是个真实的落点陷阱：它只在 `sender_map` 那段 `try` 里被赋值，而那种写法下「取不到名字」走的是 `except` 分支 ⇒ `gi_clear` **从头到尾没被绑定过**。

⇒ 这一段**必须放在 `n_senders = _write_senders(...)` 与 `on_progress(f"发信人姓名：…")` 之后**，并且用**同样的 `try/except` 包住群名读取**（不要直接引用 `gi_clear`）：

```python
            try:
                names = qqdb.group_names(qqdb.open_group_info(gi_clear, key))
            except Exception:  # noqa: BLE001 — 群名是锦上添花；gi_clear 未定义也走这支
                names = {}
```

（`except Exception` 会一并吞掉 `NameError`——它继承自 `Exception`。这是**刻意**的：群名缺失是正常状态。**但不要因此把外层的 `except` 也写成裸 `except:`**，那会连 `KeyboardInterrupt` 一起吞。）

**实施时以实际代码位置为准，并把最终落点写进报告。**

顶部 import 补：`from . import groups_snapshot`。

- [ ] **Step 5: 改 `vigil/api.py` —— 现读配置 + 五个端点**

**5a. 顶部 import** 补：

```python
import threading

from . import groups_snapshot, overrides, store
from .config import (
    REPO_ROOT, TIER_NORMAL, VALID_TIERS, Config, Group, Person,
    load_config, load_persons, save_config, save_persons,
)
```

**5b. 在 `create_app` 里、`db_path` 之后加两个东西**：

```python
    # ⚠️ **不许用 `create_app` 收到的那个 `config` 去回答「现在有哪些群」**
    # （它在进程启动那一刻就冻住了）。网页上加了一个群之后，那个对象里没有它
    # ⇒ 新群在信息流里显示成裸群号，而用户刚从「配置」页把它加进去、
    # 看着自己的操作没生效。（与 `persons_path()` 同一族：路径与文件内容
    # 都必须**每次现读**。）
    #
    # ⚠️ **`db_uri` 仍然用启动时那份 `config.output_db`**：改它要重启服务。
    # 这不是妥协——`output_db` 是「这个服务读哪个库」，热切换它意味着
    # 正在飞的请求读一半换了库，比要求重启糟得多。
    def config_path() -> pathlib.Path:
        return REPO_ROOT / "config" / "groups.toml"

    def current_config() -> Config:
        try:
            return load_config(config_path())
        except ConfigError as exc:
            # 配置文件被手工改坏了 ⇒ 500 而不是 503：后者在浏览器里会被
            # 读成「服务没起来」，而真相是**配置文件有语法错**，方向完全不同。
            raise HTTPException(
                status_code=500, detail=f"config/groups.toml 读不出来：{exc}"
            )

    # ⚠️ 进程内的写锁。`save_config` 是**整体替换**（读 → 改 → 写），
    # 两个并发请求各自读到旧版本、各自 append、后写的赢 ⇒ **丢一个群**。
    # 单用户自用下概率低，但 spec §6 R10 明说「不能因为概率低就不做原子写」——
    # 而这里的代价只是一把 `threading.Lock`。
    # ⚠️ 它是**进程内**的：本服务只有一个 uvicorn worker（`uvicorn.run(app, ...)`
    # 不带 workers 参数），所以够用。跨进程那把是 `lock.SingleInstance`，
    # 它保护的是 QQ 库与主库，**语义不同、别混用**：CLI 拿不到锁时会拒绝运行，
    # 而 Web 不该因为「任务计划在跑」就整个不能保存配置。
    write_lock = threading.Lock()
```

**5c. 把 `names` 那行改成现读**。原来在 `create_app` 里有：

```python
    names = {g.id: g.name for g in config.groups}
```

替换为：

```python
    def group_names_map() -> dict[int, str]:
        return {g.id: g.name for g in current_config().groups}
```

并把 `item_out` 与 `api_item` 里所有 `names.get(...)` 改成 `group_names_map().get(...)`。

⚠️ `item_out` 里那一处每次调用都会读一次文件。**列表接口一页 50 条 ⇒ 50 次读同一份 3KB 的 TOML。** 所以正确做法是**在端点入口读一次、传进去**：

```python
    def item_out(it: store.ApiItem, names: dict[int, str]) -> dict:
        ...
            "group_name": names.get(it.group_id, str(it.group_id)),
```

并给 `api_items` / `api_item` / `api_digest` 各加一行 `names = group_names_map()`。**实施时以实际调用点为准，把最终改了哪几处写进报告。**

**5d. 在 `api_persons` 附近加五个群端点**：

```python
    @app.get("/api/groups")
    def api_groups() -> dict:
        """QQ 库里的群清单 —— **只读快照**（M6 T4 / spec §1.6）。

        ⚠️ 本端点**绝不接触 QQ 库、绝不写 `data/cache/`、也不需要数据库密钥**。
        它读的是 `vigil export` / `vigil groups` 预生成的
        `data/groups-snapshot.json`。理由与代价都写在 `groups_snapshot`
        模块的 docstring 里，改这里之前先读它。
        """
        cfg = current_config()
        snap = groups_snapshot.load(groups_snapshot.default_path(cfg))
        watched = {g.id: g for g in cfg.groups}
        if snap is None:
            # ⚠️ **明说**，绝不回一个空列表：空列表会被读成
            # 「你的 QQ 库里一个群都没有」——一句假话，而且是最容易让人
            # 不再信任这个页面的那种（「只说自己有资格说的话」）。
            return {
                "available": False,
                "reason": (
                    "还没有群清单快照。请先在仓库根目录跑一次 "
                    "`uv run vigil export`（或 `uv run vigil groups`）——"
                    "它会把 QQ 库里所有群的清单写成 data/groups-snapshot.json。"
                    "本服务只读那份产物，不直接读 QQ 库。"
                ),
                "generated_at": None,
                "groups": [],
            }
        return {
            "available": True,
            "reason": "",
            "generated_at": snap.generated_at,
            "groups": [
                {
                    "id": g.id,
                    "name": g.name,
                    "messages": g.messages,
                    "last_ts": g.last_ts,
                    "watched": g.id in watched and watched[g.id].enabled,
                    "known": g.id in watched,
                }
                for g in snap.groups
            ],
        }

    @app.post("/api/groups", status_code=201)
    def api_add_group(body: dict = Body(...)) -> dict:
        """新增一个监视群，落盘到 `config/groups.toml`（原子、整体替换）。

        ⚠️ **群号必须在这里挡死 `bool`**（`isinstance(True, int)` 为真）：
        `save_config` 里的 `toml_int` 拦不住它——到那时 id 已经是 `True`、
        写出去是 `true`，读回来是 `1`。**闸必须在入口。**
        （与 M5 终审 #22「`uin = true` 被接受」是同一个形状。）
        """
        gid = body.get("id")
        if isinstance(gid, bool) or not isinstance(gid, int) or gid <= 0:
            raise HTTPException(
                status_code=400,
                detail="群号必须是正整数（拒绝 true：bool 是 int 的子类，会静默变成 1）",
            )
        name = str(body.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="群名不能为空")
        _reject_controls(name, "name")
        tier = str(body.get("tier", TIER_NORMAL))
        if tier not in VALID_TIERS:
            raise HTTPException(
                status_code=400, detail=f"tier 只能是 {sorted(VALID_TIERS)}，收到：{tier!r}"
            )

        path = config_path()
        with write_lock:
            cfg = current_config()
            if any(g.id == gid for g in cfg.groups):
                raise HTTPException(status_code=409, detail=f"群 {gid} 已经在配置里了")
            save_config(
                Config(
                    qq_db_dir=cfg.qq_db_dir,
                    output_db=cfg.output_db,
                    groups=cfg.groups + (Group(id=gid, name=name, tier=tier),),
                ),
                path,
            )
        return {"id": gid, "name": name, "tier": tier}

    @app.patch("/api/groups/{gid}")
    def api_patch_group(gid: int, body: dict = Body(...)) -> dict:
        """改一个已配群的名字 / 启停 / 档位。**不做删除**（见下）。"""
        path = config_path()
        with write_lock:
            cfg = current_config()
            old = next((g for g in cfg.groups if g.id == gid), None)
            if old is None:
                raise HTTPException(status_code=404, detail=f"配置里没有群 {gid}")

            name = old.name
            if "name" in body:
                name = str(body["name"]).strip()
                if not name:
                    raise HTTPException(status_code=400, detail="群名不能为空")
                _reject_controls(name, "name")
            enabled = old.enabled
            if "enabled" in body:
                if not isinstance(body["enabled"], bool):
                    raise HTTPException(status_code=400, detail="enabled 必须是布尔值")
                enabled = body["enabled"]
            tier = old.tier
            if "tier" in body:
                tier = str(body["tier"])
                if tier not in VALID_TIERS:
                    raise HTTPException(
                        status_code=400, detail=f"tier 只能是 {sorted(VALID_TIERS)}"
                    )

            updated = Group(id=gid, name=name, enabled=enabled, tier=tier)
            groups = tuple(updated if g.id == gid else g for g in cfg.groups)
            save_config(
                Config(qq_db_dir=cfg.qq_db_dir, output_db=cfg.output_db, groups=groups),
                path,
            )
        return {"id": gid, "name": name, "enabled": enabled, "tier": tier}

    @app.delete("/api/groups/{gid}", status_code=204)
    def api_delete_group(gid: int) -> None:
        """从配置里删掉一个群。

        ⚠️ **拒绝删掉最后一个群**：`load_config` 把「一个群都没配」判成
        配置错误 ⇒ 删掉它 = **把这个服务改成起不来**，而且下一次启动才现形，
        那时用户已经在网页上点过删除、拿到了「成功」。
        ⚠️ 正确动作是 `enabled = false`（保留配置、保留已导出的历史），
        **detail 里必须说清这一点**——只回一句「不能删」是没用的。
        """
        path = config_path()
        with write_lock:
            cfg = current_config()
            if not any(g.id == gid for g in cfg.groups):
                raise HTTPException(status_code=404, detail=f"配置里没有群 {gid}")
            remaining = tuple(g for g in cfg.groups if g.id != gid)
            if not remaining:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "这是最后一个群，删掉它会让配置变成「一个群都没配」——"
                        "而那是致命的配置错误，下次启动服务会直接起不来。"
                        "要停掉它请改用 enabled = false（保留配置与已导出的历史）。"
                    ),
                )
            save_config(
                Config(
                    qq_db_dir=cfg.qq_db_dir, output_db=cfg.output_db, groups=remaining
                ),
                path,
            )
        return None
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_groups_snapshot.py tests/test_api.py tests/test_export.py -v`
Expected: 全部 PASS

- [ ] **Step 7: ⭐ 写「Web 没写过 `data/`」的守卫扩展**

spec 出口判据 2 要求「**新增的测试能证明 Web 端点没写过 `data/`**（D11 的守卫；反向验证：故意让端点写一次 `data/`，守卫必须变红）」。

`tests/test_overlay_e2e.py` 已有一条**主库指纹**的守卫（三个写端点）。**本任务把它扩展到整个 `data/` 目录树的文件集合**——因为 `data/cache/` 正是 §1.6 那个后门，而它不在现有守卫的覆盖面里。在该文件末尾追加：

```python
def test_no_web_endpoint_creates_anything_at_all_under_data(data_root, client):
    """⭐ D11 的**完整**版本：Web 侧跑一遍所有写端点，`data/` 下**一个文件都不许多**。

    ⚠️ 为什么不能只盯 `data/vigil.db` 的指纹（既有那条守卫做的事）：
    spec §8 白纸黑字说旧表述「挡不住『我可以写 `data/cache/` 啊』」，
    而 §1.6 那个地雷**正是这个形状**。所以判据必须升级成
    「`data/` 下的文件集合不变」——新增一个文件也算违规。

    ⚠️ 变异反证：让 `api_groups` 改成去调 `qqdb.strip_fake_header(...)`
    ⇒ `data/cache/` 下多出一个文件 ⇒ 本条**必红**
    （而只看主库指纹的那条守卫**照样绿**——这就是本条的增量）。
    """
    before = {p.relative_to(data_root) for p in data_root.rglob("*") if p.is_file()}

    client.get("/api/groups")
    client.post("/api/persons", json={"uin": 100000001, "label": "测试"})
    client.delete("/api/persons/100000001")
    client.post("/api/items/1/kind", json={"kind": "life"})
    client.post("/api/undo", json={})

    after = {p.relative_to(data_root) for p in data_root.rglob("*") if p.is_file()}
    # ⚠️ `data/overrides.db` 是 **D11 明确允许**的例外（人工干预层），
    # 它连同 `-wal` / `-shm` 都在允许列表里；其余一律不许新增。
    allowed = {
        pathlib.Path("overrides.db"),
        pathlib.Path("overrides.db-wal"),
        pathlib.Path("overrides.db-shm"),
    }
    assert after - before <= allowed, (
        f"Web 侧往 data/ 里新增了文件：{sorted(after - before - allowed)} —— "
        "D11 只允许写 data/overrides.db 与 config/"
    )
```

⚠️ `data_root` / `client` 两个夹具**照抄 `tests/test_overlay_e2e.py` 既有用例的构造方式**（该文件已有 `data/` 隔离夹具；`grep -n "@pytest.fixture" tests/test_overlay_e2e.py` 先看清名字）。**不要新造一套。**

- [ ] **Step 8: 全量回归**

Run: `uv run pytest`
Expected: 与 T3 结束时相比 **+7（快照）+ 8（api）+ 1（e2e）**。

- [ ] **Step 9: Commit**

```bash
git add vigil/groups_snapshot.py vigil/cli.py vigil/export.py vigil/api.py tests/test_groups_snapshot.py tests/test_api.py tests/test_overlay_e2e.py
git commit -m "feat(groups,api): 群清单走只读快照（§1.6 的裁定）+ 加群/改群/退群端点"
```

---

## Task 5: 类目编辑 —— 版本快照 + 增删改 + slug 级联（`kind_alias`）

**为什么这一整个任务必须一起做**（不能拆开）：spec §4.2 ④ 说「slug 重命名/删除**必须级联**：否则 `items.kind` 指向不存在的 slug」，而 §7/§9 又说 `data/vigil.db` 是只读的。两条合起来只有一个结论：

> **级联不能靠改写 `items.kind`，只能靠读取层映射。**

⇒ 于是「删一个类目」和「建一条别名」是**同一次操作的两半**。把删除端点先写完、别名留到下一个任务，中间那段时间里删掉的类目会让条目悬空——**而那正是 spec 要禁的状态**。

**⚠️ 实施前必须知道的四处 SQL**（实测，不是推测）。「有效类目」今天写作 `COALESCE(ost.kind, i.kind)`，它出现在**四个地方**：

| # | 位置 | 谁消费 |
|---|---|---|
| 1 | `store.py:871` `_ITEM_COLS` | `search_items` → `/api/items`、`get_item` |
| 2 | `store.py:961` `_item_filters` | 按类目筛选 |
| 3 | `store.py:1086-1091` `kind_counts` | `/api/categories` 的角标（**SELECT 与 GROUP BY 各一处**） |
| 4 | `store.py:419` `window_items` | ⭐ **`digest.py` 的日报合成** |

第 4 处是**最容易漏的**：它不叫 `_ITEM_COLS`、不在 `_ITEM_JOINS` 旁边、也不在 spec §3.3 那张「5 处读路径」表里（那张表按「读 items 表」列，而 `window_items` 恰好是表里第 1 行——但**它的 kind 表达式是手抄的，不是共用常量**）。漏掉它的后果是：**界面与日报对同一个条目的类目说法不同**，正是 R13。

⇒ 本任务把这四处**收敛成一个常量** `_EFFECTIVE_KIND`，理由与 `_NOT_DELETED` 完全一样：「让『哪几处用了它』一眼可数」。

**Files:**
- Modify: `vigil/overrides.py`（`_TABLES_DDL` 加两张表；新增 5 个函数）
- Modify: `vigil/store.py`（`_EFFECTIVE_KIND` + 四处替换）
- Modify: `vigil/categories.py`（`as_dicts`）
- Modify: `vigil/api.py`（类目 CRUD + 撤销端点）
- Modify: `tests/test_overrides.py`, `tests/test_store.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: T2 的 `categories.save_categories` / `categories.validate_categories` / `config.toml_str`；T4 的 `current_config()` 与 `write_lock`（`api.py` 内的两个闭包）
- Produces:
  - `overrides.save_config_snapshot(conn, *, body: str, now: int | None = None) -> int`
  - `overrides.list_config_snapshots(conn, *, limit: int = 20) -> list[tuple[int, int]]` （`[(snapshot_id, saved_at)]`，新的在前）
  - `overrides.pop_config_snapshot(conn) -> tuple[int, str] | None` —— **取最近一条并删掉它**（撤销就是"往回走一格"）
  - `overrides.set_kind_alias(conn, *, old_kind, new_kind, now=None) -> str` —— 返回**压平后**的最终 slug
  - `overrides.kind_aliases(conn) -> dict[str, str]`
  - `store._EFFECTIVE_KIND: str` —— SQL 片段

---

- [ ] **Step 1: 写失败的测试**

在 `tests/test_overrides.py` 末尾追加：

```python
# ── M6 T5：配置快照 + slug 别名 ─────────────────────────────────────


def test_config_snapshot_roundtrips(con):
    sid = overrides.save_config_snapshot(con, body="[llm]\n", now=100)
    assert sid > 0
    assert overrides.list_config_snapshots(con) == [(sid, 100)]


def test_pop_removes_the_row_so_undo_walks_backwards(con):
    """⭐ 撤销是「往回走一格」，不是「在两份内容之间弹跳」。

    ⚠️ 这条钉的是一个具体的错法：`pop` 若不删行，那么「撤销 → 再撤销」
    会**无限撤销同一个状态**（用户看到的是"点了没反应"），
    而第三次、第四次仍是它。删行之后每一次撤销都真的往回走一格。
    """
    overrides.save_config_snapshot(con, body="第一版", now=1)
    overrides.save_config_snapshot(con, body="第二版", now=2)
    assert overrides.pop_config_snapshot(con) == (2, "第二版")
    assert overrides.pop_config_snapshot(con) == (1, "第一版")
    assert overrides.pop_config_snapshot(con) is None
    assert overrides.list_config_snapshots(con) == []


def test_kind_alias_flattens_a_chain(con):
    """⭐ 别名在**写入时压平**，读路径永远只面对一层映射。

    ⚠️ 不压平的话，`_EFFECTIVE_KIND` 那一个 JOIN 只能跟一格
    （`life → daily` 之后又 `daily → daily_v2`，条目仍会显示成 `daily`），
    要跟到底就得用**递归 CTE**——而那要把复杂度塞进 `store.py` 的
    每一条查询里（四处，漏一处就是静默的错分类）。

    ⚠️ 变异反证：把 `set_kind_alias` 里那句
    `UPDATE kind_alias SET new_kind = ? WHERE new_kind = ?` 删掉
    ⇒ 本条**必红**（`kind_aliases(con)["life"]` 会是 `"daily"` 而不是 `"daily_v2"`）。
    """
    overrides.set_kind_alias(con, old_kind="life", new_kind="daily", now=1)
    final = overrides.set_kind_alias(con, old_kind="daily", new_kind="daily_v2", now=2)
    assert final == "daily_v2"
    aliases = overrides.kind_aliases(con)
    assert aliases["life"] == "daily_v2", "旧名字必须跟着一起走到最终名"
    assert aliases["daily"] == "daily_v2"


def test_kind_alias_rejects_a_self_loop(con):
    with pytest.raises(overrides.OverlayError, match="相同"):
        overrides.set_kind_alias(con, old_kind="life", new_kind="life")


def test_kind_alias_refuses_to_build_a_cycle(con):
    """⚠️ 环只可能来自手工改库，但**死循环比报错糟得多**（它会挂住整个请求）。"""
    overrides.set_kind_alias(con, old_kind="a", new_kind="b", now=1)
    with pytest.raises(overrides.OverlayError, match="环"):
        overrides.set_kind_alias(con, old_kind="b", new_kind="a")
```

在 `tests/test_store.py` 末尾追加：

```python
# ── M6 T5：kind_alias 进读取层（四处 SQL 的收敛）────────────────────


def test_kind_alias_applies_to_every_reading_path(con_with_two_items):
    """⭐ 一条别名必须同时改变**四个**读取路径的回答（R13 的落点）。

    ⚠️ 这条测试的形状是刻意的：它**在一个用例里同时断言四处**。
    拆成四条独立用例的话，「只改了 `_ITEM_COLS`、忘了 `kind_counts`」
    会各自绿一条、红一条——而那恰恰是最可能发生的漏法（四处里有三处
    长得完全一样，只有 `window_items` 是手抄的）。

    ⚠️ 变异反证（四个方向各验一次，**实施时都要跑**）：
      · 把 `_ITEM_COLS` 里的 `_EFFECTIVE_KIND` 换回 `COALESCE(ost.kind, i.kind)` ⇒ 红
      · 把 `_item_filters` 那处换回 ⇒ 红
      · 把 `kind_counts` 那处换回（**两处都要**）⇒ 红
      · 把 `window_items:419` 那处换回 ⇒ 红
    """
    from vigil import overrides

    overrides.attach_readonly(con_with_two_items)
    ov = overrides.connect()
    try:
        overrides.set_kind_alias(ov, old_kind="life", new_kind="daily")
    finally:
        ov.close()

    # ① _ITEM_COLS（列表接口）
    items, total = store.search_items(con_with_two_items)
    assert {it.kind for it in items} == {"daily"}

    # ② _item_filters（按类目筛选）
    hit, _ = store.search_items(con_with_two_items, kinds=["daily"])
    assert len(hit) == total
    miss, _ = store.search_items(con_with_two_items, kinds=["life"])
    assert miss == [], "旧 slug 不该还能筛出东西——它已经不是任何条目的有效类目了"

    # ③ kind_counts（角标）
    assert store.kind_counts(con_with_two_items) == {"daily": total}

    # ④ window_items（日报）
    win = store.window_items(con_with_two_items, since=0, until=2**31)
    assert {w.kind for w in win} == {"daily"}
```

在 `tests/test_api.py` 末尾追加：

```python
# ── M6 T5：类目编辑端点 ─────────────────────────────────────────────


def test_api_add_category_persists(client_factory):
    c = client_factory()
    r = c.post("/api/categories", json={
        "slug": "sport", "label": "体育", "desc": "球赛、运动会", "icon": "⚽",
    })
    assert r.status_code == 201
    slugs = [x["slug"] for x in client_factory().get("/api/categories").json()["categories"]]
    assert "sport" in slugs


def test_api_add_category_rejects_a_bad_slug(client_factory):
    c = client_factory()
    assert c.post("/api/categories", json={"slug": "Sports", "desc": "x"}).status_code == 400


def test_api_add_category_rejects_a_duplicate(client_factory):
    c = client_factory()
    assert c.post("/api/categories", json={"slug": "life", "desc": "重复"}).status_code == 409


def test_api_rename_category_creates_an_alias_and_moves_the_items(client_factory):
    """⭐ **出口判据 6 的机械形式**：删/改一个类目之后，**不允许静默留下
    指向不存在 slug 的条目**。

    ⚠️ 判据必须查**条目那一侧**（`/api/items` 里那条的 `kind` 是不是新 slug），
    只查 `/api/categories` 的话，"配置改了、条目还指着老 slug"照样绿——
    而那是 spec 点名要禁的状态。
    """
    c = client_factory()
    item_id = client_factory.item_ids[0]
    old_kind = c.get(f"/api/items/{item_id}").json()["kind"]

    r = c.put(f"/api/categories/{old_kind}", json={"slug": "life_v2"})
    assert r.status_code == 200

    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life_v2"
    slugs = [x["slug"] for x in c.get("/api/categories").json()["categories"]]
    assert "life_v2" in slugs and old_kind not in slugs


def test_api_delete_category_refuses_when_items_still_point_at_it(client_factory):
    """⭐ 删除时**必须提示「有 N 条属于它」并要一个迁移目标**。

    ⚠️ 不回 400/409 而直接删掉的话，那些条目会指向一个不存在的 slug——
    `digest.py:465-469` 会把这个 slug 当成「类目表里没有的 kind」排到日报末尾
    （它**不静默丢**，这很好），但界面上会显示成裸 slug。
    """
    c = client_factory()
    old_kind = c.get(f"/api/items/{client_factory.item_ids[0]}").json()["kind"]
    r = c.delete(f"/api/categories/{old_kind}")
    assert r.status_code == 409
    assert "migrate_to" in r.json()["detail"]


def test_api_delete_category_with_migration_leaves_nothing_dangling(client_factory):
    c = client_factory()
    item_id = client_factory.item_ids[0]
    old_kind = c.get(f"/api/items/{item_id}").json()["kind"]

    r = c.delete(f"/api/categories/{old_kind}?migrate_to=life")
    assert r.status_code == 204
    assert c.get(f"/api/items/{item_id}").json()["kind"] == "life"
    slugs = [x["slug"] for x in c.get("/api/categories").json()["categories"]]
    assert old_kind not in slugs


def test_api_category_undo_restores_the_previous_file(client_factory):
    """⭐ 类目的「撤销」走**版本快照**，与 overlay 的撤销是两回事（spec §3.3）。"""
    c = client_factory()
    before = {x["slug"] for x in c.get("/api/categories").json()["categories"]}

    c.post("/api/categories", json={"slug": "sport", "desc": "球赛"})
    assert "sport" in {x["slug"] for x in c.get("/api/categories").json()["categories"]}

    assert c.post("/api/categories/undo").status_code == 200
    assert {x["slug"] for x in c.get("/api/categories").json()["categories"]} == before


def test_api_category_undo_says_so_when_there_is_nothing_to_undo(client_factory):
    """⚠️ 空栈时回一句「没有可撤销的操作」，而不是假装成功。

    ⚠️ 与 `/api/undo` 的既有语义对齐（它回 `{"undone": false}`）——
    两处撤销在**协议上**可以不同（一个是内容回滚、一个是事件删除），
    但在**「没得撤时要说出来」这一点上必须一致**。
    """
    c = client_factory()
    body = c.post("/api/categories/undo").json()
    assert body["undone"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_overrides.py tests/test_store.py tests/test_api.py -v -k "snapshot or alias or categor"`
Expected: 全部 FAIL

- [ ] **Step 3: 给 `vigil/overrides.py` 加两张表与五个函数**

**3a.** 在 `_TABLES_DDL` 末尾（`item_state` 那段之后、闭合的三引号之前）追加：

```sql
CREATE TABLE IF NOT EXISTS config_snapshots (
    snapshot_id INTEGER PRIMARY KEY,
    saved_at    INTEGER NOT NULL,
    body        TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS kind_alias (
    old_kind   TEXT PRIMARY KEY,
    new_kind   TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
```

⚠️ **不要加索引**：两张表都是个位数到几十行的规模，而 `_qualified_ddl` 的索引处理有一条**极易踩的坑**——索引名要限定 schema、但**表名不许带 schema**（SQLite 语法限制，`overrides.py:109-111` 有实测记录）。不加索引就不会碰到它。

⚠️ **已存在的 overlay 库会自动补上这两张表**：`ensure_schema` 用的是 `CREATE TABLE IF NOT EXISTS`，而 `create_app`（`api.py:152`）与 `store.ensure_schema` 都会在启动/写路径调它。**读取路径**（`attach_readonly`）只在「文件本来就不存在」时才建表——所以**升级后必须让服务重启一次**（或者跑一次 `vigil refine`），否则会撞 `no such table: ov.kind_alias`。这是**响亮**的失败，不是静默降级（与 R4 既有设计一致）。

**3b.** 在 `_state_of` 之前插入快照四函数：

```python
# ── 配置版本快照（M6 T5）────────────────────────────────────────────
#
# ⚠️ 它**不是** overlay。（spec §3.3：「类目配置的回滚是另一件事
# （`config/categories.toml` 的版本快照），两者都做，别混为一谈」。）
# overlay 记的是「人对**条目**的修改」，快照记的是「程序对**配置文件**的
# 上一次覆盖」——前者用事件日志（可逐条撤销），后者用整份存档
# （只能是整体回滚）。
#
# ⚠️ 为什么快照存在 overlay 库里而不是 `config/history/` 下：
# `config/` 是**要进 git** 的、且它的语义是「唯一真相源」；往里堆历史副本
# 会让「哪一份是真的」变得需要解释，而 `data/overrides.db` 本来就是
# 「会随时间增长的本地可写数据」——这正是快照的性质。


def save_config_snapshot(
    conn: sqlite3.Connection, *, body: str, now: int | None = None
) -> int:
    """存一份配置文件的**原文**。返回 `snapshot_id`。

    ⚠️ 存**原文**而不是解析后的结构：撤销要还原的是**那份文件**，
    重新序列化会丢掉用户手工加的注释（而 `_CATEGORIES_HEADER` 之外的东西
    正是「用户改过这里」的痕迹）。
    """
    stamp = int(time.time()) if now is None else now
    cur = conn.execute(
        "INSERT INTO config_snapshots (saved_at, body) VALUES (?, ?)", (stamp, body)
    )
    conn.commit()
    return int(cur.lastrowid)


def list_config_snapshots(
    conn: sqlite3.Connection, *, limit: int = 20
) -> list[tuple[int, int]]:
    """`[(snapshot_id, saved_at)]`，**新的在前**。"""
    return [
        (int(a), int(b))
        for a, b in conn.execute(
            "SELECT snapshot_id, saved_at FROM config_snapshots"
            " ORDER BY snapshot_id DESC LIMIT ?",
            (limit,),
        )
    ]


def pop_config_snapshot(conn: sqlite3.Connection) -> tuple[int, str] | None:
    """取最近一条快照**并删掉它**，返回 `(snapshot_id, body)`；空栈返回 `None`。

    ⚠️ **必须删掉那一行**，否则「撤销 → 再撤销」会无限撤销同一个状态
    （用户看到的是"点了没反应"）。删行之后每一次撤销都真的往回走一格——
    这与 `undo` 删事件是同一个思路（两者都是"往回走一格"）。
    """
    row = conn.execute(
        "SELECT snapshot_id, body FROM config_snapshots ORDER BY snapshot_id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM config_snapshots WHERE snapshot_id = ?", (row[0],))
    conn.commit()
    return (int(row[0]), str(row[1]))


# ── slug 别名（M6 T5）───────────────────────────────────────────────
#
# ⚠️ 它解决的是一个**结构性**矛盾：spec §4.2 ④ 要求「slug 重命名/删除必须级联」，
# 而 §7/§9 又说 `data/vigil.db` 只读 ⇒ **级联只能发生在读取层**。
# 于是 `store._EFFECTIVE_KIND` 写成 `COALESCE(ost.kind, ka.new_kind, i.kind)`，
# 而这张表就是那个 `ka`。


def set_kind_alias(
    conn: sqlite3.Connection, *, old_kind: str, new_kind: str,
    now: int | None = None,
) -> str:
    """记下「旧 slug 现在叫新 slug」。返回**最终**落进表里的 `new_kind`。

    ⚠️ **写入时压平，读取时只做一次 JOIN**（这是本函数存在的全部理由）。
    别名可以链式追加（`life → daily` 之后又 `daily → daily_v2`）。若表里留着链，
    读路径就得用**递归 CTE** 才能算出最终 slug——而那会把复杂度塞进
    `store.py` 的**四处**查询里（`_ITEM_COLS` / `_item_filters` / `kind_counts`
    两处 / `window_items`），漏一处就是静默的错分类。
    在这里压平，读路径永远只面对「一层映射」。

    ⚠️ 写入顺序在 API 侧是承重的：**先写别名、再写配置文件**。
    反过来的话，中间崩溃会留下「配置里已经没有 life 了、但别名还没建」⇒
    条目永久悬空；而先写别名的话，中间崩溃只留下一条约不到的别名（无害，
    配置写好之后就生效了）。
    """
    if not old_kind or not new_kind:
        raise OverlayError("别名两端都不能为空")
    if old_kind == new_kind:
        raise OverlayError(
            f"别名两端相同（{old_kind}）——那是一条什么都不做的映射，"
            "多半是改名时把新旧名字填成了同一个"
        )

    stamp = int(time.time()) if now is None else now

    # ① 先跟到底：新名字自己可能已经被改过名
    final = new_kind
    seen = {old_kind}
    while True:
        row = conn.execute(
            "SELECT new_kind FROM kind_alias WHERE old_kind = ?", (final,)
        ).fetchone()
        if row is None:
            break
        if row[0] in seen:
            # 环只可能来自手工改库，但**死循环比报错糟得多**——它会挂住整个请求，
            # 而请求是跑在线程池里的，几个环就能把服务拖垮。
            raise OverlayError(
                f"别名成环：{old_kind} → … → {row[0]}。"
                "这张表是程序维护的，出现环说明有人手工改过它。"
            )
        seen.add(row[0])
        final = str(row[0])

    # ② 链式传播：所有指向 old_kind 的行一起走到 final
    conn.execute(
        "UPDATE kind_alias SET new_kind = ? WHERE new_kind = ?", (final, old_kind)
    )
    # ③ 记下/更新自己
    conn.execute(
        "INSERT INTO kind_alias (old_kind, new_kind, created_at) VALUES (?,?,?)"
        " ON CONFLICT(old_kind) DO UPDATE SET new_kind = excluded.new_kind",
        (old_kind, final, stamp),
    )
    conn.commit()
    return final


def kind_aliases(conn: sqlite3.Connection) -> dict[str, str]:
    """`{旧 slug: 新 slug}`。**已是压平后的**（见 `set_kind_alias`）。"""
    return {
        str(a): str(b) for a, b in conn.execute("SELECT old_kind, new_kind FROM kind_alias")
    }
```

- [ ] **Step 4: 把四处 SQL 收敛成 `_EFFECTIVE_KIND`**

**4a.** 在 `vigil/store.py` 的 `_ITEM_COLS` **之前**插入：

```python
# ⚠️ **「有效类目」的唯一表达式**（M6 T5）。三条来源的优先级是**承重的**：
#
#     ost.kind      人工在界面上改过的分类 —— **最强的意图**，不能被改名覆盖
#     ka.new_kind   slug 改名映射（`overrides.kind_alias`）
#     i.kind        库里的原值
#
# ⚠️ 抽成常量**不是为了好看**：在 T5 之前，同一个表达式在**四个地方**各抄了一遍
# （`_ITEM_COLS` / `_item_filters` / `kind_counts` 两处 / `window_items`），
# 而 `window_items` 那份是手抄的、形状还不同（它没有 `ost` 的别名）。
# 「改三处漏一处」在这个形状下是**必然**会发生的，而漏掉 `window_items`
# 的后果是「界面与日报对同一个条目的类目说法不同」——正是 R13。
# 现在只有一处可改，与 `_NOT_DELETED` 完全同形。
_EFFECTIVE_KIND = "COALESCE(ost.kind, ka.new_kind, i.kind)"
```

**4b.** `_ITEM_JOINS` 加一行 JOIN：

```python
_ITEM_JOINS = (
    " FROM items i"
    " LEFT JOIN sender_names sn ON sn.group_id = i.group_id AND sn.uid = i.actor_uid"
    " LEFT JOIN ov.item_state ost ON ost.item_id = i.item_id"
    " LEFT JOIN ov.kind_alias ka ON ka.old_kind = i.kind"
)
```

**4c.** `_ITEM_COLS`（`store.py:871`）把 `COALESCE(ost.kind, i.kind) AS kind` 换成
`{_EFFECTIVE_KIND} AS kind`（在 f-string 里用它）。

**4d.** `_item_filters`（`store.py:961`）把
`f"COALESCE(ost.kind, i.kind) IN ({marks})"` 换成 `f"{_EFFECTIVE_KIND} IN ({marks})"`。

**4e.** `kind_counts`（`store.py:1086-1091`）把 **SELECT 与 GROUP BY 两处**都换成 `_EFFECTIVE_KIND`，
并给它补上 alias 的 JOIN：

```python
def kind_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """每个类目有多少条（**按覆盖后的类目**，且不含软删）。类目视图的角标用它。"""
    _ensure_overlay(conn)
    return {
        str(k): int(n)
        for k, n in conn.execute(
            f"SELECT {_EFFECTIVE_KIND}, COUNT(*) FROM items i"
            " LEFT JOIN ov.item_state ost ON ost.item_id = i.item_id"
            " LEFT JOIN ov.kind_alias ka ON ka.old_kind = i.kind"
            f" WHERE {_NOT_DELETED} GROUP BY {_EFFECTIVE_KIND}"
        )
    }
```

⚠️ **这里不能省 JOIN**：它不走 `_ITEM_JOINS`（那是 SELECT 列与 FROM 的配对），
所以加 `ka` 时必须**同一个函数里两处一起加**（FROM 与 GROUP BY 表达式的依赖）。

**4f.** `window_items`（`store.py:418-419`）两处：

```python
    rows = conn.execute(
        f"SELECT i.item_id, {_EFFECTIVE_KIND}, i.title, i.detail, i.event_ts,"
        " i.deadline_ts, i.group_id, i.place, i.amount, i.confidence"
        " FROM items i"
        " LEFT JOIN ov.item_state ost ON ost.item_id = i.item_id"
        " LEFT JOIN ov.kind_alias ka ON ka.old_kind = i.kind"
        f" WHERE i.event_ts >= ? AND i.event_ts < ? AND {_NOT_DELETED}"
        " ORDER BY i.event_ts ASC, i.item_id ASC",
        (since, until),
    ).fetchall()
```

- [ ] **Step 5: `categories.py` 加 `as_dicts`**

```python
def as_dicts(cats: Sequence[Category]) -> list[dict[str, str]]:
    """`Category` 序列 → `tomllib` 形状的字典列表。

    ⚠️ 存在的理由是**字段名只能有一份**：`slug`/`label`/`desc`/`icon` 这四个
    名字同时出现在读侧（`validate_categories` 的取值）、写侧（`save_categories`
    的 f-string）与 API 侧（`_category_from_body`）。让 API 侧手搓第三个
    字典字面量，就是给「改了三个漏一个」留位置。

    ⚠️ 它**不负责校验**——喂给 `validate_categories` 才有校验。
    叫 `as_dicts` 而不是 `to_raw` 是刻意的：后者听起来像"已经验过了"。
    """
    return [
        {"slug": c.slug, "label": c.label, "desc": c.desc, "icon": c.icon} for c in cats
    ]
```

- [ ] **Step 6: `api.py` 的类目端点**

**6a.** import 补：

```python
from . import categories as categories_mod
from .categories import Category, load_categories
```

**6b.** 在 `create_app` 里（`config_path` / `current_config` / `write_lock` 之后）加：

```python
    def categories_path() -> pathlib.Path:
        return REPO_ROOT / "config" / "categories.toml"

    def snapshot_categories() -> None:
        """把**当前** `categories.toml` 的原文存进 overlay。每次改动**之前**调。

        ⚠️ 文件不存在时静默跳过：那意味着这份配置还没被创建过，
        而"撤销到一个不存在的文件"没有意义。
        """
        path = categories_path()
        if not path.is_file():
            return
        ov = overrides.connect()
        try:
            overrides.save_config_snapshot(ov, body=path.read_text(encoding="utf-8"))
        finally:
            ov.close()

    def category_or_400(body: dict) -> Category:
        """把请求体变成一个 `Category`，**校验不过一律 400**（不是 500）。

        ⚠️ 校验**必须在写之前**：`save_categories` 自己也会校验（T2），
        但那是最后一道闸——先校验一次，才能做到「400 的时候
        **一份快照都没产生、一个字节都没落盘**」。
        """
        slug = str(body.get("slug", "")).strip()
        label = str(body.get("label", "")).strip() or slug
        desc = str(body.get("desc", "")).strip()
        icon = str(body.get("icon", "")).strip()
        for fname, value in (
            ("slug", slug), ("label", label), ("desc", desc), ("icon", icon),
        ):
            _reject_controls(value, fname)
        if not desc:
            raise HTTPException(
                status_code=400,
                detail="desc 不能为空——它会被**逐字**渲染进 LLM 的提示词，是类目的判据",
            )
        return Category(slug=slug, label=label, desc=desc, icon=icon)

    def validate_or_400(cats: Sequence[Category]) -> None:
        try:
            categories_mod.validate_categories(
                categories_mod.as_dicts(cats), categories_path()
            )
        except categories_mod.CategoryError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    def commit_categories(cats: Sequence[Category]) -> None:
        try:
            categories_mod.save_categories(cats, categories_path())
        except categories_mod.CategoryError as exc:
            # 走到这里说明 `validate_or_400` 放行了一份 `save_categories` 拒绝的
            # 东西——那是**程序自己的 bug**，500 才对（400 会把排障引向用户输入）。
            raise HTTPException(status_code=500, detail=f"内部错误：{exc}")
```

**6c.** 改 `api_categories`，把 `desc` 与 `aliases` 带出去（编辑器要用）：

```python
    @app.get("/api/categories")
    def api_categories() -> dict:
        cfg_cats = load_categories(categories_path())
        con = connect()
        try:
            counts = store.kind_counts(con)
        finally:
            con.close()
        ov = overrides.connect()
        try:
            aliases = overrides.kind_aliases(ov)
        finally:
            ov.close()
        return {
            "categories": [
                {
                    "slug": c.slug,
                    "label": c.label,
                    "icon": c.icon,
                    "desc": c.desc,
                    "count": counts.get(c.slug, 0),
                }
                for c in cfg_cats
            ],
            # ⚠️ 一次把别名映射也交出去，供界面显示「旧名 life → 现在叫 daily」。
            # 单独开一个端点也行，但界面每次都要它，多一次往返不值。
            "aliases": aliases,
        }
```

⚠️ 原实现用的是 `create_app` 时冻住的 `cats` / `cat_by_slug`。**改成现读**（同 T4 的 `current_config`）：变量名从 `cats` 改成 `cfg_cats` 是刻意的，好让 `grep -n "cats" vigil/api.py` 能一眼看出还有哪里在用旧的那份。`item_out` 里的 `cat_by_slug` 也要改成**每次现算**——不然网页上刚加的类目在信息流里显示成裸 slug。**实施时把最终改了哪几处写进报告。**

**6d.** 追加四个端点：

```python
    @app.post("/api/categories", status_code=201)
    def api_add_category(body: dict = Body(...)) -> dict:
        cat = category_or_400(body)
        with write_lock:
            existing = load_categories(categories_path())
            if any(c.slug == cat.slug for c in existing):
                raise HTTPException(status_code=409, detail=f"类目 {cat.slug} 已经存在")
            candidate = existing + (cat,)
            validate_or_400(candidate)      # ⚠️ 先验，后拍快照 ⇒ 400 时零副作用
            snapshot_categories()
            commit_categories(candidate)
        return {"slug": cat.slug, "label": cat.label}

    @app.put("/api/categories/{slug}")
    def api_update_category(slug: str, body: dict = Body(...)) -> dict:
        """改一个类目。**body 里带 `slug` 且与路径不同 ⇒ 这是一次改名**。

        ⚠️ **写入顺序是承重的：先写别名，再写配置文件。**
        反过来的话，中间崩溃会留下「配置里已经没有 `life` 了、但别名还没建」
        ⇒ 条目永久悬空（正是 spec §4.2 ④ 点名要禁的状态）；
        先写别名的话，中间崩溃只留下一条约不到的别名——无害，
        配置文件写好之后它立刻生效。
        """
        existing = load_categories(categories_path())
        old = next((c for c in existing if c.slug == slug), None)
        if old is None:
            raise HTTPException(status_code=404, detail=f"没有这个类目：{slug}")

        new_slug = str(body.get("slug", slug)).strip() or slug
        merged = category_or_400(
            {
                "slug": new_slug,
                "label": body.get("label", old.label),
                "desc": body.get("desc", old.desc),
                "icon": body.get("icon", old.icon),
            }
        )
        if new_slug == slug and merged == old:
            return {"slug": slug, "label": old.label}   # 空操作，不拍快照

        candidate = tuple(merged if c.slug == slug else c for c in existing)
        validate_or_400(candidate)

        with write_lock:
            if new_slug != slug:
                ov = overrides.connect()
                try:
                    overrides.set_kind_alias(ov, old_kind=slug, new_kind=new_slug)
                finally:
                    ov.close()
            snapshot_categories()
            commit_categories(candidate)
        return {"slug": merged.slug, "label": merged.label}

    @app.delete("/api/categories/{slug}", status_code=204)
    def api_delete_category(slug: str, migrate_to: str | None = None) -> None:
        """删一个类目。**还有条目指着它时必须给 `?migrate_to=`**。

        ⚠️ 「有 N 条属于它」这句话**必须真的说出来**（spec 出口判据 6）：
        只回一句「不能删」是没用的，用户需要知道**有多少条**、
        以及**不迁移会怎样**。所以 detail 里带上条数。

        ⚠️ 迁移的实现就是一条别名（`slug → migrate_to`），**不碰 `items`**
        ——那正是 `kind_alias` 存在的理由。
        """
        existing = load_categories(categories_path())
        if not any(c.slug == slug for c in existing):
            raise HTTPException(status_code=404, detail=f"没有这个类目：{slug}")

        candidate = tuple(c for c in existing if c.slug != slug)
        if not candidate:
            raise HTTPException(
                status_code=409,
                detail="这是最后一个类目，删掉它会让 refine 的提示词没有类目表可用。",
            )
        validate_or_400(candidate)

        con = connect()
        try:
            n = store.kind_counts(con).get(slug, 0)
        finally:
            con.close()

        if n and not migrate_to:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"类目 {slug} 还有 {n} 条条目指着它。删之前必须给一个迁移目标："
                    f"`DELETE /api/categories/{slug}?migrate_to=<某个现存 slug>`。"
                    "不给的话那些条目会指向一个不存在的类目。"
                ),
            )
        if migrate_to and migrate_to not in {c.slug for c in candidate}:
            raise HTTPException(
                status_code=400, detail=f"迁移目标 {migrate_to!r} 不是一个现存类目"
            )

        with write_lock:
            if migrate_to:
                # ⚠️ 先写别名（见 `api_update_category` 的 docstring）
                ov = overrides.connect()
                try:
                    overrides.set_kind_alias(ov, old_kind=slug, new_kind=migrate_to)
                finally:
                    ov.close()
            snapshot_categories()
            commit_categories(candidate)
        return None

    @app.post("/api/categories/undo")
    def api_category_undo() -> dict:
        """把 `categories.toml` 回滚到上一次程序写它之前的样子。

        ⚠️ **与 `/api/undo` 是两回事**（spec §3.3：「两者都做，别混为一谈」）：
        那条撤的是**对条目的人工修改**（删事件），这条回滚的是**配置文件**
        （整份存档）。协议上也刻意分开：这条回 `{"undone": bool}`，
        与 `/api/undo` 对齐，但**不接受 `edit_id`**——快照没有"中间某一条"，
        只有"上一格"。
        """
        ov = overrides.connect()
        try:
            popped = overrides.pop_config_snapshot(ov)
        finally:
            ov.close()
        if popped is None:
            return {"undone": False}

        _, body = popped
        # ⚠️ 恢复的是一份**手里没有第二份**的内容：先校验再落盘。
        # 直接 `atomic_write_text` 的话，一份坏快照会把配置永久写坏
        # （原子写、无回滚），而 `categories.toml` 是 refine 与 api 的硬依赖。
        try:
            raw = tomllib.loads(body)
            categories_mod.validate_categories(
                raw.get("categories"), categories_path()
            )
        except (tomllib.TOMLDecodeError, categories_mod.CategoryError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"快照内容已损坏，拒绝写回（配置未被改动）：{exc}",
            )
        with write_lock:
            config.atomic_write_text(categories_path(), body)
        return {"undone": True}
```

**6e.** `api.py` 顶部 import 补 `import tomllib` 与 `from . import config`（`atomic_write_text` 用它）。

- [ ] **Step 7: 跑测试确认通过**

Run: `uv run pytest tests/test_overrides.py tests/test_store.py tests/test_api.py -v`
Expected: 全部 PASS

- [ ] **Step 8: ⭐ 四处 SQL 的变异反证（**这一步不能省**）**

依次做四次改动，每次只改一处 `_EFFECTIVE_KIND` 回 `COALESCE(ost.kind, i.kind)`，跑
`uv run pytest tests/test_store.py -k alias -v`，确认**每次都必须变红**：

| 变异 | 期望 |
|---|---|
| `_ITEM_COLS` 那处回退 | RED |
| `_item_filters` 那处回退 | RED |
| `kind_counts` 那处回退（SELECT 与 GROUP BY 都要） | RED |
| `window_items` 那处回退 | RED |

⚠️ **任何一次不红都要停下报告，不许把测试改宽去凑。** 那说明那条路径没被真正覆盖，
而它正是 R13 的形状。**四次的实测输出贴进报告。**

- [ ] **Step 9: 全量回归**

Run: `uv run pytest`

- [ ] **Step 10: Commit**

```bash
git add vigil/overrides.py vigil/store.py vigil/categories.py vigil/api.py tests/test_overrides.py tests/test_store.py tests/test_api.py
git commit -m "feat(categories,overrides): 类目增删改 + 版本快照 + slug 级联（_EFFECTIVE_KIND 收敛四处 SQL）"
```

---

## Task 6: 重排 —— job 机制 + LLM 重判 + 人工批量改

**范围（spec §4.2 ④ + D16）**：改了类目定义之后，让模型按**新定义**重判已有条目的源消息；以及界面上多选批量改。

**两条机械判据（出口判据 7）**：
1. ⭐ **`items.item_id` 前后不变**（D16 的全部意义）；
2. 重排后**撤销**能回到重排前。

**为什么重排要复用 `repass.py` 而不是另写一套**：`repass` 已经解决了三个难问题，而它们每一个都是踩过坑才对的——
- `collect_source_messages` / `context_batches` **复现 refine 的输入构造**（M5 实测：`repass` 曾在稀疏集上建批（中位 1 条）而 `refine` 在密批（中位 30）⇒ **「重判」根本不是重判**）；
- ⚠️ **失败不写判定**（勘误 E5）：一次 429 / 超时 / 解析失败若被记成「判死」，方向是**数据丢失**；
- `_scan_payload(..., known_kinds=...)`：模型**会**呕出类目表里没有的 slug。

⇒ 本任务的 `reorder.py` 只做**一件事**与 `repass` 不同：它拿「判出的 kind」去和**现有的 kind** 比，而不是拿「有没有产出」去决定删不删。**其余一律 import 复用**（`from .repass import collect_source_messages, context_batches, _scan_payload`）。

**⚠️ 一个必须在计划期就定死的交互**：`reorder` 只写 overlay 的 `set_kind` 事件，所以它**不碰 `data/vigil.db`**——这正是判据 1 的机制来源。任何「顺手把结果写回 items」的念头都会同时打破 D11 与判据 1。

**Files:**
- Create: `vigil/jobs.py`
- Create: `vigil/reorder.py`
- Modify: `vigil/overrides.py`（`undo_batch`）
- Modify: `vigil/api.py`（`POST /api/reorder`、`GET /api/jobs/{job_id}`、`POST /api/jobs/{job_id}/undo`、`POST /api/items/kinds`（批量改））
- Create: `tests/test_jobs.py`, `tests/test_reorder.py`
- Modify: `tests/test_overrides.py`, `tests/test_api.py`

**Interfaces:**
- Consumes: T5 的 `store._EFFECTIVE_KIND`、`overrides.set_kind`、`overrides.kind_aliases`；T3 的 `config.load_llm_settings`；T4 的 `write_lock`；既有的 `repass.collect_source_messages` / `repass.context_batches` / `repass._scan_payload`、`refine.build_system_prompt` / `build_user_prompt`、`store.existing_items_for_messages`
- Produces:
  - `jobs.Job` —— dataclass：`job_id: str` / `kind: str` / `state: str` / `total: int` / `done: int` / `message: str` / `error: str` / `started_at: int` / `finished_at: int | None` / `actor: str`
  - `jobs.JobRegistry` —— `submit(kind, fn, *, actor="") -> jobs.Job`、`get(job_id) -> Job | None`、`list() -> list[Job]`、`is_busy() -> bool`
  - `jobs.registry` —— 模块级单例（API 用）
  - `reorder.ReorderPlan` —— dataclass：`changes: tuple[ReorderChange, ...]` / `unjudged: tuple[int, ...]`（item_id）
  - `reorder.ReorderChange` —— dataclass：`item_id: int` / `old_kind: str` / `new_kind: str`
  - `reorder.ReorderStats`
  - `reorder.plan_reorder(conn, *, config, api_key, cats=None, batch_size=30, context=2, budget_tokens=None, model=..., base_url=..., enable_thinking=False, on_progress=print, should_stop=None) -> tuple[ReorderPlan, ReorderStats]`
  - `reorder.apply_reorder(ov, plan, *, actor: str) -> int`
  - `overrides.undo_batch(conn, *, actor: str) -> int`

---

- [ ] **Step 1: 写 `tests/test_jobs.py` 与 `tests/test_reorder.py`（先写失败测试）**

创建 `tests/test_jobs.py`：

```python
"""后台 job 注册表 —— M6 T6。"""

from __future__ import annotations

import threading
import time

from vigil import jobs


def _wait(job, timeout=5.0):
    deadline = time.monotonic() + timeout
    while job.state == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    return job


def test_a_job_runs_and_reports_progress():
    reg = jobs.JobRegistry()

    def work(job):
        job.total = 3
        for _ in range(3):
            job.done += 1
        return "搞定"

    job = reg.submit("reorder", work, actor="reorder:1")
    _wait(job)
    assert job.state == "done"
    assert job.done == 3
    assert job.message == "搞定"
    assert job.actor == "reorder:1"
    assert job.finished_at is not None


def test_a_failing_job_records_the_error_instead_of_dying_silently():
    """⭐ 后台线程里抛出的异常**必须落到 job 上**。

    ⚠️ 这是本模块最重要的一条：线程里没接住的异常会被 Python 打到 stderr
    然后**消失**——而 stderr 属于 uvicorn 的日志，用户点完按钮看到的只有
    「一直转圈」。轮询端点必须能说出「失败了，原因是 X」。
    """
    reg = jobs.JobRegistry()

    def boom(job):
        raise RuntimeError("模型返回了看不懂的东西")

    job = reg.submit("reorder", boom)
    _wait(job)
    assert job.state == "failed"
    assert "看不懂" in job.error


def test_a_second_job_is_refused_while_one_is_running():
    """⭐ 同一时刻只许一个 job。

    ⚠️ 两个重排同时跑 = **烧两份 token 得到同一份结果**，而且两份
    `set_kind` 事件会交错落进日志（撤销会变得没法解释）。

    ⚠️ 变异反证：把 `submit` 里那句 `if self.is_busy(): raise` 删掉
    ⇒ 本条**必红**。
    """
    reg = jobs.JobRegistry()
    gate = threading.Event()

    def slow(job):
        gate.wait(5)

    reg.submit("reorder", slow)
    try:
        import pytest
        with pytest.raises(jobs.JobBusy):
            reg.submit("reorder", slow)
    finally:
        gate.set()


def test_cancel_asks_the_worker_to_stop():
    """取消是**协作式**的：置一个 Event，由 worker 自己在批次之间检查。

    ⚠️ 不是 `threading.Thread.kill`（Python 根本没有这个 API）——
    所以 `should_stop` 必须被**每一批之间**检查，漏一处就是"点了取消没反应"。
    """
    reg = jobs.JobRegistry()
    seen: list[bool] = []

    def work(job):
        for _ in range(200):
            if job.cancel.is_set():
                seen.append(True)
                return "已取消"
            time.sleep(0.005)
        seen.append(False)
        return "跑完了"

    job = reg.submit("reorder", work)
    time.sleep(0.05)
    assert reg.cancel(job.job_id) is True
    _wait(job)
    assert seen == [True]
    assert job.state == "cancelled"


def test_the_registry_keeps_a_bounded_history():
    """⚠️ 内存里的 job 表**必须有界**：服务跑一个月，点几百次重排，
    无界增长就是一次慢速内存泄漏。新的在前，只留最近 N 条。"""
    reg = jobs.JobRegistry(max_history=3)
    for i in range(6):
        _wait(reg.submit("reorder", lambda job: f"第{i}次"))
    assert len(reg.list()) == 3
```

创建 `tests/test_reorder.py`：

```python
"""重排：LLM 重判已有条目 —— M6 T6（D16）。"""

from __future__ import annotations

import pytest

from vigil import overrides, reorder, store


def test_reorder_writes_only_overlay_and_never_touches_items(db_with_items, fake_llm):
    """⭐⭐ **出口判据 7 的核心**：重排前后 `items.item_id` 集合**一模一样**。

    ⚠️ 这条同时是 D11（`data/vigil.db` 只读）与 D16（`item_id` 不变 ⇒ R9 化解）
    的机械形式。**两个不变量由同一条断言同时守住**——这不是巧合：
    重排只写 overlay 正是它们共同的机制。

    ⚠️ 变异反证：让 `apply_reorder` 改成调 `store.save_items(...)`（或任何
    直接 `UPDATE items` 的写法）⇒ 本条**必红**。
    """
    before = sorted(db_with_items.item_ids)
    plan, stats = reorder.plan_reorder(
        db_with_items.conn, config=db_with_items.config, api_key="k",
        on_progress=lambda _: None,
    )
    assert plan.changes, "夹具必须能造出至少一条要改的条目，否则本条是空守卫"

    ov = overrides.connect(db_with_items.overlay_path)
    try:
        n = reorder.apply_reorder(ov, plan, actor="reorder:test")
    finally:
        ov.close()
    assert n == len(plan.changes)

    after = sorted(db_with_items.item_ids)
    assert after == before, (
        "重排改了 items 表——D11 与 D16 同时被打破。重排只能写 overlay 的 set_kind 事件。"
    )


def test_reorder_changes_the_effective_kind(db_with_items, fake_llm):
    """判出的新 kind 必须**在读取层可见**（走 `_EFFECTIVE_KIND`）。"""
    plan, _ = reorder.plan_reorder(
        db_with_items.conn, config=db_with_items.config, api_key="k",
        on_progress=lambda _: None,
    )
    ov = overrides.connect(db_with_items.overlay_path)
    try:
        reorder.apply_reorder(ov, plan, actor="reorder:test")
    finally:
        ov.close()

    changed = plan.changes[0]
    it = store.get_item(db_with_items.conn, changed.item_id)
    assert it is not None
    assert it.kind == changed.new_kind


def test_reorder_skips_soft_deleted_items(db_with_items, fake_llm):
    """⭐ 已软删的条目不参与重排。

    ⚠️ 不跳过的后果不只是浪费 token：一条 `delete` 之后的 `set_kind`
    会让「撤销这一批重排」把条目**从可见变回已删**（因为撤掉 set_kind
    之后，它前面那条 delete 重新生效）。那是一个**静默的状态翻转**，
    而调用方拿到的是一次"成功"的撤销。
    """
    target = db_with_items.item_ids[0]
    ov = overrides.connect(db_with_items.overlay_path)
    try:
        overrides.delete_item(ov, item_id=target, msg_id=None)
    finally:
        ov.close()

    plan, _ = reorder.plan_reorder(
        db_with_items.conn, config=db_with_items.config, api_key="k",
        on_progress=lambda _: None,
    )
    assert target not in {c.item_id for c in plan.changes}


def test_a_failed_batch_produces_no_changes(db_with_items, failing_llm):
    """⭐ 失败**不写判定**（`repass` 勘误 E5 的同一条判据）。

    ⚠️ 一次 429 若被当成「模型说它该是别的类目」，方向是**静默改错分类**——
    比 `repass` 的"删掉"轻一点，但同样是"把没取得的结论当成结论"。
    """
    plan, stats = reorder.plan_reorder(
        db_with_items.conn, config=db_with_items.config, api_key="k",
        on_progress=lambda _: None,
    )
    assert plan.changes == ()
    assert stats.failed_batches == 1


def test_a_hallucinated_slug_never_reaches_the_plan(db_with_items, llm_returning_unknown_kind):
    """模型呕出一个类目表里没有的 slug ⇒ **不许进计划**。

    ⚠️ 它一旦落进 overlay，那个条目就会在界面上显示成一个没人认识的类目，
    而日报会把它排到「类表里没有的 kind」那一段末尾（`digest.py:465-469`
    **不静默丢**，所以它至少是可见的——但可见的错误仍然是错误）。
    闸在 `repass._scan_payload(..., known_kinds=...)`，本任务只是**必须继续用它**。
    """
    plan, _ = reorder.plan_reorder(
        db_with_items.conn, config=db_with_items.config, api_key="k",
        on_progress=lambda _: None,
    )
    known = {c.slug for c in db_with_items.cats}
    assert all(c.new_kind in known for c in plan.changes)


def test_should_stop_halts_between_batches(db_with_items, fake_llm):
    """取消是协作式的：`should_stop` 在**每一批之间**被检查。"""
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 1     # 第一批之后喊停

    plan, stats = reorder.plan_reorder(
        db_with_items.conn, config=db_with_items.config, api_key="k",
        should_stop=stop, on_progress=lambda _: None,
    )
    assert stats.stopped is True
```

⚠️ 夹具 `db_with_items` / `fake_llm` / `failing_llm` / `llm_returning_unknown_kind`：**照抄 `tests/test_repass.py` 里既有的「造库 + 假 LLM」套路**（`grep -n "@pytest.fixture" tests/test_repass.py`）。该文件已有 1,135 行、必然已经解决了「怎么在不联网的前提下喂给 `chat_json` 一个假响应」——**直接复用那套 monkeypatch，不要新造**。夹具需要额外提供 `item_ids` / `overlay_path` / `cats` 三个属性。

在 `tests/test_overrides.py` 末尾追加：

```python
def test_undo_batch_reverts_a_whole_reorder(con):
    """⭐ 批量撤销：重排写 N 条 `set_kind`，撤销要能**一次退回重排前**。

    ⚠️ 为什么不能靠调用 `undo` N 次：`undo` 一次只删**尾部一条**，
    而它有一条 `_reject_non_tail_undo` 闸门——那条闸门是为「撤一条历史中间
    的事件」设的（那会让状态静默翻转）。重排的 N 条是一个**原子意图**，
    它们天然是尾部连续的一段，所以批量删它们是**安全的**，
    但语义与 `undo` 不同，必须是单独一个函数（并单独论证）。
    """
    overrides.set_kind(con, item_id=1, kind="life", actor="reorder:abc")
    overrides.set_kind(con, item_id=2, kind="life", actor="reorder:abc")
    assert overrides.undo_batch(con, actor="reorder:abc") == 2
    assert overrides.undo_batch(con, actor="reorder:abc") == 0
    assert overrides._state_of(con, 1) == (None, 0)
    assert overrides._state_of(con, 2) == (None, 0)


def test_undo_batch_stops_at_a_different_actor(con):
    """⭐ 只撤**尾部连续**的那一段：一旦遇到别的 actor 就停。

    ⚠️ 继续往下删就是把历史事件从日志**中间**抽走——那正是
    `_reject_non_tail_undo` 挡的形状（撤掉中间一条 `set_kind` 能让条目
    从 Web 与日报同时消失，而调用方拿到的是"成功"）。
    """
    overrides.set_kind(con, item_id=1, kind="life", actor="reorder:abc")
    overrides.set_kind(con, item_id=2, kind="academic", actor="web")   # 夹在中间
    overrides.set_kind(con, item_id=3, kind="life", actor="reorder:abc")

    assert overrides.undo_batch(con, actor="reorder:abc") == 1   # 只撤 item 3 那条
    assert overrides._state_of(con, 3) == (None, 0)
    assert overrides._state_of(con, 2) == ("academic", 0), "别人的事件不许被碰"
    assert overrides._state_of(con, 1) == ("life", 0), "更早的那条也不许被碰"
```

在 `tests/test_api.py` 末尾追加：

```python
# ── M6 T6：重排 job + 人工批量改 ────────────────────────────────────


def test_api_reorder_starts_a_job_and_the_poll_says_it_finished(client_factory, fake_llm):
    """⭐ 出口判据 7 的接口形式：起一个 job、轮询到结束、结果落 overlay。"""
    c = client_factory()
    r = c.post("/api/reorder")
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    for _ in range(100):
        body = c.get(f"/api/jobs/{job_id}").json()
        if body["state"] != "running":
            break
        time.sleep(0.02)
    assert body["state"] == "done"
    assert body["kind"] == "reorder"


def test_api_reorder_refuses_a_second_job_while_one_runs(client_factory, slow_llm):
    c = client_factory()
    assert c.post("/api/reorder").status_code == 202
    assert c.post("/api/reorder").status_code == 409


def test_api_jobs_unknown_id_is_404(client_factory):
    assert client_factory().get("/api/jobs/nope").status_code == 404


def test_api_reorder_undo_returns_to_the_previous_kinds(client_factory, fake_llm):
    """⭐ 判据 7 的后半条：**撤销能回到重排前**。"""
    c = client_factory()
    item_id = client_factory.item_ids[0]
    before = c.get(f"/api/items/{item_id}").json()["kind"]

    job_id = c.post("/api/reorder").json()["job_id"]
    for _ in range(100):
        body = c.get(f"/api/jobs/{job_id}").json()
        if body["state"] != "running":
            break
        time.sleep(0.02)

    after = c.get(f"/api/items/{item_id}").json()["kind"]
    assert after != before, "夹具必须造出至少一条真的会变，否则本条是空守卫"

    r = c.post(f"/api/jobs/{job_id}/undo")
    assert r.status_code == 200
    assert c.get(f"/api/items/{item_id}").json()["kind"] == before


def test_api_bulk_set_kind_is_one_actor_so_it_can_be_undone_together(client_factory):
    """人工多选批量改：**同一次提交共用一个 actor**，于是能一次撤销。"""
    c = client_factory()
    ids = client_factory.item_ids[:2]
    before = [c.get(f"/api/items/{i}").json()["kind"] for i in ids]

    r = c.post("/api/items/kinds", json={"item_ids": ids, "kind": "life"})
    assert r.status_code == 200
    assert all(c.get(f"/api/items/{i}").json()["kind"] == "life" for i in ids)

    job_actor = r.json()["actor"]
    assert c.post("/api/bulk-undo", json={"actor": job_actor}).status_code == 200
    assert [c.get(f"/api/items/{i}").json()["kind"] for i in ids] == before
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_jobs.py tests/test_reorder.py -v`
Expected: FAIL（`vigil.jobs` / `vigil.reorder` 不存在）

- [ ] **Step 3: 写 `vigil/jobs.py`**

```python
"""后台 job：把「按了要等」的活儿（LLM 重排）挪出请求线程。

**为什么要它**（spec §4.2 ④ 明写「328 条 ≈ 11 批 ≈ 1-2 分钟，是"按了要等"的活儿
→ 需要 job 机制」）：一个挂 1–2 分钟的 HTTP 请求在前端看起来就是**卡死**——
用户会刷新、会再点一次，而两次点击就是两份 token。

**形态上刻意从简的三处**（单机自用工具，别过度设计）：
* 状态**只在内存里**——重启服务就没了。这不是妥协：job 的产物（overlay 事件）
  是持久的，丢的只是"进度显示"。
* **不做持久化队列**、不做重试、不做优先级。一次只跑一个。
* **不拿 `lock.SingleInstance`**（跨进程那把）。理由见 `submit` 的 docstring。
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

# ⚠️ 历史保留条数。**必须有界**：服务跑一个月、点几百次重排，无界增长就是
# 一次慢速内存泄漏——而它不会以任何显眼的方式表现出来。
MAX_HISTORY = 20

STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_CANCELLED = "cancelled"


class JobBusy(RuntimeError):
    """已有 job 在跑。API 侧映成 **409**（请求合法，与**当前状态**冲突）。"""


@dataclass
class Job:
    """一个后台活儿。字段是**可变**的（worker 线程会一直改它）⇒ 用 `list()` 取快照。"""

    job_id: str
    kind: str
    actor: str = ""
    state: str = STATE_RUNNING
    total: int = 0
    done: int = 0
    message: str = ""
    error: str = ""
    started_at: int = field(default_factory=lambda: int(time.time()))
    finished_at: int | None = None
    # ⚠️ 取消是**协作式**的：Python 没有办法从外面杀掉一个线程。
    # worker 必须在批次之间自己检查它（`reorder.plan_reorder` 的 `should_stop`）。
    # 漏掉检查点 = 点了取消没反应 = 用户以为按钮坏了。
    cancel: threading.Event = field(default_factory=threading.Event)


class JobRegistry:
    def __init__(self, max_history: int = MAX_HISTORY) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._max = max_history

    def is_busy(self) -> bool:
        with self._lock:
            return any(j.state == STATE_RUNNING for j in self._jobs.values())

    def submit(self, kind: str, work: Callable[[Job], str], *, actor: str = "") -> Job:
        """起一个 job。已有 job 在跑 ⇒ 抛 `JobBusy`。

        ⚠️ **刻意不拿 `lock.SingleInstance`**（跨进程那把）。它看起来更稳妥，
        实际会造成一个具体的伤害：那把锁是**进程级、不重入、不等待**的，
        服务进程持着它跑 2 分钟，**08:00 的任务计划就会拿到退出码 2 并跳过
        当天的 export+refine+digest**——为了一个手动点的按钮，赔掉一整天的日报。

        ⚠️ 代价要**说清**：若 daily 恰好在跑，两边会各烧一份 token。这是
        可接受的（用户手点的操作、单用户自用），而上面那个伤害不可接受。
        """
        with self._lock:
            if any(j.state == STATE_RUNNING for j in self._jobs.values()):
                raise JobBusy("已经有一个后台任务在跑了，等它结束再试")
            job = Job(job_id=uuid.uuid4().hex[:12], kind=kind, actor=actor)
            self._jobs[job.job_id] = job
            self._order.append(job.job_id)
            while len(self._order) > self._max:
                self._jobs.pop(self._order.pop(0), None)

        def runner() -> None:
            try:
                job.message = work(job) or ""
                if job.cancel.is_set() and job.state == STATE_RUNNING:
                    job.state = STATE_CANCELLED
                elif job.state == STATE_RUNNING:
                    job.state = STATE_DONE
            except Exception as exc:  # noqa: BLE001 — **必须落进 job**，见下
                # ⚠️ 后台线程里没接住的异常会被 Python 打到 stderr 然后**消失**，
                # 而 stderr 属于 uvicorn 的日志。用户点完按钮看到的只有
                # 「一直转圈」——轮询端点必须能说出「失败了，原因是 X」。
                job.state = STATE_FAILED
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                job.finished_at = int(time.time())

        threading.Thread(target=runner, name=f"vigil-{kind}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        """**新的在前**。"""
        with self._lock:
            return [self._jobs[i] for i in reversed(self._order) if i in self._jobs]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.state != STATE_RUNNING:
            return False
        job.cancel.set()
        return True


# 模块级单例：`api.py` 用它。**测试不要共享它**——每个用例自己 new 一个，
# 否则一个用例残留的 running job 会让下一个用例撞 `JobBusy`，
# 而那是一条与环境相关的假红（本项目在 `data/vigil.lock` 上吃过这个亏，
# 见 `tests/conftest.py::_isolate_lock_path`）。
registry = JobRegistry()
```

- [ ] **Step 4: 写 `vigil/reorder.py`**

```python
"""重排：改了类目定义之后，让模型按**新定义**重判已有条目（D16）。

**它与 `repass` 的唯一区别**：`repass` 拿「有没有产出」决定删不删，
本模块拿「产出的是哪一类」决定改不改类目。所以建批、上下文复现、
失败不写判定、slug 白名单**全部 import 复用**——那四件事每一件都是踩过坑
才写对的，抄一份就会漂移。

⚠️ **只写 overlay 的 `set_kind` 事件，绝不碰 `items` 表**。
这一条同时守住两个不变量：D11（`data/vigil.db` 只读）与 D16（`item_id` 不变
⇒ `digest_items` 的引用不会断）。
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from . import overrides, store
from .categories import Category, load_categories
from .config import Config
from .llm import DEFAULT_BASE, DEFAULT_MODEL, LLMConfig, chat_json
from .redact import Redactor
from .refine import build_system_prompt, build_user_prompt
from .repass import _scan_payload, collect_source_messages, context_batches


@dataclass(frozen=True)
class ReorderChange:
    item_id: int
    old_kind: str
    new_kind: str


@dataclass(frozen=True)
class ReorderPlan:
    changes: tuple[ReorderChange, ...] = ()
    # ⚠️ **没判成**的 item：失败批次、预算提前停止、取消……一条也没写进 verdicts
    # 的那些。它们与「判了、但结论是不用改」是**两回事**，必须分开报
    # （`repass` 的 E5 就是这条：把没判成的当成判死，方向是数据丢失）。
    unjudged: tuple[int, ...] = ()


@dataclass
class ReorderStats:
    scanned_msgs: int = 0
    sent_batches: int = 0
    sent_messages: int = 0
    batches: int = 0
    failed_batches: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    budget_hit: bool = False
    stopped: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        """`plan_reorder` 的预算闸用它。⚠️ 与 `RefineStats` / `RepassStats`
        同名的属性**必须是同一种算法**——两处算不一样的话，
        「预算 30 万」在两个命令里的含义就不同了。"""
        return self.input_tokens + self.output_tokens


def _current_kinds(conn: sqlite3.Connection, item_ids: Sequence[int]) -> dict[int, str]:
    """取这些条目的**有效类目**（含 overlay 与别名，走 `_EFFECTIVE_KIND`）。

    ⚠️ 必须走 `store.get_item`（它用 `_ITEM_COLS`）而**不是**自己写一句
    `SELECT kind FROM items`：后者会读到**别名之前**的老 slug，于是
    「刚改过名的类目」会被判成"需要重排"，而重排的结果是把它改回旧 slug
    ——一个**自己打自己**的循环。
    """
    out: dict[int, str] = {}
    for iid in item_ids:
        it = store.get_item(conn, iid)
        if it is not None:
            out[iid] = it.kind
    return out


def plan_reorder(
    conn: sqlite3.Connection,
    *,
    config: Config,
    api_key: str,
    cats: tuple[Category, ...] | None = None,
    batch_size: int = 30,
    context: int = 2,
    budget_tokens: int | None = None,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE,
    enable_thinking: bool | None = False,
    on_progress=print,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[ReorderPlan, ReorderStats]:
    """出一份「哪些条目的类目该改」的清单。**不写任何东西。**

    ⚠️ `should_stop` 在**每一批之间**被检查——这是取消能生效的唯一机制
    （Python 无法从外部杀掉线程）。漏掉这个检查点就是"点了取消没反应"。
    """
    cats = cats or load_categories()
    known_kinds = frozenset(c.slug for c in cats)
    system = build_system_prompt(cats)
    redactor = Redactor()
    today = dt.date.today().isoformat()
    stats = ReorderStats()

    src_msgs = collect_source_messages(conn)
    stats.scanned_msgs = len(src_msgs)
    if not src_msgs:
        on_progress("[reorder] 没有可重排的源消息")
        return ReorderPlan(), stats

    batches, src_ids = context_batches(
        conn, config=config, batch_size=batch_size, context=context
    )
    stats.sent_batches = len(batches)
    stats.sent_messages = sum(len(b) for b in batches)
    on_progress(
        f"[reorder] 源消息 {stats.scanned_msgs} 条 → {stats.sent_batches} 批 / "
        f"送 {stats.sent_messages} 条消息"
    )
    if not batches:
        on_progress("[reorder] 没有任何含源消息的上下文批次，结束（一条都不会动）")
        return ReorderPlan(), stats

    llm_cfg = LLMConfig(
        api_key=api_key, model=model, base_url=base_url,
        enable_thinking=enable_thinking,
    )

    # ⚠️ `judged[msg_id] = 模型为这条源消息产出的条目`。**失败时绝不写它**
    # （`repass` 勘误 E5 的同一条判据）：一次 429 被当成「模型说它该是别的类目」，
    # 方向是**静默改错分类**。
    judged: dict[int, store.ExtractedItem] = {}

    for index, batch in enumerate(batches, start=1):
        if should_stop is not None and should_stop():
            stats.stopped = True
            on_progress(f"[reorder] 已取消（完成 {index - 1}/{len(batches)} 批）")
            break
        if budget_tokens is not None and stats.total_tokens >= budget_tokens:
            stats.budget_hit = True
            on_progress(f"[reorder] 已达预算上限，提前停止（{index - 1} 批）")
            break

        try:
            result = chat_json(
                llm_cfg, system=system,
                user=build_user_prompt(batch, redactor, today=today),
            )
        except Exception as exc:  # noqa: BLE001 — 见上：**不写判定**
            stats.failed_batches += 1
            stats.errors.append(f"第 {index} 批失败: {exc}")
            on_progress(f"[reorder]{stats.errors[-1]}")
            continue

        # ⚠️ token 累加**留在保护圈外**：token 是真花掉的，本地后处理炸了
        # 不代表模型没被调用——圈进去会让账目说谎（与 refine / repass 同一取舍）。
        stats.input_tokens += result.input_tokens
        stats.output_tokens += result.output_tokens

        try:
            outcome = _scan_payload(
                result.payload, batch, known_kinds=known_kinds, target_ids=src_ids
            )
        except Exception as exc:  # noqa: BLE001 — 单批本地炸不许掀掉整轮
            stats.failed_batches += 1
            stats.errors.append(f"第 {index} 批本地后处理失败: {exc}")
            on_progress(f"[reorder]{stats.errors[-1]}")
            continue

        stats.batches += 1
        for mid, n in outcome.counts.items():
            if n and mid not in judged:
                for it in outcome.produced:
                    if mid in it.src_msg_ids:
                        judged[mid] = it
                        break
        on_progress(
            f"[reorder] 批次 {index}/{len(batches)}：{len(batch)} 条 → "
            f"{outcome.landed} 条 item"
        )

    # ── 把判定折成变更清单 ────────────────────────────────────────────
    items_by_msg = store.existing_items_for_messages(conn, list(judged))
    # ⚠️ 一条源消息可能对应**多个** item（`save_items` 的批内去重来源取并集，
    # 见 `overrides.delete_item` 的 E7 论证）⇒ 用列表而不是单值。
    item_ids: dict[int, list[int]] = {}
    for mid, iids in items_by_msg.items():
        item_ids[mid] = list(iids) if isinstance(iids, (list, tuple, set)) else [iids]

    wanted: dict[int, str] = {}
    for mid, produced in judged.items():
        for iid in item_ids.get(mid, ()):
            wanted.setdefault(iid, produced.kind)

    # ⚠️ 已软删的条目**不参与**（本模块的 docstring 与 `test_reorder_skips_soft_deleted_items`
    # 记着理由）：一条 delete 之后的 set_kind 会让"撤销这批重排"把条目
    # 从可见**变回已删**——那是一个静默的状态翻转。
    alive = {
        iid for iid in wanted
        if store.get_item(conn, iid) is not None
    }

    current = _current_kinds(conn, sorted(alive))
    changes = tuple(
        ReorderChange(item_id=iid, old_kind=current[iid], new_kind=wanted[iid])
        for iid in sorted(alive)
        if iid in current and current[iid] != wanted[iid]
    )
    judged_items = set(alive)
    all_items = {iid for iids in item_ids.values() for iid in iids}
    unjudged = tuple(sorted(all_items - judged_items))

    on_progress(
        f"[reorder] 判定完成：{len(alive)} 条有结论 → **{len(changes)} 条需要改类目**，"
        f"{len(unjudged)} 条没判成（它们不会被动）"
    )
    return ReorderPlan(changes=changes, unjudged=unjudged), stats


def apply_reorder(
    ov: sqlite3.Connection, plan: ReorderPlan, *, actor: str
) -> int:
    """把计划写成 overlay 的 `set_kind` 事件。返回写了多少条。

    ⚠️ **全部事件共用同一个 `actor`**——这是「撤销这一整批」的键
    （`overrides.undo_batch`）。逐条 `set_kind` 而各带各的 actor 的话，
    撤销 N 次才能退回重排前，而中途任何一次别的操作都会把它切成两段。
    """
    for change in plan.changes:
        overrides.set_kind(
            ov, item_id=change.item_id, kind=change.new_kind, actor=actor
        )
    return len(plan.changes)
```

⚠️ **`store.extracted_item.kind` 的真实属性名**：`store.ExtractedItem`（`store.py:148`）。实施前 `grep -n "class ExtractedItem" -A 15 vigil/store.py` **确认它有没有 `kind` 字段**；M1 的 refine 产出里 kind 是核心字段，但**字段名以实际为准**。若叫别的名字（比如 `slug`），**按实际改并把偏差写进报告**。

⚠️ `context_batches(conn, config=config, ...)`：**签名以 `repass.py:462` 的实际定义为准**（本计划读到的调用形式是关键字参数 `config=`，实施前再看一眼）。

- [ ] **Step 5: `overrides.undo_batch`**

在 `undo` 之后插入：

```python
def undo_batch(conn: sqlite3.Connection, *, actor: str) -> int:
    """撤掉**尾部连续的**、属于 `actor` 的全部事件。返回撤了几条。

    ⚠️ **为什么不能靠调用 `undo` N 次**：`undo` 一次只删尾部**一条**，
    而它带着 `_reject_non_tail_undo` 那道闸门。那道闸门是为「撤一条历史
    **中间**的事件」设的——那会让状态静默翻转（终审 Important-1：
    撤一条非尾部 `set_kind` 能让条目从 Web 与日报同时消失，而调用方拿到
    「成功」）。而**重排的 N 条是一个原子意图**，它们天然是尾部连续的一段，
    所以批量删它们**不会**碰到那个形状。

    ⚠️ **一旦遇到不属于 `actor` 的事件就停**——继续往下删就变成"从日志中间
    抽走事件"了，闸门要挡的正是那个。

    ⚠️ 与 `undo` 的另一处不同：本函数**只删、不判**。
    `_reject_non_tail_undo` 里那条「撤掉之后条目会从可见变成被软删 ⇒ 拒绝」
    在这里**不适用**——因为重排（`reorder.plan_reorder`）**已经跳过了软删的条目**，
    所以尾部这段 `set_kind` 背后不可能接着一条会重新生效的 `delete`。
    这条推理是**承重的**：调用方若绕过 `reorder` 自己造一批 `set_kind`，
    这条保证就不成立了。

    ⚠️ 删完走 `rebuild_state()`（**完整重算**，不是增量）：增量折叠只对
    「追加一条」成立，而删除是逆向操作。全表重算在这里是廉价的
    （单机自用、日志规模是几百到几千行），而"再写一套逆向折叠"是典型的
    「两份实现会漂移」——本项目反复吃亏的那个形状。
    """
    rows = conn.execute(
        "SELECT edit_id, actor FROM item_edits ORDER BY edit_id DESC"
    ).fetchall()
    ids: list[int] = []
    for edit_id, who in rows:
        if who != actor:
            break
        ids.append(int(edit_id))
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM item_edits WHERE edit_id IN ({marks})", ids)
    rebuild_state(conn)
    conn.commit()
    return len(ids)
```

- [ ] **Step 6: `api.py` 的四个端点**

在 `create_app` 里 `write_lock` 之后加：

```python
    # ⚠️ **每个 app 一个 registry 还是全局一个？**——本函数用**模块级**
    # `jobs.registry`。理由：job 是**进程**级的资源（线程池、token 花费），
    # 而 `create_app` 在一个进程里可能被调用多次（测试里就是这么用的）。
    # 用模块级才能在"同一个进程起了两个 app"时仍然只允许一个 job 在跑。
    # ⚠️ 代价：测试之间会**串**。`tests/test_api.py` 的夹具必须为每个用例
    # 重置它（`jobs.registry = jobs.JobRegistry()`），否则一个用例残留的
    # running job 会让下一个用例撞 409——一条与环境相关的假红，
    # 与 `data/vigil.lock` 那个坑同形（见 `tests/conftest.py::_isolate_lock_path`）。
```

```python
    def _job_out(job: jobs.Job) -> dict:
        return {
            "job_id": job.job_id,
            "kind": job.kind,
            "state": job.state,
            "total": job.total,
            "done": job.done,
            "message": job.message,
            "error": job.error,
            "actor": job.actor,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
        }

    @app.post("/api/reorder", status_code=202)
    def api_reorder() -> dict:
        """按**当前类目定义**重判已有条目。返回 `job_id`，用 `GET /api/jobs/{id}` 轮询。

        ⚠️ **它只写 overlay，不碰 `data/vigil.db`**（D11/D16 同时成立）。
        ⚠️ 202 而不是 200：活儿还没干完，这是"已受理"。
        """
        settings = load_llm_settings(on_warn=lambda m: None)
        api_key = load_llm_key()
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="没有 LLM 密钥（.env 里的 SILICONFLOW_API_KEY），重排跑不了",
            )
        actor = f"reorder:{int(time.time())}"

        def work(job: jobs.Job) -> str:
            conn = sqlite3.connect(db_uri, uri=True)
            try:
                plan, stats = reorder.plan_reorder(
                    conn, config=config, api_key=api_key,
                    model=settings.model, base_url=settings.base_url,
                    enable_thinking=settings.enable_thinking,
                    on_progress=lambda m: None,
                    should_stop=job.cancel.is_set,
                )
            finally:
                conn.close()
            if job.cancel.is_set():
                return "已取消（一条都没改）"
            ov = overrides.connect()
            try:
                n = reorder.apply_reorder(ov, plan, actor=actor)
            finally:
                ov.close()
            return (
                f"{n} 条改了类目，{len(plan.unjudged)} 条没判成（它们没被动）"
            )

        try:
            job = jobs.registry.submit("reorder", work, actor=actor)
        except jobs.JobBusy as exc:
            # 409 而不是 400：请求本身合法，与**当前状态**冲突（与 `/api/undo` 同形）
            raise HTTPException(status_code=409, detail=str(exc))
        return _job_out(job)

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: str) -> dict:
        job = jobs.registry.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"没有这个任务：{job_id}")
        return _job_out(job)

    @app.post("/api/jobs/{job_id}/undo")
    def api_job_undo(job_id: str) -> dict:
        """撤销**这一批**重排（一次退回重排前）。

        ⚠️ 与 `/api/undo` 是**两个不同的东西**：那条撤的是「最近一条事件」，
        这条撤的是「这个 job 写的**全部**事件」。协议上刻意分开。
        """
        job = jobs.registry.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"没有这个任务：{job_id}")
        if job.state == jobs.STATE_RUNNING:
            raise HTTPException(status_code=409, detail="这个任务还在跑，先取消它再撤销")
        if not job.actor:
            raise HTTPException(status_code=400, detail="这个任务没有可撤销的改动")
        ov = overrides.connect()
        try:
            n = overrides.undo_batch(ov, actor=job.actor)
        finally:
            ov.close()
        return {"undone": n > 0, "count": n}

    @app.post("/api/items/kinds")
    def api_bulk_set_kind(body: dict = Body(...)) -> dict:
        """人工多选批量改类目（D16 的「界面上多选批量改」那一半）。

        ⚠️ **同一次提交共用一个 `actor`**——那样它就能被
        `POST /api/bulk-undo` 一次撤销。逐条各给自己的 actor 的话，
        「改了 5 条、发现改错了」要撤 5 次，而中途任何别的操作都会把它切成两段。
        """
        raw_ids = body.get("item_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise HTTPException(status_code=400, detail="item_ids 必须是非空数组")
        ids: list[int] = []
        for x in raw_ids:
            if isinstance(x, bool) or not isinstance(x, int) or x <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"item_ids 里必须都是正整数（拒绝 true：bool 是 int 的子类），收到：{x!r}",
                )
            ids.append(x)

        kind = str(body.get("kind", "")).strip()
        if not kind:
            raise HTTPException(status_code=400, detail="kind 不能为空")
        _reject_controls(kind, "kind")

        known = {c.slug for c in load_categories(categories_path())}
        if kind not in known:
            raise HTTPException(
                status_code=400,
                detail=f"没有这个类目：{kind!r}。现存类目：{sorted(known)}",
            )

        con = connect()
        try:
            missing = [i for i in ids if store.get_item(con, i) is None]
        finally:
            con.close()
        if missing:
            raise HTTPException(status_code=404, detail=f"没有这些条目：{missing}")

        actor = f"bulk:{uuid.uuid4().hex[:12]}"
        ov = overrides.connect()
        try:
            for iid in ids:
                overrides.set_kind(ov, item_id=iid, kind=kind, actor=actor)
        finally:
            ov.close()
        return {"actor": actor, "count": len(ids)}

    @app.post("/api/bulk-undo")
    def api_bulk_undo(body: dict = Body(...)) -> dict:
        actor = str(body.get("actor", ""))
        if not actor:
            raise HTTPException(status_code=400, detail="actor 不能为空")
        ov = overrides.connect()
        try:
            n = overrides.undo_batch(ov, actor=actor)
        finally:
            ov.close()
        return {"undone": n > 0, "count": n}
```

import 补：`import uuid`、`import time`、`from . import jobs, reorder`、`from .config import load_llm_key, load_llm_settings`。

- [ ] **Step 7: 跑测试确认通过**

Run: `uv run pytest tests/test_jobs.py tests/test_reorder.py tests/test_overrides.py tests/test_api.py -v`
Expected: 全部 PASS

- [ ] **Step 8: ⭐ 判据 1 的变异反证（**不能省**）**

把 `reorder.apply_reorder` 改成：

```python
    for change in plan.changes:
        ov.execute("UPDATE items SET kind = ? WHERE item_id = ?",  # ← 变异体
                   (change.new_kind, change.item_id))
```

跑 `uv run pytest tests/test_reorder.py -v`。

⚠️ **期望：`test_reorder_writes_only_overlay_and_never_touches_items` RED。**
⚠️ 若它**不红**，说明 `db_with_items` 夹具里的 `conn` 是只读连接（`mode=ro`）——
那这条断言**永远不可能被考验**。这正是 M5 最值钱的那条教训的原形：

> **一个专门验证「没写过主库」的守卫，因测试用了只读连接而永远无法被考验。**

**夹具必须用可写连接打开主库**（生产里 refine/digest 也是用可写连接读 overlay 的），
否则这条守卫是空的。**实施时把这一点在报告里明确写出来**——它比本任务其它任何一条都重要。

- [ ] **Step 9: 全量回归**

Run: `uv run pytest`

- [ ] **Step 10: Commit**

```bash
git add vigil/jobs.py vigil/reorder.py vigil/overrides.py vigil/api.py tests/test_jobs.py tests/test_reorder.py tests/test_overrides.py tests/test_api.py
git commit -m "feat(reorder,jobs): LLM 重排 + 后台 job（D16：只写 overlay，item_id 不变）"
```

---

## Task 7: 配置包 —— 导入 / 导出

**形态（用户 2026-09-17 已选）**：**单个 TOML 文件**，把三份配置合成一份。

```toml
[settings]          # qq_db_dir / output_db
[[groups]]
[[categories]]
[[persons]]
[[kind_aliases]]    # slug 改名映射（见下）
```

**四条边界，每条都有具体的理由**：

| 边界 | 理由 |
|---|---|
| ⛔ **不含密钥** | `.env` 里的 `SILICONFLOW_API_KEY` / `VIGIL_DB_KEY` **永远不进配置文件**，也就进不了包。包会被人拷来拷去，密钥不会。 |
| ⛔ **不含 overlay**（`item_edits` / `item_state`） | spec §7 明写：「导出的是**配置**（D11 的范围），不含 overlay——它是本机的数据」。 |
| ✅ **含 `kind_aliases`** | 它**不是** overlay：它是「改过 slug 名」这件事的**后果**，属于配置的语义。不含它的话，另一台机器导入后条目会全部悬空——**而那正是 spec §4.2 ④ 要禁的状态**。 |
| ⚠️ **导入必须能只导「非本机」的那部分** | `qq_db_dir` 是**机器相关**的（`C:/Users/<你>/Documents/Tencent Files/...`）。把同事的包原样导入，`load_config` 会报「QQ 数据库目录不存在」——**响亮但没有用**。所以 `--keep-settings` 是必需的，不是可选糖。 |

**为什么用 TOML 而不是 JSON**：`config/*.toml` 是 TOML，导出一份 JSON 会让「导出、手改、导入」这条最常见的用法里多一层心智转换（JSON 里没有注释、`\uXXXX` 满天飞）。写侧序列化 T2 已经建好，**成本为零**。

**Files:**
- Create: `vigil/configpack.py`
- Modify: `vigil/cli.py`（`vigil config export/import`）
- Modify: `vigil/api.py`（`GET /api/config/pack`、`POST /api/config/pack`）
- Create: `tests/test_configpack.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: T2 的 `toml_str` / `toml_int` / `_toml_path` / `save_config` / `save_persons`；T2 抽出的 `config.validate_config_raw` 与 `categories.validate_categories`；T5 的 `overrides.kind_aliases` / `set_kind_alias`
- Produces:
  - `configpack.PACK_SCHEMA: int`（= 1）
  - `configpack.build(*, config, cats, persons, aliases) -> str`
  - `configpack.parse(text, path) -> Pack` —— 校验不过抛 `ConfigError`
  - `configpack.Pack` —— frozen dataclass：`config: Config | None` / `categories: tuple[Category, ...]` / `persons: tuple[Person, ...]` / `aliases: tuple[tuple[str, str], ...]`
  - `configpack.write_pack(path, *, config, cats, persons, aliases) -> pathlib.Path`
  - `configpack.ImportReport` —— dataclass：`groups: int` / `categories: int` / `persons: int` / `aliases: int` / `settings_skipped: bool`
  - `configpack.import_pack(pack, *, keep_settings: bool, paths: Paths, on_progress=print) -> ImportReport`

---

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_configpack.py`：

```python
"""配置包 —— M6 T7（spec §4.2 ① 的导入导出）。"""

from __future__ import annotations

import pathlib

import pytest

from vigil import categories, config, configpack


@pytest.fixture
def roots(tmp_path):
    """两个**互不相干**的数据根，用来验「另一个目录能导入并生效」（出口判据 4）。

    ⚠️ 每个根下都有自己的 `config/` 与 `data/`，并且**都不碰真仓库**。
    """
    class Roots:
        def __init__(self, base: pathlib.Path):
            self.base = base
            self.config_dir = base / "config"
            self.config_dir.mkdir(parents=True)
            self.qq = base / "qqdb"
            self.qq.mkdir()
            self.groups = self.config_dir / "groups.toml"
            self.cats = self.config_dir / "categories.toml"
            self.persons = self.config_dir / "persons.toml"

        def make_config(self, groups):
            return config.Config(
                qq_db_dir=self.qq,
                output_db=self.base / "data" / "vigil.db",
                groups=tuple(groups),
            )

    a = Roots(tmp_path / "A")
    b = Roots(tmp_path / "B")
    return a, b


def _seed(root):
    config.save_config(
        root.make_config([
            config.Group(id=111, name="甲群", tier="high"),
            config.Group(id=222, name="乙群", enabled=False),
        ]),
        root.groups,
    )
    categories.save_categories(
        (categories.Category(slug="notice", label="通知", desc="正式通知", icon="📋"),),
        root.cats,
    )
    config.save_persons(
        (config.Person(uin=100000001, label="某辅导员"),), root.persons
    )


def test_export_then_import_into_another_root(roots):
    """⭐ **出口判据 4 的机械形式**。"""
    a, b = roots
    _seed(a)

    pack_path = a.base / "vigil-config.toml"
    configpack.write_pack(
        pack_path,
        config=config.load_config(a.groups),
        cats=categories.load_categories(a.cats),
        persons=config.load_persons(a.persons),
        aliases=(("life_old", "life"),),
    )

    parsed = configpack.parse(pack_path.read_text(encoding="utf-8"), pack_path)
    report = configpack.import_pack(
        parsed,
        keep_settings=False,
        paths=configpack.Paths(
            groups=b.groups, categories=b.cats, persons=b.persons
        ),
    )
    assert report.groups == 2
    assert report.categories == 1
    assert report.persons == 1
    assert report.aliases == 1

    # ⭐ "生效" = 用**新根**重新读一遍，拿到的就是包里的东西
    assert [g.id for g in config.load_config(b.groups).groups] == [111, 222]
    assert [c.slug for c in categories.load_categories(b.cats)] == ["notice"]
    assert [p.uin for p in config.load_persons(b.persons)] == [100000001]


def test_keep_settings_leaves_the_local_paths_alone(roots):
    """⭐ `--keep-settings` 不是可选糖：`qq_db_dir` 是**机器相关**的。

    ⚠️ 把别人的包原样导入，`load_config` 会报「QQ 数据库目录不存在」——
    响亮，但对用户毫无帮助（他想要的只是那几个群和类目）。
    """
    a, b = roots
    _seed(a)
    # B 根上先有一份自己的配置
    config.save_config(b.make_config([config.Group(id=999, name="本机群")]), b.groups)
    local_qq = config.load_config(b.groups).qq_db_dir

    pack_path = a.base / "pack.toml"
    configpack.write_pack(
        pack_path, config=config.load_config(a.groups),
        cats=categories.load_categories(a.cats),
        persons=config.load_persons(a.persons), aliases=(),
    )
    parsed = configpack.parse(pack_path.read_text(encoding="utf-8"), pack_path)
    report = configpack.import_pack(
        parsed, keep_settings=True,
        paths=configpack.Paths(groups=b.groups, categories=b.cats, persons=b.persons),
    )
    assert report.settings_skipped is True
    assert config.load_config(b.groups).qq_db_dir == local_qq, "本机路径不许被覆盖"
    assert [g.id for g in config.load_config(b.groups).groups] == [111, 222], (
        "群清单仍然来自包——keep-settings 只保留 [settings]"
    )


def test_the_pack_never_contains_a_secret(roots):
    """⭐ **密钥永远不进配置文件**（spec §3.2）——本条检查的是**产物**。

    ⚠️ 判据是「产物里没有那些**值**」，而不是「代码里没写」。做法是把
    两个密钥塞进环境变量，再导出一次，断言它们的字面量不出现在包里。
    只 grep 字段名（`api_key`）是不够的：一个拼错的键名照样会漏。
    """
    a, _ = roots
    _seed(a)
    secret_db = "SUPER-SECRET-DB-KEY-1234567890"
    secret_llm = "sk-SUPER-SECRET-LLM-KEY"
    monkeypatch.setenv("VIGIL_DB_KEY", secret_db)      # noqa: F821 —— 见下方 ⚠️
    monkeypatch.setenv("SILICONFLOW_API_KEY", secret_llm)

    text = configpack.build(
        config=config.load_config(a.groups),
        cats=categories.load_categories(a.cats),
        persons=config.load_persons(a.persons), aliases=(),
    )
    assert secret_db not in text
    assert secret_llm not in text
    assert "key" not in text.lower() or "密钥" in text, (
        "包里出现了 key 字样——先确认它不是任何一个密钥的值"
    )


def test_a_pack_from_a_newer_schema_is_refused(roots):
    """版本闸：形状变了就必须**拒绝**，不许静默错读。"""
    a, _ = roots
    _seed(a)
    text = configpack.build(
        config=config.load_config(a.groups),
        cats=categories.load_categories(a.cats),
        persons=config.load_persons(a.persons), aliases=(),
    )
    bumped = text.replace(
        f"schema = {configpack.PACK_SCHEMA}", f"schema = {configpack.PACK_SCHEMA + 1}"
    )
    assert bumped != text, "包头部必须有一个可识别的 schema 行"
    with pytest.raises(config.ConfigError, match="版本"):
        configpack.parse(bumped, pathlib.Path("x.toml"))


def test_import_is_all_or_nothing(roots):
    """⭐ **导入是全有或全无**：校验不过 ⇒ 一个文件都不许被写。

    ⚠️ 不这么做的后果是**最坏的一种**：类目写进去了、群没写进去，
    而用户看到的是「导入失败」——他会以为什么都没发生，实际配置已经半新半旧。
    校验（`validate_config_raw` / `validate_categories`）在**任何写入之前**
    全部跑完，这一条才成立。
    """
    a, b = roots
    _seed(a)
    # 一份**类目合法、群非法**（零个群）的包
    bad = configpack.build(
        config=config.Config(
            qq_db_dir=a.qq, output_db=a.base / "data" / "vigil.db", groups=()
        ),
        cats=categories.load_categories(a.cats),
        persons=config.load_persons(a.persons), aliases=(),
    )
    with pytest.raises(config.ConfigError):
        configpack.parse(bad, pathlib.Path("bad.toml"))
    assert not b.cats.exists(), "解析失败时 b 根上不许有任何文件"
    assert not b.groups.exists()
```

⚠️ `monkeypatch` 是 `test_the_pack_never_contains_a_secret` 的参数，**记得写进签名**（上面草稿里漏了）。修正为 `def test_the_pack_never_contains_a_secret(roots, monkeypatch):`。

在 `tests/test_api.py` 末尾追加：

```python
# ── M6 T7：配置包端点 ───────────────────────────────────────────────


def test_api_export_pack_returns_toml_text(client_factory):
    body = client_factory().get("/api/config/pack").json()
    assert "[[categories]]" in body["toml"]
    assert "[[persons]]" in body["toml"]


def test_api_import_pack_rejects_a_bad_document(client_factory):
    c = client_factory()
    r = c.post("/api/config/pack", json={"toml": "[settings\n", "apply": True})
    assert r.status_code == 400


def test_api_import_pack_applies(client_factory):
    c = client_factory()
    text = c.get("/api/config/pack").json()["toml"]
    r = c.post("/api/config/pack", json={"toml": text, "apply": True})
    assert r.status_code == 200
    assert r.json()["categories"] >= 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_configpack.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 写 `vigil/configpack.py`**

```python
"""配置包：把三份配置合成一份可携带的 TOML（M6 T7）。

**形态**：单个文件，`[settings]` + `[[groups]]` + `[[categories]]` + `[[persons]]`
+ `[[kind_aliases]]`。

**四条边界见计划 §T7 的表格。** 其中最容易漏的是第三条——
`kind_aliases` **必须**进包：它是「改过 slug 名」这件事的后果，
属于配置的语义；不含它的话，另一个机器导入后**条目会全部悬空**。

⚠️ **本模块不做任何写入之外的副作用**，也不碰 `data/vigil.db`。
"""

from __future__ import annotations

import pathlib
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass

from . import overrides
from .categories import Category, validate_categories
from .config import (
    Config, ConfigError, Person, _toml_path, atomic_write_text, save_config,
    save_persons, toml_int, toml_str, validate_config_raw,
)

PACK_SCHEMA = 1

_HEADER = """\
# VIGIL 配置包
#
# 这一个文件里装着三份配置：监听群 / 类目 / 监视人物，外加 slug 改名映射。
# 用 `vigil config import <这个文件>` 或网页「配置」页导入。
#
# ⛔ **不含任何密钥**：`.env` 里的 SILICONFLOW_API_KEY / VIGIL_DB_KEY 永远不在这里。
# ⛔ **不含人工干预数据**（改过的分类、软删的条目）——那是**本机**的数据，
#    不是配置（spec §7）。
"""


@dataclass(frozen=True)
class Pack:
    config: Config | None
    categories: tuple[Category, ...]
    persons: tuple[Person, ...]
    aliases: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Paths:
    """导入的落点。**显式传入**，不在模块里读 `REPO_ROOT`——

    ⚠️ 与 `api.persons_path()` / `api.config_path()` 同一条判据：
    路径若在模块级冻住，测试里 `monkeypatch.setattr` 就够不着它，
    于是一次导入会**写进真仓库**，而所有测试照样绿（那个夹具会变成空守卫）。
    """

    groups: pathlib.Path
    categories: pathlib.Path
    persons: pathlib.Path


@dataclass
class ImportReport:
    groups: int = 0
    categories: int = 0
    persons: int = 0
    aliases: int = 0
    settings_skipped: bool = False


def build(
    *,
    config: Config,
    cats: Sequence[Category],
    persons: Sequence[Person],
    aliases: Sequence[tuple[str, str]] | dict[str, str] = (),
) -> str:
    """渲染成配置包的文本。**不落盘**（`write_pack` 才落）。"""
    lines = [_HEADER, "", f"schema = {PACK_SCHEMA}", ""]

    # ⚠️ `[settings]` **必须写在所有 `[[…]]` 之前**（与 `config.save_config`
    # 同一条 TOML 段序陷阱：`[table]` 掉到 `[[array]]` 后面会被解析成
    # 最后一个元素的子表）。
    lines += [
        "[settings]",
        f"qq_db_dir = {_toml_path(config.qq_db_dir)}",
        f"output_db = {_toml_path(config.output_db)}",
        "",
    ]
    for g in config.groups:
        lines += [
            "[[groups]]",
            f"id = {toml_int(g.id, '群号')}",
            f"name = {toml_str(g.name)}",
            f"enabled = {'true' if g.enabled else 'false'}",
            f"tier = {toml_str(g.tier)}",
            "",
        ]
    for c in cats:
        lines += [
            "[[categories]]",
            f"slug = {toml_str(c.slug)}",
            f"label = {toml_str(c.label)}",
        ]
        if c.icon:
            lines.append(f"icon = {toml_str(c.icon)}")
        lines += [f"desc = {toml_str(c.desc)}", ""]
    for p in persons:
        lines += [
            "[[persons]]",
            f"uin = {toml_int(p.uin, 'uin')}",
            f"label = {toml_str(p.label)}",
        ]
        if p.note:
            lines.append(f"note = {toml_str(p.note)}")
        lines.append("")
    items = aliases.items() if isinstance(aliases, dict) else aliases
    for old, new in items:
        lines += [
            "[[kind_aliases]]",
            f"old_kind = {toml_str(old)}",
            f"new_kind = {toml_str(new)}",
            "",
        ]
    return "\n".join(lines)


def write_pack(
    path: pathlib.Path,
    *,
    config: Config,
    cats: Sequence[Category],
    persons: Sequence[Person],
    aliases: Sequence[tuple[str, str]] | dict[str, str] = (),
) -> pathlib.Path:
    text = build(config=config, cats=cats, persons=persons, aliases=aliases)
    atomic_write_text(path, text)
    return path


def parse(text: str, path: pathlib.Path) -> Pack:
    """解析并**完整校验**一个配置包。任何问题都抛 `ConfigError`。

    ⚠️ 校验的是**整包**，而且是**在任何写入之前**——`import_pack` 靠这一点
    才能做到「全有或全无」。半新半旧的配置是最坏的结果：用户看到「导入失败」，
    以为什么都没发生，实际已经写进去了一半。
    """
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: TOML 语法错误——{exc}") from exc

    if raw.get("schema") != PACK_SCHEMA:
        raise ConfigError(
            f"{path}: 配置包版本不符（读到 {raw.get('schema')!r}，"
            f"本程序认 {PACK_SCHEMA}）。这份包可能是更新版的 VIGIL 导出的——"
            "形状变了就必须拒绝，静默错读会让导入的配置**看起来对了、其实错了**。"
        )

    # ⚠️ 群清单可以为空（"这份包只带类目"是合法的），但**真导入时**会撞
    # `validate_config_raw` 的「一个群都没配」——那是 `save_config` 的判据，
    # 与"包里有没有群"是两回事。这里用一份**宽容的**校验拿到分组数据。
    groups_raw = raw.get("groups", [])
    cfg: Config | None = None
    if raw.get("settings") is not None:
        try:
            cfg = validate_config_raw(raw, path)
        except ConfigError as exc:
            # 包里的 qq_db_dir 多半指向**导出那台机器**的路径。这是**预期内**的，
            # 所以把话说明白：要么在本机建好那个目录，要么用 `--keep-settings`。
            raise ConfigError(
                f"{path}: [settings] 段校验不过——{exc}\n"
                "  ⚠️ 若这份包来自另一台机器，它的 qq_db_dir 是**那边**的路径。"
                "用 `--keep-settings`（网页上勾「保留本机路径」）只导入群/类目/人物。"
            ) from exc
    elif groups_raw:
        raise ConfigError(
            f"{path}: 有 [[groups]] 却没有 [settings]——群配置没法独立存在"
            "（它需要 qq_db_dir 才知道去哪儿读消息）"
        )

    cats = validate_categories(raw.get("categories"), path)

    persons: list[Person] = []
    seen: set[int] = set()
    for entry in raw.get("persons", []):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: 每个 [[persons]] 段都必须是键值表")
        uin = entry.get("uin")
        if isinstance(uin, bool) or not isinstance(uin, int) or uin <= 0:
            raise ConfigError(f"{path}: 人物 uin 必须为正整数，实际是 {uin!r}")
        if uin in seen:
            raise ConfigError(f"{path}: uin {uin} 重复出现")
        label = str(entry.get("label", "")).strip()
        if not label:
            raise ConfigError(f"{path}: uin {uin} 缺 label")
        seen.add(uin)
        persons.append(
            Person(uin=uin, label=label, note=str(entry.get("note", "")).strip())
        )

    aliases: list[tuple[str, str]] = []
    seen_old: set[str] = set()
    for entry in raw.get("kind_aliases", []):
        if not isinstance(entry, dict):
            raise ConfigError(f"{path}: 每个 [[kind_aliases]] 段都必须是键值表")
        old = str(entry.get("old_kind", "")).strip()
        new = str(entry.get("new_kind", "")).strip()
        if not old or not new:
            raise ConfigError(f"{path}: kind_aliases 的两端都不能为空")
        if old == new:
            raise ConfigError(f"{path}: kind_aliases 的两端相同（{old}）")
        if old in seen_old:
            raise ConfigError(f"{path}: 旧类目 {old} 出现了两次")
        seen_old.add(old)
        aliases.append((old, new))

    return Pack(
        config=cfg,
        categories=cats,
        persons=tuple(persons),
        aliases=tuple(aliases),
    )


def import_pack(
    pack: Pack,
    *,
    keep_settings: bool,
    paths: Paths,
    on_progress=print,
) -> ImportReport:
    """把包写进 `paths`。**全有或全无**：校验在 `parse` 里已经跑完。

    ⚠️ **写入顺序有意义**：先写 `kind_aliases`，再写配置。
    反过来的话，中间崩溃会留下「配置里已经没有 `life` 了、但别名还没建」
    ⇒ 条目永久悬空。这与 `api.api_update_category` 的顺序是**同一条理由**。
    """
    report = ImportReport(settings_skipped=keep_settings)

    # ① 别名先落（只要包里有旧→新的映射，条目就不会悬空）
    if pack.aliases:
        ov = overrides.connect()
        try:
            for old, new in pack.aliases:
                overrides.set_kind_alias(ov, old_kind=old, new_kind=new)
        finally:
            ov.close()
        report.aliases = len(pack.aliases)

    # ② 类目
    from .categories import save_categories

    save_categories(pack.categories, paths.categories)
    report.categories = len(pack.categories)

    # ③ 人物
    save_persons(pack.persons, paths.persons)
    report.persons = len(pack.persons)

    # ④ 群（+ settings）
    if pack.config is not None and not keep_settings:
        save_config(pack.config, paths.groups)
        report.groups = len(pack.config.groups)
    elif pack.config is not None:
        # ⚠️ `keep_settings` 只保留 **[settings] 段**，群清单仍然来自包。
        # 「保留本机路径」被理解成「整个 groups.toml 都不动」是一个很自然的误读，
        # 而那样导入一份包就什么都不发生了——用户会以为导入坏了。
        #
        # ⚠️ 本机那份可能还不存在（第一次导入），那时**没法保留**，
        # 只能整份用包里的——但那又需要包的 qq_db_dir 在本机存在。
        # 所以这一支要么成功、要么由 `validate_config_raw` 响亮报错。
        local = paths.groups
        if local.is_file():
            try:
                with open(local, "rb") as f:
                    current = validate_config_raw(tomllib.load(f), local)
            except ConfigError:
                current = None
            if current is not None:
                merged = Config(
                    qq_db_dir=current.qq_db_dir,
                    output_db=current.output_db,
                    groups=pack.config.groups,
                )
                save_config(merged, local)
                report.groups = len(merged.groups)
        if report.groups == 0:
            save_config(pack.config, local)
            report.groups = len(pack.config.groups)
            on_progress(
                "[导入] 本机还没有 groups.toml，无法保留本机路径——"
                "整份用了包里的（包括 qq_db_dir）"
            )

    on_progress(
        f"[导入] 群 {report.groups} / 类目 {report.categories} / "
        f"人物 {report.persons} / 改名 {report.aliases}"
        + ("（保留本机 [settings]）" if keep_settings else "")
    )
    return report
```

- [ ] **Step 4: CLI 子命令**

在 `vigil/cli.py` 的 argparse 区加一组子命令（`config` 是个父命令，带两个子动作）：

```python
    p_cfg = sub.add_parser("config", help="配置包：导入 / 导出")
    cfg_sub = p_cfg.add_subparsers(dest="config_action", required=True)

    p_cfg_x = cfg_sub.add_parser("export", help="把三份配置导出成一个 TOML 包")
    p_cfg_x.add_argument("--out", default=None, help="输出路径（默认 data/vigil-config-<日期>.toml）")
    p_cfg_x.set_defaults(func=cmd_config_export)

    p_cfg_i = cfg_sub.add_parser("import", help="从 TOML 包导入配置")
    p_cfg_i.add_argument("file", help="配置包路径")
    p_cfg_i.add_argument(
        "--keep-settings", action="store_true",
        help="保留本机的 qq_db_dir / output_db（导入别人的包时几乎总要加）",
    )
    p_cfg_i.add_argument("--dry-run", action="store_true", help="只校验，不写")
    p_cfg_i.set_defaults(func=cmd_config_import)
```

```python
def cmd_config_export(args) -> int:
    """导出一个自包含的配置包（**不含密钥**，spec §4.2 ①）。"""
    from . import configpack

    config = _load_config_only()
    cats = load_categories()
    persons = load_persons()
    ov = overrides.connect()
    try:
        aliases = overrides.kind_aliases(ov)
    finally:
        ov.close()

    out = pathlib.Path(args.out) if args.out else (
        config.output_db.parent / f"vigil-config-{dt.date.today().isoformat()}.toml"
    )
    configpack.write_pack(out, config=config, cats=cats, persons=persons, aliases=aliases)
    logs.emit(f"已导出配置包：{out}")
    logs.emit(f"  群 {len(config.groups)} / 类目 {len(cats)} / 人物 {len(persons)} / 改名 {len(aliases)}")
    logs.emit("  ⛔ 不含密钥，不含人工干预数据")
    return 0


def cmd_config_import(args) -> int:
    """导入配置包。⚠️ 默认**真的写**（`--dry-run` 只校验）。"""
    from . import configpack
    from . import categories as categories_mod

    path = pathlib.Path(args.file)
    if not path.is_file():
        sys.exit(f"[参数错误] 找不到配置包：{path}")

    try:
        pack = configpack.parse(path.read_text(encoding="utf-8"), path)
    except ConfigError as exc:
        sys.exit(f"[配置错误] {exc}")

    if args.dry_run:
        logs.emit(
            f"[dry-run] 包校验通过：群 {len(pack.config.groups) if pack.config else 0} / "
            f"类目 {len(pack.categories)} / 人物 {len(pack.persons)} / 改名 {len(pack.aliases)}"
        )
        return 0

    report = configpack.import_pack(
        pack,
        keep_settings=args.keep_settings,
        paths=configpack.Paths(
            groups=REPO_ROOT / "config" / "groups.toml",
            categories=categories_mod.DEFAULT_CATEGORIES,
            persons=pathlib.Path(config.DEFAULT_PERSONS),
        ),
        on_progress=logs.emit,
    )
    return 0 if (report.groups or report.categories) else 1
```

⚠️ import 补：`import pathlib`、`from .categories import load_categories`、`from . import overrides`。

- [ ] **Step 5: API 端点**

```python
    @app.get("/api/config/pack")
    def api_export_pack() -> dict:
        """把三份配置渲染成一个配置包文本（**不含密钥**）。"""
        from . import configpack

        cfg = current_config()
        cats = load_categories(categories_path())
        people = load_persons(persons_path())
        ov = overrides.connect()
        try:
            aliases = overrides.kind_aliases(ov)
        finally:
            ov.close()
        return {
            "toml": configpack.build(
                config=cfg, cats=cats, persons=people, aliases=aliases
            ),
            "schema": configpack.PACK_SCHEMA,
        }

    @app.post("/api/config/pack")
    def api_import_pack(body: dict = Body(...)) -> dict:
        """导入一个配置包。

        ⚠️ 收的是 **JSON body 里的字符串**，不是 multipart 文件上传——
        本项目依赖表只有 sqlcipher3，而 multipart 要 `python-multipart`。
        为一处上传引一个依赖不划算，前端把文件读成文本再 POST 即可
        （`FileReader.readAsText`，浏览器原生）。
        """
        from . import configpack

        text = body.get("toml")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=400, detail="toml 字段必须是配置包文本")
        apply_ = bool(body.get("apply", False))
        keep_settings = bool(body.get("keep_settings", False))

        try:
            pack = configpack.parse(text, pathlib.Path("<上传的配置包>"))
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        if not apply_:
            return {
                "applied": False,
                "groups": len(pack.config.groups) if pack.config else 0,
                "categories": len(pack.categories),
                "persons": len(pack.persons),
                "aliases": len(pack.aliases),
            }

        with write_lock:
            report = configpack.import_pack(
                pack,
                keep_settings=keep_settings,
                paths=configpack.Paths(
                    groups=config_path(),
                    categories=categories_path(),
                    persons=persons_path(),
                ),
                on_progress=lambda _: None,
            )
        return {
            "applied": True,
            "groups": report.groups,
            "categories": report.categories,
            "persons": report.persons,
            "aliases": report.aliases,
            "settings_skipped": report.settings_skipped,
        }
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_configpack.py tests/test_api.py tests/test_cli.py -v`
Expected: 全部 PASS

- [ ] **Step 7: 全量回归**

Run: `uv run pytest`

- [ ] **Step 8: Commit**

```bash
git add vigil/configpack.py vigil/cli.py vigil/api.py tests/test_configpack.py tests/test_api.py tests/test_cli.py
git commit -m "feat(configpack): 配置包导入导出（单文件 TOML，不含密钥）"
```

---

## Task 8: 前端 DOM 测试基建 + 钉住 M5 的两个缺陷

**为什么在 M6 而不是 M7**（终审原话是「M7 做干预 UI 时一并上」，这里改判）：

> M6 自己要新增**四个配置页**（群 / 人 / LLM / 类目），它们全是「**提交 → 重取**」这**同一种**模式——正是 M5 那两个缺陷的温床。基建晚一个里程碑上，等到的就是同一类缺陷在四个新页面上重演一遍，而新页面同样**零测试保护**。

**M5 那两个缺陷是什么**（终审 A-Minor-7，T10 在浏览器里抓到的，修好了但无保护）：

| # | 缺陷 | 修法 | 为什么它是这一类模式的原型 |
|---|---|---|---|
| 1 | `onMutated={retry}` **导致删了还在** | 改成 `reload()`（重跑第一页） | `retry()` 在「列表里还有数据」时走的是 `loadMore()`——那是**往后追加**，追加**不会刷新屏幕上那条已经变了的条目**。`Feed.tsx:134-143` 有完整论证。 |
| 2 | `undo()` **不通知重取** | 成功后 `setDataTick(t => t + 1)` | 撤销改的是库的有效状态，而 `Feed` 手里那份是旧快照。不给它发信号，条目不会回到屏幕上，用户会**以为撤销没生效、再点一次**，把上一步也撤掉。 |

**Files:**
- Modify: `web/package.json`（3 个 devDependencies）
- Modify: `web/vite.config.ts`（`test` 段）
- Create: `web/src/test-setup.ts`
- Create: `web/src/__tests__/Feed.dom.test.tsx`
- Create: `web/src/__tests__/App.dom.test.tsx`

**Interfaces:**
- Consumes: 无（本任务不改产品代码——**只加测试基建**。若某条测试为了通过而要求改产品代码，**停下报告**：那说明 M5 的修复有缺口。）
- Produces: `web/src/test-setup.ts`（T9 的新页面测试直接复用）；一个可复制的「假 fetch」范式（见下）

---

- [ ] **Step 1: 装依赖**

```bash
cd web
npm install -D @testing-library/react@^16 @testing-library/user-event@^14 jsdom
```

⚠️ **已核实**：这三个**确实不在** `web/package.json` 里（M5 终审复核过），所以这一步是真的新增依赖，不是"应该已经有了"。
⚠️ 装完把 `package.json` 与 `package-lock.json` **一起提交**（只提交前者会让 CI/另一台机器装出不一致的树）。

- [ ] **Step 2: 配 vitest**

`web/vite.config.ts` —— 在 `defineConfig({...})` 的顶层加 `test` 段：

```ts
  // ⚠️ `environment: 'jsdom'` 是**全局**的（不是只给 DOM 用例）。
  // Vitest 3+ 已把 `environmentMatchGlobs` 标记为弃用、改用 projects/workspace，
  // 而本仓的 vitest 是 5.0.1 —— 与其赌一个具体 API，不如全局开 jsdom：
  // 既有的 `api.test.ts` / `format.test.ts` 是纯逻辑，在 jsdom 下照样跑，
  // 代价是每次多初始化一个 DOM，对本仓 22 条用例完全可忽略。
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
  },
```

⚠️ `defineConfig` 要从 `vitest/config` 导入才能认 `test` 段（`import { defineConfig } from 'vitest/config'`）——**而 `vite` 的 `defineConfig` 不认它**（在 TS 上不报错、运行时被忽略，于是测试跑在 node 环境里、`document is not defined`）。这一步必须改 import 来源。

`web/src/test-setup.ts`：

```ts
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// ⚠️ 必须显式 cleanup：`@testing-library/react` 只在检测到**全局** `afterEach`
// 时才自动清理，而本仓的 vitest 没开 `globals: true`。
// 没有这一句，第二个用例会看到第一个用例留在 document 里的节点，
// `screen.getByText` 于是报「找到多个元素」——**那条失败与被测行为毫无关系**，
// 而它长得像产品缺陷。本项目在 `data/vigil.lock` 上吃过同一形状的亏
// （见 `tests/conftest.py::_isolate_lock_path` 的 docstring）。
afterEach(cleanup)
```

- [ ] **Step 3: 写 `web/src/__tests__/Feed.dom.test.tsx`（缺陷 1 的守卫）**

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import Feed from '../views/Feed.tsx'
import type { Item } from '../types.ts'

const ITEM: Item = {
  item_id: 7,
  kind: 'notice',
  kind_label: '通知公告',
  kind_icon: '📋',
  title: '周三停水',
  detail: null,
  event_ts: 1_700_000_000,
  deadline_ts: null,
  group_id: 111,
  group_name: '甲群',
  actor: null,
  actor_uin: null,
  place: null,
  amount: null,
  links: [],
  source_count: 1,
}

type Call = { url: string; method: string }

/**
 * 装一个**有状态**的假 fetch。
 *
 * ⚠️ 必须 mock 全局 `fetch` 而**不是** mock `../api.ts`：本文件要钉的缺陷
 * 恰恰是「**组件有没有再发一次请求、请求长什么样**」。
 * mock 掉 api 层就把被测的那一层换掉了，测试会退化成
 * 「我 mock 的函数被我调用了」——与真实行为无关（M4「设置对了 ≠ 行为对了」同族）。
 */
function installFetch(initial: Item[]) {
  let alive = [...initial]
  const calls: Call[] = []

  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      calls.push({ url, method })

      const ok = (body: unknown) => ({
        ok: true,
        status: 200,
        json: async () => body,
      })

      if (url.startsWith('/api/categories')) {
        return ok({ categories: [{ slug: 'notice', label: '通知公告', icon: '📋', count: 1, desc: 'x' }] })
      }
      if (url.startsWith('/api/persons')) return ok({ persons: [] })
      if (method === 'DELETE' && url.startsWith('/api/items/')) {
        alive = []
        return ok({ edit_id: 1 })
      }
      if (url.startsWith('/api/items/')) return ok({ ...ITEM, sources: [] })
      if (url.startsWith('/api/items')) {
        return ok({ items: alive, total: alive.length, limit: 50, offset: 0 })
      }
      return ok({})
    }),
  )
  return calls
}

afterEach(() => vi.unstubAllGlobals())

test('删掉一条之后，它必须从列表里消失（而不是被"往后追加"留在原地）', async () => {
  /**
   * ⭐ M5 A-Minor-7 缺陷 1 的守卫。
   *
   * ⚠️ 两个断言**都要有**，它们钉的是两件不同的事：
   *   ① 「条目消失」——用户看到的结果；
   *   ② 「重取的请求里没有 offset」——机制。
   * 只有 ① 的话，一个「删完把本地 state 摘掉」的实现也能绿，
   * 而那种实现遇到分页/撤销就会错；只有 ② 的话，请求对了但渲染没跟上照样绿。
   *
   * ⚠️ 变异反证：把 `Feed.tsx` 里的 `onMutated={reload}` 改回
   * `onMutated={retry}` ⇒ 本条**必红**（`retry()` 会走 `loadMore()`，
   * 而它带 `offset=1`，删掉的条目仍留在列表里）。
   */
  const calls = installFetch([ITEM])
  render(
    <Feed kinds={[]} onKinds={() => {}} persons={[]} onPersons={() => {}} reloadSignal={0} />,
  )

  expect(await screen.findByText('周三停水')).toBeTruthy()
  await userEvent.click(screen.getByRole('button', { name: '删除' }))

  await waitFor(() => {
    expect(screen.queryByText('周三停水')).toBeNull()
  })

  const after = calls.filter((c) => c.url.startsWith('/api/items'))
  const last = after[after.length - 1]
  expect(last.url).not.toContain('offset'), (
    '删除后的重取带了 offset——那是 loadMore 的追加语义，' +
    '它不会刷新屏幕上那条已经变了的条目（M5 实测的两个缺陷之一）'
  )
})
```

- [ ] **Step 4: 写 `web/src/__tests__/App.dom.test.tsx`（缺陷 2 的守卫）**

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import App from '../App.tsx'

type Call = { url: string; method: string }

function installFetch(undoResult: boolean) {
  const calls: Call[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      calls.push({ url, method: init?.method ?? 'GET' })
      const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
      if (url.startsWith('/api/undo')) return ok({ undone: undoResult })
      if (url.startsWith('/api/categories')) return ok({ categories: [] })
      if (url.startsWith('/api/persons')) return ok({ persons: [] })
      if (url.startsWith('/api/items')) return ok({ items: [], total: 0, limit: 50, offset: 0 })
      return ok({})
    }),
  )
  return calls
}

afterEach(() => vi.unstubAllGlobals())

test('撤销成功后必须让筛选列表重取一次', async () => {
  /**
   * ⭐ M5 A-Minor-7 缺陷 2 的守卫。
   *
   * ⚠️ 变异反证：把 `App.tsx` 的 `if (r.undone) setDataTick((t) => t + 1)`
   * 删掉 ⇒ 本条**必红**。
   */
  const calls = installFetch(true)
  render(<App />)
  await waitFor(() =>
    expect(calls.some((c) => c.url.startsWith('/api/items'))).toBe(true),
  )
  const before = calls.filter((c) => c.url.startsWith('/api/items')).length

  await userEvent.click(screen.getByRole('button', { name: /撤销/ }))

  await waitFor(() => {
    expect(calls.filter((c) => c.url.startsWith('/api/items')).length).toBeGreaterThan(before)
  }, { timeout: 2000 })
})

test('撤销**没撤成**时不许白白重取一次（阴性对照）', async () => {
  /**
   * ⭐ 这条是上一条的**阴性对照**，缺了它上一条就没有说服力。
   *
   * ⚠️ 没有它的话，「无条件 `setDataTick`」这个实现照样能让上一条绿——
   * 而那样每次点「撤销」都会白拉一次列表，包括栈空的时候
   * （而栈空恰恰是最常被点到的状态：用户点一下看看有没有东西可撤）。
   * 这与本项目「假绿」的判据是同一条：**一个只在"应该发生"时才发生的守卫，
   * 必须同时验"不该发生时它没发生"。**
   */
  const calls = installFetch(false)
  render(<App />)
  await waitFor(() =>
    expect(calls.some((c) => c.url.startsWith('/api/items'))).toBe(true),
  )
  const before = calls.filter((c) => c.url.startsWith('/api/items')).length

  await userEvent.click(screen.getByRole('button', { name: /撤销/ }))
  expect(await screen.findByText('没有可撤销的操作')).toBeTruthy()

  await new Promise((r) => setTimeout(r, 300))
  expect(calls.filter((c) => c.url.startsWith('/api/items')).length).toBe(before)
})
```

- [ ] **Step 5: 跑测试**

```bash
cd web && npm test
```

Expected: **22 + 3 = 25 passed**。
⚠️ 新增的三条**必须真跑**（不是 skip）。若 jsdom 装不上或 `vitest/config` 的 import 没改对，先修环境，**不许 `test.skip`**——跳过之后这三条会变成"看起来有、其实没人跑"的空守卫。

- [ ] **Step 6: 构建验证**

```bash
cd web && npm run build
```

Expected: 成功。⚠️ `tsc -b` 会检查 `.tsx` 测试文件的类型——`@testing-library/react` 的类型若与 React 19 的 `@types/react` 冲突，**在这里就会现形**（而不是在 `npm test` 里）。

- [ ] **Step 7: 后端回归（确认没被前端改动波及）**

Run: `uv run pytest`
Expected: 与 T7 结束时相同

- [ ] **Step 8: Commit**

```bash
git add web/package.json web/package-lock.json web/vite.config.ts web/src/test-setup.ts web/src/__tests__/Feed.dom.test.tsx web/src/__tests__/App.dom.test.tsx
git commit -m "test(web): 引入 jsdom + testing-library，钉住 M5 那两个零保护的前端缺陷"
```

---

## Task 9: 前端 —— 配置界面

**范围（spec §4.2 ③④）**：一个「配置」tab，四节——**群 / 人物 / LLM / 类目**，外加**导入导出**。

**⚠️ 三条界面上的硬要求（都有具体理由，不是美观问题）**：

| 要求 | 理由 |
|---|---|
| 新增群时必须显示「**下次 export 会拉全量历史**」的提示，并给出代价数字 | spec §4.2 ③ 原文要求。首轮实测：**1,664 条 / 21 批 / 6.3 分钟**——不说的后果是用户加了个万人大群，然后以为程序卡死了。 |
| 群清单要显示**快照生成时刻**与 `available` | 快照是 CLI 预生成的产物，**会过期**。不显示时刻的话，用户会拿一份三天前的清单做决定。 |
| 删类目时**必须先显示「有 N 条属于它」并要求选一个迁移目标** | spec 出口判据 6 原文：「不允许静默留下指向不存在 slug 的条目」。N 由后端算好交上来（`/api/categories` 的 `count`）。 |

**Files:**
- Create: `web/src/views/Settings.tsx`
- Modify: `web/src/types.ts`, `web/src/api.ts`, `web/src/App.tsx`
- Create: `web/src/__tests__/Settings.dom.test.tsx`

**Interfaces:**
- Consumes: T4 的 `/api/groups`（含 `available`/`generated_at`/`watched`/`known`）、T5 的 `/api/categories`（新增 `desc` 与 `aliases`）与 `/api/categories/undo`、T3 的 `config/llm.toml`、T6 的 `/api/reorder` + `/api/jobs/{id}`、T7 的 `/api/config/pack`、T8 的 `test-setup.ts`
- Produces: `App.tsx` 的 `Tab` 联合类型加一项 `'settings'`

---

- [ ] **Step 1: 扩 `web/src/types.ts`**

```ts
/** 一个 QQ 本地库里的群（**来自 CLI 预生成的快照**，不是实时查询）。 */
export type GroupRow = {
  id: number
  name: string
  /** 该群在 QQ 库里的**全量**历史消息条数（不是已导出的）。 */
  messages: number
  last_ts: number
  /** 已纳入且 **enabled**。 */
  watched: boolean
  /** 已纳入但可能被停用。 */
  known: boolean
}

export type GroupsResponse = {
  /**
   * ⚠️ `false` = **还没有快照**，此时 `reason` 一定非空、`groups` 一定是空数组。
   * 界面**必须**把这两件事分开显示：「一个群都没有」与「还没读过」是两句不同的话，
   * 混起来说的后果是用户以为自己的 QQ 库是空的。
   */
  available: boolean
  reason: string
  generated_at: number | null
  groups: GroupRow[]
}

export type CategoryDetail = Category & {
  /** 类目判据，会**逐字**进提示词。编辑器必须能改它。 */
  desc: string
}

export type CategoriesResponse = {
  categories: CategoryDetail[]
  /** `{旧 slug: 新 slug}` —— 改过名的类目在这里留痕。 */
  aliases: Record<string, string>
}

export type LlmSettings = {
  base_url: string
  model: string
  /** `null` = **不发这个字段**（通用 OpenAI 端点最安全的形状）。 */
  enable_thinking: boolean | null
}

export type JobRow = {
  job_id: string
  kind: string
  state: 'running' | 'done' | 'failed' | 'cancelled'
  total: number
  done: number
  message: string
  error: string
  actor: string
  started_at: number
  finished_at: number | null
}
```

- [ ] **Step 2: 扩 `web/src/api.ts`**

```ts
export const fetchGroups = () => getJSON<GroupsResponse>('/api/groups')

export const addGroup = (id: number, name: string, tier: string) =>
  sendJSON<{ id: number }>('/api/groups', 'POST', { id, name, tier })

export const patchGroup = (
  id: number,
  patch: { name?: string; enabled?: boolean; tier?: string },
) => sendJSON<{ id: number }>(`/api/groups/${id}`, 'PATCH', patch)

export const removeGroup = (id: number) => sendJSON<void>(`/api/groups/${id}`, 'DELETE')

export const fetchCategoriesDetailed = () =>
  getJSON<CategoriesResponse>('/api/categories')

export const addCategory = (slug: string, label: string, desc: string, icon: string) =>
  sendJSON<{ slug: string }>('/api/categories', 'POST', { slug, label, desc, icon })

export const updateCategory = (
  slug: string,
  body: { slug?: string; label?: string; desc?: string; icon?: string },
) => sendJSON<{ slug: string }>(`/api/categories/${slug}`, 'PUT', body)

export const removeCategory = (slug: string, migrateTo?: string) =>
  sendJSON<void>(
    `/api/categories/${encodeURIComponent(slug)}` +
      (migrateTo ? `?migrate_to=${encodeURIComponent(migrateTo)}` : ''),
    'DELETE',
  )

export const undoCategorieChange = () =>
  sendJSON<{ undone: boolean }>('/api/categories/undo', 'POST')

export const fetchLlmSettings = () => getJSON<LlmSettings>('/api/llm')

export const saveLlmSettings = (s: LlmSettings) =>
  sendJSON<LlmSettings>('/api/llm', 'PUT', s)

export const startReorder = () =>
  sendJSON<JobRow>('/api/reorder', 'POST')

export const fetchJob = (jobId: string) => getJSON<JobRow>(`/api/jobs/${jobId}`)

export const undoJob = (jobId: string) =>
  sendJSON<{ undone: boolean; count: number }>(`/api/jobs/${jobId}/undo`, 'POST')

export const exportPack = () => getJSON<{ toml: string }>('/api/config/pack')

export const importPack = (toml: string, apply: boolean, keepSettings: boolean) =>
  sendJSON<Record<string, unknown>>('/api/config/pack', 'POST', {
    toml,
    apply,
    keep_settings: keepSettings,
  })
```

⚠️ **`/api/llm` 两个端点在 T3 里还没实现**——它们属于本任务。补进 `vigil/api.py`：

```python
    @app.get("/api/llm")
    def api_get_llm() -> dict:
        """读 LLM 端点配置。**永远不返回密钥**（它不在这份配置里，spec §3.2）。"""
        s = load_llm_settings()
        return {
            "base_url": s.base_url,
            "model": s.model,
            "enable_thinking": s.enable_thinking,
        }

    @app.put("/api/llm")
    def api_put_llm(body: dict = Body(...)) -> dict:
        base_url = str(body.get("base_url", "")).strip()
        model = str(body.get("model", "")).strip()
        if not base_url or not model:
            raise HTTPException(status_code=400, detail="base_url 与 model 都不能为空")
        if not base_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="base_url 必须以 http:// 或 https:// 开头")
        _reject_controls(base_url, "base_url")
        _reject_controls(model, "model")

        raw_thinking = body.get("enable_thinking")
        if raw_thinking is None:
            thinking = None
        elif isinstance(raw_thinking, bool):
            thinking = raw_thinking
        else:
            raise HTTPException(
                status_code=400,
                detail="enable_thinking 只能是 true / false / null（null = 不发这个字段）",
            )
        with write_lock:
            save_llm_settings(
                config_mod.LLMSettings(
                    base_url=base_url, model=model, enable_thinking=thinking
                ),
                llm_path(),
            )
        return {"base_url": base_url, "model": model, "enable_thinking": thinking}
```

加闭包：
```python
    def llm_path() -> pathlib.Path:
        return REPO_ROOT / "config" / "llm.toml"
```

⚠️ **`/api/llm` 在 D11 的允许列表里**：它写的是 `config/llm.toml`，属于「Web 可写 `config/`」。T4 那条「`data/` 下不许多文件」的守卫**不受影响**（它只看 `data/`）。

- [ ] **Step 3: 写 `web/src/views/Settings.tsx`**

⚠️ **这是一份骨架 + 关键实现**。四节各自是一个内部组件，**共用一个 `refreshToken`**——「提交 → 重取」的模式在四个页面里必须**一致**，否则就是 M5 那两个缺陷换个页面重演。

```tsx
import { useEffect, useState } from 'react'
import type { CategoryDetail, GroupRow, JobRow, LlmSettings } from '../types.ts'
import * as api from '../api.ts'

type Section = 'groups' | 'persons' | 'llm' | 'categories' | 'pack'

const SECTIONS: { key: Section; label: string }[] = [
  { key: 'groups', label: '群' },
  { key: 'persons', label: '人物' },
  { key: 'llm', label: 'LLM' },
  { key: 'categories', label: '类目' },
  { key: 'pack', label: '导入导出' },
]

export default function Settings() {
  const [section, setSection] = useState<Section>('groups')
  // ⚠️ 每个子组件自己持有数据与自己的 refresh；**不共用一个全局 token**——
  // 那会让"改了一个群"顺带重取四个页面的数据，而其中三个的数据没变。
  return (
    <div>
      <div className="flex flex-wrap gap-1.5">
        {SECTIONS.map((s) => (
          <button
            key={s.key}
            onClick={() => setSection(s.key)}
            className={
              'rounded-full px-3 py-1 text-xs ' +
              (section === s.key ? 'bg-sky-500/20 text-sky-300' : 'bg-white/5 text-white/55')
            }
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="mt-4">
        {section === 'groups' && <GroupsSection />}
        {section === 'persons' && <PersonsSection />}
        {section === 'llm' && <LlmSection />}
        {section === 'categories' && <CategoriesSection />}
        {section === 'pack' && <PackSection />}
      </div>
    </div>
  )
}
```

**`GroupsSection`**（本任务最要紧的一节）：

```tsx
function GroupsSection() {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.fetchGroups>> | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const [id, setId] = useState('')
  const [name, setName] = useState('')
  const [msg, setMsg] = useState<string | null>(null)

  useEffect(() => {
    setErr(null)
    api.fetchGroups().then(setData).catch((e) => {
      setErr(e instanceof Error ? e.message : String(e))
      setData(null)
    })
  }, [tick])

  async function submit() {
    setMsg(null)
    const n = Number(id.trim())
    if (!Number.isInteger(n) || n <= 0) {
      setMsg('群号必须是正整数')
      return
    }
    try {
      await api.addGroup(n, name.trim(), 'normal')
      setMsg(`已加入 ${n}。⚠️ 下次 vigil export 会拉它的**全部历史**——首轮实测大群约 1,664 条 / 21 批 / 6.3 分钟。`)
      setId(''); setName('')
      setTick((t) => t + 1)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    }
  }

  if (err !== null) return <p className="text-sm text-red-400">读取失败：{err}</p>
  if (data === null) return <p className="text-sm text-white/40">读取中…</p>

  // ⚠️ **没有快照时明说**，绝不画一张空表：空表会被读成
  // 「你的 QQ 库里一个群都没有」——一句假话（与后端 `available:false` 同一条判据）。
  if (!data.available) {
    return (
      <div className="rounded-lg bg-amber-500/10 p-3 text-sm text-amber-200">
        <p>{data.reason}</p>
      </div>
    )
  }

  return (
    <div>
      <p className="text-xs text-white/40">
        清单来自 {new Date(data.generated_at! * 1000).toLocaleString('zh-CN')} 的快照
        （由 vigil export 生成）。刚加进 QQ 的群要等下次 export 才看得见。
      </p>
      <ul className="mt-3 space-y-1">
        {data.groups.map((g) => (
          <GroupRowView key={g.id} g={g} onChanged={() => setTick((t) => t + 1)} />
        ))}
      </ul>
      <div className="mt-4 flex flex-wrap gap-2">
        <input value={id} onChange={(e) => setId(e.target.value)} placeholder="群号"
               className="w-32 rounded-lg bg-white/5 px-2 py-1.5 text-sm" />
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="群名"
               className="flex-1 rounded-lg bg-white/5 px-2 py-1.5 text-sm" />
        <button onClick={submit} className="rounded-lg bg-sky-500/20 px-3 py-1.5 text-sm text-sky-200">
          加入监视
        </button>
      </div>
      {msg !== null && <p className="mt-2 text-xs text-white/60">{msg}</p>}
    </div>
  )
}

function GroupRowView({ g, onChanged }: { g: GroupRow; onChanged: () => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setErr(null)
    try { await fn(); onChanged() }
    catch (e) { setErr(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }

  return (
    <li className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2 text-sm">
      <span className="flex-1 truncate">
        {g.name || '(无名)'} <span className="text-white/40">{g.id}</span>
        <span className="ml-2 text-xs text-white/40">{g.messages.toLocaleString()} 条</span>
      </span>
      {g.watched ? (
        <>
          <button disabled={busy}
                  onClick={() => act(() => api.patchGroup(g.id, { enabled: false }))}
                  className="rounded px-2 py-1 text-xs text-white/50">
            停用
          </button>
          <button disabled={busy} onClick={() => act(() => api.removeGroup(g.id))}
                  className="rounded px-2 py-1 text-xs text-red-300">
            移除
          </button>
        </>
      ) : (
        <button disabled={busy} onClick={() => act(() => api.addGroup(g.id, g.name, 'normal'))}
                className="rounded px-2 py-1 text-xs text-sky-300">
          加入监视
        </button>
      )}
      {err !== null && <span className="text-xs text-red-400">{err}</span>}
    </li>
  )
}
```

**`CategoriesSection`**（出口判据 6 的界面形态）：

```tsx
function CategoriesSection() {
  const [cats, setCats] = useState<CategoryDetail[]>([])
  const [aliases, setAliases] = useState<Record<string, string>>({})
  const [tick, setTick] = useState(0)
  const [msg, setMsg] = useState<string | null>(null)
  // ⚠️ 「有 N 条属于它，迁移到哪个？」——**必须是一个真的选择**，
  // 不是一个 `window.confirm`（那没法让用户挑目标类目）。
  const [pending, setPending] = useState<CategoryDetail | null>(null)
  const [migrateTo, setMigrateTo] = useState('')

  useEffect(() => {
    api.fetchCategoriesDetailed()
      .then((r) => { setCats(r.categories); setAliases(r.aliases) })
      .catch((e) => setMsg(e instanceof Error ? e.message : String(e)))
  }, [tick])

  async function doDelete() {
    if (pending === null) return
    try {
      await api.removeCategory(pending.slug, migrateTo || undefined)
      setMsg(`已删除「${pending.label}」` + (migrateTo ? `，${pending.count} 条已并入「${migrateTo}」` : ''))
      setPending(null); setMigrateTo('')
      setTick((t) => t + 1)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div>
      <ul className="space-y-1">
        {cats.map((c) => (
          <li key={c.slug} className="flex items-center gap-2 rounded-lg bg-white/5 px-3 py-2 text-sm">
            <span>{c.icon} {c.label}</span>
            <span className="text-xs text-white/40">{c.slug} · {c.count} 条</span>
            <button className="ml-auto rounded px-2 py-1 text-xs text-white/50"
                    onClick={() => { setPending(c); setMigrateTo('') }}>
              删除
            </button>
          </li>
        ))}
      </ul>

      {pending !== null && (
        <div className="mt-3 rounded-lg bg-amber-500/10 p-3 text-sm text-amber-100">
          {pending.count > 0 ? (
            <>
              <p>⚠️ 「{pending.label}」还有 **{pending.count} 条**条目指着它。删之前必须选一个迁移目标——否则那些条目会指向一个不存在的类目。</p>
              <select value={migrateTo} onChange={(e) => setMigrateTo(e.target.value)}
                      className="mt-2 rounded-lg bg-black/30 px-2 py-1 text-sm">
                <option value="">— 选一个 —</option>
                {cats.filter((c) => c.slug !== pending.slug).map((c) => (
                  <option key={c.slug} value={c.slug}>{c.icon} {c.label}</option>
                ))}
              </select>
            </>
          ) : (
            <p>「{pending.label}」下没有任何条目，可以直接删除。</p>
          )}
          <div className="mt-2 flex gap-2">
            <button onClick={doDelete} disabled={pending.count > 0 && !migrateTo}
                    className="rounded-lg bg-red-500/20 px-3 py-1 text-xs text-red-200 disabled:opacity-40">
              确认删除
            </button>
            <button onClick={() => setPending(null)}
                    className="rounded-lg bg-white/5 px-3 py-1 text-xs text-white/60">
              取消
            </button>
          </div>
        </div>
      )}

      {Object.keys(aliases).length > 0 && (
        <p className="mt-3 text-xs text-white/40">
          改过名的类目：{Object.entries(aliases).map(([o, n]) => `${o} → ${n}`).join('、')}
        </p>
      )}
      <button onClick={() => api.undoCategorieChange().then(() => setTick((t) => t + 1))}
              className="mt-3 rounded-lg bg-white/5 px-3 py-1.5 text-xs text-white/60">
        ↶ 撤销上一次类目改动
      </button>
      {msg !== null && <p className="mt-2 text-xs text-white/60">{msg}</p>}
    </div>
  )
}
```

**`PersonsSection`**：现有 `PersonPicker.tsx` 已经覆盖了「加人 / 删人」，本节的正确做法是**复用它**（`<PersonPicker selected={[]} onChange={() => {}} />` 的展示形态不匹配，所以照抄它的请求与表单**但要单独实现**）。⚠️ **实施时先读 `PersonPicker.tsx`**，能抽公共子组件就抽，抽不动就照抄并**在报告里说明为什么**。

**`LlmSection`**：三个字段 + 一个 `enable_thinking` 三态选择器：

```tsx
const THINKING_CHOICES = [
  { value: 'omit', label: '不发这个字段（通用 OpenAI 端点用这个）' },
  { value: 'false', label: '发 false（硅基流动 / Qwen 用这个）' },
  { value: 'true', label: '发 true' },
] as const
```

**`PackSection`**：导出一个 `<textarea readOnly>` 显示 TOML，一个「下载」按钮（`Blob` + `URL.createObjectURL`），一个 `<input type="file">` + `FileReader.readAsText` 导入，一个「保留本机路径」复选框，一个「先校验不写入」按钮。

- [ ] **Step 4: `App.tsx` 加 tab**

```tsx
type Tab = 'feed' | 'cats' | 'digests' | 'settings'

const TABS: { key: Tab; label: string }[] = [
  { key: 'feed', label: '信息流' },
  { key: 'cats', label: '类目' },
  { key: 'digests', label: '日报' },
  { key: 'settings', label: '配置' },
]
```

并在 `<main>` 里加 `{tab === 'settings' && <Settings />}`。

- [ ] **Step 5: 写 `web/src/__tests__/Settings.dom.test.tsx`**

```tsx
test('没有群快照时必须显示原因，而不是一张空表', async () => {
  /**
   * ⭐ 「一个群都没有」与「还没读过」是**两句不同的话**。
   *
   * ⚠️ 变异反证：让 `GroupsSection` 在 `!available` 时照样渲染
   * `<ul>`（拿到一个空 `groups` 就画空表）⇒ 本条**必红**。
   * ⚠️ 这条与后端 `groups_snapshot.load` 返回 `None` 时的行为是一对——
   * 两边都守，是因为界面**完全可能**忽略那个字段（它只是个布尔）。
   */
  ...
})

test('删类目时未知条目数就必须要求选择迁移目标', async () => {
  /**
   * ⭐ 出口判据 6 的界面形态。⚠️ 变异反证：把「确认删除」按钮的
   * `disabled={pending.count > 0 && !migrateTo}` 去掉 ⇒ 本条**必红**。
   */
  ...
})
```

⚠️ 这两条的完整实现**照抄 T8 Step 3 的 `installFetch` 范式**（同一个「假 fetch + 记 calls」骨架）。

- [ ] **Step 6: 跑测试 + 构建**

```bash
cd web && npm test && npm run build
```

Expected: 全部 PASS、构建成功

- [ ] **Step 7: ⭐ 真跑一次（**不能只跑测试**）**

```bash
cd D:/github/VIGIL && uv run vigil export   # 生成群清单快照
cd web && npm run build
cd D:/github/VIGIL && uv run vigil serve --host 127.0.0.1 --port 8787
```

浏览器打开 `http://127.0.0.1:8787` → 「配置」tab，逐项走一遍出口判据 1 与 6：

| 走法 | 期望 |
|---|---|
| 群节 → 加一个真群号 → **刷新页面** | 它还在（判据 1：重启后仍在） |
| 人物节 → 加一个真人 uin → 刷新 | 它还在 |
| 类目节 → 加一个类目 → 刷新 | 它还在，且信息流的类目筛选里**立刻**出现它 |
| 类目节 → 删一个有 count 的类目 | **弹「还有 N 条」并要求选迁移目标**；不选则按钮点不动 |
| 选好目标 → 确认 | 那个类目的条目在**信息流**里显示成新类目（判据 6：不留悬空 slug） |
| 导入导出节 → 导出 | textarea 里有完整 TOML，**且里面没有 `sk-` 开头的任何串** |

⚠️ **实测结果（含截图路径或逐条粘贴的输出）必须写进报告**。只跑 `npm test` 而没真开过浏览器的话，判据 1/6 的「真跑」那部分**没有证据**。

- [ ] **Step 8: 后端回归**

Run: `uv run pytest`

- [ ] **Step 9: Commit**

```bash
git add web/src/views/Settings.tsx web/src/types.ts web/src/api.ts web/src/App.tsx web/src/__tests__/Settings.dom.test.tsx vigil/api.py
git commit -m "feat(web,api): 配置界面（群/人物/LLM/类目/导入导出）+ /api/llm 端点"
```

---

## Task 10: M5 遗留清理

**来源**：M5 终审那张「留下一里程碑」表 + `deferred-minors.md`。**逐条给了理由**，包括**不做**的那几条——一个被静默丢掉的 finding 会在下一个里程碑以同样的形状回来。

**⚠️ 已经在本轮前面收掉的**（不要再做一遍）：#19 `uin` 注入 / #20 `uid` 无用例 / #22 `uin = true` → **T2**；`T10` 两个前端缺陷零保护 → **T8**；`_apply_to_state` 未知 action → 本任务（T10）。

| 条目 | 判定 |
|---|---|
| **#4** 时序闸门不计入 `deadlines_dropped` | ✅ **做**（本任务最实的一条） |
| **F1** `refine.py` 墓碑跳过行排在早退之后 | ✅ **做** |
| **#7** 进度话术用去重前条数 | ✅ **做**（一行） |
| **#23** `-shm` 应从 D11 哈希断言去掉 | ✅ **做**（潜伏假红） |
| **#25** `label` 先 strip 再查控制字符 | ✅ **做** |
| **#9** `_apply_to_state` 未知 action 静默忽略 | ✅ **做** |
| **#10** `test_overrides.py:127` 弱断言 | ✅ **做** |
| **#30** `deadline-audit` 刻意不接 overlay 无用例 | ✅ **做** |
| **#15** `undo` 成功路径仍 `conn.commit()` | ⛔ **不做**——终审原文「`delete_item` 已刻意逐事件提交规避它；`apply_plan` 也接受了『部分软删可撤销』。**留下有据**」。T6 的 `undo_batch` 用 `rebuild_state` + 一次 commit，不经过这条路径。 |
| **#24 / #29** 注释里的行号指错树 | ⛔ **不做**——纯注释。若实施时顺手碰到那两行，改掉即可；**不为它单开一步**。 |

**Files:**
- Modify: `vigil/refine.py`, `vigil/cli.py`, `vigil/api.py`, `vigil/overrides.py`
- Modify: `tests/test_refine.py`, `tests/test_api.py`, `tests/test_overrides.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: 全部既有模块
- Produces：
  - `refine.RefineStats.deadlines_backdated: int` —— 新增字段
  - `refine._verify_deadlines(produced, batch) -> tuple[list[ExtractedItem], int, int]` —— **返回值多一项**（`(out, dropped_unsupported, dropped_backdated)`）

---

- [ ] **Step 1: #4 —— 把时序闸门挪到写入边界，并给它一个计数器**

**问题的确切断面**（实测行号）：`deadline_sane` 在 `refine.py:334-335` 被调用，位置在 **`_to_item` 内部**；而计数的 `deadlines_dropped` 在 `refine.py:367-372` 的 `_verify_deadlines` 里，**只管 `deadline_supported` 那道闸**。于是：

> 一批里模型给出 12 条**过期死线**（`item 83` 的形状：死线 `2026-05-06`、消息日 `2026-08-05`）⇒ 全被清成 `None`，而 `cli.py:314` 那句「**[注意] N 条截止日在源消息里找不到字面依据**」**永远不为它响**。运维零告警。

**修法（两步，顺序不能反）**：

**1a.** 删掉 `_to_item` 里那两行（`refine.py:334-335`）：

```python
    deadline_ts = _parse_deadline(raw.get("deadline"))
    if deadline_ts is not None and not deadline_sane(deadline_ts, source.ts):
        deadline_ts = None
```

改成只留解析：

```python
    deadline_ts = _parse_deadline(raw.get("deadline"))
    # ⚠️ **时序闸门（`deadline_sane`）不在这里**，见 `_verify_deadlines`。
    # 挪走的理由不是洁癖：闸门留在 `_to_item` 里时，它清掉的值**没有任何
    # 计数器**——`stats.deadlines_dropped` 只数 `deadline_supported` 那道闸。
    # 后果是「一批 12 条过期死线被全清」在运维侧**零告警**（M5 遗留 #4）。
    # 两道闸现在并排站在写入边界上，谁都能一眼看全。
```

**1b.** `_verify_deadlines` 加上第二道闸与第二个计数器：

```python
def _verify_deadlines(
    produced: list[store.ExtractedItem], batch
) -> tuple[list[store.ExtractedItem], int, int]:
    """写入前核验：两道闸，各自记数。

    ⚠️ 核验放在**写入边界**而不是渲染层：数据一旦入库就到处流，每个读取方
    各挡一次，迟早有人忘——M2 就只在日报挡过，M3 的 Web 差一点把那 13 条
    幻觉日期原样复活（「今天下午16点之前」被填成 9-14、「明早7:20」被填成 9-15）。

    ⚠️ 只降级 `deadline_ts` 这一个字段：条目的标题、正文、来源一概不动。
    用户仍然看得到这条信息，只是不再被告知一个编出来的日期。

    **两道闸的区别**（M6 T10 把它们并排放在这里）：
      * `deadline_supported` —— 源文里**找不到字面依据**（模型编的）
      * `deadline_sane`      —— 字面有依据，但**死线早于消息时间**（已过期三个月的「⏰ 别忘」）

    ⚠️ 分开计数是**承重的**：两者的运维含义完全不同——前者说明模型在编，
    后者说明**提示词或数据源有问题**（为什么会有三个月前的死线被当成新的？）。

    **返回值**：`(核验后的条目, 无依据的条数, 时序倒挂的条数)`。
    """
    texts = {m.msg_id: (m.content or "") for m in batch}
    ts_by_msg = {m.msg_id: m.ts for m in batch}
    out: list[store.ExtractedItem] = []
    unsupported = 0
    backdated = 0
    for it in produced:
        if it.deadline_ts and not deadline_supported(
            it.deadline_ts, "\n".join(texts.get(mid, "") for mid in it.src_msg_ids)
        ):
            unsupported += 1
            it = replace(it, deadline_ts=None)
        elif it.deadline_ts:
            # ⚠️ `elif` 而不是第二个 `if`：一条已经被判「无依据」的截止日
            # **不该再计一次**时序倒挂——那会让两个数加起来大于被清的总数，
            # 而运维看到「2 条被清」+「2 条被清」却只有 2 条条目时会怀疑账目。
            # ⚠️ 源消息的 ts 取**最早**的那条（一条 item 可以有多条源消息）：
            # 死线必须晚于**它出现的最早时刻**才算合理，取最晚的会放过一批。
            srcs = [ts_by_msg[mid] for mid in it.src_msg_ids if mid in ts_by_msg]
            if srcs and not deadline_sane(it.deadline_ts, min(srcs)):
                backdated += 1
                it = replace(it, deadline_ts=None)
        out.append(it)
    return out, unsupported, backdated
```

**1c.** `RefineStats` 加字段（`refine.py:48` 附近）：

```python
    deadlines_dropped: int = 0   # 源文里找不到依据、被降级的截止日条数
    # ⚠️ 与上一个分开（M6 T10 / M5 遗留 #4）：那个是「模型在编」，
    # 这个是「死线早于消息时间」——运维含义完全不同，合成一个数会让两者
    # 都说不清。它此前**根本没有计数器**，于是「一批 12 条过期死线被全清」
    # 在日志里完全隐形。
    deadlines_backdated: int = 0
```

**1d.** 调用点（`refine.py:610` 附近）：

```python
                # ⚠️ 只有事务真的提交了才动 stats——回滚了还记账，账目会说谎
                stats.deadlines_dropped += dropped
                stats.deadlines_backdated += backdated
                stats.items_saved += saved
```

（`dropped, backdated = ...` 那一行的解包要跟着从二值改三值——**实施时照实际赋值处改**。）

**1e.** `cli.py` 的告警行加一句（`cli.py:314` 附近那句「[注意] N 条截止日在源消息里找不到字面依据」之后）：

```python
    if stats.deadlines_backdated:
        logs.emit(
            f"[注意] {stats.deadlines_backdated} 条截止日**早于源消息时间**，已降级为无死线"
            "（死线比消息还早 = 一条已过期的「⏰ 别忘」）"
        )
```

- [ ] **Step 2: #4 的测试**

在 `tests/test_refine.py` 末尾追加：

```python
def test_a_backdated_deadline_is_counted(conn, monkeypatch):
    """⭐ M5 遗留 #4：时序倒挂必须**有计数**，不许静默清掉。

    ⚠️ 变异反证：把 `_verify_deadlines` 里那个 `elif it.deadline_ts:` 分支
    整段删掉 ⇒ 本条**必红**（`backdated` 会是 0，而条目的 deadline 仍被清）。

    ⚠️ 更值钱的那条变异：把闸门**挪回** `_to_item`（不删、但也不计数）
    ⇒ 条目结果**完全一样**，而 `stats.deadlines_backdated` 是 0。
    **这条才是本任务要挡的形状**——「行为对、账目错」比「行为错」更难发现，
    因为没有任何用户可见的差异。
    """
    ...
    assert stats.deadlines_backdated == 1
    assert item.deadline_ts is None
```

⚠️ 夹具与假 LLM 照抄 `tests/test_refine.py` 既有用例；`item 83` 的形状是「死线 `2026-05-06`、消息日 `2026-08-05`」，**按那个形状造**。

- [ ] **Step 3: F1 —— 墓碑跳过的日志必须排在早退**之前

**问题的确切断面**：`refine.py:444-453`——墓碑过滤发生在 `stats.scanned = len(messages)` **之前**，而日志行在 `refine.py:478-481`，**排在 `refine.py:451` 的 `if not messages: return stats` 之后**。于是：

> 一整窗消息**全被墓碑**时，`messages` 变成空 ⇒ 在 451 行提前返回 ⇒ **第 478 行永远不会执行** ⇒ 日志上看到的是「`[refine] 没有待处理的消息`」，与「这个窗口本来就没有消息」**一字不差**。

**修法**：把那段日志**提到墓碑过滤之后、早退之前**。

```python
        tombstones = _tombstoned_msg_ids()
        if tombstones:
            kept = [m for m in messages if m.msg_id not in tombstones]
            stats.skipped_deleted = len(messages) - len(kept)
            messages = kept

        stats.scanned = len(messages)
        # ⚠️ **必须排在下面那个早退之前**（M5 遗留 F1）：排在后面的话，
        # 「一整窗消息全被墓碑」会走到 `if not messages: return`，
        # 于是那行日志**永远不会执行**——而它本该说出的正是这件事。
        # 用户看到的是「[refine] 没有待处理的消息」，与「这个窗口本来就空」
        # **一字不差**：一句无法区分两种事实的日志，等于没有日志。
        if stats.skipped_deleted:
            on_progress(
                f"[refine] 其中 {stats.skipped_deleted:,} 条已软删，跳过重抽（D15 墓碑）"
            )

        if not messages:
            on_progress("[refine] 没有待处理的消息")
            return stats
```

⚠️ 同时**删掉**原来 `refine.py:478-481` 的那一份——两份会漂移，而且后一份本来就不该在。

**测试**（加进 `tests/test_refine.py`）：

```python
def test_a_fully_tombstoned_window_says_so(conn):
    """⭐ M5 遗留 F1：整窗全被墓碑时，日志必须**与「窗口本来就空」不同形**。

    ⚠️ 变异反证：把那句 `on_progress` 挪回 `if not messages: return` **之后**
    ⇒ 本条**必红**（一行日志都收不到）。这个变异**不改变任何返回值、
    不改变任何数据库状态**——它只让一句人话消失。所以只有把日志本身
    当断言对象，才挡得住它。
    """
    lines: list[str] = []
    ...
    assert any("已软删" in ln for ln in lines), (
        f"整窗全被墓碑时没有说出原因，实际日志：{lines}"
    )
```

- [ ] **Step 4: #7 —— 进度话术用**去重后**的条数**

**确切断面**：`refine.py:611` 的 `stats.items_saved += saved` 用的是 `save_items` 的**返回值**（去重后），而 `refine.py:639` 的完成话术用的是 `len(produced)`（去重**前**）。后果是用户看到「12 条 → 12 条 item」而只落库 11 行——**纯话术，但它是账目**。

**修法**（`refine.py:636-640`）：

```python
            on_progress(
                f"[refine] 批次 {index}/{len(batches)}：{len(batch)} 条 → "
                # ⚠️ 用 `saved`（`save_items` 的**返回值**，去重后的落库条数）
                # 而不是 `len(produced)`（去重**前**）。`store._dedupe_batch` 会把
                # 同 (title, event_ts, group_id) 的条目并成一条，所以两个数**会**
                # 不同——而报去重前的数就是报了一个没落库的条数（M5 遗留 #7）。
                f"{saved} 条 item"
                + (f"（另有 {len(produced) - saved} 条与批次内重复，已合并）"
                   if len(produced) > saved else "")
            )
```

⚠️ **`saved` 在那一行一定已绑定**：它在 `try` 里先于任何可能抛的语句赋值，而 `try` 失败会 `continue`（`refine.py:630-637` 的注释有完整论证）。改动不会让这个性质失效。

- [ ] **Step 5: #23 —— 把 `-shm` 从 D11 的哈希断言里去掉**

**确切断面**：`tests/test_api.py:566` 与 `tests/test_repass.py:839` 的 `for suffix in ("", "-wal", "-shm")`。

**为什么它是**假红（M5 终审实测，不是推测）：

> 窗口内一条**读写**连接开-关、且它是最后一条时，**合规、零写入**，但 `-wal`/`-shm` 双双变 `<missing>` ⇒ 断言报「变了」。

⇒ 会让人去**修一个不存在的问题**，而这属于「假红比假绿更贵」那一类。
⇒ 且 `-shm` 的**检出价值 = 0**：实测那次「② 的 changed 集合」只有 `{-wal}`。

**修法（两处一样）**：

```python
    # ⚠️ **`-shm` 不在这张表里**（M6 T10 / M5 遗留 #23，终审已复现）。
    # 它的形状是**假红**：一条读写连接开-关且为最后一条时（合规、零写入），
    # `-wal`/`-shm` 双双变 `<missing>` ⇒ 守卫报「变了」，而人去看一个
    # **不存在的问题**。实测它的检出价值 = 0（「变了的集合」只有 `{-wal}`）。
    # ⚠️ 保留下来的 `-wal` 是**承重**的：`INSERT` 在 WAL 模式下先落 `-wal`，
    # 只盯主文件会漏掉「写了但还没 checkpoint」这一整类。
    for suffix in ("", "-wal"):
```

并把读取副作用的那句「把 `<missing>` 归一成空」**保留**（`-wal` 被删掉时会读不到）。

⚠️ **必须跑变异反证确认修完仍有牙**：让 `api_set_kind` 顺手 `UPDATE items` ⇒ 断言**必须变红**（`-wal` 那格变）。**这一步不能省**——去掉一格之后，"还剩的那格有没有用"必须实测，不能推理。

- [ ] **Step 6: #25 —— `label` 的控制字符检查必须排在 `strip` 之前**

**确切断面**：`api.py:411-416`

```python
        label = str(body.get("label", "")).strip()     # ← 先 strip
        if not label: ...
        note = str(body.get("note", ""))
        _reject_controls(label, "label")               # ← 再查（此时换行已经被剥掉了）
        _reject_controls(note, "note")                 # ← note 没 strip，所以查得到
```

⇒ 同一次请求里两个字段**待遇相反**：`label="甲\n"` → **201 且静默剥掉换行**；`note="备\n"` → **400**。而 `_reject_controls` 的 docstring 写着「**响亮地拒绝**」。

**修法**：两个字段都先查原始值、再 strip。

```python
        # ⚠️ **控制字符检查必须排在 `.strip()` 之前**（M6 T10 / M5 遗留 #25）。
        # 排在后面的话，`"甲\n"` 里的换行已经被 strip 剥掉、检查什么也看不见
        # ⇒ 返回 201 而用户以为自己输入的东西被原样接受了。
        # 而同一个请求里 `note` 没走 strip，于是**两个字段待遇相反**——
        # 与 `_reject_controls` docstring 承诺的「响亮地拒绝」矛盾。
        raw_label = str(body.get("label", ""))
        raw_note = str(body.get("note", ""))
        _reject_controls(raw_label, "label")
        _reject_controls(raw_note, "note")

        label = raw_label.strip()
        if not label:
            raise HTTPException(status_code=400, detail="label 不能为空")
        note = raw_note
```

⚠️ **`note` 保持不 strip**（原实现如此，且 `load_persons` 读回时会 strip `note`）。**这一点写进报告**，免得 reviewer 以为漏了。

**测试**（加进 `tests/test_api.py`）：

```python
def test_label_and_note_are_checked_for_controls_before_stripping(client_factory):
    """⭐ 两个字段必须**待遇相同**（M5 遗留 #25）。

    ⚠️ 变异反证：把 `_reject_controls(raw_label, "label")` 换回
    `_reject_controls(label, "label")`（即排在 strip 之后）⇒ 本条**必红**
    （`label="甲\\n"` 会拿到 201）。
    """
    c = client_factory()
    for field in ("label", "note"):
        r = c.post("/api/persons", json={"uin": 100000001, field: "甲\n", "label": "甲"} | {field: "甲\n"})
        assert r.status_code == 400, f"{field} 里的换行被静默接受了：{r.status_code}"
```

- [ ] **Step 7: #9 —— `_apply_to_state` 对未知 action 必须抛错**

**确切断面**：`overrides.py:482-502`——`_apply_to_state` 的 `if/elif` 对未知 `action` **静默什么都不做**，而 `rebuild_state`（`overrides.py:461-479`）也一样。两者"恒等"因此被满足，但状态是**错的**。

M5 终审实测：`_append(action="restore")` ⇒ 事件入库、`item_state` 无表示、`rebuild_state` 后**该 item 整行消失**。

**修法**（两个函数各加一个 `else`，**必须都加**——只加一个会让"恒等"契约破掉，比静默更糟）：

```python
        else:
            # ⚠️ **未知 action 必须响亮**（M6 T10 / M5 遗留 #9）。此前是静默忽略，
            # 后果实测过：`_append(action="restore")` ⇒ 事件入库、`item_state`
            # 无表示、`rebuild_state()` 之后**该 item 整行消失**。
            # ⚠️ `rebuild_state` 里也要加同一支，**少一处就会让两者不再恒等**
            # （而那正是这两个函数唯一的契约，`test_rebuild_state_matches_incremental`
            # 守着它）——"一个响一个不响"比"两个都静默"更难查。
            raise OverlayError(
                f"未知的 action：{action!r}。合法值："
                f"{sorted({ACTION_SET_KIND, ACTION_SET_FIELD, ACTION_DELETE, ACTION_TOMBSTONE})}。"
                "⚠️ `ACTION_TOMBSTONE` 对 `item_state` **完全惰性**，它**不该**
                "走到这里——若你正在给它加分支，先读 `delete_item` 的 docstring。"
            )
```

⚠️ **`ACTION_TOMBSTONE` 是特例**：它对 `item_state` 惰性，所以 `_apply_to_state` 与 `rebuild_state` 里**都不能**给它加分支。实施时确认：现有代码是靠"落到 `else` 什么都不做"来实现惰性的 ⇒ 加了 `else: raise` 之后，**必须给 `tombstone` 一个显式的空分支**：

```python
        elif action == ACTION_TOMBSTONE:
            # 惰性：墓碑行对 `item_state` **没有任何表示**（这是承重的，
            # 见 `delete_item` 的 docstring）。显式写出来，而不是靠"落到 else"。
            pass
```

（`rebuild_state` 里同一支也要有。）

**测试**：`test_an_unknown_action_is_rejected` —— `pytest.raises(OverlayError)`；**变异反证**：把 `else: raise` 换成 `else: pass` ⇒ 红。

- [ ] **Step 8: #10 + #30 —— 两条测试**

**#10**：`tests/test_overrides.py:127` 的
```python
assert OVERRIDES_DB != REPO_ROOT / "data" / "overrides.db"
```
只排除**一个字面路径**，夹具指向任何别的错路径仍绿。改成**落在仓库内的路径一律判红**：

```python
    # ⚠️ 旧写法只排除**一个字面路径**（`REPO_ROOT/"data"/"overrides.db"`），
    # 夹具指向任何别的仓库内路径（比如 `data/ov2.db`）仍然绿——
    # 而后果一样：测试会往**入不了 git 的**真 `data/` 里写字，且没有任何东西能还原它。
    # 判据改成「落在仓库内的路径一律判红」（M6 T10 / M5 遗留 #10）。
    assert not OVERRIDES_DB.is_relative_to(REPO_ROOT), (
        f"夹具把 overlay 指向了仓库内的 {OVERRIDES_DB}——测试会污染真实数据"
    )
```

**#30**：`deadline-audit` **刻意不接** overlay（`cli.py:676-679` 写明是设计），但没有任何测试钉住这个"刻意"。补一条：

```python
def test_deadline_audit_deliberately_ignores_the_overlay(cli_env, ...):
    """⭐ 把「刻意不接 overlay」钉住（M5 遗留 #30 / 终审 A-Minor-5）。

    ⚠️ 为什么这值得一条测试：一件**刻意**不做的事，与一件**忘了**做的事，
    在代码里长得一模一样。下一个人看到 `cli.py` 里别的路径都接了 overlay，
    会"顺手"给它也接上——而它读的是 `SELECT title FROM items`
    （`cli.py:530` 是 `.fetchone()[0]`），接上之后被软删的条目会返回 `None`
    ⇒ **`TypeError` 当场崩**。所以这条测试守的是"别接"。

    ⚠️ 变异反证：给它接上 overlay 过滤 ⇒ 本条**必红**（不是断错，是崩）。
    """
    # 软删一条 → deadline-audit 的输出里**照样**有它的标题
```

⚠️ 具体构造照抄 `tests/test_cli.py` 既有 `deadline-audit` 用例的夹具。

- [ ] **Step 9: 跑测试 + 全量回归**

Run: `uv run pytest`
Expected: T9 结束时 + 新增的那几条。

⚠️ **Step 1 的改动会波及 `repass.py`**（它 `from .refine import ... _to_item`）。**实施后必须单独复跑 `uv run pytest tests/test_repass.py -v` 并确认全绿**——`_to_item` 不再应用时序闸门这件事，对 `repass` 是**安全的**（`repass.apply_plan` 只软删、不写 items，所以一个未被时序闸门清掉的死线**不会**被存进库），但"我推理过它安全"和"实测它没坏"是两回事。

- [ ] **Step 10: Commit**

```bash
git add vigil/refine.py vigil/cli.py vigil/api.py vigil/overrides.py tests/test_refine.py tests/test_api.py tests/test_overrides.py tests/test_cli.py tests/test_repass.py
git commit -m "fix(refine,api,overrides): M5 遗留清理 #4/#7/#9/#10/#23/#25/#30 + F1"
```

---

## 阶段① 自审三件套

> 按 `superpowers:writing-plans` 的要求，写完计划后对着 spec 重看一遍。
> **下面是这次自审的**实际结果**，包括查出来的一个缺口（已当场补进 T5）。**

### 1. spec 覆盖对照表

**§4.2 的五块范围**：

| spec §4.2 | 落在哪个任务 | 覆盖 |
|---|---|---|
| ① 配置层统一（load/save/validate 三份 toml） | T2 | ✅ |
| ① 原子写（`tmp → fsync → os.replace`） | **既有**（`config.atomic_write_text`，M5 T7 已建）——T2/T5/T7 复用它 | ✅ |
| ① 导入 / 导出（自包含、**不含密钥**） | T7 | ✅ |
| ② LLM 配置（base_url / model 从配置读） | T3 | ✅ |
| ② `enable_thinking` 可选（通用端点不认） | T3 | ✅ |
| ② 消费方**两处**（refine **和** digest） | T3（还顺带 repass 与 daily，共四处） | ✅ 超出要求 |
| ③ 群列表**只读路径** | T4 | ✅ |
| ③ 与 **U-4 同批**解决 | T1（U-4 的机械面）+ T4（Web 的只读面） | ✅ |
| ③ 新增群的后果要在 UI 说清 | T9 的 `GroupsSection`（写死了 1,664 条 / 21 批 / 6.3 分钟） | ✅ |
| ④ 网页增删改 `categories.toml` | T5（后端）+ T9（界面） | ✅ |
| ④ 版本快照（**与 overlay 撤销是两回事**） | T5 | ✅ |
| ④ 重排 = LLM 重判 + 人工批量改 | T6 | ✅ |
| ④ 重排结果写 overlay ⇒ `item_id` 不变 | T6 | ✅ |
| ④ job 机制（「按了要等」） | T6 | ✅ |
| ④ **slug 改名/删除必须级联** | T5（`kind_alias` + `_EFFECTIVE_KIND`） | ✅ |
| ⑤ U-4 共享库 | T1 | ✅ |

**M6 的七条出口判据**：

| # | 出口判据 | 落在哪 | 备注 |
|---|---|---|---|
| 1 | 网页新增群/人 → 落盘 → **重启后仍在** | T4 Step 1（`client_factory()` 造第二个 app 等价于重启）+ T9 Step 7（真跑） | ✅ |
| 2 | `data/vigil.db` 仍 `mode=ro`，且**新测试证明 Web 没写过 `data/`**；反向验证要变红 | T4 Step 7（**升级成整个 `data/` 目录树**，不再只盯主库指纹）+ T4 Step 8 的变异 | ✅ |
| 3 | LLM 配置切自填 `base_url` → `refine` 与 `digest` **两处都生效** | T3 Step 1（`test_base_url_reaches_the_request`）+ T3 Step 7（`test_daily_passes_the_configured_llm_endpoint`） | ✅ |
| 4 | 配置包在**另一个目录**能导入并生效（临时数据根） | T7 Step 1（`roots` 夹具造 A/B 两个根） | ✅ |
| 5 | U-4 修复后 `groups` 与 `export` **并发不再互相破坏**（对照实验） | T1（锁 = 消除并发；原子写 = 消除"半个文件"；两条都钉了变异） | ⚠️ 见下方「诚实标注」 |
| 6 | 类目编辑：加类目 → `refine` **立刻认得**；删类目 → 提示 N 条 + **不静默留悬空 slug** | T5 Step 1（`test_api_delete_category_refuses_...` / `..._with_migration_...`）+ **自审补的那条**（见下） | ✅（补后） |
| 7 | 重排：`item_id` 前后不变 + 撤销回到重排前 | T6 Step 1（`test_reorder_writes_only_overlay_...`）+ Step 8 变异 + `test_api_reorder_undo_...` | ✅ |

**§6 的三条风险**：R10（配置并发写）→ T4 的 `write_lock` ✅；R12（`enable_thinking` 在非 SiliconFlow 端点报错）→ T3 ✅；R13（overlay 覆盖不全）→ T5 的 `_EFFECTIVE_KIND` + T5 Step 8 的**四向变异** ✅。

---

### ⚠️ 自审查出的一个缺口（已当场补进 T5）

**判据 6 的前半句没有被任何测试覆盖**：

> 「**类目编辑**：网页里加一个类目 → `vigil refine` **立刻认得它**（`known_kinds` 跟着变）」

原计划里只有「加类目 → 落盘 → 重启仍在」（T5 Step 1 的 `test_api_add_category_persists`），而**「refine 认不认得它」是另一件事**——`known_kinds` 来自 `refine.py` 里的 `load_categories()`，它与 `api.py` 里的 `load_categories(categories_path())` **是两次独立的读**。若哪天有人给 `refine` 加一个模块级缓存（或者给 `load_categories` 加 `functools.lru_cache`），「界面上加了、refine 不认」就会静默发生——**而所有既有测试照样绿**。

⇒ **在 T5 Step 1 的 `tests/test_api.py` 区块里补这一条**：

```python
def test_api_add_category_is_immediately_visible_to_refine(client_factory):
    """⭐ **出口判据 6 的前半句**：网页加一个类目 ⇒ `vigil refine` **立刻认得**。

    ⚠️ 为什么不能只断言「落盘了、重启还在」：`known_kinds` 是
    `refine.py` 里**另一次** `load_categories()` 的结果，与 `api.py` 里的那次
    **是两次独立的读**。任何一层加了缓存（模块级变量、`functools.lru_cache`），
    「界面上加了、refine 不认」就会静默发生——而"文件确实写对了"这件事
    **完全不能证明它**。

    ⚠️ 变异反证：给 `categories.load_categories` 加一行
    `@functools.lru_cache` ⇒ 本条**必红**。
    """
    c = client_factory()
    assert c.post("/api/categories", json={"slug": "sport", "desc": "球赛"}).status_code == 201

    # ⚠️ 走**产品自己的那条路**（refine 的提示词装配），而不是重新调一次
    # `load_categories`——后者测的还是 api 刚写过的那份文件，绕开了被测的那层。
    prompt = refine.build_system_prompt(load_categories())
    assert "sport" in prompt, (
        "网页上刚加的类目没有出现在 refine 的提示词里——"
        "要么有人给类目读取加了缓存，要么 refine 读的不是同一份文件"
    )
```

⚠️ 这条测试**跨了模块**（`api` → `categories` → `refine`），放在 `tests/test_api.py` 里可能不自然。两个选择：放 `tests/test_categories.py`（它已经有 `test_loads_real_project_config`，是同一个"文件→消费者"的形状），或放 `tests/test_api.py` 的 T5 区块。**实施时按该文件既有的 import 风格挑一个，并在报告里写明选了哪个。**

---

### 2. 占位符扫描

对着 `writing-plans` 的「No Placeholders」清单逐条扫全文：

| 红旗 | 命中 | 处理 |
|---|---|---|
| `TBD` / `TODO` / `implement later` | **0** | — |
| 「加适当的错误处理」/「加验证」/「处理边界情况」 | **0** | — |
| 「为上面的写测试」（不给测试代码） | **0** | 每条测试都有完整代码 |
| 「与 Task N 类似」（不重复代码） | **0** | 每处都重写了完整代码 |
| 描述「做什么」但不给代码 | **0** | 所有代码步都有代码块 |
| **引用了任何任务里都没定义的类型/函数** | ⚠️ **6 处**，**全部在下表点名** | 见下 |

**⚠️ 六处「本计划没给全、实施时必须先读一眼」的地方**（都是**有意的**，因为照着本计划猜会猜错）：

| # | 位置 | 要读什么 | 为什么本计划不猜 |
|---|---|---|---|
| 1 | T3 Step 7 | `tests/test_daily.py` 里既有用例怎么构造 `Config` / `ExportStats` / `RefineStats` / `DigestStats` | 四个 dataclass 的构造参数散在该文件各处，抄错一个字段名就会得到一个**看起来在测别的东西**的用例 |
| 2 | T4 Step 1 | `tests/test_api.py` 的 client 夹具（本计划管它叫 `client_no_snapshot` / `client_with_snapshot` / `client_factory`） | 夹具的实际名字与构造方式**必须**沿用该文件既有的那一套；新造一套会让"测试环境"与"产品行为"两个变量同时变 |
| 3 | T6 Step 1 | `tests/test_repass.py` 的「造库 + 假 LLM」夹具 | 该文件 1,135 行，必然已经解决了「不联网喂假响应」；**直接复用**，别重新发明 |
| 4 | T6 Step 4 | `store.ExtractedItem` 的真实字段名 | 本计划假设它叫 `kind`。**M1 起核心字段就是 kind，但字段名以实际为准** ——`grep -n "class ExtractedItem" -A 15 vigil/store.py` |
| 5 | T9 Step 3 | `web/src/components/PersonPicker.tsx` | 它已经实现了「加人/删人」；能抽公共子组件就抽，抽不动就照抄并在报告里说明 |
| 6 | T10 Step 1 | `refine.py` 里 `dropped` 的实际解包处 | 本计划读到的调用形式是 `stats.deadlines_dropped += dropped`；改成三值返回后**解包那行**也要跟着改，具体位置以实际为准 |

⚠️ **这六处都是「照抄既有代码」而不是「设计新东西」**——它们的正确答案**已经存在于仓库里**，猜反而会错。**但每一处都必须把最终选择写进 implementer 报告**，否则 reviewer 无从判断抄对了没有。

---

### 3. 跨任务签名一致性

| 符号 | 定义处 | 消费处 | 一致？ |
|---|---|---|---|
| `config.toml_str` | T2 | T2 `save_config`、T5 `categories`（经 T2 的 `categories.py` import）、T7 `configpack` | ✅ |
| `config.toml_int` | T2 | T2 `save_config`/`save_persons`、T5 `api_add_group`（**它不用**，闸在 API 层）、T7 `configpack` | ✅ |
| `config.save_config(cfg, path=None)` | T2 | T4 `api_add_group`/`api_patch_group`/`api_delete_group`、T7 `import_pack` | ✅ |
| `config.validate_config_raw(raw, path)` | T2 | T2 `save_config`、T7 `parse`/`import_pack` | ✅ |
| `categories.validate_categories(entries, path)` | T2 | T2 `save_categories`/`load_categories`、T5 `validate_or_400`、T7 `parse` | ✅ |
| `categories.save_categories(cats, path=None)` | T2 | T5 `commit_categories`、T7 `import_pack` | ✅ |
| `categories.as_dicts(cats)` | T5 | T5 `validate_or_400`、T7 `parse` | ✅ |
| `config.LLMSettings` / `load_llm_settings` / `save_llm_settings` / `DEFAULT_LLM_TOML` | T3 | T3 CLI/daily、T6 `api_reorder`、**T9 `api_get_llm`/`api_put_llm`** | ✅ |
| `groups_snapshot.{GroupInfo,Snapshot,collect,write,load,default_path}` | T4 | T4 CLI/export/api、**T9 `fetchGroups`** | ✅ |
| `overrides.{save_config_snapshot,list_config_snapshots,pop_config_snapshot}` | T5 | T5 `snapshot_categories`/`api_category_undo` | ✅ |
| `overrides.{set_kind_alias,kind_aliases}` | T5 | T5 `api_update_category`/`api_delete_category`、T7 `import_pack` | ✅ |
| `overrides.undo_batch(conn, *, actor)` | T6 | T6 `api_job_undo`/`api_bulk_undo` | ✅ |
| `store._EFFECTIVE_KIND` | T5 | T5 四处（`_ITEM_COLS`/`_item_filters`/`kind_counts`×2/`window_items`）+ T6 `_current_kinds` 经 `store.get_item` | ✅ |
| `jobs.{Job,JobRegistry,registry,JobBusy,STATE_*}` | T6 | T6 `api_reorder`/`api_job`/`api_job_undo` | ✅ |
| `reorder.{ReorderPlan,ReorderChange,ReorderStats,plan_reorder,apply_reorder}` | T6 | T6 `api_reorder` | ✅ |
| `configpack.{PACK_SCHEMA,build,parse,write_pack,import_pack,Paths,ImportReport,Pack}` | T7 | T7 CLI/api、**T9 `exportPack`/`importPack`** | ✅ |
| `api` 内闭包 `config_path` / `current_config` / `write_lock` / `categories_path` / `llm_path` | T4 / T5 / T9 | 同文件后续任务 | ✅ |

**⚠️ 两处跨任务**新增**的 API 形状**（T9 用到、但 T4–T7 没实现，**属于 T9 自己**）：`GET/PUT /api/llm`。计划里 T9 Step 2 的 ⚠️ 已经点名，**不要以为它们已经在前面做过了**。

**⚠️ 一处已知的接口漂移风险**：T4 把 `api.py` 里的 `cats` / `cat_by_slug` 从"`create_app` 时冻住"改成"每次现读"，而 `cat_by_slug` **还被 `item_out` 用着**。T4 Step 5 的 ⚠️ 已提示，但**它没有测试**——「网页上刚加的类目在信息流里显示成裸 slug」是一条**没有守卫**的行为。⇒ **T5 Step 1 的 `test_api_add_category_is_immediately_visible_to_refine` 补上了同一族的前半**（refine 侧），而 **api 侧那一半由 T9 Step 7 的真跑覆盖**（「加类目 → 信息流的类目筛选里立刻出现它」）。两条合起来才算覆盖完——**实施 T9 Step 7 时这一格不能跳**。

---

## 执行方式

**模式**：`pipeline`（用户 2026-09-17 指定；记录进 ledger 首部 `Mode: pipeline`）。

**顺序**：T1 → T10 **严格线性**。依赖关系：

```
T1 (U-4)          独立
T2 (序列化层)      独立
T3 (LLM 配置)      依赖 T2（序列化 + ConfigError）
T4 (群快照 + 加群) 依赖 T1（原子写）、T2（save_config）
T5 (类目 + 级联)   依赖 T2（save_categories/validate_categories）
T6 (重排 + job)    依赖 T5（_EFFECTIVE_KIND、kind_aliases）
T7 (配置包)        依赖 T2、T3、T5
T8 (DOM 基建)      独立
T9 (配置界面)      依赖 T3/T4/T5/T6/T7 的端点 + T8 的测试基建
T10 (遗留清理)     独立（但会碰 refine.py，T6 也碰 repass 的 import —— 顺序上放在最后最安全）
```

⚠️ **T10 放在最后是刻意的**：它会改 `_to_item` 的行为（移除时序闸门），而 `repass.py` import 了 `_to_item`。放在最后，前面所有任务都已经在"旧行为"下验证过，T10 的波及面因此**可归因**（红了就是 T10 造成的，不用怀疑 T6）。

**工作区**：`bash C:/Users/<用户名>/.claude/skills/SDD/scripts/sdd-workspace docs/superpowers/plans/2026-09-17-vigil-m6-config.md`（在**仓库根**调用）。

**冒烟 = 出口证据**：见 T9 Step 7 那张表（真进程 + 真数据 + 浏览器逐项走）。**外加** spec 出口判据 2 的反向验证（让端点故意写一次 `data/`，守卫必须变红）——它已经在 T4 Step 7 里。

**⚠️ 三条给 controller 的提醒**：

1. **T5 Step 8 的四向变异和 T6 Step 8 的那一次，一条都不能省**。它们分别守 R13（overlay/别名覆盖不全）与 D16（`item_id` 不变）。M5 的实测结论是：**「反着再问一句」每个任务都捞到东西**——本计划已经把可预见的都写成了变异反证，但**关卡在实施时仍可能发现新的**。
2. **T6 Step 8 那个陷阱要特别当心**：若 `db_with_items` 夹具用的是**只读连接**，那条「没写过主库」的守卫**永远不可能被考验**——这正是 M5 最值钱教训的原形（T9 的守卫因测试用只读连接而失效）。**实施时必须先确认夹具的连接是可写的。**
3. **T9 Step 7 是唯一的"人眼验收"环节**，也是判据 1/6 的「真跑」那一半。只跑 `npm test` 不算——`vitest` 里没有一个测试能证明"刷新后还在"。

---

## 计划完成状态

- **10 个任务**，每个都有：Files / Interfaces / TDD 红绿步骤 / 完整代码 / 变异反证 / 独立 commit。
- **self-review 三件套已跑**，查出 **1 个判据缺口**（判据 6 前半句，已补进 T5）与 **1 处无守卫的接口漂移**（`item_id`→`cat_by_slug`，已定位到 T5 + T9 两处合力覆盖）。
- **6 处「照抄既有代码」的指引**已逐条点名（避免用猜测覆盖仓库里已有的正确答案）。

