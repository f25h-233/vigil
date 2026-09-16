# VIGIL 进度接力 — **M5 计划已就绪，待执行**

> **钩子：新会话先读本文件，然后读这两个（顺序别反）：**
> 1. **spec**：`docs/superpowers/specs/2026-09-16-vigil-m5-m7-design.md`（M5–M7 设计，七条裁定 D10–D16）
> 2. **计划**：`docs/superpowers/plans/2026-09-16-vigil-m5-correctness.md`（**3917 行，含完整代码**）
>
> ⚠️ **第一版 spec（`2026-09-13-…-design.md`）只覆盖 M1–M4，已冻结，不要照它做 M5。**
>
> 最后更新：2026-09-16 深夜　｜　M5 模式：**SDD pipeline**　｜　仓库：`https://github.com/f25h-233/vigil`（private）

---

## 一句话

**M5 的 spec 与计划都写完了、都提交了（`d7f99e9` / `579b2da`），但一个任务都还没派。**
新会话要做的第一件事是**按 pipeline 派 Task 1**，不是重新规划。

**⚠️ M5 的范围在 2026-09-16 晚被用户扩大过一次**——从 4 条功能变成 **12 条功能、拆成 M5/M6/M7 三个里程碑**。
本文件 §四 里的「M5 范围」是**旧的**，**以新 spec 为准**。

---

## 一、当前工作区状态（**只放关系式，不放会漂的计数**）

> ⚠️ **M4 起每日管线每天 08:00 自己跑**，`messages`/`items`/`digests` **每天自己涨**。
> 本文件**刻意不写任何计数**——M4 收尾就踩过一次（写完 40 分钟就过期）。
> 要用就现查：`uv run vigil ...` 或 `sqlite3 file:data/vigil.db?mode=ro`。

```
HEAD          579b2da（M5 计划）—— 在 master 上，未推 origin
tests         uv run pytest -q      （M4 收尾时 422 passed；M5 未动代码，应当不变）
任务计划       VIGIL每日管线 · 每日 08:00（`schtasks /query /tn "VIGIL每日管线" /v /fo LIST`）

不随时间漂的三条关系式：
  ① 归档不变量：docs/digests/ 的文件集合 == 库里 digests 的窗口日期集合，且逐字节相等
     （`.gitattributes` 给 docs/digests/*.md 定了 text eol=lf —— 这条对 git 免疫）
  ② Web 侧不写 data/vigil.db（M3 立，M5 的 D11 把它**精确化**为「可写 config/ 与
     data/overrides.db，不可写 data/vigil.db」）
  ③ M5 之后新增：`items` 的可见集合 = 库里的行 − overlay 里软删的（见 §三）
```

---

## 二、⏭ 现在该做什么（**按顺序，别跳**）

1. **读** `docs/superpowers/specs/2026-09-16-vigil-m5-m7-design.md` 的 §1（现状实测）与 §2（七条裁定）
2. **读** `docs/superpowers/plans/2026-09-16-vigil-m5-correctness.md` 的**头部**（Global Constraints 10 条 + File Structure）与**尾部**（自审三件套 + §执行方式）
3. **确认 ledger 还在**：`.superpowers/sdd/2026-09-16-vigil-m5-correctness/progress.md`
   ——⚠️ **它在 `.superpowers/` 下，是 git-ignored 的本地文件**。若不存在，重建一个（内容看计划尾部即可，**不必重读 3917 行**）
4. **`/SDD pipeline`**，从 **Task 1** 开始：`task-brief` → implementer → `review-package` → reviewer 双裁决 → 裁决 → fix → scoped re-review

**计划里已写死、新会话不许改的四件事：**

- **模式是 pipeline 不是 wave**。理由（写者表）：`vigil/store.py` 被 **T3 / T5 / T8 / T9 四个任务**写，
  且 T5 改 `_ITEM_COLS`/`_ITEM_JOINS`、T8 紧接着在同一批函数上加列 ⇒ **T8 必须在 T5 之后**。
