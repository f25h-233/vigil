# VIGIL 产品层设计（M1–M4）

> 日期：2026-09-13 ｜ 状态：**待用户审阅**
> 上游文档：[`README.md`](../../../README.md)、[`docs/DATA-NOTES.md`](../../DATA-NOTES.md)、[`docs/FEASIBILITY.md`](../../FEASIBILITY.md)
> 本 spec 覆盖产品层（处理 + 呈现 + 自动化）；接入层（`export`/`read`/`who`/`media`）已完成，不在范围内。

---

## 1. 现状（全部为实测事实，非估计）

### 1.1 已建成的（接入层）

| 命令 | 作用 | 状态 |
|---|---|---|
| `vigil groups` | 列出 QQ 本地库里的群 | ✅ |
| `vigil export` | 按群过滤解密 → 明文库 | ✅ |
| `vigil read` | 按群/人/时间/关键词读消息 | ✅ |
| `vigil who` | 发言排行 | ✅ |
| `vigil media` | 本地已缓存的图片 | ✅ |

`data/vigil.db`（70 MB 明文 SQLite）实测行数：

| 表 | 行数 | 说明 |
|---|---:|---|
| `messages` | 47,719 | 正文已抽成文本 |
| `sender_names` | 5,542 | uid → 姓名映射 |
| `msg_media` | 7,144 | 图片引用；`path` 非空者 634（8.9%） |
| `group_msg_table` / `dataline_msg_table` | 47,719 each | 源库 schema 副本 + qqcli 兼容层 |

### 1.2 消息分布极度倾斜

| 群 | 消息数 | 占比 |
|---|---:|---:|
| 643375490 2026级常州大学新生群 | **44,935** | 94.2% |
| 其余 14 个群合计 | 2,784 | 5.8% |

**推论**：所谓"全量抽取"的成本由一个群决定。省钱的空间不在缩小群的集合，而在抽取策略本身。

### 1.3 已知的数据缺陷

| 缺陷 | 影响 | 证据 |
|---|---|---|
| 部分行 `[40050]` = 0/NULL，时间戳落到 **1970-01-01** | 会排在每次 `ORDER BY ts DESC` 末尾；被任何 `--since` 过滤静默丢弃 | 多个群 `min(ts) = 1970-01-01` |
| 富消息（转发/文件/表情/合并转发）退化为 `[非文本]` | **转发通知**在群里很常见，可能整类丢失 | `vigil/text.py:13` 的 TODO |
| 15 个群共丢 11 条（坏页） | 可忽略 | `docs/DATA-NOTES.md` §二 |

### 1.4 工程现状的空白

| 空白 | 影响 |
|---|---|
| **不是 git 仓库** | SDD 的逐任务 commit / review-package / worktree 全部不可用 |
| **没有 `tests/`** | 无法执行 TDD 红绿循环 |
| **无 `[build-system]` / `[project.scripts]`** | 只能 `python -m vigil`，没有 `vigil` 可执行文件 |
| 无日志模块，诊断全靠 `print()` | 自动化后失败会静默 |
| 无任何 LLM 集成 | 产品层从零开始 |
| 无调度器 | "定时唤起"是 README 里的愿景 |

### 1.5 环境约束

| 项 | 实测 |
|---|---|
| Python | `.venv` CPython **3.13.15**（uv 管理） |
| Node / npm | **v22.23.1 / 10.9.8** ✅ 可用 |
| Tailscale | ❌ **未安装** |
| 磁盘 | **C: 剩 7.8 GB、D: 剩 29 GB**（均 97% 占用）⚠️ |
| `.env` | 明文 16 位密钥（已 gitignore，但从未真正生效——无 VCS） |

---

## 2. 核心设计判断：日报是 items 的一个视图

**这是整个架构的枢纽，顺序错一步就要返工。**

### 2.1 两种盖法

**❌ 盖法 A —— 两套独立管线**

```
messages ──LLM总结──→ 日报文本
messages ──LLM抽取──→ 结构化条目
```

同一批消息被 LLM 读两遍（双倍成本），两条管线**各说各话**：日报写"周五有讲座"，结构化列表里却没这条。改一处要改两处。

**✅ 盖法 B —— 一条抽取管线，两个视图**

