# VIGIL 进度接力 — M1 完成 / M2 待启动

> **钩子：新会话先读此文件，再读 `docs/superpowers/specs/2026-09-13-vigil-product-layer-design.md`。**
> 最后更新：2026-09-14 深夜　｜　M1 模式：SDD **wave**（M2 建议改 **pipeline**）

---

## 一句话

**M1「抽取引擎」完成——出口标准机械项 + 人工项全部达标（分类准确率 95 / 100）。**
下一步是按 spec §4.6 写 M2 计划。

---

## 当前工作区的真实状态（**以此为准，别凭印象**）

```
data/vigil.db        （跑全量前的备份：data/vigil.db.bak-20260914-2225）
  messages     47,719        ← 完整
  items           270        ← 全量产出，全部 Qwen/Qwen3.5-35B-A3B / prompt_ver=v2
  refine_runs  47,719        ← 覆盖 100.00%，差 0；失败批次 0
  item_sources    270
tests: 138 passed
```

---

## 暂无待办 —— M1 已判过

`M1-验收抽样.md` 里用户填了 **95 / 100**。**这个文件是验收证据，别覆盖。**
后续若改了 `config/categories.toml` 或提示词，要按同样流程重出材料重判：

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/vigil.exe refine          # 全量重跑
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe vigil_exit_check.py
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe vigil_acceptance.py --n 100 --m 20 > 新抽样.md
```

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/vigil.exe refine          # 全量重跑
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe vigil_exit_check.py
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe vigil_acceptance.py --n 100 --m 20 > M1-验收抽样.md
```

---

## 已定的事（**不用重做**）

### 模型 = `Qwen/Qwen3.5-35B-A3B`，**思考必须关**

`llm.DEFAULT_MODEL` 已改，`refine(enable_thinking=False)` 已是默认值，
CLI 加 `--think` 可打开（用于对比实验）。

**关思考是硬前提**，同批 30 条实测：

| 模型 | `enable_thinking:false` | 不传该字段（默认） |
|---|---|---|
| `Qwen3.5-35B-A3B` | **2.8s** / 220 输出 tok | **111.5s** / 11,124 tok |
| `Qwen3.5-27B` | 10.5s / 513 tok | **153.3s** / 6,823 tok |
| `Qwen3-32B` | 11.3s / 373 tok | 21.4s / 781 tok |
| `Qwen3-14B` | 6.7s / 249 tok | 7.2s / 249 tok（默认就不思考） |

→ **Qwen3.5-4B 那 30 条 `read operation timed out` 的真因就是这个**：
不是模型弱，是思考默认开着拖穿 180s 超时。原推测正确。

### 六模型对照结果（5,604 条 / 41 批 / 提示词 v2 / 关思考）

| 模型 | 产出 | 询问类 | 引用匹配率 | 中位延迟 | **总延迟** | 成本 |
|---|---|---|---|---|---|---|
| **Qwen3.5-35B-A3B** | 57/58 | 1 (2%) | 98% | **1.4s** | **64s** | ¥0.038 |
| Qwen3.5-27B | 55/55 | 0 (0%) | 100% | 3.5s | 179s | ¥0.052 |
| Qwen3-32B | 66/69 | 4 (6%) | 96% | 3.5s | 221s | ¥0.072 |
| Qwen3-14B | 64/67 | 4 (6%) | 96% | 4.1s | 187s | ¥0.033 |
| Qwen2.5-32B（旧基准） | 62/63 | 2 (3%) | 98% | 4.6s | 191s | ¥0.063 |
| Qwen2.5-7B | 56/58 | 0 (0%) | 97% | 1.2s | 259s | 免费 |

**选它的唯一硬理由**：快 3–4 倍。**已知代价**：它会补出原文没有的实体
——「9.11左右截止」它归成「编辑部」，而上下文发信人是「技术部朱泓烨」。

### 全量跑结果（317 批 / 0 失败）

```
扫描 47,719 → 本地筛掉 38,447（含硬丢弃 5,069）→ 送模型 9,272
产出 270 条 ｜ 输入 363,033 / 输出 31,933 token
```

**270 条是合理的，别怀疑**：按月归一化 7 月 0.36 / 8 月 0.52 / 9 月 1.10 条每百条消息，
对照实验窗口（9 月，1.02）与 9 月档一致。历史 32B 那次的 479 条是**旧提示词 v1** 下的数。

---

## 已经通过的出口标准（**不用重做**）

```
1. 「无遗漏」每条消息都有 refine_runs 记录   47,719 / 47,719   ✓
2. 无来源的 items                                            0  ✓
3. 指向不存在消息的来源                                       0  ✓
4. 类目越界（不在 categories.toml 里）                        0  ✓
5. item_sources 重复行                                       0  ✓
6. refine_runs 孤儿行                                        0  ✓
7. 失败批次                                                  0  ✓
8. 无混版（items 全部同一模型 + 同一 prompt_ver）              ✓
9. 分类准确率 ≥ 80%（用户人工判定）               95 / 100    ✓
```

⚠️ 第 9 项的**可回溯部分**（20 条机械核验里 10 条被标 ⚠️）我逐条查过原文：
**8 条是这个保守指标的误报**（「买自行车的来」→「自行车求购/出售信息」这种正确概括），
1 条存疑，**1 条真瑕疵**（#101：detail 内容来自相邻消息，来源却挂在提问那句上）。
真实可回溯率 ~90%+，过。

