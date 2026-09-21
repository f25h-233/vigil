# VIGIL 进度接力 — **M6 已完成并推送，M7 待规划**

> **钩子：新会话先读本文件。** 然后按需读下面三个：
> 1. **M5–M7 spec**：`docs/superpowers/specs/2026-09-16-vigil-m5-m7-design.md`（裁定 D10–D16）
>    —— **它的 §4.3 就是 M7 的范围**；§1.5 是「前端的真实工作量」实测
> 2. **M6 计划**：`docs/superpowers/plans/2026-09-17-vigil-m6-config.md`
>    —— ⚠️ **它有 `## ⚠️ 执行期勘误` 一节（E1–E9 + E7-补 + E8-补），读计划正文前先读它**
> 3. **M6 的过程记忆**：`.superpowers/sdd/2026-09-17-vigil-m6-config/`
>    （**git-ignored 本地**：`progress.md` = ledger；`final-review.md` = 终审；`smoke.md` = 冒烟；
>    每任务的 brief + 报告）
>
> ⚠️ **第一版 spec（`2026-09-13-vigil-product-layer-design.md`）只覆盖 M1–M4，已冻结。**
>
> 最后更新：2026-09-22 上午　｜　仓库：`https://github.com/f25h-233/vigil`（private）
> **HEAD `b03e0a8` 已推 origin/master**

---

## 一、一句话

**M6「配置从文件走到界面」已完成并推送**（11 个任务 / 43 笔提交 / 后端 **844 passed** + 前端 **55 passed**）。
**下次会话要做的是 M7「外观」的规划**——**不是重做 M6**。

---

## 二、当前工作区状态（**只放关系式，不放会漂的计数**）

> ⚠️ **每日管线每天 08:00 自己跑**，`messages`/`items`/`digests` **每天自己涨**。
> **本文件刻意不写计数**——M4 收尾踩过一次，**M5 期间又踩了一次**（08:00 管线把真库从 328 变成 333，清单当场作废）。
> 要用就现查：`uv run vigil ...` 或 `sqlite3 file:data/vigil.db?mode=ro`。

```
HEAD          b03e0a8（已推 origin/master，落后 0 / 领先 0）
测试          uv run pytest（**不加 -q**）→ 844 passed
              cd web && npm test → 55 passed；npm run build → 改前端必跑
任务计划       VIGIL每日管线 · 每日 08:00
              VIGIL网页服务 · 登录时起（2026-09-21 新增，见 §七 侧记）

不随时间漂的关系式：
  ① 归档不变量：docs/digests/ 的文件集合 == 库里 digests 的窗口日期集合，且**逐字节相等**
     （`.gitattributes` 给 docs/digests/*.md 定了 text eol=lf —— 对 git 免疫）
     ⚠️ **M6 收尾时实测仍成立**（11 个文件、逐字节相等）
  ② Web 侧不写 data/vigil.db（D11）。**M6 把它钉得更死**：守卫覆盖**整个 data/ 目录树**
     （不只是主库指纹），且 `/api/config/pack` 与 `PUT /api/llm` 都进了那份端点表
  ③ `items` 的可见集合 = 库里的行 − overlay 里软删的
  ④ `deadline_ts < event_ts` 的条目 = **0**
  ⑤ ⭐ **M6 新增的不变量**：`kind_alias` 表里**不许有 `old_kind ∈ 现存 slug` 的行**
     ⇒ 由 `overrides.prune_kind_aliases` 维持；`reconcile_if_stale` 兜底手改配置
     ⚠️ **它的探测器是「连续失败 ≥3 次升 ERROR」**（进程内）；**进程外仍无仪器**
```

---

## 三、⏭ 现在该做什么

**M6 已经收口。下一步是 M7「外观」的规划**（`/SDD` 从阶段① 写计划开始）。

M7 之前**先读** spec 的 **§4.3**（M7 范围）与 **§1.5**（前端工作量的实测）。

**M6 留下的、M7 或终审 triage 该接手的**：

