# VIGIL M4「自动化」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让管线在**无人值守**下每天自己跑完 `export → refine → digest`——失败看得见（非零退出 + `LAST-ERROR.txt` + 日志落文件），且重复/被中断的运行**不产生重复数据**。

**Architecture:** 新增三个自包含模块：`vigil/logs.py`（控制台原文 + 按日轮转文件 + 失败留痕）、`vigil/lock.py`（操作系统级单实例锁）、`vigil/daily.py`（三阶段串联，逐阶段记账、失败继续、返回最坏状态）。`cli.py` 加 `daily` 子命令，并把管线命令的输出接到日志上。写入路径补原子性：`items` + `refine_runs` 合成一个事务，`save_digest` 的 DELETE/INSERT 合成一个事务。Windows 侧由任务计划调用 `scripts/vigil-daily.cmd`。

**Tech Stack:** Python 3.13 / stdlib `logging` + `msvcrt`（Windows 文件锁）/ 批处理 + PowerShell + `schtasks`（任务计划注册）

**Spec:** [`docs/superpowers/specs/2026-09-13-vigil-product-layer-design.md`](../specs/2026-09-13-vigil-product-layer-design.md) §4.8（自动化）、§5（M4 出口标准）、§6 0.7（日志模块移入 M4）

**Mode:** SDD **wave**。分波 3 / 3 / 2，波内文件所有权互不重叠（写者表见 §一）。模式与理由记在 ledger 首部。

---

## Milestone 范围裁决（用户 2026-09-16 裁定，记录在案，执行时**不要自行扩大或缩小**）

| 决定 | 内容 |
|---|---|
| **进 M4 的遗留** | **M3-1**（`_MIME` 删键无守卫）、**M3-2**（`record_run` 裸奔）、**M2-3**（refine 侧全角引号退化）、**M2-4**（日志同名不同义 / 差 7.6 倍）。**M2-7**（覆盖率分支）经实测**已实现且有单测**（`tests/test_digest.py:1866`、`:1897`）——M4 对它**不写代码**，只在冒烟里用真数据唤醒一次 |
| **推后的遗留** | M3-3、M3-4、M3-5、M2-2、M2-5、M2-6、M2-8（M2-8「日报措辞不可复现」是 LLM 固有性质，只记录不改） |
| **幂等口径** | 「三次正常跑不重复」**今天已成立**；M4 补的是两个洞——**单实例锁**（防任务计划双触发/手动撞车）+ **写入原子化**（关掉崩溃窗口） |
| **24h 出口证据** | 用**短触发器自触发实测**证明「无人干预」这一环；「连续 24 小时」那条标 **⏸** 留给用户次日确认。**不许把 1 小时的表现说成 24 小时** |

**M5 待办（本轮不做，记录在案，别在 M4 顺手做）：** 前端「新增监视群号」、前端「新增监视人物」、类目多选（维度内并集）、**按发布人**筛选（跨维度与类目取交集）。
> **语义已裁定**：`items.actor_uid` = 源消息发信人（`vigil/refine.py:234`），即**发布人**，不是「信息是关于谁的」。用户 2026-09-16 明确接受这一语义 ⇒ **M5 零重抽成本**，不需要新的 LLM 字段。

---

## Global Constraints

以下约束适用于**每一个**任务，不再逐任务重复。

1. **不许在真库真窗口重跑已验收的产物。** `docs/digests/` 里已有的 4 篇与库里 `digests` 的 4 行是**用户已验收**的出口证据。本里程碑一切验证都在**副本**上做。**唯一例外**：冒烟阶段为取证真实跑一次 `vigil daily`——但那次只允许产出**新日期**的日报，且跑之前必须先备份 `data/vigil.db`。
2. **不改提示词与 `PROMPT_VERSION`。** 本里程碑不改变抽取质量，`items` 既有行一个字段都不许变。
3. **不碰 QQ 加密库。** `vigil/qqdb.py` 一行不改。
4. **所有源码文件以 `from __future__ import annotations` 开头**，UTF-8 编码，注释与文档字符串一律中文，注释写**为什么**而不写**是什么**。**唯一例外**：`scripts/vigil-daily.cmd` 的**文件名与内容**必须能安全通过 `cmd.exe` 的字节解析——里面**不许出现中文以外的非 ASCII 风险**见 Task 2 的专门说明。
5. **测试绝不联网、绝不碰真实 QQ 加密库、绝不写 `data/vigil.db`。** 真库只允许 `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`。
6. **修改既有测试文件必须追加而非覆盖**（`tests/test_store.py`、`tests/test_refine.py`、`tests/test_digest.py`、`tests/test_api.py` 是 M1–M3 行为未变的证据）。**唯一例外**：接口被刻意变更时（Task 5 把 `save_items` + `record_run` 改成一次事务提交），测试注入点必须跟着改——但**改在明处**：在 `task-N-report.md` 里点名"我改了哪条既有测试、为什么、断言是变强了还是变弱了"。
7. **每个任务一个独立 commit**，消息格式 `feat: ...` / `fix: ...` / `test: ...` / `chore: ...`。**文件级 `git add`**，提交后 `git show --stat` 自查——`git add -A` 会卷入无关改动。
8. **禁止在任何日志、报告、异常消息里出现密钥。** `.env` 内容、`VIGIL_DB_KEY`、`SILICONFLOW_API_KEY` 的值一律不许进日志文件。
9. **禁止 `taskkill //F //IM node.exe`**——会杀掉 claude-mem 的 hook 进程，造成 `UserPromptSubmit hook error`。杀进程一律按 PID（`taskkill /F /T /PID <pid>`）。
10. **`vigil serve` 的只读不变量不放松。** M4 新增的全部写入都发生在 **CLI 进程**里；`vigil/api.py` 仍然只开 `mode=ro`，Task 3 是它在 M4 里唯一被碰的一次，且**只碰 `_MIME` 及其测试**。
11. **多值/新参数一律不用 `argparse` 的位置参数**——本项目的 CLI 全部是 `--flag` 风格，保持一致。

### 逃逸舱（**wave 模式下已收紧**）

**波内 implementer 只允许修改自己 `Touches:` 里列出的文件。**

- 计划里的断言/命令/顺序与实现不符时：**按实际情况修正并继续，无需请示**，但必须在 `task-N-report.md` 里写明偏差（报告是审查输入）。
- **若需求自相矛盾或无法同时满足 → 停下报告，不许挑一半照做。** 这一条与上一条**不是**同一件事：上一条管"代码与计划不符"，这一条管"计划自己的两句话不可能同时为真"。M3 实测过这个形状——controller 给的测试配方与它自己指定的修法互斥，按字面写下去会得到一个**变异下不变红的"验收核心"**。**驳回 + 摆出证据是高质量行为，不记为偏差。**
- 需要动 `Touches:` 之外的任何文件时：**停下，报告 controller，等裁决**——不许自己"顺手改一下"。裁决只有两种：移出本波转顺序执行，或改走 worktree。**「只改一个文件而已」是波内打架的头号入口。**
- 某一步**根本走不通**时同样停下报告，不要硬凑一个"看起来通过"的结果。

---

## 一、波次与写者表（`Mode: wave` 的边界契约）

```
波 0（串行·controller 自己做）  真库备份 + BASE 记录 + 契约冻结（本计划 §三）
        ↓
波 1   T1 日志模块（Python 新文件）  ∥  T2 任务计划三件套（无 Python）  ∥  T3 _MIME 守卫（api.py）
        ↓ 同步点：全量测试 + 机械越界检查 + 波级窄审查
波 2   T4 单实例锁（Python 新文件）  ∥  T5 写入原子化（store.py+refine.py）  ∥  T6 日志口径（digest.py）
        ↓ 同步点
波 3   T7 daily 批命令（新文件）     ∥  T8 CLI 接线 + 退出码（cli.py）
        ↓ 同步点
波 4   冒烟 = M4 出口证据（串行，controller + 真进程 + 真任务计划）
        ↓
阶段③ 最终全分支 opus review
```

### 写者表（从各任务 `Touches` 汇总，**同波内不得重叠**）

| 文件 | 写它的任务 | 所在波 | 同波冲突？ |
|---|---|---|---|
| `vigil/logs.py`（新） | T1 | 1 | |
| `tests/test_logs.py`（新） | T1 | 1 | |
| `scripts/vigil-daily.cmd`（新） | T2 | 1 | |
| `scripts/register-task.ps1`（新） | T2 | 1 | |
| `docs/SETUP-自动化.md`（新） | T2 | 1 | |
| `vigil/api.py` | T3 | 1 | |
| `tests/test_api.py` | T3 | 1 | |
| `vigil/lock.py`（新） | T4 | 2 | |
| `tests/test_lock.py`（新） | T4 | 2 | |
| `vigil/store.py` | T5 | 2 | |
| `vigil/refine.py` | T5 | 2 | |
| `tests/test_store.py` | T5 | 2 | |
| `tests/test_refine.py` | T5 | 2 | |
| `vigil/digest.py` | T6 | 2 | |
| `tests/test_digest.py` | T6 | 2 | |
| `vigil/daily.py`（新） | T7 | 3 | |
| `tests/test_daily.py`（新） | T7 | 3 | |
| `vigil/cli.py` | T8 | 3 | |
| `tests/test_cli.py`（新） | T8 | 3 | |
| `.gitignore`、`docs/superpowers/progress/*` | **波 0 / 收尾** | 0 | 不派给任何任务 |

**三处需要留意的归属**（写在这里免得 implementer 猜）：

1. **`vigil/cli.py` 本里程碑只被 T8 写一次**。T5（refine.py）与 T6（digest.py）都**不许碰 cli.py**——它们要改的文案只在各自模块内，CLI 侧对应的那处由 T8 统一改（见 §三 的词汇表，三个文件必须用同一套词）。
2. **`vigil/store.py` 只被 T5 写**。T6 若要动 `save_digest`，**停下报告**——`save_digest` 的原子化**归 T5**，实现方式是"DELETE + INSERT 在同一事务里"，**改动全部在 store.py 内部，`digest.py` 一行不用动**。
3. **T7 与 T8 同波，靠 §三 冻结的接口并行**：`daily.py` 产出 `RunReport`，`cli.py` 消费它。两边都**逐字照抄计划里的签名**，谁都不许改。

---

## 二、规划期实测（**本计划的事实依据，不是背景资料**）

写计划时每条关键设计都在真机真数据上跑过。执行时以这些实测为准，**不要按直觉改回去**。

### 发现 1 ⭐：Windows 文件锁在**进程被强杀后由内核回收**——所以不需要"陈旧锁"逻辑

这是 M4 锁设计的唯一事实依据，实测过程与结果：

```
① 进程 A 用 msvcrt.locking(fd, LK_NBLCK, 1) 拿锁       → acquired=True  pid=25516
② 进程 B 试着拿同一把锁                                 → acquired=False 退出码=3
③ taskkill /F /T /PID 强杀 A（模拟断电/任务被杀）
④ 进程 B 再试                                           → acquired=True  ✓
⑤ 锁文件仍在磁盘上，内容是 A 写进去的 "x"                 → 证明是「锁被释放」，不是「文件被删」
```

**推论：`os.O_CREAT | os.O_EXCL` 那种"建文件当锁"的写法必须禁止。** 它在强杀后会把锁文件永远留在磁盘上，下次启动误判成"已有实例在跑"，逼你写一套"这个文件是不是陈旧的"判定——而那套判定本质不可靠（PID 会复用、时间戳会被调）。**操作系统级的字节范围锁由内核在进程终止时无条件回收，不存在陈旧锁问题。**

### 发现 2 ⭐：「三次正常跑不重复」成立，但它**不是靠唯一键**——靠的是记账

实测 `vigil/store.py` 的 schema：

```sql
CREATE TABLE items (...)          -- 无 UNIQUE、无 ON CONFLICT，item_id 只是 rowid 别名
CREATE TABLE refine_runs (msg_id INTEGER PRIMARY KEY, ...)   -- 幂等靠这个
CREATE TABLE digests (...)  +  CREATE UNIQUE INDEX digests_window ON digests(window_from, window_to)
```

`store.pending_messages` 的过滤条件是 `m.msg_id NOT IN (SELECT msg_id FROM refine_runs WHERE status != 'error')`——**`items` 表本身没有任何东西阻止重复插入**，重复与否完全取决于"记账有没有跟上"。于是有两个洞：

- **洞 A（并发）**：全仓 `grep` 确认**没有任何锁、没有 PID 文件、没有 `busy_timeout`**。两个 `vigil refine` 同时跑 ⇒ 各自读到同一批 `pending_messages`（谁都没看见对方的 `refine_runs` 行）⇒ 同一批消息抽两遍 ⇒ **重复 items，消息各计一次账，白烧一份 token**。
- **洞 B（崩溃窗口）**：`refine.py:421` 的 `save_items` **自己 commit**，`refine.py:425` 的 `record_run` 再 commit 一次。**两步之间崩掉（断电/重启/任务被杀——正是无人值守会遇到的那种）⇒ items 落库了但消息没标记 ⇒ 下次重抽 ⇒ 重复 items，全程无声。**

### 发现 3 ⭐：`export` 有一条**整群静默消失**的路径

`vigil/export.py:153-155`：

```python
    except Exception:  # noqa: BLE001 — 连索引都读不到，整群放弃
        src.close()
        return GroupRead([], [])
```

`skipped_ranges == []` ⇒ `skipped_count == 0` ⇒ 调用方把它当**成功**：`per_group` 记 0 条、进度打 `✓ …：0 条`、**`failed_groups` 里没有它**、CLI 最后 `return 0`。

**「这个群没消息」与「这个群读不到」在输出上一模一样。** 对无人值守来说这是最坏的一类失败：日志干干净净，而数据静悄悄地少了。

### 发现 4 ⭐：`cmd_export` / `cmd_refine` **无条件 `return 0`**

- `vigil/cli.py:130` — `cmd_export` 结尾 `return 0`，**即使 `stats.failed_groups` 非空**（那几行明明打了 `[失败]`）。
- `vigil/cli.py:291` — `cmd_refine` 结尾 `return 0`，**即使 `stats.errors` 非空**。
- `vigil/cli.py:331-335` — `cmd_digest` 是全管线**唯一**的主动非零退出（注释里已经写着"非零退出码是 M4 自动化的报警信号——别吞掉"），但它 `return 1` 在汇总行**之前**，所以失败时日志里**没有本次的计数**。

⇒ **退出码是 Task Scheduler 唯一能看见的信号**，而三个阶段里两个永远报喜。

### 发现 5：M2-4 的真实倍数在真库上是 **7.6 倍**，而且 CLI 那句「其中」是假话

真库实测（`pending_messages(redo=True)` + `prefilter.screen` + `expand_context`）：

```
扫描 scanned        = 47,719
候选 kept           =  3,211    ← refine 进度行叫「规则保留」
规则硬丢弃 dropped  =  5,069    ← refine 进度行叫「本地丢弃」
送模型 sent         =  9,272    （= 候选 3,211 + 上下文邻居 6,061）
本地筛掉            = 38,447    （= scanned - sent，CLI 汇总行与日报用这个）
```

两个问题：

1. **同一个概念两个词，数字差 7.6 倍。** 进度行说「本地丢弃 5,069」，日报说「本地筛掉 38,447」。用户对照两处会认为有一处在撒谎。
2. **`cli.py:267` 的「（其中硬丢弃 5,069 条）」里的「其中」是假话。** 「其中」断言 `硬丢弃 ⊂ 本地筛掉`。实测**不成立**：`expand_context` 取 ±2 邻居时**不看那条消息有没有被硬规则判死**，于是被判死的消息照样作为上下文出网。在出网的 6,061 条上下文邻居里，用内容特征做代理判据，找到 **710 条本身就是硬丢弃形状的**（`[非文本]`、空串、单字应答）——**足以否定包含关系**。
   > `vigil/digest.py:713-720` 的 docstring **已经记录过这个非子集事实**，并且正是因此把「硬丢弃」计数从日报文案里**删掉**了。CLI 那句是同一处认识的**漏网点**。

### 发现 6：M2-7 的覆盖率分支**已经实现且有单测**——M4 对它不写代码