```
messages ──抽取一次──→ items 表（唯一真相源）
                          ├──→ 视图1：日报
                          └──→ 视图2：Web 列表/分类/搜索
```

### 2.2 具体形态

假设昨天 300 条消息里 3 条有价值。**抽取层跑一次**产出三行 `items`：

| # | kind | event_ts | title | 附加字段 | 来源 |
|---|---|---|---|---|---|
| 1 | `notice` | 昨天 14:20 | 10月8日前交体检表 | `deadline_ts`=10-08 | msg 88123 |
| 2 | `activity` | 昨天 16:05 | 周五晚7点西太湖讲座 | `place`=西太湖报告厅 | msg 88190 |
| 3 | `secondhand` | 昨天 20:11 | 出九成新自行车 200 | — | msg 88240 |

**日报（视图1）** = 把这 3 条写成一段通顺的话：

> 昨天 3 个群共 300 条消息，3 条值得看：
> 📋 班助通知体检表，10月8日前交
> 🎤 周五晚 7 点，西太湖报告厅讲座
> 🚲 有人出二手自行车，200

**Web 列表（视图2）** = 同样这 3 条，但可筛"活动"、可按时间排、可搜"自行车"。

### 2.3 这个判断带来什么

1. **日报里说的每一条，必然能在 Web 里找到**——同一行数据，不存在"日报有、列表没有"。
2. **日报的 prompt 只需读几十条 items，不再读几万条原文**——又快又便宜，群再大也不怕。
3. **顺序反了就要返工**：若先做日报（直接对原文 summarization），到 M3 做 Web 时仍得抽 items，那时日报已上线，两套 LLM 判断打架，得回头把日报改成读 items。

### 2.4 一处精确化

日报不是纯渲染，它还要一层**叙述合成**——LLM 把 items 写成通顺的话、判断哪条更该提醒、合并同类项。所以准确表述是：

> **日报的输入是 items，不是原始消息。**

---

## 3. 已决策清单

| # | 决策 | 裁定 | 影响 |
|---|---|---|---|
| **D1** | 类目体系 | 我给默认，用户在此基础上**把「二手」和「失物招领」拆出来与「生活」同级** | → §4.3 |
| **D2** | 手机访问 | **Tailscale**（自带 HTTPS，校外也可用） | → §4.7；需先安装 |
| **D3** | 抽取范围 | **全量历史 backfill**（用户到校不足半月，全部历史都相关） | → §4.4 |
| **D4** | 搜索层级 | **关键词（FTS5 trigram）先做，语义搜索留接口** | → §4.7 |
| **D5** | 隐私脱敏 | **发前脱敏**：uid/群号换代号，QQ号不发 | → §4.5 |
| **D6** | Web 技术栈 | **React + Vite**（用户明确要好看；Node 已具备） | → §4.7；需处理 npm 缓存落盘位置 |
| **D7** | 自动化触发 | **Windows 任务计划程序** | → §4.8 |
| **D8** | 富消息段解析器 | **暂不做，但留接口**（接缝见 §8.1） | → §8.1；`[非文本]` 标记即接口 |
| **D9** | 日报推送形态 | **只写文件 + Web 看**（不加桌面/手机推送） | → §9 明确排除 |

---

## 4. 架构

### 4.1 数据流

```
QQ 加密库 nt_msg.db（3.0 GiB，有坏页）
   │  vigil export                    ✅ 已有
   ▼
data/vigil.db
   ├─ messages / sender_names / msg_media    ✅ 已有
   │
   │  vigil refine                    🔨 M1 新增
   │    ① 规则预筛（本地，零成本）
   │    ② 脱敏
   │    ③ 批量 LLM 精抽（SiliconFlow）
   ▼
   ├─ items / item_sources / refine_runs     🔨 M1 新增
   │
   ├── vigil digest ──→ digests 表 ──→ 一页 Markdown      🔨 M2
   │
   └── vigil serve ──→ FastAPI ──→ React SPA (PWA)        🔨 M3
                                    ├ 类目筛选
                                    ├ 时间轴
                                    ├ 关键词搜索（FTS5）
                                    └ 点回原消息
```

### 4.2 新增数据表