一条命令复核：`vigil_exit_check.py`

⚠️ **分母要用 `messages` 全量**（含 14 条 `ts=0` 的 `[非文本]` 占位行）。
写成 `WHERE ts>0` 会差出 14 条报**假红**——已踩过。

---

## 本轮抓到的两个坑

### 1. commit message 说「改了」≠ 代码改了

`481dfb9` message 写「提示词加了三条规则」，但 scope 是 `feat(plan)`，
改的是计划文档里内嵌的代码块，**`vigil/refine.py` 一行没动**。
模型继续把「怎么向一卡通里充钱啊」抽成条目。
→ **判据：`git show --stat <commit>` 看文件名，别信 message。**
（修好后 `PROMPT_VERSION` 升到 v2，询问类条目从 17% 降到 2%）

### 2. 自造指标也会假绿

「引用匹配率」看着硬，**却漏掉真正的幻觉**：6 个模型全给它 95%+，
连已知会幻觉的 7B 也 97%——那条幻觉的 quote 是匹配得上的，**引用对 ≠ 摘要对**。
补的「标题重合度」又精度太低（低分尾部几乎全是正确概括）。
→ **机械指标只能排除重故障，排不了质量名次；选优必须人工读并排对照。**

---

## 已完成的任务（**全部已审查通过，不用重做**）

| # | 任务 | commit |
|---|---|---|
| 1 | 测试骨架 + 可执行入口 | `cb54876` |
| 2 | 类目体系 | `c90c28f` |
| 3 | 脱敏 | `c36102c` |
| 4 | 持久化层 | `f91bbef` |
| 5 | 规则预筛与切批 | `73872d4` |
| 6 | SiliconFlow 客户端 | `6235d1b` |
| 7 | 抽取编排与 CLI | `079bc52` |
| — | 历次审查修复 | 20+ 个 commit，见 `git log` |

**模块总览**：`vigil/` 13 个模块 —— 接入层 8 个（export/reader/qqdb/text/senders/media/config/cli）
+ 产品层 5 个（categories/redact/store/prefilter/llm/refine）。

---

## 文件地图

| 路径 | 内容 |
|---|---|
| `vigil_eval.py` | **模型对照实验工具**。`--replay <json>` 可从存档重出报告，不重烧 token |
| `vigil_exit_check.py` | **M1 出口机械核验**，含「禁止混版」检查 |
| `M1-模型评估.md` | 六模型对照报告。**「并排对照」节是选型判读的主材料** |
| `M1-模型评估-promptv1.md/.json` | 修提示词前的基线，用于前后对照 |
| `M1-验收抽样.md` | **待用户判定的 100 条材料** |
| `M1-验收抽样-32B-历史留存.md` | 32B 旧提示词那次的抽样快照 |
| `_probe_think.py` | 思考开关实测（8 次调用并行） |
| `_probe_mutation.py` | 变异反证脚本。**还原走 try/finally**，别用 `cp A /tmp/x \|\| cp`——git bash 下 `/tmp` 存在，`\|\|` 不跑，源码会被留在变异状态（踩过） |
| `docs/superpowers/specs/2026-09-13-vigil-product-layer-design.md` | 产品层 spec（M1–M4） |
| `.superpowers/sdd/2026-09-13-vigil-m1-refine-engine/progress.md` | SDD ledger |

---

## SDD 执行方式（延续）

- **模式：wave**（用户显式指定）。但 M1 的实际经验是——
  **8 个任务粒度太小，不该上 wave**；后两个任务改单任务执行后**快得多**（3.4 分钟 vs 15-30 分钟）。
- **M2 建议走 pipeline**（SDD 默认），除非任务边界真的干净。
- 每任务 = brief → implementer（haiku/sonnet）→ 审查 → 裁决 → 修复 → re-review。
- **派发时必带**：先落盘再补细节、不许改源码做变异、文件级 `git add` + pathspec 提交 + `git show --stat` 自检。

---

## 已知未关闭项

1. **分类准确率 ≥80% 的判定**（需用户）——当前唯一待办
2. `Qwen3.5-35B-A3B` 会补出原文没有的实体（见上「已知代价」）
3. `vigil_eval.py` 的「标题重合度」指标精度太低，若还要用需换成 n-gram 类度量
4. ledger 延迟清单里 ~15 条 Minor，留给最终全分支 review triage
5. **未提交的改动**（用户未要求 commit）：`vigil/{llm,refine,cli}.py`、`tests/test_{llm,refine}.py`、
   `vigil_eval.py`、`vigil_exit_check.py`、`_probe_{think,mutation}.py`、`M1-*.md/json`

---

## 方法论沉淀（详见记忆 `vigil-sdd-lessons`）

1. **测试有效性三陷阱**：假绿 / 假红 / 空守卫——本轮**四次重现**。
   唯一可靠验证是**变异反证**，且**必须看红的原因**是不是被守语义本身。
2. **A/B 实验条件不符则结论不能外推**——我在这上面栽过一次。
3. **LLM 不适合做编号对应**——改为**让它逐字摘录、程序本地匹配**（自校验，且省 token）。
4. **计划写完后真跑一遍自己写的测试代码**——能挡掉约一半缺陷。
5. **commit scope 与 message 不符**——`git show --stat` 看文件名。
6. **自造指标也会假绿**——先用已知正/负例验一遍再拿它下结论。