`vigil/digest.py:393-406` 的 `stat_line(..., refined=)` 已实现 `if refined is not None and refined < messages` 分支；单测已有 `tests/test_digest.py:1866`（`test_stat_line_shows_partial_coverage`，断言 `"仅抽取了 300/514"`）与 `:1897`（正文级）。

⇒ 接力文件说的"M4 会唤醒它"指的是 **51 个有数据的日子覆盖率全 100%，这条分支从没在真数据上跑过**。所以 M2-7 在 M4 里的形态是**冒烟清单的一条**（人为压低 `--budget` 造出部分覆盖，看日报那句限定是不是真的对了），**不是代码任务**。执行时**不要**为它新写实现。

### 发现 7：全仓零日志基础设施，`print(` 60 处**全在 `cli.py` 一个文件**

`grep -rn "import logging" vigil/ tests/` → **零命中**。`print(` 计数：`vigil/cli.py` **60**，其余 `vigil/*.py` **0**。

但库函数会**间接触发** `print`——三个模块的进度回调默认值就是内建 `print`：

| 位置 | 默认值 |
|---|---|
| `vigil/refine.py:285` | `on_progress=print` |
| `vigil/digest.py:559` | `on_progress=print` |
| `vigil/export.py:316` | `on_progress=print` |

⇒ 设计含义：**不去动那 60 处 `print` 的形态，而是换掉它们的落点**。见 §三 的 `logs.emit` 契约——它**先 `print` 原文、再写日志**，于是既有的 `capsys` 断言（`tests/test_digest.py` 里有 ~10 处）**一个字都不用改**。这是刻意的：M4 不该顺带重写一整套 CLI 输出测试。

### 发现 8：`config/groups.toml` 的注释在说谎（顺带修）

`config/groups.toml` 的「怎么加群」第 3 步写着"重跑 `vigil export`。**已纳群只补新消息，新群拉全量历史**"。而 `vigil/export.py:9-13` 的模块 docstring 写着"**不做增量记账。每次全量重读已纳群 + `INSERT OR REPLACE`（幂等）**"，`export.py:136-138` 的查询也没有任何时间谓词。

⇒ **export 每次都是全量重读**（实测 4.7 万条几秒）。注释与实现矛盾，而注释更"动听"——按本项目"过期快照会烂掉"的先例，这句话该在 M4 改对（`T2` 顺带，因为 `docs/SETUP-自动化.md` 要引用这段流程）。

### 发现 9 ⭐：M2-3 不只是"防退化"——refine 侧不 sanitize **已经在一个现成的洞上**

规划期实测（真函数、真判据）：

```
raw = '有人捡到校园卡吗（640）？'          # 源消息（不含引号）
_normalize(raw)                             → '有人捡到校园卡吗640'

_match_source('“有人捡到校园卡吗（640）？”', [msg])              → False  ❌
_match_source(sanitize_for_llm('“有人捡到校园卡吗（640）？”'), [msg]) → True   ✅
```

**原因**：`vigil/refine.py:160` 的归一化字符集是

```python
_PUNCT = re.compile(r"[\s，。！？、：；「」『』【】（）()\[\]…~～\-—]+")
```

——**里面没有 `“”`**。而 `vigil/digest.py:197` 的同一张表**多了 `“”` 与 `"`**，并且 `digest.py:188` 明写这是刻意的（"取值比 refine.py 的 `_PUNCT` 多一组引号"）。

**后果**：模型只要把摘录**用引号包一层**（源文没有引号，它自己加），`_match_source` 就匹配不上 → 那条 item **丢掉来源**。而 refine 的提示词今天不过 `sanitize_for_llm`，所以模型看到的是 `“…”`、回出来的也是 `“…”`——正好落在这个洞里。

**⇒ M2-3 在 refine 侧的修法（把 `sanitize_for_llm` 接到提示词边界）一举两得**：既掐掉模型退化成无限空格循环的路径（原本的理由），又让 `“”` 在出网前就变成 `「」`——而 `「」` **是** refine 归一化表里的字符，于是匹配洞同时被堵上。

**⚠️ 本里程碑不要去改 `refine.py` 的 `_PUNCT`。** 那是 M1 已验收的匹配语义，动它要另证——而且 `sanitize_for_llm` 这条修法已经把现实路径盖住了。若日后仍发现漏匹配，那是 M5 带证据的独立条目。

---

## 三、冻结的接口与措辞（**跨任务并行的唯一接口权威**）

三个波要并行，靠的是下面这些签名与词**逐字冻结**。任何任务都不许改它们；不够用就停下报告。

### 3.1 `vigil/logs.py`（T1 产出，T7/T8 消费）

```python
LOG_DIR: pathlib.Path                      # REPO_ROOT / "data" / "logs"
KEEP_DAYS: int                             # 30
LAST_ERROR_NAME = "LAST-ERROR.txt"

def setup(*, level: int = logging.INFO) -> logging.Logger   # 幂等；只装文件 handler
def emit(message: str) -> None             # print(原文) + 写日志。CLI 与 daily 的唯一输出口
def log_path(day: dt.date | None = None) -> pathlib.Path    # data/logs/vigil-YYYY-MM-DD.log
def clear_last_error() -> None             # 开跑时清——「文件存在」⟺「本次跑失败过」
def write_last_error(message: str, *, tail_lines: int = 40) -> pathlib.Path
def prune_old_logs(*, keep_days: int = KEEP_DAYS, today: dt.date | None = None) -> list[str]
def reset() -> None                        # 只给测试用，生产零调用点
```

`emit` 的**精确语义**（这条是契约的核心）：

```python
def emit(message: str) -> None:
    """人看的原文走 stdout，日志留一份带时间戳的。

    ⚠️ **先 print 再 log，顺序不能反**：既有测试用 capsys 读 stdout，
    stdout 上必须是**一字不改的原文**（没有时间戳前缀），否则
    tests/test_digest.py 里那 ~10 处 capsys 断言会集体变红——
    而 M4 不该顺带重写一整套 CLI 输出测试。
    """
    print(message)
    logging.getLogger("vigil").info(message)
```

### 3.2 `vigil/lock.py`（T4 产出，T8 消费）

```python
LOCK_PATH: pathlib.Path                    # REPO_ROOT / "data" / "vigil.lock"

class AlreadyRunning(RuntimeError):
    """已有实例在跑。消息里必须带上是哪个 pid 拿着锁，便于人工查看。"""

class SingleInstance:
    """上下文管理器。拿不到锁 → 抛 AlreadyRunning（**不等待、不重试**）。

    用操作系统级字节范围锁（Windows: msvcrt.locking / POSIX: fcntl.flock），
    内核在进程终止时无条件回收——**所以没有陈旧锁逻辑**，见 §二 发现 1。
    """
    def __init__(self, path: pathlib.Path | None = None) -> None: ...
    def __enter__(self) -> "SingleInstance": ...
    def __exit__(self, *exc: object) -> None: ...
```

### 3.3 `vigil/daily.py`（T7 产出，T8 消费）

```python
@dataclass(frozen=True)
class StageResult:
    name: str                    # "export" | "refine" | "digest"
    ok: bool
    detail: str                  # 一行中文摘要，进日志与 LAST-ERROR
    skipped_reason: str = ""     # 非空表示"因为上游失败而跳过"，ok 必为 False

@dataclass(frozen=True)
class RunReport:
    stages: tuple[StageResult, ...]
    last_error: str              # 空串 = 全程无错
    deadline: str                # 本次日报窗口日期 YYYY-MM-DD（digest 跳过时是计划值）
    @property
    def ok(self) -> bool: ...    # 全部 stage.ok

def run(*, config, key: str, llm_key: str, day: str | None = None,
        export_on_progress=..., ) -> RunReport
```

**`run()` 的失败语义（冻结，不许各写各的）**：

| 阶段 | 失败判据 | 后续阶段 |
|---|---|---|
| `export` | `stats.failed_groups` 非空，**或**抛异常 | **跳过 `digest`**——export 失败 ⇒ `messages` 不完整 ⇒ 日报的「这天安静」判据不可信，写出来就是一句假话。`refine` 照跑（存量消息仍值得抽） |
| `refine` | `stats.errors` 非空，**或**抛异常 | `digest` **照跑**——它自己的覆盖率检查会标出「仅抽取了 X/Y」，那是它在说自己有资格说的话 |
| `digest` | `stats.errors` 非空，**或**抛异常 | —— |

### 3.4 退出码契约（**冻结；T2 的文档、T4 的异常、T8 的 CLI 三处必须一致**）

| 码 | 含义 | 谁返回 |
|---|---|---|
| `0` | 成功 | 全部命令 |
| `1` | 有阶段失败/不完整，或参数/配置错误 | `cmd_daily`、`cmd_export`、`cmd_refine`、`cmd_digest` |
| `2` | **已有实例在跑**（`lock.AlreadyRunning`）——不是错误，是并发保护生效 | 任何加锁的命令 |

> 为什么 `2` 而不是复用 `1`：无人值守下「上一次还没跑完」与「这次跑失败了」需要**两种不同的处置**——前者等着就行，后者要人来看。用同一个码会把这两件事混成一件。
> 为什么不是 `3` 或更大：`2` 是 `cmd` 生态里对"用法/占用"类退出的常见约定，且 `argparse` 自己用的是 `2`……**注意**：`argparse` 用法错误也返回 `2`。本项目的参数解析走 `parse_args` 失败即退出，那条路径不经过我们的锁，所以实务上不冲突；但 **`docs/SETUP-自动化.md` 里要把这句写清楚**，免得排障时把"参数写错了"误读成"已有实例在跑"。

### 3.5 `RefineStats` 新增字段（T5 加，T7/T8 用）

```python
candidates: int = 0      # 通过预筛的候选数（= prefilter.ScreenStats.kept）
```
`discarded_local` **语义不变**（= `screen_stats.dropped` = 规则硬丢弃），只是显示口径变了（见 3.6）。

### 3.6 词表（**M2-4 的修复口径；T5 / T6 / T8 三个文件必须用同一套词**）

| 概念 | **唯一正确术语** | 定义（字段） |
|---|---|---|
| 从库里取出来待处理的消息数 | **扫描** | `stats.scanned` |
| 预筛**硬规则判死**的 | **规则硬丢弃** | `screen_stats.dropped`（`prefilter.ScreenStats.dropped`） |
| 通过预筛的 | **候选** | `screen_stats.kept` |
| **真正出网**的（候选 + 上下文邻居） | **送模型** | `stats.sent_messages` |
| **一步没出本机**的 | **本地筛掉** | `scanned - sent_messages` |

**两条禁令**：

1. **「本地丢弃」这个词从此废止**——它在 refine 进度行里指"规则硬丢弃"，在别处又像"本地筛掉"。一律换成上表的词。
2. **「其中」不许再用来连接「规则硬丢弃」与「本地筛掉」**——两者**不是**包含关系（§二 发现 5）。「扫描 47,719 → 本地筛掉 38,447 → 送模型 9,272」这三个数**自洽**（前者 − 中者 = 后者），要并列就并列，不要写「其中」。

---

## 四、文件结构（本里程碑结束时的样子）

```
vigil/
  logs.py      新增  ~120 行  日志：setup / emit / LAST-ERROR / 轮转
  lock.py      新增   ~70 行  单实例锁（msvcrt + fcntl 分支）
  daily.py     新增  ~180 行  三阶段串联 + RunReport
  cli.py       改   +daily 子命令；60 处 print → logs.emit；退出码语义
  store.py     改   +transaction()；save_items/record_run 加 commit=；save_digest 原子化
  refine.py    改   批量写入进事务；_record_error；on_progress 接 emit；词表
  digest.py    改   文案词表；_persist 失败可见
  api.py       改   _MIME 守卫（只碰这一处）
scripts/
  vigil-daily.cmd      新增  任务计划的入口（ASCII-only）
  register-task.ps1    新增  幂等注册任务（要先查后建）
docs/
  SETUP-自动化.md      新增  安装/验证/排障
tests/
  test_logs.py    新增
  test_lock.py    新增
  test_daily.py   新增
  test_cli.py     新增
  test_api.py     追加
  test_store.py   追加 + 注入点更新
  test_refine.py  追加 + 注入点更新
  test_digest.py  追加
```

## 五、任务

### Task 1（波 1 · 独立）：日志模块 `vigil/logs.py`

**Files:**
- Create: `vigil/logs.py`
- Test: `tests/test_logs.py`

**Interfaces:**
- Consumes: `vigil/config.py` 的 `REPO_ROOT`（已存在）
- Produces: §三 3.1 的**全部**符号——`setup` / `emit` / `log_path` / `clear_last_error` / `write_last_error` / `prune_old_logs` / `reset` / `LOG_DIR` / `KEEP_DAYS` / `LAST_ERROR_NAME`。T7、T8 消费它们，签名**逐字不许改**。

**Dependencies:** 无
**Touches:** `vigil/logs.py`、`tests/test_logs.py`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_logs.py`：

```python
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
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_logs.py -p no:warnings -q
```
期望：`ModuleNotFoundError: No module named 'vigil.logs'`（全红）。**把输出贴进报告**。

- [ ] **Step 3: 写实现**

创建 `vigil/logs.py`：

```python
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
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_logs.py -p no:warnings -q
```
期望：全绿。再跑一次全量确认没有回归：

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:warnings -q
```

- [ ] **Step 5: 变异反证（**必做，否则"全绿"不可信**）**

把下面三条改动逐个做一遍，**每条改完跑 `tests/test_logs.py` 确认有且仅有对应的测试变红，然后改回来**。把每条的实测输出贴进报告：

| # | 变异 | 期望变红的测试 |
|---|---|---|
| M1 | `setup()` 里去掉 `if _configured: return logger`（幂等标志） | `test_setup_is_idempotent_no_duplicate_lines` |
| M2 | `prune_old_logs` 的 `_LOG_NAME_RE.match` 换成 `p.suffix == ".log"` | `test_prune_only_deletes_our_own_filename_shape` |
| M3 | `emit` 里把 `print(message)` 换成 `print(f"[INFO] {message}")` | `test_emit_prints_verbatim_without_timestamp` |

**⚠️ 跑变异前必须清 `__pycache__` 并带 `PYTHONDONTWRITEBYTECODE=1`**——`.pyc` 只按 `(mtime 秒, 大小)` 校验，同尺寸变异同秒写入会**复用旧字节码**，于是变异"存活"（M1 血泪教训）。

```bash
cd D:/github/VIGIL && find . -name __pycache__ -type d -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null; PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_logs.py -p no:warnings -q
```

- [ ] **Step 6: 提交**

```bash
cd D:/github/VIGIL && git add vigil/logs.py tests/test_logs.py && git commit -m "feat(logs): 日志模块——按日轮转文件 + LAST-ERROR 留痕 + emit 保持 stdout 原文" && git show --stat HEAD
```

---

### Task 2（波 1 · 独立）：Windows 任务计划三件套

**Files:**
- Create: `scripts/vigil-daily.cmd`
- Create: `scripts/register-task.ps1`
- Create: `docs/SETUP-自动化.md`
- Modify: `config/groups.toml`（**只改注释**，见发现 8）

**Interfaces:**
- Consumes: `vigil daily` 这个 CLI 子命令（**由 Task 8 提供**，签名见 §三）。本任务**不实现它**，只调用它。
  ⚠️ **本任务与 Task 8 同属一个里程碑但不同波次**：Task 2 在波 1，Task 8 在波 3。所以本任务的脚本**跑起来会因为 `vigil daily` 还不存在而失败**——这是**预期的**，不是缺陷。本任务的验收只看：① 脚本语法能被 `cmd.exe` / PowerShell 正确解析；② `register-task.ps1` 能幂等注册出正确的任务定义（`schtasks /query` 原文为证）；③ 文档与环境实测相符。**端到端串通是波 4 冒烟的事**，别在本任务里硬凑。
- Produces: 任务计划里那条任务的**名字与定义**——`VIGIL每日管线`，每日 08:00，动作是 `scripts\vigil-daily.cmd`。Task 8 与冒烟按这个名字找它。

**Dependencies:** 无（不依赖任何 Python 改动）
**Touches:** `scripts/vigil-daily.cmd`、`scripts/register-task.ps1`、`docs/SETUP-自动化.md`、`config/groups.toml`

#### 2.0 先说清楚：为什么入口是 `.cmd` 而不是 `.ps1`，以及它为什么没有中文注释