```sql
-- 结构化条目：唯一真相源。日报与 Web 都读它。
CREATE TABLE items (
    item_id     INTEGER PRIMARY KEY,
    kind        TEXT    NOT NULL,   -- 类目 slug，见 §4.3
    title       TEXT    NOT NULL,   -- 一句话，建议 ≤40 字
    detail      TEXT,               -- 补充细节，可空
    event_ts    INTEGER NOT NULL,   -- 事件发生时间（= 源消息 ts）
    deadline_ts INTEGER,            -- 截止时间，可空（日报的「别忘」依据）

    group_id    INTEGER NOT NULL,
    actor_uid   TEXT,               -- 发送者 uid，本地保留（不发往 LLM）

    place       TEXT,               -- 地点
    links       TEXT,               -- JSON 数组：报名链接等
    amount      TEXT,               -- 金额原文（二手价 / 兼职工资）

    confidence  REAL    NOT NULL,   -- 0..1，模型自评
    model       TEXT    NOT NULL,   -- 产出模型名
    prompt_ver  TEXT    NOT NULL,   -- prompt 版本；改 prompt 后可精准重跑
    created_at  INTEGER NOT NULL
);
CREATE INDEX items_kind_ts  ON items(kind,     event_ts DESC);
CREATE INDEX items_group_ts ON items(group_id, event_ts DESC);
CREATE INDEX items_deadline ON items(deadline_ts) WHERE deadline_ts IS NOT NULL;

-- 可回溯：每条 item 指向它的源消息（一条 item 可能聚合多条消息）
CREATE TABLE item_sources (
    item_id INTEGER NOT NULL,
    msg_id  INTEGER NOT NULL,
    PRIMARY KEY (item_id, msg_id)
);
CREATE INDEX item_sources_msg ON item_sources(msg_id);

-- 抽取记账：幂等的依据，也用于增量
CREATE TABLE refine_runs (
    msg_id     INTEGER PRIMARY KEY,
    refined_at INTEGER NOT NULL,
    status     TEXT    NOT NULL,   -- ok / discarded / error
    item_count INTEGER NOT NULL DEFAULT 0,
    prompt_ver TEXT    NOT NULL,
    err        TEXT
);

-- 日报（⚠️ M2 才建，M1 不建——建了也没有写入方）
CREATE TABLE digests (
    digest_id   INTEGER PRIMARY KEY,
    window_from INTEGER NOT NULL,
    window_to   INTEGER NOT NULL,
    body_md     TEXT    NOT NULL,
    model       TEXT    NOT NULL,
    created_at  INTEGER NOT NULL
);

-- 日报 ↔ 条目 的互跳（⚠️ 同样属 M2）
CREATE TABLE digest_items (
    digest_id INTEGER NOT NULL,
    item_id   INTEGER NOT NULL,
    PRIMARY KEY (digest_id, item_id)
);

-- 全文搜索（M3 建；trigram 分词器支持中文子串匹配，无需外部分词器）
CREATE VIRTUAL TABLE items_fts USING fts5(
    title, detail,
    content='items', content_rowid='item_id',
    tokenize='trigram'
);
-- 由 M3 提供触发器或显式重建语句保持同步
```

**为什么 `item_sources` 独立成表而不是 JSON 数组**：需要**双向**查询——"这条 item 来自哪几条消息"（点回原文）和"这条消息产出了哪条 item"（避免重复抽）。JSON 数组只能单向高效。

### 4.3 类目体系

配置化（`config/categories.toml`），不硬编码。默认七类（D1 裁定后的版本）：

| slug | label | 范围 | icon |
|---|---|---|---|
| `notice` | 通知公告 | 辅导员/班助/老师/管理部门发的正式通知：办事流程、缴费、体检、材料提交、纪律要求 | 📋 |
| `academic` | 学业 | 作业、考试、课程调整、选课、成绩、补考、四六级 | 📚 |
| `activity` | 活动 | 讲座、社团招新、比赛、晚会、志愿活动、报名 | 🎤 |
| `life` | 生活 | 食堂、宿舍、水电、校园卡、校车、快递、门禁、维修 | 🏠 |
| `secondhand` | 二手 | 转让、出售、求购物品 | 🛒 |
| `lostfound` | 失物招领 | 寻物启事、失物认领、走失找寻 | 🔍 |
| `job` | 兼职招聘 | 兼职、实习、校招、家教、勤工助学 | 💼 |

**不产出入库的**：广告（校园卡王、维修蔡师傅一类刷屏）、纯闲聊、系统事件、纯图片无文字。

