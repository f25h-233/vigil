# VIGIL 进度接力 — M1 收尾

> **钩子：新会话先读此文件，再读 `docs/superpowers/specs/2026-09-13-vigil-product-layer-design.md`。**
> 最后更新：2026-09-14 晚　｜　模式：SDD **wave**（用户显式指定）

---

## 一句话

**M1「抽取引擎」八个任务全部实现并过审**（32 commit、135 tests passed），
唯一的尾巴是 **Task 8 冒烟验收**，卡在**模型选型**与**分类准确率判定**上。

---

## 当前工作区的真实状态（**以此为准，别凭印象**）

```
data/vigil.db
  messages     47,719        ← 完整，未被破坏
  sender_names  5,542
  msg_media     7,144
  items             2        ← 只剩模型测试残留；32B 那次的 479 条已被清掉
  refine_runs     931
tests: 135 passed
工作区: 干净（最后 commit 481dfb9）
```

⚠️ **`items` / `refine_runs` 现在几乎是空的**——为测 Qwen3.5-4B 清过表。
重跑一次即恢复（全量约 30 分钟、35 万输入 token）。

---

## 立即要做的三件事

### ① 定模型（**当前唯一阻塞项**）

同窗口（`--since 2026-09-12`，1,050 条消息）实测：

| 模型 | 产出 | 问题 | 输入 token |
|---|---|---|---|
| `Qwen/Qwen2.5-7B-Instruct` | 15 条 | **1 条纯幻觉**（标题与来源完全无关） | 13,520 |
| `Qwen/Qwen2.5-32B-Instruct` | **23 条** | 无幻觉，逐条核对正确 | 13,520 |
| `Qwen/Qwen3.5-4B`（用户推荐，**免费**） | **2 条** | **30 条消息因超时丢失**（`error: 30`，全是 `read operation timed out`） | — |

**未做完的实验**：单独测一批、给足超时（180s），分辨 Qwen3.5-4B 是「慢」还是「弱」。
- 只是慢 → 调大 `LLMConfig.timeout` 可能就能用（免费且新）
- 真弱 → 用 32B

### ② 分类准确率验收（**需用户本人**）

spec 出口标准：**抽样 100 条人工验收分类准确率 ≥ 80%**。

- 工具已就绪：`vigil_acceptance.py --n 100 --m 20`
- **`M1-验收抽样.md`（仓库根）是 32B 那次运行的抽样快照**——
  该次数据已被清掉，此文件是唯一留存，可直接读
- 用户观察：**「纯询问」被误归为「通知公告」**，价值低应丢弃

### ③ 改完提示词后重跑 + 重验

提示词刚加了「纯询问/提问不产出」规则（commit `481dfb9`），**尚未在任何真实运行中生效**。

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/vigil.exe refine --model <选定的模型>
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe vigil_acceptance.py --n 100 --m 20 > 验收.txt
```

---

## 已经通过的出口标准（**不用重做**）

```
refine_runs 覆盖 47,719 / 47,719 = 100.00%，差 0   ✓ spec 要求「无遗漏」
无来源的 items: 0                                  ✓
指向不存在消息的来源: 0                             ✓
可追踪性 20 条机械核验                              ✓（5 条「可疑」逐条人工看全对）
32B 全量：479 条 item，输入 353,680 / 输出 44,628 token
```

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
| `docs/superpowers/specs/2026-09-13-vigil-product-layer-design.md` | **产品层 spec**（M1–M4，用户已审阅） |
| `docs/superpowers/plans/2026-09-13-vigil-m1-refine-engine.md` | **M1 计划**（八任务含完整代码，已被历次审查修正 20+ 处） |
| `.superpowers/sdd/2026-09-13-vigil-m1-refine-engine/progress.md` | **SDD ledger**（恢复地图、裁决记录、方法论，32KB，gitignored） |
| `M1-验收抽样.md` | 32B 运行的抽样快照 |
| `_probe_refine.py` / `_probe_attribution.py` / `_probe_index.py` / `_probe_batch.py` | 诊断脚本，都是证据 |
| `vigil_acceptance.py` | 验收抽样生成器 |

---

## SDD 执行方式（延续）

**模式：wave**（用户显式指定，记于 ledger 首部）。

但 M1 的实测结论是：**8 个任务粒度太小，不该上 wave**——
SDD 自己说「单任务半小时以内禁用 wave」。后两个任务改单任务执行后
**快得多**（3.4 分钟 vs 15-30 分钟）。

→ **M2 建议走 pipeline**（SDD 默认），除非任务边界真的干净。

**派发时必带**（本会话 6 次 agent 断线换来的）：
- 增量落盘：每完成一项就写进报告，不许攒到最后
- 不许 agent 改源码做变异（改由 controller 用带回滚保护的原子命令代劳）
- 文件级 `git add` + pathspec 提交 + `git show --stat` 自检
- 不靠 agent 自述、靠 `git log` 查证

---

## 已知未关闭项

1. **模型选型**（阻塞）
2. **分类准确率 ≥80% 的判定**（需用户）
3. 改 `DEFAULT_MODEL` 默认值——本轮刻意没改，避免为可覆盖的默认值再开一轮 fix
4. ledger 延迟清单里 ~15 条 Minor，留给最终全分支 review triage

---

## 方法论沉淀（详见记忆 `vigil-sdd-lessons`）

1. **测试有效性三陷阱**：假绿 / 假红 / 空守卫——本轮**四次重现**。
   唯一可靠验证是**变异反证**，且**必须看红的原因**是不是被守语义本身。
2. **A/B 实验条件不符则结论不能外推**——我在这上面栽过一次
   （手工构造的窗口通过了，真实管线仍错）。
3. **LLM 不适合做编号对应**——`msg_id` 与序号都不可靠，
   改为**让它逐字摘录、程序本地匹配**（自校验，且省 token）。
4. **计划写完后真跑一遍自己写的测试代码**——能挡掉约一半缺陷。