两条都是刻意的，写在这里免得审查当成疏漏：

1. **入口用 `.cmd`**：`.ps1` 需要 `-ExecutionPolicy Bypass` 才对，而执行策略是**机器级**设置——组策略、企业策略、或用户改过都可能让它变。任务计划配好的东西不该因为一条机器策略就静默不跑。`.cmd` 由 `cmd.exe` 直接执行，没有这层变量。
2. **`.cmd` 里不写中文**：`cmd.exe` 按 OEM 代码页逐字节解析文件。UTF-8 中文的字节在 GBK 控制台下会变成乱码字符；注释行通常无害，但**被 `echo` 输出到文件的内容会带上真实字节**，而且括号/管道符混在中文里可能被解析成命令分隔符。**人类可读的中文全部交给 Python 写**（它有确定的 UTF-8 处理），`.cmd` 里只留 ASCII。这一条是 Global Constraint 4 的唯一例外，理由就在这里。

- [ ] **Step 1: 写 `scripts/vigil-daily.cmd`**

```bat
@echo off
REM VIGIL daily pipeline. Invoked by Windows Task Scheduler.
REM
REM Why a .cmd wrapper instead of calling `vigil daily` directly:
REM Task Scheduler discards a task's stdout/stderr. If Python never starts
REM (uv missing from PATH, venv broken, dependency gone), a direct call
REM leaves NO trace at all -- the task just "did nothing". This wrapper is
REM the only place that can notice that case.
REM
REM ASCII-only on purpose: cmd.exe parses this file byte-by-byte in the OEM
REM codepage. All human-readable Chinese output comes from Python instead.
setlocal

set "REPO=D:\github\VIGIL"
set "LOGDIR=%REPO%\data\logs"
set "ERRFILE=%LOGDIR%\LAST-ERROR.txt"

if not exist "%LOGDIR%" mkdir "%LOGDIR%"

REM Delete last run's error marker BEFORE starting: "file exists" then means
REM "THIS run failed". It also makes the fallback below meaningful -- when
REM Python wrote a detailed error we must not overwrite it with a generic one.
if exist "%ERRFILE%" del /q "%ERRFILE%"

cd /d "%REPO%"
uv run vigil daily
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" if not exist "%ERRFILE%" (
  > "%ERRFILE%" echo [%DATE% %TIME%] vigil daily exited with %RC% but wrote no LAST-ERROR.txt. This usually means Python failed before it started: uv not on PATH, broken venv, or a missing dependency. Run "uv run vigil daily" by hand in %REPO% to see the full error.
)

exit /b %RC%
```

> ⚠️ 上面那句 `echo` 的内容**不许出现 `(`、`)`、`&`、`|`、`>`、`<`**——它在 `if (...)` 块里，这些字符会被 `cmd.exe` 解析成分隔符而破坏语法。这就是为什么它是平铺的一句话。

- [ ] **Step 2: 实测 `.cmd` 的语法与兜底分支**

**不要跑完整的 `vigil daily`**（Task 8 还没做，必然失败）。分两步测**脚本自身**：

```bash
cd D:/github/VIGIL && cmd //c "scripts\vigil-daily.cmd" ; echo "外层退出码=$?"
```
期望：`uv run vigil daily` 报「无效选择：daily」之类的错误（因为该子命令还没有），脚本**不崩**、`%RC%` 非 0、并在 `data/logs/` 下写出 `LAST-ERROR.txt`（内容是英文那句兜底）。**把三件事的原文贴进报告**：命令输出、退出码、`LAST-ERROR.txt` 内容。

再测**兜底只在没有 LAST-ERROR.txt 时才写**：

```bash
cd D:/github/VIGIL && printf 'x' > data/logs/LAST-ERROR.txt && cmd //c "scripts\vigil-daily.cmd" ; echo "退出码=$?" ; echo "--- 内容应被脚本先删掉、再重新写出兜底句 ---" ; cat data/logs/LAST-ERROR.txt
```
期望：脚本开头的 `del` 先删掉我们放的 `x`，跑完再写兜底句——所以内容是英文兜底句而**不是** `x`。

- [ ] **Step 3: 写 `scripts/register-task.ps1`**

```powershell
<#
.SYNOPSIS
  幂等注册 VIGIL 每日管线任务。

.DESCRIPTION
  「幂等」在这里是硬要求不是洁癖：这个脚本要被反复执行（换了路径、
  改了时间、重装机器），而 schtasks /create 在任务已存在时会失败。
  先删后建——而且删除用 -ErrorAction SilentlyContinue，因为「本来就没有」
  不是错误。

  为什么不用 XML 导入（schtasks /create /xml）：XML 要手写一整套
  Task Scheduler schema，字段名一旦拼错报的是无关的错误码。命令行开关
  少得多，而且 /tr /sc /st 这三个就是我们要的全部。

  为什么用 -Force（覆盖）而不是先判断存在性再建：判断与建立之间有窗口，
  而 /f 本身就是原子的"有则覆盖"。少一次查询，少一类竞态。

.PARAMETER Time
  每日触发时间，HH:mm，默认 08:00。

  为什么是早上 08:00：`vigil digest` 的默认日期是**昨天**
  （vigil/digest.py 的 yesterday()）。早上跑，昨天已经是一个完整的、
  不会再变的窗口；若放在深夜 23:00 跑，"昨天"指的是前天，会重复处理
  一个已经出过日报的日子。
#>
[CmdletBinding()]
param(
    [string]$TaskName = "VIGIL每日管线",
    [string]$Time = "08:00",
    [string]$RepoPath = "D:\github\VIGIL"
)

$ErrorActionPreference = "Stop"

$script = Join-Path $RepoPath "scripts\vigil-daily.cmd"
if (-not (Test-Path -LiteralPath $script)) {
    throw "找不到入口脚本：$script"
}

Write-Host "[1/3] 删除同名旧任务（若存在）…"
schtasks /delete /tn $TaskName /f 2>$null | Out-Null

Write-Host "[2/3] 注册任务：$TaskName 每日 $Time"
$args = @(
    "/create",
    "/tn", $TaskName,
    "/tr", "`"$script`"",
    "/sc", "DAILY",
    "/st", $Time,
    "/rl", "LIMITED",
    "/f"
)
$out = & schtasks @args 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "schtasks /create 失败（退出码 $LASTEXITCODE）：`n$out"
}
Write-Host $out

Write-Host "[3/3] 回读任务定义，确认真的写进去了："
schtasks /query /tn $TaskName /v /fo LIST

Write-Host ""
Write-Host "完成。任务名：$TaskName"
Write-Host "手工跑一次（不等触发器）：schtasks /run /tn `"$TaskName`""
Write-Host "看上次结果：Get-ScheduledTaskInfo -TaskName `"$TaskName`" | Format-List LastRunTime,LastTaskResult,NextRunTime"
```

- [ ] **Step 4: 实测注册脚本（**这是本任务的主要证据**）**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/register-task.ps1
```

期望：三步打印，最后 `schtasks /query /v /fo LIST` 的输出里有
`任务名: VIGIL每日管线`、`要运行的任务: D:\github\VIGIL\scripts\vigil-daily.cmd`、`计划: 每天 08:00`。

**再跑一遍**，确认幂等（第二次不报错、任务定义一致）。**把两遍的 `schtasks /query` 原文都贴进报告。**

> ⚠️ 注册后**不要**用 `schtasks /run` 触发它——Task 8 还没做，会失败并写出一个误导性的 `LAST-ERROR.txt`。触发实测留到波 4 冒烟。

- [ ] **Step 5: 写 `docs/SETUP-自动化.md`**

内容必须覆盖（每条都要有可复制粘贴的命令）：

1. **它是什么**：任务计划每日 08:00 跑 `export → refine → digest`，产物是 `docs/digests/<昨天>.md` 与 `data/logs/`。
2. **前置**：`.env` 里有 `VIGIL_DB_KEY` 与 `SILICONFLOW_API_KEY`；`uv` 在 PATH 上；QQ 在跑（本地库才有新消息）。
3. **安装**：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts/register-task.ps1`
4. **改时间**：`... -Time 07:30`
5. **看它跑没跑**（三条，从粗到细）：
   - `Get-ScheduledTaskInfo -TaskName "VIGIL每日管线" | Format-List LastRunTime,LastTaskResult,NextRunTime`
   - `ls data/logs/` —— 当天有没有 `vigil-YYYY-MM-DD.log`、有没有 `LAST-ERROR.txt`
   - 日志尾部：`Get-Content data/logs/vigil-*.log -Tail 40`
6. **失败了怎么读**：`LAST-ERROR.txt` 的第一行是失败摘要，后面附日志尾部。**退出码含义表**：
   | 退出码 | 含义 |
   |---|---|
   | `0` | 三阶段全过 |
   | `1` | 有阶段失败或不完整（见 `LAST-ERROR.txt`） |
   | `2` | 已有实例在跑，本次直接退出（**不是错误**，见下） |
   | 其它 | 看日志；若连日志都没有，说明 Python 没起来（`.cmd` 的英文兜底句就是这种情况） |
7. **为什么会有「已有实例在跑」**：上一次还没跑完（比如 QQ 库很大、模型慢）时，下一次触发不会叠加——这是**有意的**。两个 refine 同时跑会产出重复条目并白烧两份 token。

   > ⚠️ 退出码 `2` 这个值**由 Task 4 与 Task 8 冻结**：`lock.AlreadyRunning` 在 CLI 里映射为 `2`。写文档时按此表写，**不要**写别的数字。
8. **卸载**：`schtasks /delete /tn "VIGIL每日管线" /f`
9. **日志轮转**：保留 30 天，自动删。

- [ ] **Step 6: 修 `config/groups.toml` 那句与实现矛盾的注释（发现 8）**

把「怎么加群」第 3 步里的：

```toml
#   3. 重跑 `vigil export`。已纳群只补新消息，新群拉全量历史
```

改成：

```toml
#   3. 重跑 `vigil export`。**每次都是全量重读所有已纳群**（不做增量记账，
#      实测 4.7 万条几秒），写入用 INSERT OR REPLACE，所以重跑不会产生重复行。
#      新群加进来后第一次 export 就会拉到它的全部历史。
```

- [ ] **Step 7: 提交**

```bash
cd D:/github/VIGIL && git add scripts/vigil-daily.cmd scripts/register-task.ps1 docs/SETUP-自动化.md config/groups.toml && git commit -m "feat(scripts): 任务计划三件套——每日管线入口 + 幂等注册 + 排障文档" && git show --stat HEAD
```

---

### Task 3（波 1 · 独立）：`_MIME` 的「键缺失」守卫（**M3-1**）

**Files:**
- Modify: `vigil/api.py:248-262`（`_MIME` 附近，**只碰这一处**）
- Test: `tests/test_api.py`（追加）

**Interfaces:**
- Consumes: 无
- Produces: 无（纯内部守卫，不改任何对外行为）

**Dependencies:** 无
**Touches:** `vigil/api.py`、`tests/test_api.py`

**这个缺陷的形状（终审原话 + 本轮复核）：** `_MIME` 同时承担**两个**职责：

```python
# 职责一：真文件发出去时的 media type
return FileResponse(candidate, media_type=_MIME.get(candidate.suffix.lower()))
# 职责二：「这个后缀是静态资源，不是前端路由」的判据
if candidate.suffix.lower() in _MIME:
    raise HTTPException(404, ...)        # 磁盘上没有 → 宁 404，绝不用 index.html 顶
```

删掉 `_MIME[".js"]` 之后：**职责一照样对**（`media_type=None` 时 Starlette 回落到 `mimetypes.guess_type`，实测 `.js → ('text/javascript', None)`），**职责二悄悄坏掉**（`.js` 不再被判为静态资源 → 缺文件时落进 SPA 兜底 → 返回 **200 的 index.html**）。而既有的 A-3 测试只断言职责一，**照样绿**。这正是 M3 花大力气防的那种假绿（浏览器把 HTML 当 JS 解析失败，而状态码全是 200）。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_api.py` **追加**（不要删任何既有测试）：

```python
# ── M4 T3：_MIME 的「键缺失」守卫（M3-1）──────────────────────────────
#
# ⚠️ 这张表是**故意与 vigil/api.py 的 _MIME 重复**的，不要改成
# `for suffix in api._MIME` ——那样就变成空守卫了：从 _MIME 里删掉一个键，
# 参数集合同步缩小一个，测试**照样绿**，而缺陷（缺文件时不再 404、
# 改成返回 200 的 index.html）原封不动。要抓的就是"键少了"这件事，
# 判据就必须独立于它。
_EXPECTED_STATIC_SUFFIXES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".webmanifest": "application/manifest+json",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain",
}


def test_mime_table_matches_the_frozen_contract():
    """键与值都钉死。

    值被改（`.js` → `text/html`）与键被删（少了 `.js`）**都要红**：
    前者让浏览器拒绝执行脚本，后者让「缺文件宁 404」那条守卫失效——
    两种都只有真跑才现形，所以靠这张独立的表当判据。
    """
    assert api._MIME == _EXPECTED_STATIC_SUFFIXES


@pytest.mark.parametrize("suffix", sorted(_EXPECTED_STATIC_SUFFIXES))
def test_missing_static_asset_is_404_not_index_html(tmp_path, monkeypatch, suffix):
    """⭐ 「职责二」的守卫：磁盘上没有的静态资源宁可 404，绝不许拿 index.html 顶。

    这条是 M3-1 的核心——删掉 `_MIME` 里任意一个键，**这一条会红**，
    因为该后缀不再被判为静态资源，请求会落进 SPA 兜底拿到 200 的 HTML。
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>INDEX</html>", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    client = TestClient(api.create_app(StubConfig()))
    r = client.get(f"/不存在{suffix}")

    assert r.status_code == 404, (
        f"{suffix} 是静态资源后缀，磁盘上没有就必须 404——"
        f"拿到 {r.status_code} 说明它落进了 SPA 兜底"
    )
    assert "INDEX" not in r.text, "绝不许把 index.html 当静态资源发出去"
```

> ⚠️ 上面用了 `StubConfig` 与 `TestClient`——**先看 `tests/test_api.py` 里既有的夹具叫什么名字**，用**既有**的名称，不要新建重复的。若既有夹具名不同，按实际情况改这两行并**在报告里写明**（这是允许的偏差，不是驳回理由）。

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_api.py -p no:warnings -q -k "mime or missing_static"
```
期望：`test_mime_table_matches_the_frozen_contract` 通过（表本来就是对的），`test_missing_static_asset_is_404_not_index_html[...]` 通过（守卫生效）。**这一步大概率全绿——因为它测的是"现状本来就对"。**

⚠️ **这就是为什么本任务的关键动作是 Step 3 的变异反证，不是 Step 2。** 一条只会绿的测试不证明任何事；它证明自己的方式是**改坏实现后变红**。

- [ ] **Step 3: 变异反证（**本任务的核心证据，必做**）**

逐个做，每次跑 `tests/test_api.py -k "mime or missing_static"`，**记录哪几条红了**，然后改回来：

| # | 变异 | 期望变红 |
|---|---|---|
| M1 | 从 `_MIME` 里删掉 `".js": "text/javascript"` | `test_mime_table_matches_the_frozen_contract` + `test_missing_static_asset_is_404_not_index_html[.js]` |
| M2 | 把 `_MIME[".js"]` 的值改成 `"text/html"` | 只有 `test_mime_table_matches_the_frozen_contract` |
| M3 | 删掉 `api.py:299` 那个 `if candidate.suffix.lower() in _MIME:` 整块 | 全部 9 条 `test_missing_static_asset_is_404_not_index_html[*]` |

**M1 是本任务存在的理由**：它必须让**两条**测试同时红——只红一条的话说明守卫只覆盖了一半，报告里要指出来。

- [ ] **Step 4: 提交**

```bash
cd D:/github/VIGIL && git add vigil/api.py tests/test_api.py && git commit -m "test(api): 钉死 _MIME 的键与值——删键会让「缺文件宁 404」守卫静默失效（M3-1）" && git show --stat HEAD
```

---

### Task 4（波 2 · 独立）：单实例锁 `vigil/lock.py`

**Files:**
- Create: `vigil/lock.py`
- Test: `tests/test_lock.py`

**Interfaces:**
- Consumes: `vigil/config.py` 的 `REPO_ROOT`
- Produces: §三 3.2 的全部符号——`LOCK_PATH` / `AlreadyRunning` / `SingleInstance`。T8 消费它们。

**Dependencies:** 无
**Touches:** `vigil/lock.py`、`tests/test_lock.py`

**为什么需要它**（§二 发现 2 洞 A）：全仓**没有任何锁、没有 PID 文件、没有 `busy_timeout`**。两个 `vigil refine` 同时跑 ⇒ 各自读到同一批 `pending_messages` ⇒ 同一批消息抽两遍 ⇒ 产出两份重复 items，且消息只被记一次账。任务计划**会**双触发（触发器重叠、上一次还没跑完、用户手动又跑一次），所以这不是理论风险。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_lock.py`：

