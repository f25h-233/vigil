# VIGIL 进度接力 — M3 完成 / M4 待启动

> **钩子：新会话先读此文件，再读 `docs/superpowers/specs/2026-09-13-vigil-product-layer-design.md`（§4.8 与 §5 的 M4 节）。**
> 最后更新：2026-09-16　｜　M3 模式：SDD **wave**（收窄为 2 道）　｜　仓库：`https://github.com/f25h-233/vigil`（private）

---

## 一句话

**M3「Web 前端 + PWA」完成——spec §5 五条出口标准全过**（3/4/5 由 PC 侧实测，1/2 由用户手机确认「可添加到主屏」）。
下一步是按 spec §4.8 写 **M4「自动化」** 计划：任务计划程序每日 `export → refine → digest`。

---

## 当前工作区的真实状态（**以此为准，别凭印象**）

```
HEAD      6c0b24a（已推 origin/master，与远端同步、零遗留）
tests     328 Python passed + 11 前端 vitest
data/vigil.db
  messages     47,719      items      270      refine_runs 47,719    item_sources 270
  digests           4      digest_items  21
  带截止日的 items  13（全部有源文字面依据——M1 的 26 条已核验降级，见 §M3 交付）
docs/digests/  2026-08-08 / 2026-09-11 / 2026-09-12 / 2026-09-13
前端构建   web/dist/  180 模块（gitignore，不入库）
```

**归档不变量**（M4 开始每天追加后，这是「归档是否完整」的唯一机械判据）：
**`docs/digests/` 的文件集合 == 库里 `digests` 的窗口日期集合**，且文件与 `body_md` 逐字节相等。

---

## ⚠️ M4 开工前**必须先处理**的两条

### 1. 已经铺好的路：怎么跑一次完整管线

```bash
cd D:/github/VIGIL
uv run vigil serve --host 127.0.0.1 --port 8787   # 后端 + 前端静态托管
tailscale serve --bg 8787                        # 手机 HTTPS 入口
# 手机：https://f15h.tail324373.ts.net
```

**Tailscale 的坑（最容易误判成"中国区网络问题"）**：`tailscale serve --bg 8787` 会
**挂死 90 秒、无输出、无报错**——因为 `serve` 默认 HTTPS 模式、卡在等证书。
诊断命令是 `tailscale cert f15h.tail324373.ts.net`（会回 `your Tailscale account does not support getting TLS certs`）。
解法：<https://login.tailscale.com/admin/dns> → HTTPS Certificates → Enable（本机已于 2026-09-16 开启）。
**HTTPS 不是锦上添花**：Service Worker 要安全上下文，没 HTTPS 就没有 PWA。

### 2. M4 的**天然前提**：日志模块（spec 记在「前置工作 Step Zero」0.7，明确移入 M4）

现在**全靠 `print()`**，而 M4 要挂机无人值守 ⇒「日志落文件 + 失败可见」是自动化能不能成立的前提。
`data/logs/vigil-YYYY-MM-DD.log` + 非零退出 + `data/logs/LAST-ERROR.txt`（spec §4.8 原文）。

---

## M3 出口标准 · 用户判定

spec §5 五条，**证据全文**在
`.superpowers/sdd/2026-09-15-vigil-m3-web-pwa/smoke-report.md`（含每格的证据形态：进程输出 / DOM 实测 / 截图）。

| # | 标准 | 结论 |
|---|---|---|
| 1 | 手机通过 Tailscale HTTPS 打开 | ✅ 用户手机确认 |
| 2 | 添加到主屏幕后独立图标、全屏 | ✅ 用户确认「可添加到主屏」（`display:standalone` 那条**未单独复核**） |
| 3 | 按七个类目筛选正确 | ✅ 「学业」→ 共 **59** 条（与真库 `academic` 计数一致） |
| 4 | 中文关键词搜到东西 | ✅ 短词「选课」**8** 条（LIKE 路径）+ 长词「校园卡」**42** 条（trigram 路径） |
| 5 | 点任意 item 看到源消息原文 | ✅ 含**失败 → 重试 → 真数据回来**的完整回路 |

**三个前端视图有史以来第一次在浏览器里渲染**：零 console 错误、零未捕获 JS 异常、零失败请求。

---

## M3 交付了什么

| 命令 / 产物 | 说明 |
|---|---|
| `vigil serve [--host] [--port]` | 只读 FastAPI 服务 + `web/dist` 静态托管 + SPA 兜底 |
| 5 个只读端点 | `/api/items`（含搜索/筛选/分页）、`/api/items/{id}`、`/api/categories`、`/api/digests`、`/api/digests/{id}` |
| React + Vite + TS + Tailwind 前端 | 三块视图（信息流 / 类目 / 日报）+ `ItemCard` 源消息回溯 + PWA manifest/SW |
| FTS5 + trigram 搜索 | **短词（<3 字）走 LIKE 兜底**——trigram 对短词**静默返回 0**，这是只有真跑才现形的缺陷 |
| `vigil deadline-audit` | 截止日核验；**13 条无依据的已置 NULL**（26 → 13），并接进 refine 写入路径 |