- **Task 9 Step 7 是全程最危险的一步**：`vigil repass` 干跑出的清单里若出现
  **item 14 / 84 / 86 / 111 / 143**，**立刻停下报告**——那是 prompt v3 没吃住 D13 的信号。
  计划里写死了：**不许自行调 prompt 消化**。
- **三个不许跳过的变异反证点**：Task 6（墓碑，两遍：变异 + 阳性对照）、
  Task 8 Step 10（D11 守卫反向验证）、Task 2 的四条闸门分支。
- **CRLF 纪律**（Global Constraint 4）：工作区所有源码是 **CRLF**（`store.py` 882/882 全是）。
  变异脚本做文本替换**必须先断言"替换生效"**再跑测试，否则会得到 M4 终审那种
  「四条全『符合预期』」的假绿。

---

## 三、M5 会交付什么（一句话版）

**让 `items` 是对的、且可控。**

| # | 交付 | 关键点 |
|---|---|---|
| T1 | prompt v3 | 加「商业推广 → 不入库」，**判据看消息目的不看词** |
| T2 | 两道要素闸门 | `place` 证据（**2 字子串**）+ `deadline` 时序（不早于消息当天） |
| T3 | `items` 批内去重 | `(title, event_ts, group_id)` 同键合并，**来源取并集** |
| T4 | **人工干预层** | `data/overrides.db`：append-only 事件日志 + 物化 `item_state` |
| T5 | overlay 接 5 处读路径 | **收敛在 `store.py` 查询函数里**，不在消费方打补丁 |
| T6 | 墓碑阻复活 | `refine` 读 overlay，软删条目**永不被 `--redo` 复活** |
| T7 | `config/persons.toml` | **uin 主键**（QQ 号），拒绝匿名哨兵 `uin=0`，原子写 |
| T8 | API 多值 + 人物 + 写端点 | **维度内并集 × 维度间交集**；写端点**只写 overlay** |
| T9 | `vigil repass` | 存量重判，**只删不换** + 字段降级；默认只出清单 |
| T10 | 前端 | 多选类目 / 人物筛选 / 改分类 / 删除 / 撤销 |

---

## 四、M5 之后（**M6 / M7 的范围，别再问用户**）

用户 2026-09-16 已裁定拆三个里程碑：**M5 正确性 → M6 配置 → M7 外观**。
M6/M7 的完整范围在 spec §4.2 / §4.3 与 §5。要点：

**M6「配置从文件走到界面」**：统一配置层 + 导入导出（#6）、LLM 配置（#5）、
群号管理（#3）、**类目编辑 + 撤销 + 重排**（用户追加）、U-4 遗留。

> ⚠️ **M6 有一个必须在计划期就处理的雷**（spec §1.6 实测）：
> `vigil groups` 列群列表靠 `qqdb.strip_fake_header(...)`，它**就地截断重写
> `data/cache/nt_msg_clear.db`**——那正是遗留缺陷 **U-4**，且**与 `export` 共用同一个文件**。
> Web 端点直接复用它 = ① 从后门打破「Web 不写 `data/`」；② 与正在跑的 `export` 抢文件，
> 最坏后果是**部分消息静默消失、还被报告成「QQ 库物理坏页」**。
> **裁定：群列表必须走只读路径，且必须与 U-4 同批解决。**

**M7「外观」**：五套主题（默认 / material design / 粗野主义 / 蒸汽波 / 毛玻璃）。

---

## 五、⭐ 规划期实测推翻的假设（**别再凭印象重来**）

这些是 2026-09-16 写 spec/计划时，用真库与真代码量出来的。**新会话不需要重测，直接采信**：