1. **终审的 4 条 Minor**（F4–F7）：新增契约（`JobRow`/`GroupsResponse`）**没有「字段集冻结」守卫** /
   `api_reorder` 传的是 `create_app` **冻住的 `config`**（改了 tier 不生效）/
   「只带类目的包」是 `parse` 承诺的合法形状而 `import_pack` **必失败** / D11 守卫范围窄
2. **5 条「留下一里程碑」**（`final-review.md` 的 triage 表里）
3. **reorder 的「一条批都没有」早退只报数不说原因**（实现者判为**新功能**，没有偷偷塞进去）
4. **两条 ⚠️ 残余**：跨进程 `ALIAS_LOCK` 毫秒窗；`jobs` 的 **LRU(20)** 让「撤销这次重排」
   有一个**没人说过的上限**
5. ⚠️ **`vigil_acceptance.py`**：M6 才给它补上测试（`tests/test_acceptance.py`）。
   它是**人工验收的仪器**，而 `vigil_exit_check.py` 末尾**明确指引用户跑它**——动它前先看那三条用例

---

## 四、M6 交付了什么 / 出口判据现状（**如实标注，别粉饰**）

| # | 出口判据 | 状态 |
|---|---|---|
| 1 | 网页新增群/人 → 落盘 → **重启后仍在** | ✅ **冒烟 PASS**（界面加真群 + 真 uin + 类目 ⇒ **杀服务重启** ⇒ 三者仍在） |
| 2 | `data/vigil.db` 仍 `mode=ro` + Web 没写过 `data/` | ✅ **冒烟 PASS**（`data/` 文件集合**不多不少**、主文件 + `-wal` sha256 逐字相同） |
| 3 | LLM 配置切自填 `base_url` → refine 与 digest **两处都生效** | ✅ **冒烟 PASS**（假端点收到 6 个请求、`Host: 127.0.0.1:8791`） |
| 4 | 配置包在**另一目录**能导入并生效 | ✅ 由测试覆盖（`tests/test_configpack.py` 的 A/B 双根） |
| 5 | U-4 修复后 `groups` 与 `export` 并发不互相破坏 | ✅ 判据按方法论换成**无计时依赖的 `st_ino`** + 锁的退出码 2 |
| 6 | 类目编辑：加类目 ⇒ refine 认得；删类目 ⇒ 提示 N 条 + 不留悬空 | ✅ **冒烟 PASS**（删 18 条 ⇒ 弹「还有 18 条」；迁移后 **悬空 slug 0 条**） |
| 7 | 重排：`item_id` 前后不变 + 撤销能回到重排前 | ✅ **冒烟 PASS（真 LLM）**：388/388 逐字相同、22 条真变、撤销差异 0 条 |

**十一个任务**：T1 U-4 原子写｜T2 配置序列化层｜T3 LLM 配置｜T4 群快照 + 加群｜T5 类目编辑 + slug 级联｜
T6 重排 + job｜T7 配置包｜T8 前端 DOM 基建｜T9 配置界面｜T10 M5 遗留清理｜T11 重排界面（补遗）。

---

## 五、M5 的出口判据（历史，别再问）

| # | 出口判据 | 状态 |
|---|---|---|
| 1 | 噪声：「生活」卡类 34% → <5% | 🛑 **用户裁定归档** |
| 2 | 误杀为零 | 🛑 **同上归档**（独立探针只 1/2 存活） |
| 3 | 无倒挂死线 | ✅ 0 条 |
| 4 | 人物筛选 | ✅ |
| 5 | 幂等 | ⚪ **随 `--apply` 归档**——**没有对象** |
| 6 | 人工干预层 + `db` 全程 `ro` | ✅ |

**🛑 噪声过滤线的完整归档**：`docs/superpowers/specs/2026-09-17-vigil-filtering-archive.md`
← **涉及噪声/广告的任何问题先读它**。

**M7 / M6 的范围**由用户 2026-09-16 裁定拆分：**M5 正确性 → M6 配置 → M7 外观**。

---

## 六、⭐ M5 实测推翻/确立的关键事实（**别再凭印象重来，也别重测**）