**M3 的真实教训（代码层）**：
1. **SPA 兜底会吞掉 PWA 全部静态文件**（`sw.js`/manifest/图标返回 200 的 index.html）——
   浏览器把 HTML 当 manifest 解析、当 SW 注册，**而所有状态码都是 200、日志上一个异常都没有**
2. **裸查询串喂 MATCH 会抛 OperationalError**（用户打个引号就 500）→ 短语包裹 + LIKE 转义
3. **`strptime().timestamp()` 对合法日期也会抛 `OSError`**（`"1970-01-01"`——模型最常用的 null 哨兵），
   而它在每批 try/except **之外** ⇒ **一个模型输出掀掉整轮 refine**

---

## ⭐ M3 最重要的一条设计判断：**没有单一所有者的缺陷，分块审查看不见**

全分支 opus 终审抓到的 **4 条 Important，共同结构是「没有哪个任务同时拥有它」**：

| 缺陷 | 为什么任务级审查必漏 |
|---|---|
| `_day_start` 能被用户输入换 500 | `_parse_day`（400）与 `_day_start`（日期算术）在同一任务里被当成"同一个校验" |
| `_parse_deadline` 一个模型输出掀掉整轮 | 是 **M1 留下的保护圈缺口**，M3 只是往里又塞了一个调用点 |
| `ItemCard` 源消息失败后死路 | 三个视图的重试各由 T5/T6 写，而它是 T4 的「共用组件」——**没哪个任务同时拥有这四处**。**而它正是出口标准 5 本身** |
| `/api/digests` 零字段断言 | 契约测试归 T3、视图归 T4，**"冻结契约"的覆盖面从来没人整体核对** |

> **这就是最后那道全分支审查不能省的理由。** 与「假绿/空守卫」是**两个不同的问题**。

---

## 已知缺陷（**带着走，别当它完美**）

**M3 新增 5 条**（证据在 `smoke-report.md` §六）：

| # | 项 |
|---|---|
| M3-1 | **`_MIME` 的「键缺失」无守卫**：删掉 `_MIME[".js"]` 后 Starlette 回落 `mimetypes.guess_type`（实测 `('text/javascript', None)`），测试**照样绿**；而删键会同时破坏"缺文件宁 404"分支。**改值被抓、删键漏网** ← 建议 M4 优先 |
| M3-2 | `except` 分支里的 `store.record_run` 仍裸奔（库坏到写不进去时异常仍逃出 `refine()`）——与 LLMError 分支暴露面相同，没把洞挖大 |
| M3-3 | 捕宽 `Exception` 会吞 `MemoryError`/`RecursionError`（`BaseException` 不受影响） |
| M3-4 | `ItemCard` 无 `seq` ref——复审论证**在本组件内不可达**（一个卡片实例终生只对一个 item 发请求） |
| M3-5 | `test_refine_keeps_going...` 断言了错误文案前缀「第 1 批」——改文案会红（轻耦合） |

**M2 记的 8 条**——⚠️ **M3 只动了第 1 条（已修：26 条 → 13 条，其余各条 M3 未触碰相关文件，但没复核**。
本项目出过"没人复核的清单会烂掉"（两条过期快照）的先例，**开工前请各花一分钟核对**）：

1. ~~`items.deadline_ts` 半数不可信~~ → **M3 已修**（数据层核验 + 接进写入路径 + 同一性守卫）
2. **M1 补出的日期在正文里仍可见**：9/13「课程安排：第五周开课」正文的「今日（9月14日）」，
   源文只有「今天上午有一节课第五周开」。**走的不是 deadline 路径，所以那轮核验管不到**
3. **`vigil refine` 仍有全角引号退化隐患**：全库 **25 条**消息含 `“ ”`，会让模型退化成无限空格循环。
   M2 只在日报载荷侧修了（`sanitize_for_llm`），**refine 侧未修**
4. **`refine.py` 日志与日报同名不同义**：日志「本地丢弃 83」只算**硬丢弃**，日报「本地筛掉 1,014」含「没命中保留规则」——**差 12 倍**
5. **`PROMPT_VERSION` 的 payload 侧无自动守卫**：指纹只覆盖 `build_system_prompt`
6. **汉字日期写法无数字边界**：`1月6日` 会在 `11月6日` 里命中；点号写法引入新假阳性面（全库 87 处 `M.D` token）
7. **Task 12 的覆盖率分支今天不可达**：51 个有数据的日子覆盖率**全 100%**——**这条限定是 M4 才会唤醒的**
8. **日报措辞不可复现**：结构幂等 ≠ 字节幂等（temperature 0.1 ≠ 0）。**不能用 sha256 证明「LLM 产物没被改动」**

---

## 关键文件地图