| # | 我以为是 | 实测是 |
|---|---|---|
| 1 | 噪声是"要加个过滤功能" | **是 spec §4.3 已被违反**：328 条 items 里 46 条（14.0%）来自办卡号；7 月 26% / 8 月 28%。机理：`prefilter.py` 的保留关键词里有「办理」⇒ 单条广告被**保送**进 LLM |
| 2 | 屏蔽那 4 个办卡号就行 | ⛔ **实测否决**：那是**真学生**，还贡献 15 条好条目（早自习时间 / 住宿费 / 抢课通知 / **诈骗提醒**——是卡王本人发的）。**误杀率 1:2** ⇒ D13：**禁止 uid 维度过滤** |
| 3 | `place` 闸门用整串匹配 | 会**误杀 item 40**（源文 `西太湖连隔板` 里有「西太湖」）。改为 **任一 2 字子串命中**：保留 58 / 清掉 8。且**单字 place（item 295 的「湖」）判据不适用 ⇒ 保留** |
| 4 | 真读 `items` 的路径有 8 处 | **5 处**。且 **`digest.py` 根本不直接读 `items`**（走 `store.window_items`）⇒ overlay 的 apply **收敛在 `store.py`**，这是设计改进不是妥协 |
| 5 | `tests/test_refine.py` 要自己造夹具 | **已有** `FakeLLM` / `StubConfig` / `seeded`。`tests/test_api.py` **已有** `db_path` / `client`。**别造第二套** |
| 6 | `search_items(kind=)` 调用点"到处都是" | **只有 2 处**：`vigil/api.py:170`、`tests/test_store.py:842` |
| 7 | 重抽会打断日报引用（R9） | **实测收窄**：46 条广告**零条**被 `digest_items` 引用 ⇒ 删它们安全。但另有 66 条**是**被引用的 ⇒ **不能整批替换**，语义定为「**只删不换**」 |
| 8 | （M6）群列表可以复用 `vigil groups` | ⛔ 见 §四 的雷 |

---

## 六、怎么跑 / 怎么重启

```bash
cd D:/github/VIGIL && uv run vigil serve --host 127.0.0.1 --port 8787   # 后端 + 前端静态托管
tailscale serve --bg 8787                                               # 手机 HTTPS 入口
# 手机：https://f15h.tail324373.ts.net

uv run vigil daily          # 手动跑一次完整管线（任务计划跑的是 scripts/vigil-daily.cmd）
Get-ScheduledTaskInfo -TaskName "VIGIL每日管线" | Format-List LastRunTime,LastTaskResult,NextRunTime
tail -40 data/logs/vigil-$(date +%Y-%m-%d).log

cd web && npm run build     # ⚠️ 前端改完**必须构建**，serve 托管的是 web/dist
```

**Tailscale 的坑**：`tailscale serve --bg 8787` 会**静默挂死 90 秒**（卡在等证书）。
诊断：`tailscale cert f15h.tail324373.ts.net`（回 `does not support getting TLS certs`）。
解法：<https://login.tailscale.com/admin/dns> → HTTPS Certificates → Enable（**已于 2026-09-16 开启**）。

**⚠️ 任务计划的两个坑**（M4 实测）：
1. **`schtasks /change /tn … /st HH:MM` 会弹密码提示并挂死**（实测卡死 180s）。
   替代：`Set-ScheduledTask -Trigger`，且 **`StartBoundary` 必须设未来时间**
   （`StartWhenAvailable=true` 会让过去时刻立刻补跑一次完整管线）。
2. **含中文的 `.ps1` 必须 UTF-8 BOM**——无 BOM 时任务名被**静默**注册成乱码，且**伪装成"注册成功"**。

---

## 七、SDD 执行方式（M5 沿用）