> 用户的判断："二手和失物招领会很常用"——这两类在校园群里确实是高频刚需（`vigil who` 已显示广告号占据发言榜首，说明该生态活跃）。

### 4.4 抽取管线

**两级设计**：规则预筛砍量 → LLM 精抽保质。

```
① 规则预筛（本地，零 API 成本）
   ├ 硬丢弃（先于保留规则判定，命中即丢）
   │   ├ content == "[非文本]" 且无 CJK
   │   ├ 长度 < 4 字节（"dd"/"1" 一类）
   │   ├ ts == 0 或落在 1970-01-01（§1.3 的脏数据）
   │   ├ 整条即纯应答：已完成/收到/好的/嗯嗯/OK（**全匹配**——
   │   │   「收到，明天9点集合」不能被丢）
   │   └ 同 uid 在 60 秒内 ≥3 条内容高度相似（刷屏广告）
   └ 保留候选（满足任一）
       ├ 命中关键词表：通知/报名/截止/考试/作业/选课/讲座/招新/面试/成绩/
       │                体检/缴费/办理/领取/登记/补考/四六级/兼职/招聘/
       │                转让/出售/求购/丢失/拾到/捡到/失物…
       ├ 发送者昵称命中角色模式：辅导员|班主任|老师|班助|助理|管理员|部长|团长|学长|学姐
       └ 所在群为高价值群（见下方 `[[groups]].tier`）
```

**群分级**：`config/groups.toml` 的每个 `[[groups]]` 增加 `tier` 字段，取值 `high` / `normal`（缺省 `normal`）。

> ⚠️ **精确语义**：`high` = **不受关键词过滤**，但**硬丢弃仍然生效**。
> 不是"全部消息都进候选"——实测班级群 15 条里有 8 条是「已完成」，
> 全喂 LLM 纯属浪费。硬丢弃规则的设计就是为了挡住这类。

```toml
[[groups]]
id = 1074335063
name = "储运263班级群"
enabled = true
tier = "high"        # 班级群 —— 全量进候选
```

初始建议：班级群、课程群、部门/技术群、宿舍长群、团员群为 `high`；新生群（44,935 条，量太大）与二手/跑团群为 `normal`，靠关键词与昵称模式筛。

**② 批量 LLM 精抽（SiliconFlow）**

- **带上下文**：每批取同一群内**前后各 2 条**作为上下文。单条消息常常没头没尾（"明天记得带"），上下文能救回这类。
- **成批调用**：一次提交 20–30 条，返回 JSON 数组；一条消息最多产出一条 item（跨消息聚合在合并阶段做）。
- **输出契约**：
  ```json
  [{"msg_id": 88123, "kind": "notice", "title": "10月8日前交体检表",
    "detail": "…", "deadline": "2026-10-08", "place": null,
    "links": [], "amount": null, "confidence": 0.9},
   {"msg_id": 88124, "kind": "discard"}]
  ```
- **prompt 版本化**：`prompt_ver` 落库（如 `v1`）；改 prompt 后可 `vigil refine --redo --prompt-ver v2` 精准重跑。
- **预算护栏**：`config` 里设 `max_tokens_per_run`，超限即停并报告（防止一次跑飞）。

**③ 幂等与增量**

- `refine_runs` 记 `msg_id` → 已处理的跳过，重跑不重复花钱。
- `--redo` 强制重抽；`--since` 限定窗口。
- 全量 backfill（D3）与后续增量走同一条路径，只是窗口不同。

### 4.5 脱敏（D5 裁定）

**发送给 SiliconFlow 的内容里，以下一律不进 prompt**：

| 项 | 处理 |
|---|---|
| **QQ 号**（`sender_names.uin`） | ❌ 完全不发 |
| 群号 | → 代号 `G1`/`G2` |
| uid（`u_m-DGcmJpBZd4wB9FTOCKCQ`） | → 代号 `U1`/`U2`（本次 run 内稳定） |
| 手机号 | 正则 `1[3-9]\d{9}` → `<号码>` |
| 长数字串（学号） | 正则 `\d{10,}` → `<号码>` |
| **姓名 / 群昵称** | ✅ **保留**——这是判断"谁发的、是不是官方"的关键信号 |