| 路径 | 内容 |
|---|---|
| `vigil/api.py` | **M3 主体**：只读 FastAPI、5 个端点、`_MIME` 表、SPA 兜底（含三条边界守卫） |
| `vigil/refine.py` | M1 主体 + M3 加了**每批本地后处理的保护圈**（"单批失败不中断整轮"） |
| `vigil/store.py` | M1+M2+M3 累加：FTS5 索引、`search_items`、`window_items`、`save_digest` |
| `vigil/deadline.py` | M3 新增：截止日**源文核验**（唯一实现，带同一性守卫） |
| `web/src/` | M3 前端：`views/{Feed,Categories,Digests}.tsx` + `components/ItemCard.tsx` + `types.ts`（**冻结契约**） |
| `vigil/digest.py` | M2 主体（831 行） |
| `vigil/cli.py` | 命令入口：`export` / `refine` / `digest` / `serve` / `deadline-audit` |
| `M2-验收材料.md` | **用户的判定原文在这里，别覆盖** |
| `docs/superpowers/plans/*.md` | M1/M2/M3 计划（含探针实测、全部裁决、下个里程碑该复用的纪律） |
| `.superpowers/sdd/2026-09-15-vigil-m3-web-pwa/` | M3 ledger + **`smoke-report.md`**（本地过程记忆，不入库） |
| `vigil_exit_check.py` | M1 出口机械核验，改完提示词重跑后先跑它 |

---

## SDD 执行方式（**M4 直接沿用**）

- **模式：按任务边界算，别凭习惯**。M3 用 **wave 收窄为 2 道**（`vigil/**` ∥ `web/**`，跨语言零重叠），
  **三个波打架率 p 全为 0、零越界**——但那是**写者表算出来的真实并行度只有 2**，不是"wave 更好"。
  M1 上 wave 吃过亏（任务粒度太小）。**M4 若只有 Python 一条链，就该回 pipeline。**
- 每任务 = brief → implementer → 审查 → 裁决 → fix → **scoped re-review**。
- **派发时必带**（M1/M2 血泪 10 条）：

  1. **变异反证必须加阳性对照**，否则「全红」不可信
  2. **跑测前清 `__pycache__` + `PYTHONDONTWRITEBYTECODE=1`**——`.pyc` 只按 `(mtime 秒, 大小)` 校验，同尺寸变异同秒写入会**复用旧字节码**
  3. **隔离副本要用 `git -c core.autocrlf=false -c core.eol=lf archive`**——默认产出 CRLF，不是被审字节
  4. **副本里先自检 `vigil.__file__` 指向副本**——editable finder 会把 `vigil` 硬映射到工作区，不自检则**副本里所有变异都会「存活」**
  5. **变异锚点写成脚本文件、不走命令行传**——Git Bash 向原生 python 传非 ASCII 参数会被**静默打空**
  6. **锚点必须全局唯一**，并断言命中次数 ≥1
  7. **不要在共享工作区里做变异**——会污染并发的其它 agent
  8. **禁止在真库真窗口重跑已验收产物**——重跑会不可逆地刷新 `created_at`/`digest_id`。证明 LLM 产物未变只能用**隔离副本 + 冻结模型 A/B**
  9. **文件级 `git add`**，提交后 `git show --stat` 自查——`git add -A` 会卷入同事的未提交改动
  10. **agent 断线后先查仓库再决定**，不靠自述

- **M3 新增 3 条**（都是本轮实测，详见记忆 `vigil-sdd-lessons` 十八至二十一）：

  11. ⭐ **判据的可判定性**——写断言前先问「**这段代码若是坏的，这个断言会怎样？**」
      答不上来（"两种情况下都长这样"）就不是判据。**这是变异反证的「上游」**：
      当测试环境让两种行为产出同一现象时，**变异反证会给出假安全**。
      （M3 实例：C-1 冒烟判据用"仍显示失败态"，而服务停着时重发与不重发**屏幕一模一样**；
      改判据为**数请求条数**后才可判定）
  12. ⭐ **brief 自相矛盾时，「驳回 + 出证据」> 「照做」**——派发词固定加
      「**若需求自相矛盾或无法同时满足 → 停下报告，不许挑一半照做**」。
      （M3 实例：controller 的 B-1 测试配方与它自己指定的修法第一步不可能同时为真，
      **照做会得到一个变异下不变红的"验收核心"**）
  13. **解释任何耗时/现象之前先测一次**——"听着合理"不是解释。

---

## 未尽事项

- 上述 **5 条 M3 新增缺陷 + 7 条 M2 遗留**（第 7 条正是 M4 会唤醒的）
- M4 自身的前置：**日志模块**（spec §4.8）、`LAST-ERROR.txt`、幂等可重入验证
- ledger 里的延迟清单（Minor，各任务审查留档）
- `.superpowers/` 下的 workspace 与 `_smoke/` 均**不入库**，是本地过程记忆

---

## 方法论沉淀（详见记忆 `vigil-sdd-lessons`，已含 M1/M2/M3）

**M3 最贵的三条**：

1. **判据的可判定性**（第十九条的上游问题，见上 11）
2. **brief 自相矛盾**（见上 12）
3. **没有单一所有者的缺陷，分块审查结构上看不见**——终审 4 条 Important 全是这一类

**M2 最贵的三条**（仍然有效）：八条「验证工具本身不可信」；「结论对、依据错」四次；
**已记录的教训不会自动执行**——教训要起作用，必须在**它适用的那个动作发生之前**被强制检索到。