```python
"""单实例锁的测试。

⚠️ 跨进程锁**只能用两个真进程测**。同进程内拿两次锁，`msvcrt.locking`
按文件句柄判定，测出来的是"同一个进程能不能锁两次"——那正是我们要禁止
的用法，却**测不出**真正的并发保护。所以下面用 subprocess 起真子进程。

⚠️ 全部用 tmp_path 里的锁文件，绝不碰 `data/vigil.lock`。
"""

from __future__ import annotations

import subprocess
import sys
import time
import pathlib

import pytest

from vigil import lock


@pytest.fixture
def lockfile(tmp_path):
    return tmp_path / "t.lock"


def test_second_instance_raises_already_running(lockfile):
    """同一进程里拿两次 → 第二次必须抛（且**不等待**）。

    「不等待」是刻意的：无人值守下等待会变成任务计划里的僵尸进程，
    而"已经有实例在跑"这件事本来就该原样告诉调度器。
    """
    with lock.SingleInstance(lockfile):
        with pytest.raises(lock.AlreadyRunning) as ei:
            with lock.SingleInstance(lockfile):
                pass
        assert str(lockfile) in str(ei.value)


def test_lock_released_after_exit(lockfile):
    with lock.SingleInstance(lockfile):
        pass
    with lock.SingleInstance(lockfile):   # 必须能拿到
        pass


def test_lock_released_on_exception(lockfile):
    with pytest.raises(ValueError):
        with lock.SingleInstance(lockfile):
            raise ValueError("模拟中途失败")
    with lock.SingleInstance(lockfile):
        pass


def test_lock_released_when_holder_is_force_killed(lockfile):
    """⭐⭐ 这是本任务存在的那条判据：**持锁进程被强杀后，锁必须自动释放。**

    它是 M4 锁设计的唯一事实依据（计划 §二 发现 1）。用 PID 文件 + 陈旧
    时间戳那套方案会在这一步失败——强杀不会执行任何清理代码，锁文件会
    永远留在磁盘上，下次启动误判成"已有实例在跑"。

    操作系统级字节范围锁由内核在进程终止时回收，所以这里必须绿。
    ⚠️ 杀进程**按 PID**，禁止 `taskkill /F /IM`（会误杀别的进程）。
    """
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s');"
         "from vigil import lock;"
         "ctx = lock.SingleInstance(r'%s'); ctx.__enter__();"
         "print('held', flush=True);"
         "import time; time.sleep(60)" % (str(REPO_ROOT), str(lockfile))],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"

        # 持锁期间：另一个进程拿不到
        with pytest.raises(lock.AlreadyRunning):
            with lock.SingleInstance(lockfile):
                pass

        # 强杀（不执行任何 finally / atexit / __exit__）
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(holder.pid)],
            capture_output=True, check=False,
        )
        holder.wait(timeout=10)
        time.sleep(0.5)          # 给内核一点回收时间

        # ⭐ 内核已回收 → 必须能拿到
        with lock.SingleInstance(lockfile):
            pass
    finally:
        if holder.poll() is None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(holder.pid)],
                capture_output=True, check=False,
            )
```

> 上面 `REPO_ROOT` 从 `vigil.config` 导入（`from vigil.config import REPO_ROOT`），子进程靠它找到 `vigil` 包——**不要**依赖 `cwd`，测试的运行目录不一定在仓库根。

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_lock.py -p no:warnings -q
```
期望：`ModuleNotFoundError: No module named 'vigil.lock'`。

- [ ] **Step 3: 写实现**

创建 `vigil/lock.py`：

```python
"""单实例锁：同一时刻只许一个写库的 vigil 进程。

为什么需要（M4 规划期实测）：全仓**没有任何锁、没有 PID 文件、没有
`busy_timeout`**。两个 `vigil refine` 同时跑会各自读到同一批
`pending_messages`（谁都没看见对方的 `refine_runs` 行），于是同一批消息
抽两遍、产出两份重复 items、白烧两份 token。而任务计划**会**双触发：
触发器重叠、上一次还没跑完、用户手动又跑一次——都是现实场景。

⚠️ **为什么用操作系统级字节范围锁，而不用"建锁文件"（`O_CREAT|O_EXCL`）**：
实测（见计划 §二 发现 1）操作系统锁在进程被**强杀**后由内核回收，锁文件
仍在磁盘上但锁已经没了。而"建文件当锁"在强杀后会把文件永远留下，下次
启动误判成"已有实例在跑"，逼你写一套"这个文件是不是陈旧的"判定——
那套判定本质不可靠（PID 会复用、时间戳会被调），而且它**恰好会在最需要
它的场景（断电重启）下给出错误答案**。

⚠️ **不做重入**：同一进程里拿两次会抛 `AlreadyRunning`，这正是我们要的
行为，也是测试覆盖的。需要串联多个写阶段时，由**最外层**加一次锁，
内层直接调库函数而不调 `cmd_*`（`vigil/daily.py` 就是这么做的）。
"""

from __future__ import annotations

import os
import sys
from types import TracebackType

from .config import REPO_ROOT

LOCK_PATH = REPO_ROOT / "data" / "vigil.lock"


class AlreadyRunning(RuntimeError):
    """已有实例在跑。消息里带上是哪个 pid 拿着锁，便于人工查看。"""