| # | 事实 |
|---|---|
| 1 | ⛔ **「屏蔽办卡号」实测否决**（D13）：那 4 个号是**真学生**，贡献 15 条好条目，**误杀率 1:2** |
| 2 | ⭐ **prompt v3 的探针有一半是受污染的**：真独立的是 **183（主）/ 182（次）** |
| 3 | ⭐ **「重判」可能根本不是重判**：`repass` 在稀疏集上建批（中位 **1**）而 `refine` 在密批（中位 **30**） |
| 4 | ⭐ **「整批返回空」≠「逐条判死」**：39 个空批的候选条数**中位 8**，与非空批一样多 |
| 5 | **判决有 10% 量级噪声**：同批逐字节重放 3 次，**10% 条目翻转** |
| 6 | **行尾唯一可信量具是 `git ls-files --eol`**。⛔ `grep -c $'\r$'` 是**静默假阴性** |
| 7 | **`ATTACH 'file:…?mode=ro'` 只在连接带 `uri=True` 时被解析** |
| 8 | **`mode=ro` 连接无法把库转成 WAL** ⇒ WAL 必须在建库时设 |

---

## 七、怎么跑 / 怎么重启

```bash
cd D:/github/VIGIL && uv run vigil serve --host 127.0.0.1 --port 8787   # ⚠️ 已有任务计划自启，别手工起（见下面 2026-09-21 侧记）
tailscale serve --bg 8787                                               # 手机 HTTPS 入口（配置持久，通常不用重跑）

uv run vigil daily          # 手动跑一次完整管线（任务计划跑的是 scripts/vigil-daily.cmd）
uv run vigil downgrade      # 字段降级（默认 --fields deadline；**加 --apply 才写**）
uv run vigil repass         # 存量重判（**只出清单**；⚠️ --apply 已被用户裁定永久不执行）
cd web && npm run build     # ⚠️ 前端改完**必须构建**，serve 托管的是 web/dist
```

**Tailscale 的坑**：`tailscale serve --bg 8787` 会**静默挂死 90 秒**（等证书）。
解法：<https://login.tailscale.com/admin/dns> → HTTPS Certificates → Enable（**已开启**）。

**⚠️ 任务计划的两个坑**：① `schtasks /change … /st` 会弹密码提示并挂死；
用 `Set-ScheduledTask -Trigger` 且 **`StartBoundary` 必须设未来时间**。
② **含中文的 `.ps1` 必须 UTF-8 BOM**（无 BOM 时任务名被**静默**注册成乱码）。

**⭐ 2026-09-21 侧记：网页服务自启/自愈 + 漏天补跑（动 serve 之前读一下）**
- 新任务计划 **`VIGIL网页服务`**（登录时起）：`vigil-serve.cmd` → `serve_supervisor.py` → `uv run vigil serve`。
  **别手工起 serve**（端口被占会 bind 10048）；**别用 `schtasks /end` 当重启**（实测会留孤儿占端口）。
  重启姿势：`netstat -ano | findstr :8787` 拿 PID → `taskkill /F /PID` → 监督器约 1 分钟自动拉起（实测）。
- 手机/浏览器 **502 的语义 = Tailscale 转发活着、后端没起**（当日真因）。监督器：崩溃 60 秒后重启、
  连续 5 次放弃、单实例锁 `data/logs/vigil-serve.lock`（**别删**：删了单实例保护会失效）。
  任务计划自带的 RestartOnFailure **实测不干活**，注册脚本已把它清掉。文档 §十一。
- 漏天补跑 `scripts\digest_backfill.py`（daily 成功后补最近 7 天缺的日报）：上线首跑补出 **09-14、09-19** 两天
  （任务计划补跑**只补最近一次错过的**）。文档 §十二。
- 实测 **QQ 会回灌离线历史**：9/20 的 52 条在机器重开、QQ 跑起来后进库，该日空壳日报被重跑重成真日报。

**⚠️ M6 追加的两条**：
- **`npm run build` 会重写 `web/dist`，而 8787 上那个自启服务正在托管它** ⇒ **前端一构建，线上就是新的**（无发布步骤）
- **`addopts=-q` 叠 `-q` 会变成 `-qq`，吃掉 pytest 的总数行**（排查时别被"没有汇总"骗到）