**为什么保留姓名**：群昵称直接编码了角色（实测：`储运263班主任助理卞雨琦19551968610`、`西太湖新媒体杨馨雅`）。剥掉姓名等于剥掉抽取层最可靠的官方性信号。

**数字遮蔽的边界**：只遮蔽手机号与 ≥10 位连续数字，**不动日期**。`2026-10-08` 中间的连字符使其不命中，`10月8日` 同理——避免把截止日期打成 `<号码>` 而毁掉抽取。

**映射本地留存**：`G1`↔群号、`U1`↔uid 的映射只存在于本次进程内存与本地日志，回填时反解。

### 4.6 日报合成（M2）

**输入**：时间窗内的 `items`（通常几十条），**不是**原始消息。

**流程**：
1. 取窗口（默认昨天 00:00–24:00）内的 items，按类目分组、按 `event_ts` 排序。
2. **合并同类项**：同一截止日期的多条通知合并；同一活动的多条讨论只留一条。
3. LLM 写成一页 Markdown：先给"需要行动的"（有 `deadline_ts` 的），再给"知道就好"的。
4. 落 `digests` 表 + 写 `docs/digests/YYYY-MM-DD.md`。

**输出形态**（Markdown，便于 M3 直接渲染）：

```markdown
# 守夜人日报 · 2026-09-13

昨天 3 个群 412 条消息，提炼出 7 条。

## ⏰ 别忘
- **体检表** 10月8日前交到辅导员处 · 储运263班级群
- **选课补退选** 9月15日 24:00 截止 · 26级高数（一）储运

## 📋 通知
- …

## 🎤 活动
- 周五 19:00 西太湖报告厅 AI 讲座 · 求索技术部
```

**空窗处理**：窗口内无 items 时明确输出"昨天没有值得一提的信息"，不假装有事。

### 4.7 Web 前端 + PWA（M3）

**后端**：FastAPI，只读 `data/vigil.db`，提供 JSON API。

| 端点 | 作用 |
|---|---|
| `GET /api/items` | 筛选参数：`kind` / `since` / `until` / `group` / `q`（关键词）/ `limit` |
| `GET /api/items/{id}` | 单条详情 + 源消息原文（通过 `item_sources` 回溯） |
| `GET /api/digests` | 日报列表 |
| `GET /api/digests/{id}` | 单篇日报 |
| `GET /api/categories` | 类目表（供前端渲染筛选器） |

**搜索**：SQLite **FTS5 + trigram tokenizer** 建在 `items.title` / `items.detail` 上。trigram 支持中文子串匹配，无需分词器。语义搜索留接口（`?mode=semantic` 预留，M3 不实现）。

**前端**：React + Vite + TypeScript + Tailwind。
- 三块视图：**信息流**（按时间）/ **类目筛选**（D1 的七类）/ **日报**
- 每条 item 可展开看源消息原文（可回溯是"不信 LLM"的落地）
- 构建产物 `web/dist/` → FastAPI 静态托管，**运行时仍是单栈**（只需 Python），Node 只在开发/构建时需要

**PWA**：`vite-plugin-pwa` 生成 manifest + service worker。
⚠️ Service Worker 要求安全上下文——这正是 **D2 选 Tailscale 的收益**：`tailscale serve` 代理本地端口并提供 `https://<machine>.<tailnet>.ts.net` 证书，手机无论在校内校外都能满血访问。

**npm 缓存重定向**（§1.5 磁盘紧）：
```bash
npm config set cache D:\npm-cache
```

### 4.8 自动化（M4）

Windows 任务计划程序，每日定时：

```
vigil export  →  vigil refine  →  vigil digest
```

配套要求（否则会静默失败）：
- **日志落文件**：`data/logs/vigil-YYYY-MM-DD.log`（现在全靠 `print()`，必须补日志模块）
- **失败可见**：非零退出 + 日志尾部写入 `data/logs/LAST-ERROR.txt`
- **幂等可重入**：三次跑不产生重复 items（`refine_runs` 保证）

---

## 5. 里程碑与出口标准

> 按 SDD 流程，每个里程碑 = 一轮完整的「计划 → 实现 → 双层审查 → 冒烟 → 收尾 → 记忆埋点」。

### M1 · 抽取引擎

