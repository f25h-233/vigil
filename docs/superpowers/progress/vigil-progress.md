# VIGIL 进度接力 — M4 完成 / M5 待启动

> **钩子：新会话先读此文件，再读 `docs/superpowers/specs/2026-09-13-vigil-product-layer-design.md`（§8.1 与 §9）。**
> 最后更新：2026-09-16　｜　M4 模式：SDD **wave**（三波 3/2/3，p 全 0）　｜　仓库：`https://github.com/f25h-233/vigil`（private）

---

## 一句话

**M4「自动化」完成——spec §5 三条出口标准 ①②③ 全部通过**（②③ 由 PC 侧实测；① 的「产出日报」与「无人干预」都实测通过，
**只有「连续 24 小时」标 ⏸ 待你确认**）。下一步按 spec 走 **M5**：**前端可编辑 + 多维筛选**（范围见 §四）。

---

## 当前工作区的真实状态（**以此为准，别凭印象**）

```
HEAD      8eadda3（已推 origin/master，与远端同步、零遗留）
tests     422 passed（M3 收尾时是 328）
data/vigil.db
  messages     49,434      items      325      refine_runs 49,434    item_sources 325
  digests           5      digest_items 34
docs/digests/  2026-08-08 / 09-11 / 09-12 / 09-13 / **09-15**（M4 产出的第一篇）
data/logs/     vigil-2026-09-16.log（LAST-ERROR.txt 已被成功运行清掉）
任务计划       VIGIL每日管线 · Next Run 2026/9/17 08:00 · Status Ready
真库备份       data/vigil.db.bak-m4-smoke-20260916-165727
```

**归档不变量**（M4 起每天追加，这是「归档是否完整」的唯一机械判据）：

> **`docs/digests/` 的文件集合 == 库里 `digests` 的窗口日期集合，且文件与 `body_md` 逐字节相等。**

⚠️ **这条现在对 git 免疫了**（`.gitattributes` 给 `docs/digests/*.md` 定了 `text eol=lf`，M4 终审 U-6），
**但跑该判据前仍不要做会重新检出这些文件的 git 操作**——注记在计划 §6.4(a)。

---

## 一、M4 交付了什么

| 命令 / 产物 | 说明 |
|---|---|
| `vigil daily` | **每日管线入口**：`export → refine → digest` 一条命令；逐阶段记账、失败继续、返回最坏状态 |
| `scripts/vigil-daily.cmd` | 任务计划的入口（ASCII-only；含"Python 没起来"的兜底） |
| `scripts/register-task.ps1` | 幂等注册任务（`VIGIL每日管线`，每日 08:00） |
| `vigil/logs.py` | 日志：按日轮转文件 + `LAST-ERROR.txt` + `emit`（stdout 原文 + 文件带时间戳） |
| `vigil/lock.py` | 单实例锁（OS 级字节范围锁，**强杀后由内核回收**） |
| 退出码契约 | `0` 成功 / `1` 失败或参数配置错误 / **`2` 已有实例在跑（不是错误）** |
| 写入原子化 | `items`+`refine_runs` 同一事务；`save_digest` 的 DELETE/INSERT 同一事务 |

**出口证据全文**：`.superpowers/sdd/2026-09-16-vigil-m4-automation/smoke-report.md`
（每格注明**证据形态**；`review-final.md` 是终审报告）。

---

## 二、⏭ 带进 M5 的遗留（**按优先级**）

### 1. ⭐ **`items` 无批内去重**（用户裁定「记进 M5，本轮不动」）

真库 325 条 items 里有 **1 组重复**：`item 290` 与 `item 296` **同标题、同 `event_ts`、同群**，
`created_at` **同秒** ⇒ 同一次 `save_items` ⇒ **同一批**，且**来源是同一条消息**
（`7685735400902931272`）。

> **机理**：模型在一次响应里把同一条消息抽了两遍，而 `save_items` 没有批内去重。
> `items` 表按设计没有唯一键（防重复**完全**靠 `refine_runs` 记账跟得上）。