---

## 八、关键文件地图

| 路径 | 内容 |
|---|---|
| **`docs/superpowers/specs/2026-09-17-vigil-filtering-archive.md`** | **噪声过滤线归档（涉及噪声/广告先读它）** |
| `docs/superpowers/specs/2026-09-16-vigil-m5-m7-design.md` | M5–M7 设计（D10–D16）。**§4.3 = M7 范围** |
| `docs/superpowers/plans/2026-09-17-vigil-m6-config.md` | M6 计划（**含勘误 E1–E9 + E7-补 + E8-补**） |
| `docs/superpowers/plans/2026-09-16-vigil-m5-correctness.md` | M5 计划（含勘误 E1–E11） |
| `.superpowers/sdd/2026-09-17-vigil-m6-config/` | **M6 的 ledger / 终审 / 冒烟 / 每任务 brief+报告**（git-ignored） |
| **`vigil/config.py`** | 三份 toml 的**写侧序列化层**（`toml_str`/`toml_int`/`toml_path`/`save_config`）+ `load_llm_settings` |
| **`vigil/categories.py`** | 类目 load/save/**validate（读写共用）**/`as_dicts` |
| **`vigil/configpack.py`** | **配置包**导入导出（单文件 TOML；不含密钥/overlay；**全有或全无**） |
| **`vigil/groups_snapshot.py`** | **群清单只读快照**——Web 侧唯一数据源（**不需要 DB 密钥**） |
| **`vigil/jobs.py` / `vigil/reorder.py`** | 重排：**进程内** job 注册表 + LLM 重判（**只写 overlay**） |
| **`vigil/overrides.py`** | 人工干预层（D14）+ **`kind_alias`** + `config_snapshots` + `reconcile_if_stale` |
| `vigil/store.py` | **overlay 与 `kind_alias` 的 apply 都收敛在这里**；**`_EFFECTIVE_KIND` 有五个消费点** |
| `vigil/api.py` | 全部端点；**写锁 `write_lock`**；显示路径读不出配置时**降级** |
| `web/src/views/Settings.tsx` | 配置界面五节（群/人物/LLM/类目/重排 + 导入导出） |
| `web/src/test-setup.ts` + `web/src/__tests__/*.dom.test.tsx` | **DOM 测试基建**（T8）+ 5 个组件的用例 |
| `vigil_exit_check.py` / `vigil_acceptance.py` | 两个仪器；**`acceptance` 的判据 M6 才跟上 T5** |
| `.gitattributes` | `docs/digests/*.md text eol=lf` —— 归档不变量的免疫层 |

---

## 九、未尽事项

- §三 的 5 条
- ⚠️ **两条"环境陷阱"**（M5 终审报的，**M6 又各踩了一次**）：
  - **`-shm` 不该进 D11 哈希断言** ⇒ **假红**。M6 实测：去掉 `-shm` 后**变了的集合只有 `{-wal}`**，守卫仍有牙
  - **`monkeypatch.undo()` 会静默拆掉 `tests/conftest.py` 的 autouse 隔离补丁**
    ⇒ M5 实测往真 `data/overrides.db` 写了 9 条事件且**无断言变红**
- ⚠️ **工作区可能不是干净的**：`data/` 与 `config/*.toml` **会被运行中的服务与 08:00 管线改**
  （M6 收尾时 `config/groups.toml` 就被**网页保存过**一次——手写注释按文档说明被生成头部替换）
- `.superpowers/` 与 `_smoke/` 均**不入库**，是本地过程记忆
- `/tmp` 与 `%TEMP%` 下累积了 M1–M6 的过程产物（**数百 MB 到 GB 级**）；
  ⚠️ M6 冒烟留了约 **550 MB** 在 `%TEMP%`（`tmp.Lq8J0DwbEE` / `tmp.IZyhtA6IyJ`）。**清之前先确认没有实验在跑**