**交付**：`vigil refine` 命令、`config/categories.toml`、`items`/`item_sources`/`refine_runs` 三张表、SiliconFlow 客户端、脱敏模块、规则预筛模块。

**出口证据**：
- `vigil refine` 对全量 47,719 条跑完无异常退出；`refine_runs` 覆盖全部消息（每条要么 `ok`/`discarded`，要么 `error`），无遗漏
- `items` 表有数据，且每条 item 都能通过 `item_sources` 跳回源消息
- **抽样 100 条 item 人工验收，分类准确率 ≥ 80%** —— ⚠️ **这一步需要用户本人参与**，是 M1 冒烟出口的必要环节，不能用自动检查替代
- 重跑一次 `vigil refine`，`items` 行数不变（幂等验证）
- 预算护栏可触发（人为设小 `max_tokens_per_run`，确认会停并报告）

### M2 · 日报合成

**交付**：`vigil digest` 命令、`digests`/`digest_items` 表、日报模板。

**出口证据**：连续 3 天真实日报，用户读完判定"有用"。含一次空窗日（无 items）的正确表现。

### M3 · Web 前端 + PWA

**交付**：FastAPI 服务、React 前端、FTS5 搜索、`vigil serve` 命令、PWA manifest。

**出口证据**：
- 手机通过 Tailscale HTTPS 打开
- "添加到主屏幕"后独立图标、全屏
- 按七个类目筛选正确
- 中文关键词搜到东西
- 点任意 item 能看到源消息原文

### M4 · 自动化

**交付**：任务计划程序配置、脚本、日志模块。

**出口证据**：挂机 24 小时无人干预，产出至少一篇日报；日志完整；人为制造一次失败（如拔掉 QQ 库路径），确认 `LAST-ERROR.txt` 有记录。

---

## 6. 前置工作（Step Zero，不占里程碑）

SDD 流程的硬性依赖，必须在 M1 开工前完成：

| # | 事项 | 原因 |
|---|---|---|
| 0.1 | **`git init` + 首次 commit** | SDD 的逐任务 commit / review-package / worktree 全靠它；现在零版本控制，唯一备份是手工的 `data/vigil.db.bak-2223` |
| 0.2 | 确认 `.gitignore` 真的生效（`data/`、`.env`、`.venv/`） | 规则早已写好，但从未被 VCS 执行过。**首次 commit 前必须核对，密钥不能入库** |
| 0.3 | **`tests/` + pytest 配置** | TDD 红绿循环的前提；顺带为 `export`/`reader` 补最小回归测试 |
| 0.4 | `pyproject.toml` 补 `[build-system]` + `[project.scripts]`（`vigil = "vigil.cli:main"`） | 冒烟出口要真实进程；现在只能 `python -m vigil` |
| 0.5 | `npm config set cache D:\npm-cache` | C: 仅剩 7.8 GB，npm 缓存在 C 盘会雪上加霜 |
| 0.6 | 安装 Tailscale | D2 的落地前提（M3 前完成即可） |
| 0.7 | ~~补日志模块~~ **移入 M4** | M1 阶段 `on_progress` 回调就是进度通道；现在建日志模块没有消费者，是悬空工件。到 M4（自动化）时它才有真正的前提 |

---

## 7. 风险与未验证项

| # | 风险 | 影响 | 缓解 |
|---|---|---|---|
| R1 | **SiliconFlow 抽取质量未验证** | 最大风险。若分类差、字段抽不准，M2/M3 全部建在沙上 | **M1 第一个任务就是小样本试跑**（取 200 条真实消息，人工看 prompt 效果），质量不达标就不铺开 |
| R2 | **富消息占比未知** | 转发通知可能整类丢失，而那可能是最有价值的一类 | D8 已裁定暂不做解析器，故**不再统计占比**（没有决策价值）。知悉即可；将来若要做，接缝见 §8.1 |
| R3 | 1970-01-01 脏数据行数未统计 | 抽稀了会低估成本 | 预筛层已设计为直接丢弃；M1 首任务顺带统计 |
| R4 | 磁盘紧张（C: 7.8 GB / D: 29 GB） | 前端依赖树 + 日志 + 可能的模型缓存 | Step Zero 0.5；日志做轮转；不上本地模型 |
| R5 | Tailscale 未安装、校园网可能有策略限制 | D2 可能落空 | M3 前实测；失败则退回局域网方案（PWA 降级为普通快捷方式） |
| R6 | `64034` 列语义未解 | 官方发送者识别少一个信号 | **已实测否定"简单角色枚举"假设**（178 群中 163 群有 3+ 少数派）。改用群昵称模式 + LLM 判断，不依赖此列。列为 M1 可选验证项 |
| R7 | 群消息外发云端（隐私） | — | 已由 D5 脱敏缓解；但**姓名仍会外发**，这是有意的权衡（§4.5） |