def _lock_fd(fd: int) -> None:
    """对 fd 的第 0 字节加**非阻塞**排他锁。拿不到就抛 OSError。

    ⚠️ 锁的字节范围从**当前文件位置**算起，所以 `os.open` 之后、
    `os.lseek` 之前立刻锁——别在中间读写把位置挪了。
    """
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_fd(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _read_holder(path: os.PathLike[str] | str) -> str:
    """读锁文件里上次写下的 "pid=…" 一行（读不到就返回空串）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(200).strip()
    except OSError:
        return ""


class SingleInstance:
    """上下文管理器。拿不到锁 → 抛 `AlreadyRunning`（**不等待、不重试**）。

    不等待是刻意的：无人值守下"等待"会变成任务计划里的僵尸进程，而
    「已经有实例在跑」本来就该原样告诉调度器（CLI 映射成退出码 2）。
    """

    def __init__(self, path: os.PathLike[str] | str | None = None) -> None:
        self._path = str(path or LOCK_PATH)
        self._fd: int | None = None

    def __enter__(self) -> "SingleInstance":
        parent = os.path.dirname(self._path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        fd = os.open(self._path, os.O_RDWR | os.O_CREAT)
        try:
            _lock_fd(fd)
        except OSError:
            holder = _read_holder(self._path)
            os.close(fd)
            raise AlreadyRunning(
                f"已有实例在跑（锁：{self._path}；上次写入：{holder or '无'}）\n"
                f"  若确认没有进程在跑，直接删掉这个文件不影响——锁本身由\n"
                f"  操作系统持有，文件只是标记。"
            ) from None
        self._fd = fd

        # 把 pid 写进去，纯粹为了**人**排障时知道是谁拿着；锁的正确性不靠它。
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            os.truncate(fd, 0)
            os.write(fd, f"pid={os.getpid()}\n".encode("utf-8"))
        except OSError:
            pass          # 写不进去不影响锁的效力
        return self

    def __exit__(self, exc_type: type[BaseException] | None,
                 exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        if self._fd is None:
            return
        try:
            _unlock_fd(self._fd)
        except OSError:
            pass
        finally:
            os.close(self._fd)      # 关句柄本身也会释放锁，双保险
            self._fd = None
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_lock.py -p no:warnings -q
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:warnings -q
```

- [ ] **Step 5: 变异反证（**必做**）**

| # | 变异 | 期望变红 |
|---|---|---|
| M1 | `SingleInstance.__enter__` 里去掉 `_lock_fd(fd)` 调用（等于没有锁） | `test_second_instance_raises_already_running` |
| M2 | `_lock_fd` 用 `msvcrt.LK_LOCK`（**阻塞**）代替 `LK_NBLCK` | `test_second_instance_raises_already_running`（变成挂起 → 靠 pytest 超时；**报告里要写明是超时红的**） |
| M3 | `__exit__` 里去掉 `os.close(self._fd)`，只留 `_unlock_fd` | 应当**仍然全绿**——这是**阳性对照**：M3 证明"锁不是靠关句柄捡漏释放的"。若 M3 红了说明 `_unlock_fd` 没起作用，得回去查 |

> **⚠️ M3 是阳性对照（必做）**：没有它，「杀掉持锁进程后还能拿锁」可能是"因为句柄被关了"而不是"因为内核回收了锁"——那结论就错了。M3 全绿才说明 `_unlock_fd` 那条路真的在工作。

- [ ] **Step 6: 提交**

```bash
cd D:/github/VIGIL && git add vigil/lock.py tests/test_lock.py && git commit -m "feat(lock): 单实例锁——操作系统级字节范围锁，强杀后由内核回收" && git show --stat HEAD
```

---

### Task 5（波 2）：写入原子化 + `record_run` 保护圈 + M2-3 + M2-4（refine 侧）

**Files:**
- Modify: `vigil/store.py`
- Modify: `vigil/refine.py`
- Test: `tests/test_store.py`（追加）、`tests/test_refine.py`（追加 + 一处注入点更新）

**Interfaces:**
- Consumes: `vigil/llm.py` 的 `sanitize_for_llm`（已存在，`llm.py:59`）
- Produces: §三 3.5 的 `store.transaction(conn)` 与 `save_items/record_run/save_digest` 的 `commit: bool = True` 参数；`RefineStats.candidates`。**T6 与 T7 消费它们，签名逐字不许改。**

**Dependencies:** 无
**Touches:** `vigil/store.py`、`vigil/refine.py`、`tests/test_store.py`、`tests/test_refine.py`

**这个任务修的三件事**（都是 §二 实测出来的）：

1. **洞 B（崩溃窗口）**：`refine.py:421` 的 `save_items` 自己 commit，`refine.py:425` 的 `record_run` 再 commit 一次。中间崩掉 ⇒ items 落库、消息没标记 ⇒ 下次重抽 ⇒ **重复 items，无声**。
2. **M3-2（`record_run` 裸奔）**：三处调用**在 `except` 体里**（`refine.py:336`、`383`、`448`）。异常处理路径上再抛异常，`except` 接不住自己——它会穿过整个批次循环掀掉整轮，**而那时恰恰是最可能连续失败的时候**（库锁死、只读、磁盘满）。
3. **M2-3（全角引号）**：`build_user_prompt` 不过 `sanitize_for_llm`。见 §二 发现 9——它同时堵着一个**现成的来源匹配洞**。

- [ ] **Step 1: 写失败的测试（store 侧）**

在 `tests/test_store.py` **追加**：

```python
# ── M4 T5：写入原子性 ──────────────────────────────────────────────


def test_transaction_rolls_back_on_exception(memdb):
    """事务里抛异常 → 之前的写全部不见。"""
    store.ensure_schema(memdb)
    item = _make_item(memdb, msg_id=1)          # 用本文件既有的构造夹具

    with pytest.raises(RuntimeError):
        with store.transaction(memdb):
            store.save_items(memdb, [item], model="m", prompt_ver="v1", commit=False)
            raise RuntimeError("模拟崩在两步之间")

    assert memdb.execute("SELECT count(*) FROM items").fetchone()[0] == 0
    assert memdb.execute("SELECT count(*) FROM item_sources").fetchone()[0] == 0


def test_transaction_commits_on_success(memdb):
    store.ensure_schema(memdb)
    item = _make_item(memdb, msg_id=1)
    with store.transaction(memdb):
        store.save_items(memdb, [item], model="m", prompt_ver="v1", commit=False)
        store.record_run(memdb, [1], status=store.STATUS_OK,
                         prompt_ver="v1", commit=False)
    assert memdb.execute("SELECT count(*) FROM items").fetchone()[0] == 1
    assert memdb.execute("SELECT count(*) FROM refine_runs").fetchone()[0] == 1


def test_save_digest_is_atomic(memdb):
    """⭐ DELETE 与 INSERT 之间崩掉，**旧日报必须还在**。

    `save_digest` 是 先删 digest_items、再删 digests、最后 INSERT。
    三步不在一个事务里的话，崩在中间会让**当天日报凭空消失**——
    而 docs/digests/ 的文件还在，归档不变量（文件集合 == 窗口日期集合）
    当场破掉，且没有任何东西会报错。
    """
    store.ensure_schema(memdb)
    first = store.save_digest(memdb, window_from=10, window_to=20,
                              body_md="第一版", model="m", prompt_ver="v1",
                              item_ids=[])
    assert memdb.execute("SELECT count(*) FROM digests").fetchone()[0] == 1

    real_execute = memdb.execute

    def boom(sql, *a, **kw):
        if sql.strip().startswith("INSERT INTO digests"):
            raise sqlite3.OperationalError("模拟写库失败")
        return real_execute(sql, *a, **kw)

    memdb.execute = boom                      # type: ignore[method-assign]
    try:
        with pytest.raises(sqlite3.OperationalError):
            store.save_digest(memdb, window_from=10, window_to=20,
                              body_md="第二版", model="m", prompt_ver="v1",
                              item_ids=[])
    finally:
        memdb.execute = real_execute          # type: ignore[method-assign]

    rows = memdb.execute("SELECT digest_id, body_md FROM digests").fetchall()
    assert rows == [(first, "第一版")], "崩在 INSERT 时旧日报必须原样还在"
```

> ⚠️ 上面用了 `_make_item(...)` 这个夹具名——**先看 `tests/test_store.py` 里既有的 item 构造辅助函数叫什么**，用既有名字。若既有的写法是内联构造，就按既有的写法来。这是允许的偏差，**在报告里写明即可**。

- [ ] **Step 2: 跑 store 侧测试，确认失败**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_store.py -p no:warnings -q -k "transaction or atomic"
```
期望：`AttributeError: module 'vigil.store' has no attribute 'transaction'`（前两条）、第三条 `test_save_digest_is_atomic` **必须也是红的**（现有实现会在删完旧行之后才抛）。

- [ ] **Step 3: 改 `vigil/store.py`**

三处改动，**只动这三处**：

**(a) 顶部加 `import contextlib` 与 `from collections.abc import Iterator`**（按文件既有的 import 风格排进去），然后在 `save_items` 之前插入：

```python
@contextlib.contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    """把一段写操作圈成一个事务：正常退出 commit，出异常 rollback 后原样抛出。

    ⚠️ 存在的唯一理由是**关掉一个窗口**：`save_items` 与 `record_run` 各自
    commit 一次，两步之间崩掉（断电/重启/任务被杀）会留下「items 落库了、
    消息没标记」的状态——下次 `pending_messages` 把同一批消息再抽一遍，
    **产出重复 items 且全程无声**（`items` 表没有任何唯一键，唯一防重复的
    机制就是 `refine_runs` 的记账跟得上）。写进一个事务后要么两件事都成、
    要么都不成，重抽是干净的。

    ⚠️ 捕 `BaseException` 而不是 `Exception`：`KeyboardInterrupt` 与
    `SystemExit` 也必须 rollback，否则 Ctrl-C 会留下半个批次。

    ⚠️ **不可重入**：不要在 `with transaction(conn)` 里面再开一层——
    sqlite3 的嵌套提交会让内层先落盘，窗口就回来了。
    """
    try:
        yield
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
```

**(b) `save_items` 与 `record_run` 各加一个 `commit: bool = True` 关键字参数**，把末尾那句 `conn.commit()` 改成：

```python
    if commit:
        conn.commit()
```

`save_items` 与 `record_run` 的 docstring 各补一句：

```python
    ⚠️ `commit=False` 用于把本函数并入外层 `transaction()` —— 调用方有责任
    用 `with transaction(conn):` 圈住，否则写的东西永远不会落盘。
```

**(c) `save_digest` 改成事务化，并加 `commit` 参数**：

```python
def save_digest(
    conn: sqlite3.Connection,
    *,
    window_from: int,
    window_to: int,
    body_md: str,
    model: str,
    prompt_ver: str,
    item_ids: Sequence[int],
    now: int | None = None,
    commit: bool = True,
) -> int:
    """写一篇日报，返回 digest_id。同一个窗口**替换**而不是追加。

    ⚠️ 三步（删 digest_items → 删 digests → 插新行）**必须在同一个事务里**。
    分开提交的话，崩在中间会让当天日报凭空消失——而 `docs/digests/` 的
    文件还在，归档不变量（文件集合 == 库里的窗口日期集合）当场破掉，
    且没有任何东西会报错。

    ⚠️ `commit=False` 时**不自己开事务**，由调用方用 `transaction()` 圈住——
    这样「写库」与「落文件」能进同一个事务（见 `digest._persist`）。
    """
    stamp = int(time.time()) if now is None else now

    def _write() -> int:
        # 不删关联行的话，重跑一次就会在 digest_items 里留下指向前一版日报的孤儿行
        conn.execute(
            "DELETE FROM digest_items WHERE digest_id IN"
            " (SELECT digest_id FROM digests WHERE window_from=? AND window_to=?)",
            (window_from, window_to),
        )
        conn.execute(
            "DELETE FROM digests WHERE window_from=? AND window_to=?",
            (window_from, window_to),
        )
        cur = conn.execute(
            "INSERT INTO digests (window_from, window_to, body_md, model,"
            " prompt_ver, created_at) VALUES (?,?,?,?,?,?)",
            (window_from, window_to, body_md, model, prompt_ver, stamp),
        )
        new_id = int(cur.lastrowid or 0)
        conn.executemany(
            "INSERT OR IGNORE INTO digest_items (digest_id, item_id) VALUES (?,?)",
            [(new_id, iid) for iid in item_ids],
        )
        return new_id

    if commit:
        with transaction(conn):
            return _write()
    return _write()
```

> ⚠️ `Sequence` 需要 `from collections.abc import Sequence`——**先看 `store.py` 顶部的 import**，`item_ids` 原来的类型标注是什么就保持什么，不要为了这个参数新引一个类型。若原来标的是 `list[int]`，就用 `list[int]`。

- [ ] **Step 4: 跑 store 侧测试，确认通过**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_store.py -p no:warnings -q
```
期望：全绿（含既有的 `test_save_digest_replaces_same_window` 等——那条是**行为未变**的证据，必须仍然过）。

- [ ] **Step 5: 写失败的测试（refine 侧）**

在 `tests/test_refine.py` **追加**：

```python
# ── M4 T5：批次写入原子化 + record_run 保护圈 + M2-3 ────────────────


def test_batch_write_is_atomic_items_do_not_survive_a_failed_record(seeded, monkeypatch):
    """⭐⭐ 洞 B 的判据：**items 落库与消息记账要么都成、要么都不成。**

    注入一个"记账那一步炸掉"的失败。旧实现里 `save_items` 已经自己 commit
    过了，于是这一批的 items **留在库里**而消息**没被标记**——下次
    `pending_messages` 会把同一批再抽一遍，产出重复 items，全程无声。
    修好后：两者在同一个事务里，记账失败 ⇒ items 一并回滚。

    断言三件事：
      · 那一批的 items **不在**库里（回滚了）
      · 那一批的消息**没有**被标成 ok/discarded（否则下次就不再抽它了，
        那才是真丢数据）
      · 整轮没有被掀掉（别的批照常产出）——保护圈仍然有效
    """
    fake = FakeLLM(lambda user: _scripted(user, deadline=None))
    monkeypatch.setattr(refine, "chat_json", fake)

    real_record = store.record_run
    state = {"blown": False}

    def flaky_record(conn, msg_ids, **kwargs):
        # 只炸**成功路径**的那次（status=ok），不炸 error 记账——
        # 炸后者会连带把 _record_error 也弄坏，那就测不出想测的东西了
        if not state["blown"] and kwargs.get("status") == store.STATUS_OK:
            state["blown"] = True
            raise sqlite3.OperationalError("模拟记账失败")
        return real_record(conn, msg_ids, **kwargs)

    monkeypatch.setattr(refine.store, "record_run", flaky_record)

    stats = refine.refine(
        StubConfig(), api_key="k", conn=seeded, batch_size=1,
        on_progress=lambda *a, **k: None,
    )

    assert state["blown"], "注入没生效——测试本身有问题，别当成通过"
    assert stats.batches == 3, "3 批必须全部跑完"
    assert any("第 1 批" in e for e in stats.errors), stats.errors
    # 第 1 批那 3 条消息（scripts 里第 1 条）不许留下 ok/discarded 记账——
    # 留下了就意味着这条消息永远不会再被抽，而它的 item 已经回滚没了
    assert seeded.execute(
        "SELECT count(*) FROM refine_runs WHERE msg_id = 1 AND status != 'error'"
    ).fetchone()[0] == 0, "回滚要连记账一起回滚"
    assert seeded.execute("SELECT count(*) FROM items").fetchone()[0] >= 1, \
        "后面那批的条目照常落库——「继续跑」得是有产出的"


def test_record_error_failure_does_not_kill_the_run(seeded, monkeypatch):
    """⭐ M3-2：**记账自己也失败时，不许掀掉整轮。**

    三处 `record_run` 原先都裸奔在 `except` 体里。异常处理路径上再抛异常，
    `except` 接不住自己。这里让 `record_run` **永远**炸——模拟"库锁死/只读/
    磁盘满"，那正是最可能连续失败的时候。

    断言：整轮跑完、错误**仍然可见**（进 stats.errors），不是静默吞掉。
    """
    fake = FakeLLM(lambda user: _scripted(user, deadline=None))
    monkeypatch.setattr(refine, "chat_json", fake)

    def always_boom(conn, msg_ids, **kwargs):
        raise sqlite3.OperationalError("模拟库一直写不进去")

    monkeypatch.setattr(refine.store, "record_run", always_boom)

    stats = refine.refine(
        StubConfig(), api_key="k", conn=seeded, batch_size=1,
        on_progress=lambda *a, **k: None,
    )

    assert stats.batches == 3, "记账全炸也不许掀掉整轮"
    assert any("记账" in e for e in stats.errors), \
        f"记账失败必须可见（进 stats.errors），实际：{stats.errors}"


def test_prompt_sanitizes_fullwidth_quotes(monkeypatch):
    """M2-3 + 发现 9：出网文本里不许有全角引号。

    两重收益：① 防模型退化成无限空格循环（原先的理由）；② `“”` 换成
    `「」` 之后，refine 的归一化表（`_PUNCT`）**认得** `「」` 而不认得 `“”`
    ——所以模型摘录时引号包一层也不会再丢掉来源（发现 9 实测的那个洞）。
    """
    from vigil.llm import sanitize_for_llm

    sent = {}

    def capture(cfg, *, system, user):
        sent["user"] = user
        return FakeLLM(lambda u: {"items": []})(cfg, system=system, user=user)

    monkeypatch.setattr(refine, "chat_json", capture)

    msg = store.PendingMessage(
        msg_id=1, group_id=100, ts=1_700_000_000, sender_uid="u_x",
        sender="某同学", content="他说“明天交作业”了",
    )
    refine.refine(StubConfig(), api_key="k", conn=_seeded_with(msg),
                  batch_size=1, on_progress=lambda *a, **k: None)

    assert "“" not in sent["user"] and "”" not in sent["user"], \
        "全角引号必须被 sanitize_for_llm 换掉"
    assert "「明天交作业」" in sent["user"]
```

> ⚠️ 上面第三条用了 `_seeded_with(...)` / `FakeLLM(...)(cfg, ...)` 这两种写法占位——**按 `tests/test_refine.py` 里既有的夹具与 FakeLLM 真实形状改写**（`FakeLLM` 是既有的，它的调用签名照抄文件里的其它测试）。**不要**为了这条测试新造一套夹具。改完在报告里写明你用了哪些既有夹具。

- [ ] **Step 6: 跑 refine 侧测试，确认失败**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_refine.py -p no:warnings -q -k "atomic or record_error or sanitiz"
```
期望：前两条红（旧实现 items 会存活 / 整轮被掀掉），第三条红（提示词里还是 `“”`）。

- [ ] **Step 7: 改 `vigil/refine.py`**

**(a) import**：把 `from .llm import DEFAULT_MODEL, LLMConfig, LLMError, chat_json` 改成

```python
from .llm import DEFAULT_MODEL, LLMConfig, LLMError, chat_json, sanitize_for_llm
```

**(b) `RefineStats` 加字段**（放在 `discarded_local` 之后，**位置与 §三 3.5 一致**）：

```python
    candidates: int = 0          # 通过预筛的候选数（= prefilter.ScreenStats.kept）
```

**(c) `build_user_prompt` 的两行**（`refine.py:125-127`）改成：

```python
    for m in messages:
        # ⚠️ 出网前**必须**过 sanitize_for_llm（M2-3）。全角引号会让模型退化成
        # 无限空格循环——而 refine 侧的 max_tokens 默认是 None（不发这个字段），
        # 所以唯一的刹车是 180s 超时 × 3 次重试 ≈ 9 分钟空转。
        # 附带收益：`“”` 换成 `「」` 之后 refine 的归一化表认得后者，
        # 模型摘录时自己包一层引号也不会再丢掉来源（计划 §二 发现 9 实测）。
        body = sanitize_for_llm(redactor.text(m.content))
        if m.sender_uid:
            name = sanitize_for_llm(redactor.text(m.sender)) or "未知"
```

**(d) 在 `_parse_deadline` 之前**（模块级函数区，`build_user_prompt` 之后）插入：

```python
def _record_error(
    conn: sqlite3.Connection, msg_ids: list[int], *, prompt_ver: str, err: object
) -> str | None:
    """把一批消息记成 error 状态。**自己失败不再抛**。

    ⚠️ 存在的理由（M3-2）：三处 `store.record_run` 原先都**裸奔在 `except`
    体里**。异常处理路径上再抛异常，`except` 是接不住自己的——它会穿过整个
    批次循环把整轮 refine 掀掉，**而那时恰恰是"库出了问题"的时候**（锁死、
    只读、磁盘满），也就是最可能连续失败的时候。

    ⚠️ 本函数**不吞**异常：它把失败**返回**给调用方，由调用方照常写进
    `stats.errors`——账目仍然可见，只是不再掀桌子。M1/M3 的教训是
    「静默吞异常不可接受」，这条守住了。

    返回值：记账也失败时的描述；成功返回 `None`。
    """
    try:
        with store.transaction(conn):
            store.record_run(
                conn, msg_ids, status=store.STATUS_ERROR,
                prompt_ver=prompt_ver, err=str(err)[:200], commit=False,
            )
    except Exception as inner:  # noqa: BLE001 — 见 docstring：返回而非抛出
        return f"error 记账也失败了: {inner}"
    return None
```

**(e) 进度行（`refine.py:321-328`）改成用**三个自洽的数**（M2-4 词表）**：

```python
        candidates, screen_stats = prefilter.screen(
            messages, tier_of=config.tier_of
        )
        stats.candidates = screen_stats.kept
        stats.discarded_local = screen_stats.dropped
        # ⚠️ `expand_context` **提前到这里**：进度行要报「送模型」就必须先算出来。
        # 它是纯函数、不碰 I/O，提前没有副作用；下面那个 `if not candidates`
        # 分支在空候选时 expand_context 返回空表，行为一字不变。
        in_scope = prefilter.expand_context(messages, candidates, context=context)
        stats.sent_messages = len(in_scope)

        # ⚠️ 这三个数**自洽**：本地筛掉 + 送模型 == 扫描。这是 M2-4 的修法。
        # 旧版写「扫描 N 条 → 规则保留 M 条（本地丢弃 D 条）」——43,439 条
        # 消息同时不属于「保留」也不属于「丢弃」（`prefilter.py:177-179` 的
        # 「软丢弃」分支），三个数加起来对不上，而 D 又与日报里的「本地筛掉」
        # 差 7.6 倍。**不要**改回「其中」：规则硬丢弃与本地筛掉**不是**包含
        # 关系（`expand_context` 不看消息有没有被硬规则判死，被判死的照样
        # 作为上下文出网）。
        on_progress(
            f"[refine] 扫描 {stats.scanned:,} 条 → 本地筛掉 "
            f"{stats.scanned - stats.sent_messages:,} 条"
            f" → 送模型 {stats.sent_messages:,} 条（候选 {stats.candidates:,} 条）"
        )
```

**(f) 删掉下面原来的这三行**（它们已被 (e) 接管，留着会重复计算）：

```python
        in_scope = prefilter.expand_context(messages, candidates, context=context)
        batches = prefilter.make_batches(in_scope, max_batch=batch_size)
        stats.sent_messages = len(in_scope)
        stats.batches_planned = len(batches)
```
改成只留：

```python
        batches = prefilter.make_batches(in_scope, max_batch=batch_size)
        stats.batches_planned = len(batches)
```

**(g) 非候选记账那处（`refine.py:335-339`）圈进事务**：

```python
        if not dry_run and not_candidate_ids:
            with store.transaction(conn):
                store.record_run(
                    conn, not_candidate_ids, status=store.STATUS_DISCARDED,
                    prompt_ver=prompt_ver, commit=False,
                )
```

**(h) 两处 `except` 体里的 `record_run` 换成 `_record_error`**（`refine.py:379-387` 与 `439-452`）：

```python
            except LLMError as exc:
                msg = f"第 {index} 批失败: {exc}"
                stats.errors.append(msg)
                on_progress(f"[refine] {msg}")
                if extra := _record_error(
                    conn, batch_ids, prompt_ver=prompt_ver, err=exc
                ):
                    stats.errors.append(f"第 {index} 批 {extra}")
                continue
```

```python
            except Exception as exc:
                # 捕 `Exception` 而不是某个具体类型：设计意图是「单批失败不中断
                # 整轮」，捕窄一类，下一个未知异常类型会**再次**掀掉整轮——
                # 那正是这次在修的模式（同一类缺陷在本项目已是第三次出现）。
                # 捕宽的前提是**可见**：异常照样进 stats.errors、照样
                # on_progress 出来、照样记进 refine_runs；静默吞异常不可接受。
                msg = f"第 {index} 批本地后处理失败: {exc}"
                stats.errors.append(msg)
                on_progress(f"[refine] {msg}")
                if extra := _record_error(
                    conn, batch_ids, prompt_ver=prompt_ver, err=exc
                ):
                    stats.errors.append(f"第 {index} 批 {extra}")
                continue
```

**(i) 成功路径的写入块（`refine.py:418-438`）改成一次事务**：

```python
                # 截止日降级是**纯本地**判定，放事务外——事务里只留 DB 写。
                dropped = 0
                if produced:
                    produced, dropped = _drop_unsupported_deadlines(produced, batch)

                # ⚠️ 落库 + 记账必须在**同一个事务**里（见 store.transaction 的
                # docstring）：分开提交时，两步之间崩掉会让同一批消息下次被
                # 重抽，产出重复 items 且无声。`commit=False` 是关键——漏一个
                # 就白搭，而且**不会报错**，只会静默地退回旧行为。
                with store.transaction(conn):
                    saved = 0
                    if produced:
                        saved = store.save_items(
                            conn, produced, model=model, prompt_ver=prompt_ver,
                            commit=False,
                        )
                    store.record_run(
                        conn, batch_ids, status=store.STATUS_DISCARDED,
                        prompt_ver=prompt_ver, commit=False,
                    )
                    if hit_ids:
                        store.record_run(
                            conn, sorted(hit_ids), status=store.STATUS_OK,
                            prompt_ver=prompt_ver, item_count=saved,
                            commit=False,
                        )

                # ⚠️ 只有事务真的提交了才动 stats——回滚了还记账，账目会说谎
                stats.deadlines_dropped += dropped
                stats.items_saved += saved

                on_progress(
                    f"[refine] 批次 {index}/{len(batches)}：{len(batch)} 条 → "
                    f"{len(produced)} 条 item"
                )
```

- [ ] **Step 8: 跑测试，确认通过**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_refine.py tests/test_store.py -p no:warnings -q
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:warnings -q
```
期望：全绿。**特别注意既有的 `test_refine_keeps_going_when_a_batch_postprocess_fails`**——它的注入点是 `refine.store.save_items`，本任务没有改这个调用点，所以它**应当原样通过**。若它红了，说明你把调用点换掉了——停下报告，不要改那条测试去迁就。

- [ ] **Step 9: 变异反证（**必做**）**

| # | 变异 | 期望变红 |
|---|---|---|
| M1 | 成功路径里 `store.save_items(..., commit=False)` 的 `commit=False` **删掉** | `test_batch_write_is_atomic_items_do_not_survive_a_failed_record`（items 会存活） |
| M2 | 成功路径里把 `with store.transaction(conn):` 整块**去掉**（保留 `commit=False`） | 同上 + `test_transaction_*` 不受影响（它们在 store 侧）——**注意**：去掉事务后 `commit=False` 会让写永不落盘，所以 `stats.items_saved` 会变 0，别的 refine 测试也会红，**报告里要如实写明红了哪几条** |
| M3 | `_record_error` 里的 `try/except` **去掉** | `test_record_error_failure_does_not_kill_the_run` |
| M4 | `build_user_prompt` 里 `sanitize_for_llm(...)` **去掉** | `test_prompt_sanitizes_fullwidth_quotes` |
| M5 | `save_digest` 的 `with transaction(conn):` **去掉**（只留 `_write()`） | `test_save_digest_is_atomic` |

- [ ] **Step 10: 提交**

```bash
cd D:/github/VIGIL && git add vigil/store.py vigil/refine.py tests/test_store.py tests/test_refine.py && git commit -m "fix(store,refine): 落库与记账同一事务 + record_run 失败不再掀掉整轮 + 提示词过 sanitize（M3-2/M2-3）" && git show --stat HEAD
```

---

### Task 6（波 2）：日报落盘与库写的一致性 + 词表（M2-4 digest 侧）

**Files:**
- Modify: `vigil/digest.py`（`_persist` 与其附近的文案）
- Test: `tests/test_digest.py`（追加）

**Interfaces:**
- Consumes: §三 3.5 的 `store.transaction(conn)` 与 `store.save_digest(..., commit=False)` ——**由 Task 5 同波提供**。签名已冻结；若你拿到的实现与冻结签名不符，**停下报告**。
- Produces: 无（不改对外签名）

**Dependencies:** Task 5（同波，接口已冻结）
**Touches:** `vigil/digest.py`、`tests/test_digest.py`

> ⚠️ **本任务不许改 `vigil/store.py`**。`save_digest` 的原子化归 Task 5；你只消费它。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_digest.py` **追加**：

```python
# ── M4 T6：落盘失败不许留下"库里有、文件没有"的日报 ────────────────


def test_persist_rolls_back_db_when_file_write_fails(seeded, monkeypatch, tmp_path):
    """⭐ 归档不变量的守护。

    不变量（接力文件原文）：`docs/digests/` 的文件集合 == 库里 `digests` 的
    窗口日期集合。旧 `_persist` **先写库、后写文件**，文件那步失败就留下
    一个没有 `.md` 的库行——不变量当场破掉，而没有任何东西会报错。
    修好后两者在同一事务里：文件写失败 ⇒ 库行一并回滚，两者都没有。
    """
    ...
    # 让落盘那一步炸掉，然后断言：
    #   · 调用方拿到异常（失败可见，不是静默）
    #   · `SELECT count(*) FROM digests` == 0（库行回滚了）
    #   · 目标 .md 文件不存在
```

> ⚠️ 上面刻意**没给完整代码**——`_persist` 是私有函数，本文件里已有大量对它的既有测法（搜 `_persist` 附近的测试）。**照抄本文件既有的注入方式**（是 monkeypatch `Path.write_text`？还是 monkeypatch `digest.store.save_digest`？），不要新造一套。写出完整测试后，**在报告里说明你用的是哪种注入、以及为什么它能真的触发那条路径**——「注入没生效、测试假绿」是本项目抓过的形状。

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_digest.py -p no:warnings -q -k persist
```
期望：红——旧实现会留下库行，或异常根本不是从那个位置出来的。

- [ ] **Step 3: 改 `vigil/digest.py` 的 `_persist`**

把 `_persist` 的函数体（`digest.py:936` 起）整段改成：

```python
    # ⚠️ 写库与落文件必须在**同一个事务**里，且顺序是「先写临时文件 → 原子改名
    # → 再提交库」。理由与两种旧写法的坏处：
    #
    #   · 旧版先 `save_digest`（自己 commit）再 `write_text`：落盘失败会留下
    #     一个没有 .md 的库行，归档不变量（文件集合 == 窗口日期集合）当场
    #     破掉，而没有任何东西会报错。
    #   · 直接 `write_text` 是「截断原文件再写」：写到一半失败会让**上一版**
    #     日报变成半截文件——而 docs/digests/ 是**归档**，它唯一的价值就是完整。
    #     所以先写 `.md.tmp` 再用 `Path.replace` 原子改名（同目录内改名，
    #     Windows 上也是原子的）。
    #
    # 落盘失败 ⇒ 事务回滚 ⇒ 库行与文件都没有，且异常照常抛给调用方
    # （CLI 转成非零退出 + LAST-ERROR），重跑 `vigil digest --date <day>` 即可。
    with store.transaction(conn):
        stats.digest_id = store.save_digest(
            conn,
            window_from=stats.window_from,
            window_to=stats.window_to,
            body_md=body,
            model=model,
            prompt_ver=prompt_ver,
            item_ids=item_ids,
            commit=False,
        )
        if write_file:
            path = out_dir / f"{day_label}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(body, encoding="utf-8", newline="\n")
            tmp.replace(path)
            stats.output_path = str(path)
    return stats
```

> ⚠️ `newline="\n"` **必须保留**——`digest.py:925-934` 的 docstring 记着原因：Windows 默认 CRLF 会让**文件字节 ≠ `body_md` 字节**，而归档不变量要求两者逐字节相等。

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_digest.py -p no:warnings -q
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:warnings -q
```
期望：全绿——特别是既有的 `test_digest_preview_equals_body_actually_written`（比对预览与真实落盘正文的那条），它证明 `body` 一个字节都没变。

- [ ] **Step 5: 词表核对（M2-4 digest 侧，**改之前先量**）**

先把当天所有用户可见的文案里出现「丢弃 / 筛掉 / 保留」的地方列出来：

```bash
cd D:/github/VIGIL && grep -n "丢弃\|筛掉\|规则保留" vigil/digest.py
```

对每一处，按 §三 3.6 的词表判断用词是否正确，**把表贴进报告**（位置 / 现用词 / 应收词 / 是否要改）。判定规则：

- 指「一步没出本机」的 → **本地筛掉**
- 指「真正出网」的 → **送模型**
- 指「通过预筛的」 → **候选**
- 指 `screen_stats.dropped`（硬规则判死）的 → **规则硬丢弃**
- **一律不许出现「本地丢弃」**；**一律不许用「其中」连接「规则硬丢弃」与「本地筛掉」**

> ⚠️ **`screening_breakdown`（`digest.py:696-732`）与其调用方的用词大概率已经是对的**——它的 docstring 记录了两次修复轮次，且 `tests/test_digest.py:1565` 已经在断言 `local + sent == total`。**量完如果发现无需改动，就如实报告"无需改动"，不要为了交差去改文案。** 改了反而会动到已被 `test_digest.py` 钉死的字符串。
> ⚠️ 若确实要改，改完**必须**跑全量测试，并且**在报告里列出改动的字符串前后对照**。

- [ ] **Step 6: 变异反证**

| # | 变异 | 期望变红 |
|---|---|---|
| M1 | `_persist` 里 `store.save_digest(..., commit=False)` 的 `commit=False` 删掉 | 你 Step 1 写的那条 |
| M2 | `tmp.replace(path)` 换成 `path.write_text(body, ...)` | 应当**仍然全绿**（这是**阳性对照**：说明 Step 1 的测试是靠提交顺序红的，不是靠"临时文件"这个实现细节）。若 M2 红了，说明你的测法钉在了实现细节上，报告里要写明 |

- [ ] **Step 7: 提交**

```bash
cd D:/github/VIGIL && git add vigil/digest.py tests/test_digest.py && git commit -m "fix(digest): 写库与落盘同一事务——落盘失败不再留下没有文件的日报行" && git show --stat HEAD
```

---

### Task 7（波 3）：每日管线 `vigil/daily.py`

**Files:**
- Create: `vigil/daily.py`
- Test: `tests/test_daily.py`

**Interfaces:**
- Consumes:
  - `vigil/logs.py` 的 `emit`（Task 1）
  - `vigil/export.py::export(config, key, *, on_progress) -> ExportStats`（已存在）
  - `vigil/refine.py::refine(config, *, api_key, db_path, ..., on_progress) -> RefineStats`（签名不变；Task 5 只改内部）
  - `vigil/digest.py::digest(config, *, api_key, db_path, since, until, day_label, ..., on_progress) -> DigestStats`、`yesterday()`、`day_window(day)`（已存在）
- Produces: §三 3.3 的 `StageResult` / `RunReport` / `run(...)`。**T8 消费它们，签名逐字不许改。**

**Dependencies:** Task 1、Task 5（波 1/2，已完成）
**Touches:** `vigil/daily.py`、`tests/test_daily.py`

**为什么单独一个模块而不是塞进 `cli.py`**：`cli.py` 已经 526 行、60 处输出；把三阶段编排塞进去会让它变成两个职责。分开还有个直接好处：`run()` 只做编排与记账，**不碰日志配置、不碰锁、不碰退出码**——于是它可以用假的三阶段纯本地测试，而"加锁/落日志/退出码"归 `cmd_daily`（Task 8）。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_daily.py`：

```python
"""每日管线的编排测试。

⚠️ 三个阶段全部被 monkeypatch 成假的——本文件**不调模型、不碰真库**。
测的是编排语义：失败判据、跳过规则、最坏状态、账目。
"""

from __future__ import annotations

import pytest

from vigil import daily


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
    report = daily.run(config=object(), key="k", llm_key="l",
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
    report = daily.run(config=object(), key="k", llm_key="l",
                       day="2026-09-16", on_progress=lambda *_: None)

    assert calls == ["export", "refine"], "digest 必须被跳过"
    assert not report.ok
    assert "export" in report.last_error
    skipped = [s for s in report.stages if s.name == "digest"]
    assert skipped and not skipped[0].ok and skipped[0].skipped_reason


def test_export_raises_is_also_a_failure(wired):
    calls, plan = wired
    plan["export"] = RuntimeError("QQ 库路径没了")
    report = daily.run(config=object(), key="k", llm_key="l",
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
    report = daily.run(config=object(), key="k", llm_key="l",
                       day="2026-09-16", on_progress=lambda *_: None)
    assert calls == ["export", "refine", "digest"]
    assert not report.ok
    assert "429" in report.last_error


def test_digest_failure_is_reported(wired):
    _, plan = wired
    plan["digest"] = _digest_stats(errors=["模型调用失败: 超时"])
    report = daily.run(config=object(), key="k", llm_key="l",
                       day="2026-09-16", on_progress=lambda *_: None)
    assert not report.ok
    assert "超时" in report.last_error


def test_default_day_is_yesterday(wired):
    from vigil.digest import yesterday

    report = daily.run(config=object(), key="k", llm_key="l",
                       on_progress=lambda *_: None)
    assert report.deadline == yesterday()


def test_progress_goes_through_the_given_sink(wired):
    lines: list[str] = []
    daily.run(config=object(), key="k", llm_key="l",
              day="2026-09-16", on_progress=lines.append)
    text = "\n".join(lines)
    assert "export" in text and "refine" in text and "digest" in text
    assert "2026-09-16" in text
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_daily.py -p no:warnings -q
```
期望：`ModuleNotFoundError: No module named 'vigil.daily'`。

- [ ] **Step 3: 写实现**

创建 `vigil/daily.py`：

```python
"""每日管线：export → refine → digest，一条命令跑完，失败看得见。

存在的理由（spec §4.8 / §5 M4）：任务计划每天调一次，产出当天该有的日报。
拆成三条独立命令由调度器串起来是**不行**的——任务计划不保存输出，
三个任务各自的成败、各自的耗时、各自的错误会散成三份互相不知情的东西，
而"那天到底跑成了没有"恰恰是无人值守唯一要回答的问题。

⚠️ **本模块只管编排**：不配置日志、不加锁、不定退出码。那三件事归
`cli.cmd_daily`——这样 `run()` 可以用假的三个阶段纯本地测试，而那三件事
（要碰文件系统、要拿进程级锁、要决定退出码）各自单独验。

失败语义见 `run()` 的 docstring，那是本模块唯一需要记住的东西。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from . import digest as digest_mod
from . import export as export_mod
from . import logs
from . import refine as refine_mod
from .config import Config

STAGE_EXPORT = "export"
STAGE_REFINE = "refine"
STAGE_DIGEST = "digest"


@dataclass(frozen=True)
class StageResult:
    """一个阶段的结局。`skipped_reason` 非空表示"因上游失败而跳过"。"""

    name: str
    ok: bool
    detail: str
    skipped_reason: str = ""


@dataclass(frozen=True)
class RunReport:
    """一次 daily 的完整账目。全部进日志，失败时进 LAST-ERROR.txt。"""

    stages: tuple[StageResult, ...] = ()
    last_error: str = ""
    deadline: str = ""
    # 阶段名 → 该阶段话术里用到的计数，纯给日志/排障看
    counters: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.stages)