**不是 M4 引入的**（M1 时代的缺失），**也不是 spec §4.8 要的「幂等」**（那条验的是"三次**跑**"，已通过）。
**修法方向**：`produced` 落库前按 `(title, event_ts, group_id)` 批内去重（~3 行）；
或给 `items` 加唯一约束——**会与「抽取是视图、不是加工后销毁原件」的既有设计冲突，需权衡**。

### 2. **终审 triage 的「留在下一个里程碑」11 条**

详见 `.superpowers/sdd/.../review-final.md` §四。最值得先做的三条：

| 项 | 说明 |
|---|---|
| **U-4 `groups` 与 `export` 共用 `data/cache/nt_msg_clear.db`** | 两侧都不拥有那个文件；`qqdb.strip_fake_header` 是**就地截断重写**（无临时文件/无原子改名/无锁）。**最坏后果**：导出中途读到被替换的库 ⇒ 分块回退把失败算成 `skipped_count` ⇒ **那部分消息静默消失，还被报告成「QQ 库物理坏页」** |
| **`_MIME` 守卫里 `.lower()` 无判据**（`api.py`） | 现行代码正确，缺的是"大小写变体"的判据 |
| **文档退出码表**与 §三 3.4 的措辞对齐 | 已在终审修复 B 里改过一轮，复核一轮 |

### 3. **⏸ 两条没取到直接证据的**

- **`StartWhenAvailable` 的「睡眠错过 → 唤醒补跑」**：设置值已核实（`<StartWhenAvailable>true</StartWhenAvailable>`），
  **行为未验**（要真让机器睡过触发时刻再唤醒）
- **「连续 24 小时无人干预」**：短触发器自触发已实测通过，连续 24h 待你确认

### 4. **M2/M3 的老清单**：M4 动了 M3-1 / M3-2 / M2-3 / M2-4 / M2-7，其余原样带过来（见 M3 接力）

---

## 三、⭐ M4 最贵的五条教训（**都已进 `vigil-sdd-lessons` 记忆**）

### 1. **「记下来了」不等于「派下去了」——计划的「发现」节必须与「任务」节双向覆盖**

M4 唯一那条 **Critical**（`export.py` 的整群静默消失）**在规划期就被发现、写进了计划 §二 发现 3**，
然后……**它没有变成任何任务**，§7.1 的 spec 覆盖对照表里也没有它。

> 后果：`cmd_export` 退 0、`daily` 跳过 digest 的判据失效、**日报照写**——
> 以「这天很安静」的口气叙述一个**整个群没读进来**的日子，而出口标准①的全部判据都会通过。

**⇒ 下次写计划时：「发现」节里每一条要么有归属任务，要么显式标注"本里程碑不做且因为 X"。**
（这与记忆里那条「已记录的教训不会自动执行」是同族。）

### 2. ⭐ **「判据本身不可信」的五个形态**（本轮一次收齐）

| 形态 | 实例 |
|---|---|
| 变异**存活** | 删掉 `_MIME[".js"]` 后旧测试照样绿（M3-1） |
| **测试装置自带的行为替代了被测行为** | pytest 9.1.1 的 `LogCaptureHandler.handleError` **就是 `raise`** ⇒ 判据单跑红、整文件跑绿（T1 重开） |
| **成功路径根本不调那个东西** | emit 替身测试在成功路径上从不触发 ⇒ 假绿（T8） |
| **变异脚本写错行** | `15 failed` 看着"很有牙"，其实根本没改到目标（T6） |
| **文本替换静默失效** | 在 CRLF 文本里做替换 ⇒ 四条全"符合预期"（终审修复 A） |

**⇒ 纪律升级**：**变异之后、跑测试之前，必须有"替换生效"的锚点断言**——
**光是"打印被改的那几行"不够**（打印出来的东西看着像改了、其实没改）。

### 3. **错的论证留在代码里，比没有论证更危险**