---

## 8. 为未来留的口子

本 spec 明确不做、但**设计上不挡路**的两件事。判断依据：将来想补时，改动应该是"加一个模块"，而不是"回头重构已上线的部分"。

### 8.1 富消息段解析器（D8 裁定：暂不做，留接口）

`vigil/text.py:13` 的 TODO：转发/文件/表情/合并转发目前退化为 `[非文本]`。qqcli 的 `segment.rs` + `normalize.rs` 做了这件事，可以移植。

**接缝在哪（三条，已天然成立，无需额外工作）**：

1. **`text.py::extract_text(raw: bytes) -> str` 是纯函数、单一入口**。将来换成段解析器，只需改这一个函数的实现，调用方（`export.py::_write_messages`）一行不动。
2. **`[非文本]` 标记就是筛选器**。当前产不出文本的行都落在这个常量上，未来的解析器可以直接 `WHERE content = '[非文本]'` 精确锁定待重解析的行——不需要新增列来标记"待处理"。
3. **原始库永远在，`vigil export` 可重跑且幂等**（实测全量 2.9 秒）。所以历史回填的路径是：改 `extract_text` → 重跑 `vigil export`。**不需要为将来预留任何 schema 字段。**

> 因此 M1 **不做** R2 的占比统计——既然不做解析器，统计它就没有决策价值。R2 降级为"知悉即可"。

### 8.2 吃瓜板块（用户构想，本 spec 不做）

用户原话："聊天记录多半是瓜。"

这确认了一条**已经成立**的设计性质：

> **丢弃 ≠ 删除。** 预筛丢弃的消息 (`refine_runs.status = 'discarded'`) 与 `discard` 类目的抽取结果，原文**始终留在 `messages` 表里**，从未被清理。

将来若要做"吃瓜板块"（按热度/戏剧性重新索引闲聊内容），只需**换一套 prompt + 一个新的 kind** 重跑同一批消息即可，现有数据一行都不用动。

**这也是这套架构的通用红利**：抽取是"视图"，不是"加工后销毁原件"。任何新的信息维度（吃瓜、情绪、人脉、活跃度）都是"对 `messages` 再抽一遍"，而不是"当初没存就没了"。

---

## 9. 不做的（明确排除，避免范围蔓延）

| 项 | 原因 |
|---|---|
| 图片 OCR / CDN 下载 | D 轮已决策「暂不做」。实测纯图片消息仅占 3.4%、官方消息可读率已 82.4%，性价比不成立 |
| 富消息段解析器 | D8 裁定暂不做（接缝已留，见 §8.1） |
| 日报的桌面/手机推送 | D9 裁定只写文件 + Web 看 |
| 语义搜索（embedding + 向量库） | D4 裁定先做关键词，留接口 |
| 发言、登录、任何写 QQ 的操作 | 路线 C 的核心前提，不可动摇 |
| 增量导出 | 实测全量重读仅 2.9 秒，不值得为它引入复杂度（`export.py` 的既有决策，继续沿用） |
| 本地 LLM | D2 选 SiliconFlow；且磁盘不允许 |
| 多人使用 / 账号体系 | 单机自用工具 |
| 吃瓜板块 | §8.2 的构想，本 spec 不做；数据已保留，将来可补 |

---

## 10. 术语

| 术语 | 含义 |
|---|---|
| **接入层** | 从 QQ 加密库取数 → 明文库（已完成） |
| **抽取层 / refine** | messages → items（M1） |
| **item** | 一条结构化信息条目，可回溯到源消息 |
| **日报 / digest** | items 在某个时间窗内的叙述性渲染（M2） |
| **路线 C** | 不登录、不发言、不占用 QQ 登录位，直读本地加密库 |
| **坏页** | QQ 库的物理页损坏；只在查询计划不走索引时触发 |