- ⚠️ `data/` 下有多条备份（`vigil.db.bak-*`，各 75–80 MB）+ **3.2 GB 的 `data/cache/`**；
  **D 盘当时只剩 24 GB（97% 占用）**——见 M6 勘误 E1

---

## 十、方法论沉淀（**M6 新增，本里程碑最值钱的产出**）

M1–M5 的完整教训在记忆 `vigil-sdd-lessons`。**M6 贡献了三节**：

### 1. ⭐⭐⭐ **空守卫的八格形态**（把 M5 的「五个形态」扩到底）

判据不是"我写了变异反证"，而是「**那个变异真跑过、真的红了、红的还是那条断言**」。

| # | 形态 | M6 的实例 |
|---|---|---|
| 1 | 变异**不会红** | E4：挪 `[settings]` 段序——**TOML 语义本来就搞错了** |
| 2 | 断言**永远到不了** | 我提议的"顶层键恰为 {settings,groups}"断言——`validate_config_raw` **先抛** |
| 3 | 变异**不在执行路径上** | 名叫"端到端"的测试**没调 `refine()`**；T11 的针落在**注释里**的 `reload()` |
| 4 | **红不是那条断言红的** | `no such table` / `SyntaxError` / `TestClient` 默认重抛 / `FileNotFoundError` |
| 5 | ⭐ **变异没打上却报绿** | **针不唯一** / **CRLF 不匹配**——M6 踩了 **6 次** |
| 6 | **断言跑在伤害之前** | T6：判据第一版在 worker 写完之前就断言了 |
| 7 | **守卫互相遮蔽** | 删掉 A 没人红，因为 B 先拦下了 |
| 8 | ⭐ **反证的前置没上场** | 用 `-t` 只跑**探测器自己** ⇒ 被探测的那条**根本没执行** ⇒ **绿不是"没有伤害"，是"这次实验里没有会受伤的对象"** |

**另有独立一维**：一条"传参"测试**必须让「传入值」与「默认值」不同**，否则测不出"有没有传"。

### 2. ⭐⭐ **「错的论证」有五种落脚点**（M6 每一种都出现过）

> **错的论证比没有论证更危险——它让后来者以为自己理解了，于是不去验证。**

| 落脚点 | M6 的实例 |
|---|---|
| **计划正文** | E4（TOML 段序）、E5（"端到端"变异反证）、`test_write_is_atomic`、T3 的「`or` 碰巧正确」 |
| **计划给测试写的变异反证** | 「挪段序 ⇒ 必红」那个**根本不会红**的变异 |
| **代码注释** | 「会被反复扫到…越积越多」（**该函数从不列目录**）；「`REPO_ROOT` monkeypatch 够不着」（**够得着**） |
| **测试夹具** | 修前那句假话 `'4 条改了类目，0 条没判成'` **被当成"正常形状"留在夹具里** |
| ⭐ **controller 的背书** | T7 的「成环已静态挡下」——**我采纳了**，reviewer 用**执行**推翻 |

⇒ **可执行的**：没有实测支撑的理由**一律不许写**；写不出时**宁可只写"我们选了这个形状"**。
⇒ **"删掉它并写实话"与修一个 bug 同等重要。**

### 3. **「环境相关的绿」**——绿得诚实，但不可复现

一处守卫实现者报"变异下红了"，reviewer **2/2 复现不出来**——伤害落进了**用例自己的**替身，
而那条证据取决于"worker 跑到真 `chat_json` 的结局"，**那个结局是机器相关的**。

⇒ 与"假绿"不同：假绿是**判据坏了**；这一格是**现象本身依赖时序**。
⇒ **一条"我这边红了"的证据，若别人复现不出来，就当它不存在。**

**⚠️ M6 最反直觉的一条实测**：**重排的真实代价是计划的 40–80 倍**——
计划写「328 条 ≈ 11 批 ≈ 1–2 分钟」，冒烟实测 **360 源消息 → 172 批 → 78 分 27 秒**。
（**172 批从哪来的值得先想清楚**：按群 × 上下文切分，15 个群不该切出 172 批。）