同一条论证我犯了三次：M2-3 的"对称剥离所以不会误归属"**逻辑上被推翻**（反例可构造且实跑成立），
只是**在真实语料上恰好安全**（全库 47,719 条，新增歧义簇 = 0）。
⇒ 裁定结果站得住，但**理由必须换成"实测"，并写明"日后扩大字符集必须重跑同一测量"**。

### 4. **「设置写对了」≠「行为对了」**（T2 的电源设置那条）

`<StartWhenAvailable>true</StartWhenAvailable>` 是**设置正确**；
「睡眠错过之后真的会补跑」是**行为正确**。**两件事要分开取证**——
前者 `/xml` 一读就有，后者要真睡一夜。

### 5. **为了并发安全而加的锁，会把测试变成环境相关的**

F4 给人工命令也上了锁之后，`cli_env` 那批用例**碰到了真实的 `data/vigil.lock`**。
后果：**"恰好有实例在跑"时那些测试会拿到退出码 2 而莫名变红**，
且红的 5 条名字里全写着"退出码""密钥"——**看着像产品缺陷**。
已由 `tests/conftest.py` 的 autouse 夹具挡住（并把 `LOCK_PATH` 指向 `tmp_path`）。

---

## 四、M5 范围（**用户 2026-09-16 口头裁定，规划期第一件事是确认**）

| # | 功能 | 需要先定的 |
|---|---|---|
| 1 | 前端「**新增监视群号**」 | **会打破 M3 的机械不变量**（"绝不让 Web 侧写 `data/vigil.db`"，靠 `mode=ro`）。要回答"Web 侧能写什么"——写 `config/groups.toml` 是最省的（可不碰 DB）。<br>⚠️ **实际后果**：下次 `export` 会拉一整批新群的历史 → 慢、走 LLM、可能整群读不到。**M4 的日志/LAST-ERROR/非零退出正是让这件事看得见的东西** |
| 2 | 前端「**新增监视人物**」 + 「按人物筛选」 | ✅ **语义已裁定**：`items.actor_uid` = 源消息发信人（`refine.py:234`）= **发布人**，不是"信息是关于谁的"。用户明确接受 ⇒ **零重抽成本** |
| 3 | 类目**多选**（维度内并集） | 设计已清楚：`kind IN (...)` |
| 4 | 人物维度**跨维度交集** | `kind IN (...) AND actor_uid IN (...)`——维度内并集、维度间交集，不与类目体系冲突 |

**API 现状**：`/api/items` 的 `kind` 是**单值** `str | None`，要改成多值。

---

## 五、已经铺好的路：怎么跑 / 怎么重启

```bash
cd D:/github/VIGIL && uv run vigil serve --host 127.0.0.1 --port 8787   # 后端 + 前端静态托管
tailscale serve --bg 8787                                               # 手机 HTTPS 入口
# 手机：https://f15h.tail324373.ts.net

uv run vigil daily          # 手动跑一次完整管线（任务计划跑的是 scripts/vigil-daily.cmd）
Get-ScheduledTaskInfo -TaskName "VIGIL每日管线" | Format-List LastRunTime,LastTaskResult,NextRunTime
tail -40 data/logs/vigil-$(date +%Y-%m-%d).log
```

**Tailscale 的坑**：`tailscale serve --bg 8787` 会**静默挂死 90 秒**（默认 HTTPS、卡在等证书）。
诊断：`tailscale cert f15h.tail324373.ts.net`（回 `does not support getting TLS certs`）。
解法：<https://login.tailscale.com/admin/dns> → HTTPS Certificates → Enable（**已于 2026-09-16 开启**）。

**⚠️ 任务计划的两个坑**（M4 实测）：
1. **`schtasks /change /tn … /st HH:MM` 会弹密码提示并挂死**（实测卡死 180s）。
   可用替代：`Set-ScheduledTask -Trigger`，且 **`StartBoundary` 必须设未来时间**
   （`StartWhenAvailable=true` 会让过去时刻立刻补跑一次完整管线）。
2. **含中文的 `.ps1` 必须 UTF-8 BOM**——无 BOM 时任务名被**静默**注册成乱码，且**伪装成"注册成功"**。

---