- **模式按写者表算，不按愿望**。M4 用 wave（三波 3/2/3，p 全 0），**M5 回 pipeline**（理由见 §二）。
- **每任务 = brief → implementer → 审查 → 裁决 → fix → scoped re-review**。
- **派发时必带**（M1–M4 血泪，逐条都有实测事件）：

  1. **变异之后、跑测试之前，必须有「替换生效」的锚点断言**——光打印不够
  2. **取对象按类型不按位置**（`handlers[0]` 拿到过 pytest 自己的 handler）
  3. **修正一句"声称"时，先证伪旧的、再证实新的**
  4. **「设置对了」与「行为对了」分开取证**，取不到就标 ⏸
  5. **碰到真实全局资源的测试必须有 autouse 夹具 + 反向验证**（`data/overrides.db` 同此例）
  6. **计划里的「发现」节必须与「任务」节双向覆盖**——M4 的 Critical 就是在规划期
     被发现、写进计划、然后**没有任何任务拥有它**
  7. **副本里跑测试只设 `PYTHONPATH` 不够**：`sys.path[0]=''`（cwd）优先于它。
     先 `cd` 进副本并**断言 `vigil.<模块>.__file__` 的父目录就是副本根**
  8. **controller 给的代码片段/判据本身也会错**（M4 实测 6 次）——
     implementer **按实际修正并报告 = 正解，不记偏差**
  9. **若需求自相矛盾 → 停下报告，不许挑一半照做**（把"驳回 + 出证据"记为**高质量行为**）

- **模型分配**：转录型 implementer 用 haiku/sonnet；小 fix 的 scoped 复审 haiku 够用；
  **最终全分支审查用 opus**。

---

## 八、关键文件地图

| 路径 | 内容 |
|---|---|
| **`docs/superpowers/specs/2026-09-16-vigil-m5-m7-design.md`** | **M5–M7 设计（七条裁定 D10–D16）。这是 M5 之后的权威。** |
| **`docs/superpowers/plans/2026-09-16-vigil-m5-correctness.md`** | **M5 计划，3917 行含完整代码** |
| `.superpowers/sdd/2026-09-16-vigil-m5-correctness/` | ledger + brief + 报告（**git-ignored，本地过程记忆**） |
| `docs/superpowers/specs/2026-09-13-…-design.md` | **第一版 spec，只覆盖 M1–M4，已冻结** |
| `vigil/daily.py` | M4 主体：三阶段编排 + `RunReport` |
| `vigil/logs.py` | **`emit` 的契约是「写不进就抛」** |
| `vigil/lock.py` | 单实例锁。**锁偏移是 `1_000_000` 不是 0** |
| `vigil/store.py` | `transaction()`（**`commit()` 在 `try` 里**）；M5 的 T3/T5/T8/T9 都要改它 |
| `vigil/refine.py` | 批次写入同一事务；**成功话术在 `try` 之外** |
| `vigil/prefilter.py` | 规则预筛。**保留关键词里有「办理」——这就是噪声的机理** |
| `vigil/deadline.py` | `deadline_supported`；M5 的 T2 在这里加 `place_supported` / `deadline_sane` |
| `.gitattributes` | `docs/digests/*.md text eol=lf` —— 归档不变量的免疫层 |
| `docs/SETUP-自动化.md` | 安装/验证/排障 |

---

## 九、未尽事项

- §四 的 M6 雷（`vigil groups` 写 `data/cache/`）与 U-4
- M4 终审 triage 的「留在下一个里程碑」11 条（最值得先做的三条见 M4 接力记录）
- ⏸ 两条没取到直接证据的：`StartWhenAvailable` 的「睡眠错过→唤醒补跑」；
  「连续 24 小时无人干预」
- `.superpowers/` 与 `_smoke/` 均**不入库**，是本地过程记忆
- `/tmp` 下累积了 M1–M5 的过程产物（数百 MB）；**C 盘紧张时值得清**，
  但**删之前先确认不是某个在跑的实验的输入**

---

## 十、方法论沉淀

**M1–M4 的完整教训在记忆 `vigil-sdd-lessons`（含 M4 五条）。**
M5 规划期新增两条，值得单独记：

1. **「计划写好了」≠「有人知道它在哪」。**
   接力文件的钩子是唯一入口；新文件若不被它指向，等于不存在。
   **写完 spec/计划要立刻更新钩子，不要等收尾。**（M4「记下来了 ≠ 派下去了」的入口版。）
2. **测试夹具要先读再写，不能先写后验。**
   规划期我为 Task 6/8 自造了 `_cfg()` / `_client()`，读完真实测试后整段重写——
   约 400 行白写。**"我以为测试长什么样"和"测试长什么样"之间的差距，是纯浪费。**