def _summarize(results: list[StageResult]) -> tuple[str, dict[str, str]]:
    """把失败的阶段拼成一句人话 + 一份计数表。"""
    failed = [r for r in results if not r.ok]
    last_error = "；".join(f"{r.name}: {r.detail}" for r in failed)
    counters = {r.name: r.detail for r in results}
    return last_error, counters


def run(
    *,
    config: Config,
    key: str,
    llm_key: str,
    day: str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> RunReport:
    """跑一轮完整管线。**任何阶段失败都不抛异常**——全部记进返回值。

    ⚠️ 为什么不抛：`daily` 的调用方是任务计划，它唯一能看的只有退出码。
    一个抛到顶的异常只会留下一个 traceback，而这轮"跑到哪一步、产出多少"
    全部丢失。所以这里把每个阶段都圈起来，**失败也继续**，最后一次性汇报。

    ⚠️ 捕宽 `Exception` 的前提是**可见**：每一条失败都进 `StageResult`
    → 进 `RunReport.last_error` → 由 CLI 写进 `LAST-ERROR.txt` 并返回非零。
    静默吞异常在本项目是不可接受的（M1/M3 反复记录）。

    失败语义（冻结，见计划 §三 3.3）：

    ========  ==============================  ==========================
    阶段      失败判据                        对后续的影响
    ========  ==============================  ==========================
    export    ``failed_groups`` 非空，或抛异常  **跳过 digest**（见下）
    refine    ``errors`` 非空，或抛异常         digest 照跑
    digest    ``errors`` 非空，或抛异常         ——
    ========  ==============================  ==========================

    **export 失败为什么跳过 digest**：export 失败 ⇒ `messages` 不完整 ⇒
    日报那句「当天 N 个群 M 条消息」可能读起来像"这天很安静"，而其实是
    "根本没读进来"。这个项目已经抓过四次同一句假话的不同变体（见 M2/M3
    的「只说自己有资格说的话」），不能让它有第五个入口。
    """
    emit = on_progress or logs.emit
    day = day or digest_mod.yesterday()
    since, until = digest_mod.day_window(day)

    results: list[StageResult] = []
    emit(f"═══ vigil daily 开始 · 日报窗口 {day} ═══")

    # ── 阶段 1：export ────────────────────────────────────────────────
    emit(f"[daily] 1/3 export：从 QQ 本地库导出到 {config.output_db}")
    export_failed = False
    try:
        est = export_mod.export(config, key, on_progress=emit)
        if est.failed_groups:
            export_failed = True
            who = "、".join(str(gid) for gid, _ in est.failed_groups[:5])
            detail = (
                f"{len(est.failed_groups)} 个群整群读不到（{who}…），"
                f"其余 {len(est.per_group)} 个群共 {est.total_rows:,} 条消息"
            )
        else:
            detail = f"{len(est.per_group)} 个群，共 {est.total_rows:,} 条消息"
            if est.total_skipped:
                # 坏页读不到是**已知且非致命**的（QQ 库物理损坏），照实说
                detail += f"（另有 {est.total_skipped:,} 条因 QQ 库坏页读不到）"
        results.append(StageResult(STAGE_EXPORT, not export_failed, detail))
    except Exception as exc:  # noqa: BLE001 — 见 docstring：记下并继续
        export_failed = True
        results.append(StageResult(STAGE_EXPORT, False, f"抛出异常：{exc}"))
        emit(f"[daily] export 失败：{exc}")

    # ── 阶段 2：refine ────────────────────────────────────────────────
    emit("[daily] 2/3 refine：把消息提炼成结构化条目")
    try:
        rst = refine_mod.refine(
            config,
            api_key=llm_key,
            db_path=config.output_db,
            prompt_ver=refine_mod.PROMPT_VERSION,
            model=refine_mod.DEFAULT_MODEL,
            on_progress=emit,
        )
        if rst.errors:
            detail = (
                f"扫描 {rst.scanned:,} 条 → 送模型 {rst.sent_messages:,} 条"
                f"（{rst.batches} 批）→ 产出 {rst.items_saved} 条；"
                f"{len(rst.errors)} 批出错"
            )
            results.append(StageResult(STAGE_REFINE, False, detail))
        else:
            detail = (
                f"扫描 {rst.scanned:,} 条 → 送模型 {rst.sent_messages:,} 条"
                f"（{rst.batches} 批）→ 产出 {rst.items_saved} 条"
            )
            results.append(StageResult(STAGE_REFINE, True, detail))
    except Exception as exc:  # noqa: BLE001
        results.append(StageResult(STAGE_REFINE, False, f"抛出异常：{exc}"))
        emit(f"[daily] refine 失败：{exc}")

    # ── 阶段 3：digest ────────────────────────────────────────────────
    if export_failed:
        why = "export 失败 ⇒ messages 不完整，日报的「这天安静」判据不可信"
        emit(f"[daily] 3/3 digest：跳过（{why}）")
        results.append(
            StageResult(STAGE_DIGEST, False, f"已跳过：{why}", skipped_reason=why)
        )
    else:
        emit(f"[daily] 3/3 digest：合成 {day} 的日报")
        try:
            dst = digest_mod.digest(
                config,
                api_key=llm_key,
                db_path=config.output_db,
                since=since,
                until=until,
                day_label=day,
                model=digest_mod.DEFAULT_MODEL,
                on_progress=emit,
            )
            if dst.errors:
                detail = "；".join(dst.errors)
                results.append(StageResult(STAGE_DIGEST, False, detail))
            else:
                detail = (
                    f"{dst.groups} 个群 {dst.messages:,} 条消息 → "
                    f"{dst.items} 条 item → 日报 {dst.lines} 行"
                )
                if dst.output_path:
                    detail += f"，已落 {dst.output_path}"
                results.append(StageResult(STAGE_DIGEST, True, detail))
        except Exception as exc:  # noqa: BLE001
            results.append(StageResult(STAGE_DIGEST, False, f"抛出异常：{exc}"))
            emit(f"[daily] digest 失败：{exc}")

    last_error, counters = _summarize(results)
    report = RunReport(
        stages=tuple(results), last_error=last_error,
        deadline=day, counters=counters,
    )

    emit("─── 本轮小结 ───")
    for r in report.stages:
        mark = "✓" if r.ok else "✗"
        emit(f"  {mark} {r.name}: {r.detail}")
    emit("═══ vigil daily 结束：" + ("全部成功" if report.ok else "有失败") + " ═══")
    return report
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_daily.py -p no:warnings -q
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:warnings -q
```

- [ ] **Step 5: 变异反证**

| # | 变异 | 期望变红 |
|---|---|---|
| M1 | 把 `if export_failed:` 那个分支去掉（export 失败也跑 digest） | `test_export_failure_skips_digest_but_still_refines` |
| M2 | 把 refine 阶段的 `try/except` 去掉 | `test_export_raises_is_also_a_failure` 不受影响，但 `plan["refine"] = ...` 那两条会变成抛异常 → 红 |
| M3 | `RunReport.ok` 改成 `return True` | 所有 `assert not report.ok` 的条目 |

- [ ] **Step 6: 提交**

```bash
cd D:/github/VIGIL && git add vigil/daily.py tests/test_daily.py && git commit -m "feat(daily): 三阶段串成一条命令——逐阶段记账、失败继续、export 失败即跳过 digest" && git show --stat HEAD
```

---

### Task 8（波 3）：CLI 接线——`daily` 子命令、退出码、日志落点、词表

**Files:**
- Modify: `vigil/cli.py`
- Test: `tests/test_cli.py`（新建）

**Interfaces:**
- Consumes: `logs.emit/setup/clear_last_error/write_last_error/prune_old_logs`（T1）、`lock.SingleInstance/AlreadyRunning`（T4）、`daily.run/RunReport`（T7）、`RefineStats.candidates`（T5）
- Produces: `vigil daily` 这个 CLI 入口（T2 的 `.cmd` 调用它）+ §三 3.4 的退出码。**签名与退出码逐字不许改**——T2 的文档已按此写。

**Dependencies:** Task 1、Task 4、Task 7
**Touches:** `vigil/cli.py`、`tests/test_cli.py`

本任务四件事：

**(1) 退出码语义（**这是 M4 最核心的一处**）**：`cmd_export` 与 `cmd_refine` 今天**无条件 `return 0`**，即使打了 `[失败]`。退出码是任务计划**唯一**能看见的信号（§二 发现 4）。

**(2) `print` → `logs.emit`**：管线命令的输出要同时落到日志文件。`emit` 先 `print` 原文再写日志，所以 stdout 一字不变。

**(3) `daily` 子命令**：配日志 + 清 LAST-ERROR + 加锁 + 调 `daily.run` + 按结果写 LAST-ERROR 与退出码。

**(4) M2-4 词表在 CLI 侧的落点**：`cmd_refine` 的汇总行。**「其中」必须消失**。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_cli.py`：

```python
"""CLI 层的退出码与接线。

⚠️ 退出码是 M4 的**核心交付**：任务计划就只能看见这一个数。所以这里
每一条都在钉"什么时候返回几"，而不是钉输出文字。
"""

from __future__ import annotations

import pytest

from vigil import cli


def test_export_returns_nonzero_when_a_group_could_not_be_read(tmp_path, monkeypatch):
    """⭐ export 有整群读不到 ⇒ 非零。

    实测旧实现（M4 规划期）：`cmd_export` 结尾无条件 `return 0`，
    即使它自己刚打了 `[失败] N 个群整群读不到`。任务计划看到的是成功。
    """
    ...
    # 用本仓库既有的 CLI 测试手法（master 里 tests/test_digest.py 的
    # `cli_env` 夹具就是现成的样板）造出配置与库，让 export 报 failed_groups。
    # 断言 rc != 0 且输出里有「失败」。


def test_refine_returns_nonzero_when_batches_errored(...):
    """⭐ refine 有批次出错 ⇒ 非零（且**汇总行仍然打出来**）。"""
    ...


def test_refine_still_prints_summary_before_returning_nonzero(...):
    """汇总行必须在 return 之前——否则失败时日志里没有本次的计数。"""
    ...


def test_daily_returns_2_when_another_instance_holds_the_lock(monkeypatch):
    """⭐ 已有实例在跑 ⇒ 退出码 **2**（§三 3.4 冻结）。

    2 不是 1：无人值守下「上一次还没跑完」只要等着就行，「这次跑失败了」
    要人来看。用同一个码会把这两件事混成一件。
    """
    from vigil import lock

    monkeypatch.setattr(cli.logs, "setup", lambda **kw: None)
    monkeypatch.setattr(cli.logs, "clear_last_error", lambda: None)
    monkeypatch.setattr(cli.logs, "prune_old_logs", lambda **kw: [])

    def boom(*a, **kw):
        raise lock.AlreadyRunning("已有实例在跑（锁：x；上次写入：pid=123）")

    monkeypatch.setattr(cli.lock, "SingleInstance", boom)

    rc = cli.main(["daily"])
    assert rc == 2


def test_daily_writes_last_error_and_returns_1_on_failure(monkeypatch):
    """⭐ 有阶段失败 ⇒ 写 LAST-ERROR.txt + 退出码 1。"""
    written = {}
    monkeypatch.setattr(cli.logs, "setup", lambda **kw: None)
    monkeypatch.setattr(cli.logs, "clear_last_error", lambda: None)
    monkeypatch.setattr(cli.logs, "prune_old_logs", lambda **kw: [])
    monkeypatch.setattr(
        cli.logs, "write_last_error",
        lambda msg, **kw: written.setdefault("msg", msg),
    )
    monkeypatch.setattr(cli.lock, "SingleInstance", _null_ctx)

    from vigil.daily import RunReport, StageResult

    monkeypatch.setattr(
        cli.daily_mod, "run",
        lambda **kw: RunReport(
            stages=(StageResult("export", False, "2 个群整群读不到"),),
            last_error="export: 2 个群整群读不到",
            deadline="2026-09-16",
        ),
    )

    rc = cli.main(["daily"])
    assert rc == 1
    assert "2 个群整群读不到" in written["msg"]


def test_daily_returns_0_on_success(monkeypatch):
    monkeypatch.setattr(cli.logs, "setup", lambda **kw: None)
    monkeypatch.setattr(cli.logs, "clear_last_error", lambda: None)
    monkeypatch.setattr(cli.logs, "prune_old_logs", lambda **kw: [])
    monkeypatch.setattr(cli.logs, "write_last_error", lambda *a, **kw: None)
    monkeypatch.setattr(cli.lock, "SingleInstance", _null_ctx)

    from vigil.daily import RunReport

    monkeypatch.setattr(cli.daily_mod, "run", lambda **kw: RunReport(deadline="2026-09-16"))
    assert cli.main(["daily"]) == 0
```

> ⚠️ `...` 那几条与 `cli_env`、`_null_ctx` 是**占位**——`tests/test_digest.py` 里已有一套完整的"造配置 + 造库 + 调 `cli.main`"样板（夹具名 `cli_env`，见 `tests/test_digest.py:1458` 附近），**照抄那一套**，别新造。`_null_ctx` 自己写三行（一个 `__enter__`/`__exit__` 都返回 `None` 的假上下文管理器）即可。

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_cli.py -p no:warnings -q
```
期望：红（`daily` 子命令不存在 → `argparse` 报错退出；退出码用例全红）。

- [ ] **Step 3: 改 `vigil/cli.py`**

**(a) 顶部 import** 加：

```python
from . import lock, logs
```

**(b) 机械替换**：把 `cmd_export` / `cmd_refine` / `cmd_digest` / `cmd_daily` 这四个函数体里的 **`print(` 全部换成 `logs.emit(`**。
**`cmd_groups` / `cmd_read` / `cmd_who` / `cmd_media` / `cmd_deadline_audit` / `cmd_serve` 一律不动**——它们是人工即时查询，永不无人值守，让它们也往日志里灌只会把日志淹掉。

```bash
# 先看清有多少处、分布在哪些行（本任务只动前四个函数）
cd D:/github/VIGIL && grep -n "print(" vigil/cli.py
```

**(c) 管线调用传 `on_progress=logs.emit`**：`cmd_refine` 里 `refine_mod.refine(...)` 与 `cmd_digest` 里 `digest_mod.digest(...)` 各加一个关键字参数：

```python
            on_progress=logs.emit,
```

`cmd_export` 的调用同理：`export_mod.export(config, key, on_progress=logs.emit)`。

**(d) `cmd_export` 的退出码**（`cli.py:130` 那句 `return 0`）：

```python
    if stats.failed_groups:
        # ⚠️ 非零退出码是 M4 自动化的报警信号——别吞掉。旧版这里无条件
        # return 0，于是「N 个群整群读不到」在任务计划看来是**成功**。
        # 坏页（skipped_by_group）**不算失败**：那是 QQ 库的物理损坏，
        # 已知、非致命、且同群其余消息不受影响，上面已经照实报了。
        return 1
    return 0
```

**(e) `cmd_refine` 的汇总行**（`cli.py:264-269`）—— **M2-4 词表在 CLI 侧的落点**：

```python
    shown_batches = stats.batches_planned if args.dry_run else stats.batches
    # ⚠️ 三个数必须**自洽**：本地筛掉 + 送模型 == 扫描。
    # ⚠️ **不许用「其中」**连接「规则硬丢弃」与「本地筛掉」——两者**不是**
    # 包含关系：`prefilter.expand_context` 取 ±2 邻居时不看那条消息有没有
    # 被硬规则判死，所以被判死的消息照样可能作为上下文出网
    # （`digest.py:713-720` 的 docstring 记着这条，并且正是因此把"硬丢弃"
    # 计数从日报文案里删掉了）。旧版写「（其中硬丢弃 N 条）」——实测在真库上
    # 是假话。这里改用「；」并列，两个数各自独立。
    logs.emit(
        f"完成：扫描 {stats.scanned:,} 条 → 本地筛掉 "
        f"{stats.scanned - stats.sent_messages:,} 条"
        f" → 送模型 {stats.sent_messages:,} 条（{shown_batches:,} 批）"
        f"（候选 {stats.candidates:,} 条；规则硬丢弃 {stats.discarded_local:,} 条）"
    )
```

**(f) `cmd_refine` 的退出码**（原 `cli.py:291` 的 `return 0`）：

```python
    if args.dry_run:
        logs.emit("（--dry-run：未调用模型、未写库）")
        return 0
    # ⚠️ 非零退出码是 M4 自动化的报警信号——别吞掉。旧版无条件 return 0，
    # 于是「3 批出错」在任务计划看来是成功。
    return 1 if stats.errors else 0
```

> ⚠️ 注意顺序：`--dry-run` 仍然返回 0（它本来就不该有错误），而**汇总行必须在 `return 1` 之前**——旧版 `cmd_digest` 就是踩了这个（见下）。

**(g) `cmd_digest` 的退出码位置**（`cli.py:331-335`）：把那段提前 `return 1` 的代码改成**先报错、再走完汇总、最后统一返回**：

```python
    # ⚠️ 失败**不再提前 return**：提前返回会让日志里只有一句「[失败]」，
    # 而没有本次的计数——事后根本判断不出这轮跑到哪、抓到几条。所以先报错，
    # 汇总照打，最后由这一处统一给退出码。
    for err in stats.errors:
        logs.emit(f"[失败] {err}")

    logs.emit(
        f"完成：{stats.day} 窗口内 {stats.groups} 个群 {stats.messages:,} 条消息"
        f" → {stats.items} 条 item → 日报 {stats.lines} 行"
    )
    # ……… 中间那些 `[注意]` 行原样保留 ………
    if args.dry_run:
        logs.emit("（--dry-run：未调用模型、未写库、未落文件）")
        return 0

    logs.emit(f"token 用量：输入 {stats.input_tokens:,} / 输出 {stats.output_tokens:,}")
    if stats.output_path:
        logs.emit(f"日报文件：{stats.output_path}")
    else:
        logs.emit("（--no-write：只入库，未落文件）")
    # ⚠️ 非零退出码是 M4 自动化的报警信号——别吞掉
    return 1 if stats.errors else 0
```

**(h) 新增 `cmd_daily`**（放在 `cmd_digest` 之后）：

```python
def cmd_daily(args) -> int:
    """每日管线。任务计划的入口——见 docs/SETUP-自动化.md。

    ⚠️ **加锁是在这里、不是在 daily.run() 里**：锁是**进程级**关注点，
    而 run() 只做编排。分开也让 run() 能在测试里不碰文件系统。
    """
    from . import daily as daily_mod

    logs.setup()
    # 开跑就清 LAST-ERROR：于是「文件存在」⟺「本次跑失败过」（见 logs 的 docstring）
    logs.clear_last_error()
    logs.prune_old_logs()

    try:
        config = load_config()
    except ConfigError as exc:
        logs.emit(f"[配置错误] {exc}")
        logs.write_last_error(f"配置错误：{exc}")
        return 1
    key = load_key()
    if not key:
        msg = "没有数据库密钥（.env 里的 VIGIL_DB_KEY）"
        logs.emit(f"[配置错误] {msg}")
        logs.write_last_error(msg)
        return 1
    llm_key = load_llm_key()
    if not llm_key:
        msg = "没有 LLM 密钥（.env 里的 SILICONFLOW_API_KEY）"
        logs.emit(f"[配置错误] {msg}")
        logs.write_last_error(msg)
        return 1

    try:
        with lock.SingleInstance():
            report = daily_mod.run(
                config=config, key=key, llm_key=llm_key, day=args.date,
            )
    except lock.AlreadyRunning as exc:
        # ⚠️ 退出码 2 不是 1：无人值守下「上一次还没跑完」只要等着就行，
        # 「这次跑失败了」才要人来看。详见计划 §三 3.4。
        logs.emit(f"[跳过] {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 — 顶层兜底，必须留痕
        logs.emit(f"[失败] daily 未预期地抛出：{exc!r}")
        logs.write_last_error(f"daily 未预期异常：{exc!r}")
        return 1

    if not report.ok:
        logs.write_last_error(report.last_error)
        return 1
    return 0
```

**(i) 注册子命令**（在 `p_digest` 之后，`args = parser.parse_args(argv)` 之前）：

```python
    p_daily = sub.add_parser(
        "daily", help="每日管线：export → refine → digest（任务计划入口）"
    )
    p_daily.add_argument("--date", help="日报日期 YYYY-MM-DD（默认昨天）")
    p_daily.set_defaults(func=cmd_daily)
```

**(j) `load_llm_key` 的 import**：`cli.py` 顶部已从 `.config` 导入 `ConfigError, load_config, load_key`，加上 `load_llm_key`：

```python
from .config import ConfigError, load_config, load_key, load_llm_key
```

- [ ] **Step 4: 跑测试，确认通过**

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest tests/test_cli.py -p no:warnings -q
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:warnings -q
```

**⭐ 全量测试是这一步最关键的判据**：`tests/test_digest.py` 里约 10 处 `capsys` 断言**必须原样通过**。它们红了就意味着 `emit` 没有保持 stdout 原文（那是 T1 的契约）或者你在替换时改了文案。**若红了，先查这两条，不要改那些测试。**

- [ ] **Step 5: 变异反证**

| # | 变异 | 期望变红 |
|---|---|---|
| M1 | `cmd_export` 的 `if stats.failed_groups: return 1` 删除 | export 退出码那条 |
| M2 | `cmd_refine` 的 `return 1 if stats.errors else 0` 改回 `return 0` | refine 退出码那条 |
| M3 | `cmd_daily` 里 `except lock.AlreadyRunning: ... return 2` 改成 `return 1` | `test_daily_returns_2_when_another_instance_holds_the_lock` |
| M4 | `cmd_daily` 里 `logs.write_last_error(report.last_error)` 那行删掉 | `test_daily_writes_last_error_and_returns_1_on_failure` |
| M5 | `cmd_refine` 汇总行里把「本地筛掉」改回「其中」式表述（`（其中规则硬丢弃 {stats.discarded_local:,} 条）`） | **应当仍然全绿**——这是**阳性对照**：说明本项目没有一条测试守着这句文案，所以它当初才敢是假话。**报告里必须明确写出这一条**（"此文案零覆盖"是个要带进接力文件的事实，不是缺陷） |

- [ ] **Step 6: 提交**

```bash
cd D:/github/VIGIL && git add vigil/cli.py tests/test_cli.py && git commit -m "feat(cli): daily 子命令 + 退出码语义 + 日志落点 + refine 汇总行词表（M2-4）" && git show --stat HEAD
```

---

## 六、阶段④ 冒烟 = M4 出口证据

> **在波 4 由 controller 亲自做**，不派 implementer。冒烟抓到的 bug 立即走 scoped fix（真实数据破坏优先，不等最终 review）。

### 6.0 前置（**做任何事之前先做这一步**）

```bash
cd D:/github/VIGIL && cp data/vigil.db "data/vigil.db.bak-m4-smoke-$(date +%Y%m%d-%H%M%S)" && ls -la data/vigil.db.bak-m4-smoke-*
```

并记下**冒烟前的基线**（这些数字在 6.4 要对比）：

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run python -c "
import sqlite3
c = sqlite3.connect('file:data/vigil.db?mode=ro', uri=True)
for t in ('messages','items','refine_runs','item_sources','digests','digest_items'):
    print(f'{t:14s}', c.execute(f'select count(*) from {t}').fetchone()[0])
print('digests 窗口', [r[0:2] for r in c.execute('select window_from,window_to from digests')])
c.close()"
ls docs/digests/
```

### 6.1 出口标准 3：人为制造一次失败 → `LAST-ERROR.txt` 有记录

**做法**：临时把 `config/groups.toml` 的 `qq_db_dir` 改成一个不存在的路径，**手工**触发一次（**不**用 `schtasks /run`，先把脚本链路单独验）：

```bash
cd D:/github/VIGIL && cmd //c "scripts\vigil-daily.cmd" ; echo "退出码=$?"
cat data/logs/LAST-ERROR.txt
ls -la data/logs/
```

**通过判据**（四条都要）：

| # | 判据 | 期望 |
|---|---|---|
| 1 | 退出码 | **非 0** |
| 2 | `data/logs/LAST-ERROR.txt` | **存在**，第一行是失败摘要（含"QQ 数据库目录不存在"之类） |
| 3 | `data/logs/vigil-YYYY-MM-DD.log` | **存在**且非空，含本次的 traceback 或错误行 |
| 4 | 日报**没有**被写出来 | `docs/digests/` 的文件集合与基线一致（export 失败 ⇒ digest 被跳过，见 §三 3.3） |

> 第 4 条是**语义判据**，不是形式判据：它证明「export 失败 ⇒ 跳过 digest」真的生效，而不是只写了个 `if`。

验完**把 `qq_db_dir` 改回去**。

### 6.2 出口标准 2：日志完整

正常跑一次（真库、真 QQ 路径）：

```bash
cd D:/github/VIGIL && cmd //c "scripts\vigil-daily.cmd" ; echo "退出码=$?"
cat data/logs/LAST-ERROR.txt 2>/dev/null && echo "（不该存在！）" || echo "LAST-ERROR.txt 不存在 ✓"
```

**通过判据**：日志文件里能按顺序读到 `═══ vigil daily 开始` → 三个阶段各自的起始行 → 本轮小结的三行 `✓/✗` → `═══ vigil daily 结束`，且**每条都有时间戳**。把日志原文贴进报告。

### 6.3 出口标准 1 + 3（真任务计划）：短触发器自触发

按用户裁定：注册正式每日任务后，**另设一个 2 分钟后的触发器**，然后什么都不做。

```powershell
# 1) 先撤掉临时触发器（若有），再注册正式的
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/register-task.ps1

# 2) 加一个一次性触发器，2 分钟后
$t = Get-Date "00:00"; $when = (Get-Date).AddMinutes(2)
schtasks /change /tn "VIGIL每日管线" /ri 1 /du 0000:02   # 仅作示例；实际用下面的 XML 或 /sc ONCE 方式
```

> ⚠️ **实现提示**：`schtasks` 命令行**没有**"插入一个临时触发器"的开关。最干净的两种做法，**执行时二选一并在报告里写明用了哪种**：
> - **A（推荐）**：临时把正式任务的 `/st` 改到 2 分钟后（`schtasks /change /tn ... /st HH:MM`），观察它自触发一次，然后**改回 08:00**。
> - **B**：用 `Register-ScheduledTask` + `New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2)` 单独建一个临时任务，验完删掉。

**通过判据**：

| # | 判据 | 怎么取 |
|---|---|---|
| 1 | 任务真的被注册 | `schtasks /query /tn "VIGIL每日管线" /v /fo LIST` 原文 |
| 2 | **到点自己跑起来**（全程无人敲键盘） | 到点后 `Get-ScheduledTaskInfo -TaskName "VIGIL每日管线" \| Format-List LastRunTime,LastTaskResult,NextRunTime` |
| 3 | 日志里有本轮 | `data/logs/` 里当天文件出现新的 `═══ vigil daily 开始` 段，**时间戳与触发器时间吻合** |
| 4 | 产出日报 | `docs/digests/<昨天>.md` 存在，且库里有对应的 `digests` 行 |
| 5 | 磁盘上的文件与库里的 `body_md` **逐字节相等** | 见 6.4 |

### 6.4 归档不变量 + 幂等三连跑（**M4 最重要的机械判据**）

**(a) 归档不变量**（接力文件原文：「`docs/digests/` 的文件集合 == 库里 `digests` 的窗口日期集合，且文件与 `body_md` 逐字节相等」）:

```bash
cd D:/github/VIGIL && PYTHONDONTWRITEBYTECODE=1 uv run python -c "
import sqlite3, pathlib, datetime as dt
c = sqlite3.connect('file:data/vigil.db?mode=ro', uri=True)
rows = list(c.execute('select window_from, body_md from digests order by window_from'))
c.close()
files = sorted(p.stem for p in pathlib.Path('docs/digests').glob('*.md'))
inbase = sorted(dt.datetime.fromtimestamp(w).strftime('%Y-%m-%d') for w, _ in rows)
print('磁盘文件 :', files)
print('库里窗口 :', inbase)
print('集合相等 :', files == inbase)
bad = [d for (w, body), d in zip(rows, inbase)
       if pathlib.Path(f'docs/digests/{d}.md').read_text(encoding='utf-8') != body]
print('字节相等 :', not bad, bad)
"
```

三条都要 `True`。

**(b) 幂等三连跑**——**在副本上做，绝不在真库上**：

```bash
cd D:/github/VIGIL && WORK=$(mktemp -d) && cp data/vigil.db "$WORK/v.db" && echo "$WORK"
# 三次跑 refine（同一个副本，不带 --redo），每次记 items 计数
for i in 1 2 3; do
  PYTHONDONTWRITEBYTECODE=1 uv run python -c "
import sqlite3, sys
c = sqlite3.connect(r'$WORK/v.db')
print('第 $i 次前 items =', c.execute('select count(*) from items').fetchone()[0]); c.close()"
done
```

> ⚠️ **务必用副本**：在真库上跑 refine 会走真模型、花真钱，而且会不可逆地刷新 `refine_runs.refined_at`（M2 记录在案的禁忌）。副本里**没有待处理消息**（真库已经全抽过了），所以三连跑应当**全部 0 变化**——这正是「幂等可重入」的机械证据。若副本里还剩待处理消息（说明真库有积压），那就用 `--limit` 圈小一点，但**必须在报告里写清用了哪个范围**。

**通过判据**：三次的 `items` / `item_sources` / `refine_runs` 计数**逐次相同**，且与第一次之前相同。

### 6.5 M2-7 的真数据唤醒（**只验不改**）

人为造一次**部分覆盖**，看日报那句限定是不是真的出现且对：

```bash
cd D:/github/VIGIL && WORK=$(mktemp -d) && cp data/vigil.db "$WORK/v.db" && echo "$WORK"
# 在一个**还没抽完**的窗口上跑 digest，看正文的 stat_line
```

**通过判据**：日报正文里出现 `（仅抽取了 X/Y）`，且 **X/Y 与 `window_refine_coverage` 的值一致**（把两者都贴进报告对比）。若该窗口本来覆盖率就是 100%，就人为构造一个（例如把副本里某个窗口的若干 `refine_runs` 行改回 `error` 状态）——**构造手法必须写进报告**。

> 这一条**不需要改任何代码**（§二 发现 6）。它验的是"真数据下这句话对不对"。

### 6.6 冒烟报告的形态要求

写进 `.superpowers/sdd/2026-09-16-vigil-m4-automation/smoke-report.md`，并且：

- **每一格都注明证据形态**（进程输出 / 文件内容 / 任务计划查询原文 / 手工构造）
- **「已验」不等于「已通过」的项一律标 ⏸**
- **连续 24 小时那条标 ⏸**，并写明它只被验到"触发器能自触发一次"这一层

---

## 七、自审三件套

### 7.1 spec 覆盖对照

| spec 要求 | 落在哪个任务 |
|---|---|
| §4.8「任务计划程序，每日定时 export → refine → digest」 | T2（注册）+ T7（编排）+ T8（入口） |
| §4.8「日志落文件 `data/logs/vigil-YYYY-MM-DD.log`」 | T1 |
| §4.8「失败可见：非零退出」 | T8（(d)(f)(g) 三处 + `cmd_daily`） |
| §4.8「失败可见：`LAST-ERROR.txt`」 | T1（写）+ T8（调）+ T2（`.cmd` 兜底） |
| §4.8「幂等可重入：三次跑不产生重复 items」 | T4（锁，防并发重复）+ T5（事务，防崩溃重复）+ §六 6.4（机械验证） |
| §5 M4「挂机 24 小时无人干预，产出至少一篇日报」 | §六 6.3（短触发器自触发）+ **⏸ 24h 部分待用户确认** |
| §5 M4「日志完整」 | §六 6.2 |
| §5 M4「人为制造一次失败，确认 `LAST-ERROR.txt` 有记录」 | §六 6.1 |
| §6 0.7「补日志模块」 | T1 |
| 用户裁定：M3-1 | T3 |
| 用户裁定：M3-2 | T5（(d)(h)） |
| 用户裁定：M2-3 | T5（(a)(c)） |
| 用户裁定：M2-4 | T5（e）+ T6（Step 5）+ T8（(e)） |
| 用户裁定：M2-7 | §六 6.5（**只验不改**） |
| §二 发现 8（`groups.toml` 注释与实现矛盾） | T2 Step 6 |

**没有 spec 要求悬空。**

### 7.2 占位符扫描

本计划里出现的"待补"字样**只有两类，且都是刻意的**：

1. **T6 Step 1 的测试体**与 **T8 Step 1 的两条测试**——因为它们的注入手法**必须照抄同文件里既有的夹具**（新造一套会与既有夹具打架），而既有夹具的名字只有 implementer 打开那个文件才知道。**这不是"实现留给后来人"，是"接口由既有代码决定"**：计划明确要求 implementer 报告用了哪些既有夹具。
2. **§六 6.3 的触发器做法**——两种方案在计划里都写全了，执行时二选一。

除此之外**没有** TBD / TODO / "加适当的错误处理" / "类似 Task N"。

### 7.3 跨任务类型一致性（**波级窄审查专核这一项**）

| 符号 | 定义处 | 使用处 | 一致？ |
|---|---|---|---|
| `logs.emit(message: str) -> None` | T1 | T7（`on_progress` 默认）、T8（全部输出） | ✓ |
| `logs.setup/clear_last_error/write_last_error/prune_old_logs` | T1 | T8 `cmd_daily` | ✓ |
| `lock.SingleInstance` / `lock.AlreadyRunning` | T4 | T8 `cmd_daily` | ✓ |
| `store.transaction(conn)` | T5 | T5（refine）、T6（`_persist`） | ✓ |
| `store.save_digest(..., commit=False)` | T5 | T6 `_persist` | ✓ |
| `save_items/record_run(..., commit=)` | T5 | T5 | ✓ |
| `RefineStats.candidates: int` | T5 | T7（日志）、T8（汇总行） | ✓ |
| `StageResult` / `RunReport` / `daily.run(*, config, key, llm_key, day, on_progress)` | T7 | T8 `cmd_daily` | ✓ |
| 退出码 `0/1/2` | §三 3.4 | T2 文档、T4 异常、T8 CLI | ✓ |
| 词表（本地筛掉 / 送模型 / 候选 / 规则硬丢弃） | §三 3.6 | T5、T6、T8 | ✓ |

> ⚠️ **T6 与 T5 同波**，所以上表里 `store.transaction` / `save_digest(commit=False)` / `RefineStats.candidates` 三行是**波内跨任务接口**——这是 `Mode: wave` 下唯一允许的形式：接口在计划里冻结、两边逐字照抄。**波级窄审查第一件事就是核这三行。**