## 六、SDD 执行方式（**M5 直接沿用**）

- **模式按任务边界算**：M4 用 wave 三波（3/2/3），**p 全为 0、零越界**。
  但**真实并行度只由写者表决定**——M4 三波分别只有 3/2/3 条道，不是"wave 更好"。
  **M5 若只有 Python 一条链或有共享文件，就回 pipeline。**
- **每任务 = brief → implementer → 审查 → 裁决 → fix → scoped re-review → 波级同步点**。
- **派发时必带**（M1–M4 血泪，前 13 条见 M3 接力，M4 新增）：

  14. ⭐ **「打印被改的那几行」不够**——必须有**可判定的锚点断言**（"替换生效"），
      否则打印出来的东西看着像改了、其实没改
  15. ⭐ **副本里跑测试只设 `PYTHONPATH` 不够**：`sys.path[0]=''`（cwd）**优先于**它。
      **先 `cd` 进副本**并**断言 `vigil.<模块>.__file__` 的父目录就是副本根**，不满足就停
  16. ⭐ **计划里的「发现」节必须与「任务」节双向覆盖**（见 §三 教训 1）
  17. **brief 里的变异也要能在真实代码上跑起来**——写变异前先看目标函数的实际形状
  18. **controller 给的代码片段/判据本身也会错**——M4 实测 **6 次**：
      假绿判据、会削弱覆盖的替换片段、自相矛盾的约束、与冻结接口不符的要求……
      **implementer 按实际修正并报告 = 正解，不记偏差**

- **模型分配实测**：转录型 implementer 用 haiku/sonnet；**小 fix diff 的 scoped 复审用 haiku 足够**
  （M4 实测产出不逊 sonnet，还做了 AST 证明与数字核对）；**最终全分支审查用 opus**。

---

## 七、关键文件地图

| 路径 | 内容 |
|---|---|
| `vigil/daily.py` | **M4 主体**：三阶段编排 + `RunReport`（失败语义见其 docstring） |
| `vigil/logs.py` | 日志。**`emit` 的契约是「写不进就抛」**，靠 `handleError` 裸 `raise` 实现 |
| `vigil/lock.py` | 单实例锁。**锁偏移是 `1_000_000` 不是 0**（Windows 强制锁会让另一句柄**读不了**被锁字节） |
| `vigil/cli.py` | 四个写库命令**各持锁**；退出码 `0/1/2` |
| `scripts/` | 任务计划三件套 |
| `docs/SETUP-自动化.md` | 安装/验证/排障 |
| `vigil/store.py` | `transaction()`（**`commit()` 在 `try` 里**）+ `save_*` 的 `commit=` 参数 |
| `vigil/refine.py` | 批次写入同一事务；**成功话术在 `try` 之外**（否则报进度失败会把 ok 改记成 error） |
| `.gitattributes` | `docs/digests/*.md text eol=lf` —— **归档不变量的免疫层** |
| `.superpowers/sdd/2026-09-16-vigil-m4-automation/` | ledger（R1–R85）+ `review-final.md` + **`smoke-report.md`**（本地过程记忆，不入库） |
| `docs/superpowers/plans/2026-09-16-vigil-m4-automation.md` | M4 计划。**§八 是执行期增补与作废表——读它，别照抄计划里的代码块** |

---

## 八、未尽事项

- §二 的 M5 遗留（1 条数据缺陷 + 11 条 triage + 2 条 ⏸）
- `.superpowers/` 与 `_smoke/` 均**不入库**，是本地过程记忆
- `/tmp` 下累积了 M1–M4 的过程产物（约数百 MB，含几个 71–217 MB 的临时 db）；
  **C 盘紧张时值得清**，但**删之前先确认不是某个在跑的实验的输入**

---

## 九、方法论沉淀（详见记忆 `vigil-sdd-lessons`，已含 M1–M4）

**M4 最贵的五条**见 §三。其中**最值得记住的是第 1 条**——
它说明「审查层」也有结构性的盲区：**没有哪个任务拥有它，就没有任何审查会看它**。
