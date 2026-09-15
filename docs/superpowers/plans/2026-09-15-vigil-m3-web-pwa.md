# VIGIL M3「Web 前端 + PWA」实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `items` 与 `digests` 在手机上可读——FastAPI 只读服务 + React SPA + FTS5 中文检索 + PWA「添加到主屏」，全程不碰 QQ 加密库、不写 `data/vigil.db`。

**Architecture:** 后端只加一层**只读 JSON API**（`vigil/api.py`），数据层复用 M1/M2 的 `store`，新增 FTS5 trigram 索引与查询函数；前端 `web/` 用 Vite 构建成静态产物，由同一个 FastAPI 进程托管，**运行时仍是单栈（只需 Python）**。开新里程碑前先还一笔债：把 M2 长在渲染层的「截止日字面核验」提到**数据层**，否则 Web 直接读 `items.deadline_ts` 会把那一批幻觉日期原样复活。

**Tech Stack:** Python 3.13 / FastAPI 0.141 + uvicorn 0.53（新增）/ SQLite FTS5（stdlib）/ React 19.3 + Vite 8.3 + TypeScript 5.9 + Tailwind **4.3** + vite-plugin-pwa 1.3（前端栈全部版本已实测锁定，见下）

**Spec:** [`docs/superpowers/specs/2026-09-13-vigil-product-layer-design.md`](../specs/2026-09-13-vigil-product-layer-design.md) §4.5、**§4.7**、§5（M3）、§1.5、§7 R5

**Mode:** SDD **wave**（收窄为 2 道：`vigil/**` Python 链 ∥ `web/**` 前端链）。模式与理由记在 ledger 首部。

---

## Global Constraints

以下约束适用于**每一个**任务，不再逐任务重复。

1. **绝不让 Web 侧写 `data/vigil.db`。** `vigil/api.py` 的连接一律 `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`。这不是约定是机械保证：只读连接执行写操作会被 SQLite 直接拒绝（实测 `attempt to write a readonly database`）。**`vigil/serve` 进程之外，任何人都不得为了「让页面好看」去改库。**
2. **不碰 QQ 加密库。** `vigil/qqdb.py` / `export.py` / `media.py` 一行不改。
3. **不改 M1 已验证的提示词与 `PROMPT_VERSION`。** 本里程碑不重跑 `refine`、不重跑 `digest`，`items` 的既有行**除 `deadline_ts` 一列外**任何字段都不许变。**禁止在真库真窗口重跑已验收的日报**——会不可逆地刷新 `created_at`/`digest_id`（M2 记录在案）。
4. **所有源码文件用 `from __future__ import annotations` 开头**（跟随 `vigil/` 现有模块）。前端沿用 `web/` 内的 ESLint-free 约定：只靠 `tsc` 严格模式把关。
5. **所有文件编码 UTF-8，注释与文档字符串一律中文。** 注释要写**为什么**，尤其是「这里为什么不能用更直觉的写法」。
6. **测试绝不联网、绝不碰真实 QQ 加密库。** Python 测试用 `sqlite3.connect(":memory:")` 与构造样本；**读真库只允许只读连接**。前端测试只用纯函数（`format.ts` / `api.ts`），不引 jsdom、不测组件渲染。
7. **修改既有测试文件必须追加而非覆盖**：`tests/test_digest.py`、`tests/test_store.py`、`tests/test_refine.py` 由 M1/M2 建立并通过，是**行为未变的证据**。
8. **每个任务一个独立 commit**，消息格式 `feat: ...` / `test: ...` / `chore: ...` / `fix: ...`。**文件级 `git add`**，提交后 `git show --stat` 自查——`git add -A` 会卷入无关改动。
9. **前端依赖版本一律照抄，不许写 `^` 或 `latest`。** 本计划里的版本号是**实测装出来的**，不是查来的（Tailwind v4 与 v3 的配置方式不兼容，凭记忆写必崩）。
10. **Tailwind v4 没有 `tailwind.config.js`。** 主题在 `src/index.css` 里用 `@theme` 声明。**不要创建 config 文件**——它不会被读取，且会让人以为改了生效。
11. **`web/dist/` 不入库**（`.gitignore` 已含）。`vigil serve` 启动时若发现前端未构建，必须**明说**并给出构建命令，不许静默返回空白页。

### 逃逸舱（**wave 模式下已收紧**）

**波内 implementer 只允许修改自己 `Touches:` 里列出的文件。**

- 计划里的断言/命令/顺序与实现不符时：**按实际情况修正并继续，无需请示**，但必须在 `task-N-report.md` 里写明偏差（报告是审查输入）。
- 需要动 `Touches:` 之外的任何文件时：**停下，报告 controller，等裁决**——不许自己"顺手改一下"。controller 的裁决只有两种：移出本波转顺序执行，或改走 worktree。**「只改一个文件而已」是波内打架的头号入口。**
- 某一步**根本走不通**时同样停下报告，不要硬凑一个"看起来通过"的结果。

---

## 一、波次与写者表（`Mode: wave` 的边界契约）

```
波 0（串行·controller 自己做）  环境前置 + 真库备份 + 契约冻结
        ↓
波 1   T1 截止日修复（Python）      ∥   T4 前端骨架+组件+PWA（TS）
        ↓ 同步点：全量测试 + 机械越界检查 + 波级窄审查
波 2   T2 FTS5+查询层（Python）     ∥   T5 信息流视图（TS）
        ↓ 同步点
波 3   T3 FastAPI+serve（Python）   ∥   T6 类目+日报视图（TS）
        ↓ 同步点
波 4   T7 端到端联调 + 修正（串行，无并行同伴）
        ↓
阶段③ 最终全分支 opus review → 阶段④ 冒烟（真机 Tailscale）
```

### 写者表（从各任务 `Touches` 汇总，**同波内不得重叠**）

| 文件 | 写它的任务 | 所在波 | 同波冲突？ |
|---|---|---|---|
| `vigil/deadline.py`（新） | T1 | 1 | |
| `vigil/digest.py` | T1 | 1 | |
| `vigil/refine.py` | T1 | 1 | |
| `vigil/store.py` | T1、T2 | 1、**2** | 否（不同波） |
| `vigil/cli.py` | T1、T3 | 1、**3** | 否（不同波） |
| `vigil/api.py`（新） | T3、T7 | 3、4 | 否 |
| `tests/test_deadline.py`（新） | T1 | 1 | |
| `tests/test_digest.py` | T1 | 1 | |
| `tests/test_refine.py` | T1 | 1 | |
| `tests/test_store.py` | T2 | 2 | |
| `tests/test_api.py`（新） | T3 | 3 | |
| `web/**` | T4、T5、T6、T7 | 1、2、3、4 | 否（不同波） |
| `.gitignore`、`pyproject.toml`、`uv.lock` | **波 0** | 0 | 不派给任何任务 |

**三个需要留意的归属**（写在这里免得 implementer 猜）：

1. `vigil/cli.py` 被 T1（加 `deadline-audit`）和 T3（加 `serve`）先后写——**分处波 1 与波 3，不重叠**。T3 开写前必须先 `git pull`/读 T1 落地的 `cli.py` 现状，**不许照着计划里的旧片段覆盖**。
2. `vigil/store.py` 同理（T1 加两个函数，T2 加一整节）。T1 的改动会被 T2 继承。
3. `web/` 内三个任务**写不同的文件**：T4 写骨架与共用组件，T5 只写 `src/views/Feed.tsx`，T6 只写 `src/views/Categories.tsx` 与 `src/views/Digests.tsx`。**T5/T6 不许改 `App.tsx`/`types.ts`/`api.ts`**——它们要的一切都由 T4 提供的接口满足；不够用就停下报告。

---

## 二、规划期实测（**本计划的事实依据，不是背景资料**）

写计划时把每条关键设计都在真机真数据上跑过一遍。执行时以这些实测为准，**不要按直觉改回去**。

### 发现 1 ⭐：FTS5 trigram **对短于 3 字符的查询静默返回 0 条**

| 查询 | trigram MATCH | 结论 |
|---|---|---|
| `选课`（2 字） | **0 条**（不报错） | 🔴 中文双字词是最常见的查询 |
| `讲座`（2 字） | **0 条** | 🔴 |
| `补退选`（3 字） | 1 条 | ✅ |
| `校园卡`（3 字） | 命中 | ✅ |

照 spec §4.7 直译（「trigram 支持中文子串匹配」）会让**搜索在双字词上静默返回空**——而「搜不到」会被读成「库里没有」，是本项目反复防的那类假话。→ **`search_items` 必须有 LIKE 兜底分支**（items 270 行、年增约两千行，全表扫可忽略）。

真实数据上的**两条路径阳性对照**（都验过，不是设计意图）：

```
LIKE 路径（<3 字）  选课 8 · 兼职 16 · 面试 19 · 开学 16 · 招聘 9 · 成绩 4 · 快递 2 · 食堂 1
trigram 路径（≥3 字）校园卡 42 · 四六级 16 · 辅导员 5 · 晚自习 4 · 图书馆 1 · 面试通 2
一致性            同一词两路径计数相同（校园卡 42=42）
```

### 发现 2：裸查询串喂给 `MATCH` 会**抛异常**，用户输入必须转义

| 输入 | 裸 `MATCH` | 包成短语后 |
|---|---|---|
| `NOT` | `OperationalError: syntax error` | 0 条 |
| `a"b` | `OperationalError: unterminated string` | 0 条 |
| `(` | `OperationalError: syntax error` | 0 条 |
| `补退选 -卡` | `OperationalError: no such column: 卡` | 0 条 |

→ `_fts_phrase()` 用引号包裹并转义内部引号。**不转义 = 用户在搜索框打个引号就是 500。**
→ `LIKE` 路径同理需要转义 `%` / `_` / `\`（`_escape_like`），否则 `%` 会匹配一切。

### 发现 3 ⭐：SPA 兜底会**吞掉 PWA 的全部静态文件**，且状态码全是 200

用 `app.mount("/assets", StaticFiles(...))` 时，真实进程实测：

```
GET /manifest.webmanifest → 200   712 字节   ← 712 = index.html 的大小
GET /sw.js                → 200   712 字节
GET /icon-192.png         → 200   text/html
```

挂载只覆盖 `/assets` 前缀，而 PWA 要的 `sw.js` / `manifest.webmanifest` / 图标全在**根路径**，全部掉进兜底被当成前端路由。后果：manifest 解析失败、Service Worker 因 MIME 不符注册失败，**「添加到主屏」整条路走不通——而所有状态码都是 200，日志上一个异常都没有**。

→ 静态文件必须在兜底里**显式判一次**再决定发文件还是发 `index.html`（见 T3）。

### 发现 4：`web/dist` 静态托管的路径逃逸必须**断言正文**，不是状态码

四种逃逸变体（`/..%2f.env`、`/..%2f..%2f.env`、三重、`%2e%2e`）实测**全部返回 712 字节的 index.html**——安全。但**只看状态码会得到 200**，看状态码的测试是**空的**：

- 阳性对照（把 `.env` 放进 `dist/` 再请求）→ 测试**确实能抓到** `VIGIL_DB_KEY`。
- 所以 T3 的逃逸测试**必须断言响应正文不含 `VIGIL_DB_KEY`**，并带上这个阳性对照。

### 发现 5：前端栈全是**大版本**，凭记忆写必崩

`npm view` + 真装真构建实测：

| 包 | 实测版本 | 陷阱 |
|---|---|---|
| `tailwindcss` | **4.3.3** | v4 是 CSS-first：`@import 'tailwindcss'` + `@theme`，**没有 `tailwind.config.js`** |
| `@tailwindcss/vite` | 4.3.3 | Tailwind 的接入方式是 Vite 插件，不是 PostCSS 配置 |
| `vite` | **8.3.0** | 底层换 Rolldown |
| `react` / `react-dom` | 19.3.0 | |
| `typescript` | **5.9.3**（刻意不取 `latest` 的 7.0.2） | 7.x 是 Go 重写版，本里程碑不引入这个变量 |
| `vite-plugin-pwa` | 1.3.0 | 产物：`sw.js` / `workbox-*.js` / `manifest.webmanifest` / `registerSW.js` |
| `react-markdown` | 10.1.0 | 日报正文渲染；默认**不渲染原始 HTML**，无需额外 sanitizer |
| `vitest` | 5.0.1 | 只测纯函数，不引 jsdom |
| `@types/react` / `@types/react-dom` | 19.2.7 / 19.2.4 | |

另有一条 TS 编译配置陷阱：模板式的 `import App from './App.tsx'` **必须**配 `allowImportingTsExtensions: true`，否则 `tsc` 报 `TS5097`（实测踩到）。

### 发现 6：截止日回填的**真实数字**（在副本库上跑出来的）

```
带截止日的条目: 26
✅ 源文里找得到依据: 13
❌ 找不到依据（该清掉）: 13
```

清掉的样例（**方向一致往后飘**，且把已发生的事说成「别忘了」）：

| item | 标着 | 标题 | 源文实际 |
|---|---|---|---|
| 184 | 2026-09-14 | 新生需在14日16点前改备注 | 「请于**今天下午16点之前**…」 |
| 219 | 2026-09-14 | 统计截止提醒 | 「还有**半小时**截止统计」 |
| 235 | 2026-09-15 | 开学典礼集合安排 | 「**明早7:20**各班在宿舍楼下集合」 |
| 249 | 2026-09-19 | 西太湖新媒体面试 | 「**周六下午**4.00-8.00」 |
| 4 | 2026-08-31 | 六级成绩将于八月公布 | 「**八月**要出六级成绩了」 |

回填只动 `deadline_ts` 一列——**实测断言过**：改动前/后 `(item_id, title, detail, kind)` 四元组逐一相等。

### 发现 7：隔离副本的两条「假红」来源（**本轮实测踩到**）

1. **副本必须带 `config/`**：`REPO_ROOT` 按包位置解析，只拷 `vigil/` 会让 `load_categories()` 找不到 `config/categories.toml`，**8 个测试集体变红**，看起来像代码坏了。
2. **副本里先自检 `vigil.__file__` 指向副本**：editable finder 可能把 `vigil` 硬映射回工作区，那样副本里改什么都没用（M2 记录在案，本轮再次自检通过）。写法是 `sys.path.insert(0, ".")` 后断言路径含副本目录名。

---

## 三、冻结的 API 契约（**两道并行的唯一接口权威**）

`vigil/api.py` 与 `web/src/types.ts` 是这份契约的两个影子。**改任何一边都必须同时改另一边**——波级窄审查专门核这件事。

### 3.1 端点

| # | 方法 | 路径 | 查询参数 | 成功 | 失败 |
|---|---|---|---|---|---|
| 1 | GET | `/api/items` | `kind` `since` `until` `group` `q` `limit`(默认 50，1..200) `offset` | 200 `ItemPage` | 400 日期格式错；422 参数越界 |
| 2 | GET | `/api/items/{item_id}` | — | 200 `ItemDetail` | 404 |
| 3 | GET | `/api/digests` | `limit`(默认 30，1..200) | 200 `{digests: DigestSummary[]}` | — |
| 4 | GET | `/api/digests/{digest_id}` | — | 200 `DigestDetail` | 404 |
| 5 | GET | `/api/categories` | — | 200 `{categories: Category[]}` | — |
| 6 | GET | `/{任意}` | — | 200 静态文件 或 index.html | 404（`/api/*` 前缀）；503（未构建） |

**错误体一律** `{"detail": "..."}`（FastAPI 默认形状；前端 `api.ts` 就是按它解析的）。

### 3.2 数据形状（字段名逐字冻结）

```ts
Item = {
  item_id: number;  kind: string;  kind_label: string;  kind_icon: string;
  title: string;  detail: string | null;
  event_ts: number;
  deadline_ts: number | null;   // ⚠️ 已过数据层核验；NULL = 源文里没有依据，前端不显示
  group_id: number;  group_name: string;      // 群名来自 config，不是群号
  actor: string | null;  place: string | null;  amount: string | null;
  links: string[];  source_count: number;
}
Source      = { msg_id: number; ts: number; sender: string; group_name: string; content: string }
ItemDetail  = Item & { sources: Source[] }
ItemPage    = { items: Item[]; total: number; limit: number; offset: number }
Category    = { slug: string; label: string; icon: string; count: number }
DigestSummary = { digest_id: number; day: string; window_from: number; window_to: number;
                  created_at: number; item_count: number }
DigestDetail  = DigestSummary & { body_md: string; items: Item[] }
```

### 3.3 语义约定（**这几条不写清楚就会各写各的**）

- **`since` / `until` 都按「包含该日」理解**，内部窗口右端取**次日** 00:00（左闭右开）。选了 9/13 却搜不到 9/13 当天的消息，是最容易让人不信任搜索的错法。
- **日期一律按本地时区**换算 epoch。⚠️ 不用 SQLite 的 `strftime('%s', ...)`——它按 **UTC** 解释同一个日期串，与产品口径差 8 小时（M2 实测记录在案）。
- **`/api/items` 排序为 `event_ts DESC, item_id DESC`（新的在前）**；`/api/digests/{id}` 里的 `items` 为 `event_ts ASC`（与日报正文同序）。两处顺序不同是**故意的**，不许「顺手改成一致」。
- **`q` 先 `strip()`**；空串等于不筛选。
- **`deadline_ts` 不做二次核验**——未经核验的值在**数据层**就已经是 NULL（T1）。这正是「把核验提到数据层」的收益：读取方不需要各自记得再挡一次。
- **API 不做脱敏**。spec §4.5 的「不发群号/uid 给模型」管的是**出网到 LLM**；Web 是本地自用，原文照登是「可回溯」的落地（出口标准第 5 条）。

---

## 四、文件结构

```
vigil/
  deadline.py     新增  ★ 截止日字面核验（从 digest.py 平移）+ 回填用的集合计算
  digest.py       改动  ★ 删掉本地核验定义，改为 import（既有 72 条测试必须全绿）
  refine.py       改动  ★ 写入前核验：源文里找不到的截止日一律不落库
  store.py        改动  ★ T1 加 items_with_deadline/clear_deadlines；T2 加 FTS5 与整节查询层
  cli.py          改动  ★ T1 加 deadline-audit；T3 加 serve
  api.py          新增  ★ 只读 FastAPI 应用工厂（endpoint + 静态托管 + SPA 兜底）
tests/
  test_deadline.py 新增
  test_api.py      新增
web/                     （前端全部新增）
  package.json  vite.config.ts  tsconfig.json  index.html  .gitignore
  tools/make_icons.py    纯 stdlib 生成 PWA 图标（可复现，不引 Pillow）
  public/icon-192.png  icon-512.png  icon-maskable-512.png
  src/main.tsx  index.css  types.ts  api.ts  format.ts  App.tsx
  src/components/ItemCard.tsx  SourceList.tsx
  src/views/Feed.tsx  Categories.tsx  Digests.tsx
  src/__tests__/format.test.ts  api.test.ts
```

---

## 五、波 0：环境前置（**串行，controller 自己做，不派任务**）

已完成的两项（本会话实测）：

- [x] `npm config set cache D:\npm-cache`（spec §1.5 的 Step Zero 0.5）
- [x] `uv add fastapi uvicorn` + `uv add --group dev httpx` → fastapi 0.141.1 / uvicorn 0.53.0 / httpx 0.28.1

开工前必须补的三项：

- [ ] **真库备份**：T2 会给真库加 FTS 表与触发器，虽为**追加性**变更，仍先备份。
      ```bash
      cd /d/github/VIGIL && cp data/vigil.db "data/vigil.db.bak-$(date +%Y%m%d-%H%M)"
      ```
- [ ] **根 `.gitignore` 追加**（前端产物不入库）：
      ```
      web/node_modules/
      web/dist/
      web/dev-dist/
      ```
- [ ] **记 BASE**：`git rev-parse HEAD` 写入 ledger，作为波 1 的 review-package 基点。

---

## Task 1（波 1 · Python 链）：截止日核验提到数据层

**为什么这是 M3 的第一个任务**：M2 只在**日报渲染层**挡住了幻觉截止日。Web 直接读 `items.deadline_ts`，那 13 条没有依据的日期会**原样复活**——而它们正是「把已经发生的事说成别忘了」那一批。核验必须挪到**数据能出错的地方**：写入时挡一次，历史数据回填一次，之后所有读取方自动安全。

**Files:**
- Create: `vigil/deadline.py`、`tests/test_deadline.py`
- Modify: `vigil/digest.py`（删本地定义 → import）
- Modify: `vigil/store.py`（加 `items_with_deadline` / `clear_deadlines`）
- Modify: `vigil/refine.py`（写入前核验）
- Modify: `vigil/cli.py`（加 `deadline-audit`）
- Test（**追加，不许覆盖**）：`tests/test_digest.py`、`tests/test_refine.py`、`tests/test_store.py`

**Interfaces:**
- Consumes: `store.item_sources_text(conn, item_ids) -> dict[int, str]`（M2 已有）；`store.ExtractedItem` / `store.PendingMessage`（M1 已有）
- Produces:
  - `vigil.deadline.deadline_supported(deadline_ts: int | None, sources: str) -> bool`
  - `vigil.deadline.unverified_item_ids(items: list[tuple[int, int | None]], sources: dict[int, str]) -> frozenset[int]`
  - `vigil.store.items_with_deadline(conn) -> list[tuple[int, int]]`
  - `vigil.store.clear_deadlines(conn, item_ids: list[int]) -> int`
  - `vigil.refine._drop_unsupported_deadlines(produced, batch) -> tuple[list[ExtractedItem], int]`
  - `RefineStats.deadlines_dropped: int`

**Dependencies:** 无（波 1 起点）
**Touches:** `vigil/deadline.py` `vigil/digest.py` `vigil/store.py` `vigil/refine.py` `vigil/cli.py` `tests/test_deadline.py` `tests/test_digest.py` `tests/test_refine.py` `tests/test_store.py`

---

- [ ] **Step 1：写失败测试** `tests/test_deadline.py`

```python
"""截止日核验：源文里能不能逐字找到这个日期。

⚠️ 本文件的用例是**从 tests/test_digest.py 的既有覆盖里长出来的**：
核验函数原在 digest.py，M3 平移到 deadline.py。平移的正确性由
「test_digest.py 的 72 条既有测试全绿」证明，本文件补的是**新增的那部分**：
「哪些该清掉」这个集合计算。
"""

from __future__ import annotations

import datetime as dt

from vigil import deadline


def _ts(y: int, m: int, d: int) -> int:
    return int(dt.datetime(y, m, d, 12, 0).timestamp())


def test_supported_when_source_has_the_date_literally():
    assert deadline.deadline_supported(_ts(2026, 9, 16), "9月16日12:00开始报名缴费")


def test_unsupported_when_source_only_has_relative_words():
    # 四条都是真实库里出现过的原文（见计划「发现 6」）
    assert not deadline.deadline_supported(_ts(2026, 9, 14), "请于今天下午16点之前改备注")
    assert not deadline.deadline_supported(_ts(2026, 9, 15), "明早7：20各班在宿舍楼下集合")
    assert not deadline.deadline_supported(_ts(2026, 9, 19), "周六下午4.00-8.00")
    assert not deadline.deadline_supported(_ts(2026, 8, 31), "八月要出六级成绩了")


def test_no_deadline_is_never_supported():
    assert not deadline.deadline_supported(None, "随便什么 9月16日")


def test_unverified_ids_picks_only_the_unsupported():
    items = [(1, _ts(2026, 9, 16)), (2, _ts(2026, 9, 14)), (3, None)]
    sources = {1: "9月16日截止", 2: "今天下午截止", 3: "无关"}
    assert deadline.unverified_item_ids(items, sources) == frozenset({2})


def test_unverified_ids_treats_missing_source_row_as_unsupported():
    """没有来源行 = 证不出来 = 没有依据。**口径必须与 M2 一致。**"""
    assert deadline.unverified_item_ids([(7, _ts(2026, 9, 16))], {}) == frozenset({7})


def test_unverified_ids_ignores_items_without_deadline():
    assert deadline.unverified_item_ids([(1, None), (2, None)], {}) == frozenset()
```

- [ ] **Step 2：跑测试确认失败**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m pytest tests/test_deadline.py -q
```
Expected: `ModuleNotFoundError: No module named 'vigil.deadline'`

- [ ] **Step 3：建 `vigil/deadline.py`**

把 `vigil/digest.py` 里从 **`# 汉字写法里各成分之间允许的空白` 起、到 `def verified_deadlines(` 之前止**的那一段（实测 **69 行**）**逐字搬过来**，保留所有注释——那些注释记录的是真实踩坑（数字边界、不跨消息拼接、裸日不算依据），**不许"顺手精炼"**。文件头与新增函数如下，中间三段原样搬入：

```python
"""截止日核验：这个日期能不能在**源消息正文里逐字找到**。

为什么单独成模块：核验最初长在 M2 的日报渲染层（「别忘」那一节），
而**截止日的可信度是数据属性，不是渲染属性**。M3 的 Web 直接读
`items.deadline_ts`，只在渲染层挡的那道闸门就绕过去了——实测全库 26 条
带截止日的 item 里约半数过不了核验，Web 会把它们原样复活。

所以核验被提到数据层：写入时（refine）挡一次，历史数据用
`vigil deadline-audit --apply` 回填一次。之后**所有读取方自动安全**。
"""

from __future__ import annotations

import datetime as dt
import re

# ………… 逐字搬入 digest.py 的【_GAP 注释块 + _GAP】、【_date_patterns】、【deadline_supported】…………


def unverified_item_ids(
    items: list[tuple[int, int | None]], sources: dict[int, str]
) -> frozenset[int]:
    """哪些 item 的截止日**在源文里没有依据**（只统计真有截止日的那些）。

    没有来源行的 item（``sources`` 里查不到）一律按**无依据**处理——
    与 ``digest.verified_deadlines`` 同一口径：**证不出来就是没有**。

    ⚠️ 这里返回的是「该清掉」的集合，而不是「该保留」的集合。命名方向
    故意与 ``verified_deadlines`` 相反，因为它们各自的调用点是反的：
    渲染层是「挑出可信的去显示」，数据层是「挑出不可信的来清掉」。
    """
    out: list[int] = []
    for item_id, deadline_ts in items:
        if deadline_ts and not deadline_supported(deadline_ts, sources.get(item_id, "")):
            out.append(item_id)
    return frozenset(out)
```

- [ ] **Step 4：跑测试确认通过**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m pytest tests/test_deadline.py -q
```
Expected: `6 passed`

- [ ] **Step 5：`digest.py` 改为 import**

删掉刚搬走的那一段，原地替换为：

```python
# 截止日的字面依据核验已提到 `vigil/deadline.py`——数据层（refine 写入、
# deadline-audit 回填）与渲染层（日报「别忘」）共用同一套判据。
# ⚠️ 保留 import 而不是各复制一份：两处判据一旦漂移，就会出现
# 「日报说这条截止日没依据、Web 里却明晃晃显示着」这种自相矛盾。
from .deadline import deadline_supported
```

⚠️ **只删这三段**：`_GAP` 及其注释块、`_date_patterns`、`deadline_supported`。
**`_PUNCT` 与 `_norm` 一个字都不许动**——它们管「摘录匹配」，与截止日无关；`verified_deadlines` 也保留（它操作 `WindowItem`，是日报专属）。
⚠️ `import datetime as dt` 与 `import re` 在 digest.py 里可能因此变成未使用——**先查再删**（`_norm`/`_PUNCT` 用 `re`，别处可能用 `dt`）。

- [ ] **Step 6：跑 M2 全量测试，证明平移没改行为**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m pytest tests/test_digest.py -q
```
Expected: **`72 passed`**（与平移前一致。这 72 条里有 10 条直接调用 `digest.deadline_supported`，它们全绿就是**行为未变的证据**）

- [ ] **Step 7：给 `tests/test_digest.py` 追加同一性测试**

```python
def test_deadline_supported_is_the_shared_module_not_a_local_copy():
    """守住「判据只有一份」。

    若有人日后又在 digest.py 里写回一个本地 `deadline_supported`，
    Web 侧（读 deadline.py）与日报侧（读本地副本）就会各判各的——
    同一条截止日可能在日报里被隐去、在 Web 上照常显示。
    """
    from vigil import deadline

    assert digest.deadline_supported is deadline.deadline_supported
```

- [ ] **Step 8：`store.py` 追加两个函数**

```python
def items_with_deadline(conn: sqlite3.Connection) -> list[tuple[int, int]]:
    """所有**带截止日**的 ``(item_id, deadline_ts)``。回填核验用。"""
    return [
        (int(a), int(b))
        for a, b in conn.execute(
            "SELECT item_id, deadline_ts FROM items"
            " WHERE deadline_ts IS NOT NULL ORDER BY item_id"
        )
    ]


def clear_deadlines(conn: sqlite3.Connection, item_ids: list[int]) -> int:
    """把给定条目的 ``deadline_ts`` 置 NULL，返回实际改动行数。

    只动这一列：条目的标题、正文、来源一概不碰——**降级的是那一个字段，
    不是整条信息**。用户仍然看得到这条，只是不再被告知一个编出来的日期。
    """
    if not item_ids:
        return 0
    marks = ",".join("?" * len(item_ids))
    cur = conn.execute(
        f"UPDATE items SET deadline_ts = NULL WHERE item_id IN ({marks})",
        list(item_ids),
    )
    conn.commit()
    return int(cur.rowcount)
```

- [ ] **Step 9：给 `tests/test_store.py` 追加**

```python
def test_items_with_deadline_only_returns_rows_that_have_one():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, deadline_ts=1000)
    _insert_item(conn, 2, deadline_ts=None)
    assert store.items_with_deadline(conn) == [(1, 1000)]


def test_clear_deadlines_only_touches_that_column():
    """降级的必须是**那一个字段**，不是整条信息。"""
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, deadline_ts=1000)
    before = conn.execute("SELECT item_id, title, kind FROM items").fetchall()
    assert store.clear_deadlines(conn, [1]) == 1
    assert conn.execute("SELECT item_id, title, kind FROM items").fetchall() == before
    assert conn.execute("SELECT deadline_ts FROM items").fetchone()[0] is None


def test_clear_deadlines_with_empty_list_is_a_noop():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    assert store.clear_deadlines(conn, []) == 0
```

> `_insert_item` 若不存在，**按本文件既有的插桩风格补一个**（读文件开头看它怎么造 items，照它的样子来）。属**逃逸舱内**修正，报告里写一句。

- [ ] **Step 10：`refine.py` 写入前核验**

① import 行补 `replace`：`from dataclasses import dataclass, field, replace`
② import 区加：`from .deadline import deadline_supported`
③ `RefineStats` 加字段（放 `items_saved: int = 0` 之后）：
```python
    deadlines_dropped: int = 0   # 源文里找不到依据、被降级的截止日条数
```
④ 加函数（放 `_to_item` 附近）：
```python
def _drop_unsupported_deadlines(
    produced: list[store.ExtractedItem], batch: list[store.PendingMessage]
) -> tuple[list[store.ExtractedItem], int]:
    """写入前核验：源文里找不到字面依据的截止日一律置 None。

    ⚠️ 核验放在**写入边界**而不是渲染层：数据一旦入库就到处流，每个读取方
    各挡一次，迟早有人忘——M2 就只在日报挡过，M3 的 Web 差一点把那 13 条
    幻觉日期原样复活（「今天下午16点之前」被填成 9-14、「明早7:20」被填成 9-15）。

    ⚠️ 只降级 deadline_ts 这一个字段：条目的标题、正文、来源一概不动。
    用户仍然看得到这条信息，只是不再被告知一个编出来的日期。
    """
    texts = {m.msg_id: (m.content or "") for m in batch}
    out: list[store.ExtractedItem] = []
    dropped = 0
    for it in produced:
        if it.deadline_ts and not deadline_supported(
            it.deadline_ts, "\n".join(texts.get(mid, "") for mid in it.src_msg_ids)
        ):
            dropped += 1
            it = replace(it, deadline_ts=None)
        out.append(it)
    return out, dropped
```
⑤ 批次循环里保存那一段改为：
```python
            if produced:
                produced, dropped = _drop_unsupported_deadlines(produced, batch)
                stats.deadlines_dropped += dropped
                stats.items_saved += store.save_items(
                    conn, produced, model=model, prompt_ver=prompt_ver
                )
```

- [ ] **Step 11：给 `tests/test_refine.py` 追加**

```python
def test_refine_drops_deadline_without_literal_evidence():
    """源文写「明早」，模型却填了具体日期——这个截止日不许落库。

    真实数据里的原样：「明早7：20各班在宿舍楼下集合」被填成 09-15。
    """
    ts = int(dt.datetime(2026, 9, 15, 12, 0).timestamp())
    batch = [_msg(1, content="各位小班：明早7：20各班在宿舍楼下集合")]
    item = _extracted(deadline_ts=ts)
    out, dropped = refine._drop_unsupported_deadlines([item], batch)
    assert dropped == 1
    assert out[0].deadline_ts is None
    assert out[0].title == item.title       # 其余字段一个都不许动


def test_refine_keeps_deadline_with_literal_evidence():
    ts = int(dt.datetime(2026, 9, 16, 12, 0).timestamp())
    batch = [_msg(1, content="9月16日12:00开始报名缴费")]
    out, dropped = refine._drop_unsupported_deadlines([_extracted(deadline_ts=ts)], batch)
    assert dropped == 0
    assert out[0].deadline_ts == ts
```

> `_msg` / `_extracted` 若不存在，**按本文件既有风格补**（逃逸舱内修正，报告写明）。

- [ ] **Step 12：`cli.py` 加 `deadline-audit`**

```python
def cmd_deadline_audit(args) -> int:
    """截止日核验：列出源文里**找不到字面依据**的 deadline_ts。--apply 才写库。"""
    import sqlite3

    from . import deadline as deadline_mod

    config = _load_config_only()
    db = _require_export_db(config)

    conn = sqlite3.connect(str(db))
    try:
        rows = store.items_with_deadline(conn)
        if not rows:
            print("（库里没有带截止日的条目）")
            return 0
        sources = store.item_sources_text(conn, [r[0] for r in rows])
        bad = deadline_mod.unverified_item_ids(rows, sources)
        kept = [r for r in rows if r[0] not in bad]

        print(f"带截止日的条目：{len(rows)} 条")
        print(f"  源文里找得到依据：{len(kept)} 条")
        print(f"  找不到依据（应清掉）：{len(bad)} 条")
        for item_id, ts in rows:
            if item_id in bad:
                title = conn.execute(
                    "SELECT title FROM items WHERE item_id = ?", (item_id,)
                ).fetchone()[0]
                print(
                    f"    item {item_id}: 标着 "
                    f"{dt.datetime.fromtimestamp(ts):%Y-%m-%d} · {title[:24]}"
                )
        if not bad:
            print("无需改动。")
            return 0
        if not args.apply:
            print("\n（--dry-run：未写库。确认无误后加 --apply）")
            return 0
        changed = store.clear_deadlines(conn, sorted(bad))
        print(f"\n已把 {changed} 条的 deadline_ts 置 NULL（其余字段未动）。")
        return 0
    finally:
        conn.close()
```

⚠️ `cli.py` 需要 `import sqlite3`——**放在文件顶部 import 区**（该文件现有 import 里没有它），别用局部 import 混过去。同时确认 `dt` 已导入（现有 `_fmt_ts` 用了它）。

并在 `main()` 里注册（放 `p_digest` 之前）：
```python
    p_dl = sub.add_parser(
        "deadline-audit", help="截止日核验：源文里找不到依据的一律清掉"
    )
    p_dl.add_argument("--apply", action="store_true", help="真的写库（默认只报告）")
    p_dl.set_defaults(func=cmd_deadline_audit)
```

另在 `cmd_refine` 的 `if stats.errors:` **之前**补：
```python
    if stats.deadlines_dropped:
        # 降级必须看得见——静默丢掉一个日期和静默编造一个日期同样有害
        print(
            f"[注意] {stats.deadlines_dropped} 条截止日在源消息里找不到字面依据，"
            f"未落库（条目本身仍照常出现）"
        )
```

- [ ] **Step 13：全量测试**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: **`270 + 新增` 全绿**，无 failure、无 error。

- [ ] **Step 14：对真库跑 dry-run（不写库）**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m vigil deadline-audit
```
Expected（与规划期副本实测一致）：
```
带截止日的条目：26 条
  源文里找得到依据：13 条
  找不到依据（应清掉）：13 条
```
**数字若与 26/13 不符，停下报告 controller**——库可能被动过，先查清楚再动。

- [ ] **Step 15：`--apply` 回填，并证明幂等**

```bash
cd /d/github/VIGIL && cp data/vigil.db "data/vigil.db.bak-before-deadline-$(date +%H%M)" \
  && .venv/Scripts/python.exe -m vigil deadline-audit --apply \
  && .venv/Scripts/python.exe -m vigil deadline-audit
```
Expected: 第一次 `已把 13 条的 deadline_ts 置 NULL（其余字段未动）。`；
第二次 **`找不到依据（应清掉）：0 条` + `无需改动。`**（幂等证据）。

- [ ] **Step 16：自查后提交**

```bash
cd /d/github/VIGIL \
  && git add vigil/deadline.py vigil/digest.py vigil/store.py vigil/refine.py vigil/cli.py \
             tests/test_deadline.py tests/test_digest.py tests/test_refine.py tests/test_store.py \
  && git commit -m "feat(deadline): 截止日字面核验提到数据层，回填 13 条无依据的 deadline_ts" \
  && git show --stat HEAD
```
⚠️ **数据回填（Step 15）不进 commit**——它是数据变更不是代码变更；但**报告里必须写 before/after 数字**，reviewer 靠它核。

---

## Task 2（波 2 · Python 链）：FTS5 搜索索引 + 查询层

**Files:**
- Modify: `vigil/store.py`
- Test（**追加**）：`tests/test_store.py`

**Interfaces:**
- Consumes: `store.ensure_schema`（M1）、`_ITEM_COLS` 等本任务新建
- Produces:
  - `store.MIN_TRIGRAM: int = 3`
  - `store.rebuild_search_index(conn) -> None`
  - `store.search_items(conn, *, kind=None, since=None, until=None, group=None, q=None, limit=50, offset=0) -> tuple[list[ApiItem], int]`
  - `store.get_item(conn, item_id: int) -> ApiItem | None`
  - `store.source_messages(conn, item_id: int) -> list[SourceRow]`
  - `store.kind_counts(conn) -> dict[str, int]`
  - `store.list_digests(conn, *, limit=30) -> list[DigestSummaryRow]`
  - `store.get_digest(conn, digest_id: int) -> DigestRow | None`
  - `store.digest_items(conn, digest_id: int) -> list[ApiItem]`
  - dataclass：`ApiItem` / `SourceRow` / `DigestSummaryRow` / `DigestRow`

**Dependencies:** Task 1（同一文件，T1 的两个函数要先落地）
**Touches:** `vigil/store.py`、`tests/test_store.py`

---

- [ ] **Step 1：写失败测试**（`tests/test_store.py` 追加）

```python
def test_search_finds_two_chinese_chars_via_like_fallback():
    """⭐ 双字词必须搜得到——这是本任务的头号陷阱。

    FTS5 trigram 对**短于 3 字符**的查询静默返回 0 条（不报错），
    而中文双字词（「选课」「讲座」）恰恰是最常见的查询。
    没有 LIKE 兜底的话，「搜不到」会被读成「库里没有」。
    """
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, title="选课通知", kind="academic")
    _insert_item(conn, 2, title="失物招领", kind="lostfound")
    items, total = store.search_items(conn, q="选课")
    assert total == 1 and items[0].item_id == 1


def test_search_finds_three_chinese_chars_via_trigram():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, title="校园卡补办", kind="life")
    items, total = store.search_items(conn, q="校园卡")
    assert total == 1 and items[0].item_id == 1


def test_search_survives_fts5_syntax_characters():
    """用户输入直接喂 MATCH 会抛 OperationalError——必须被包成短语。"""
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, title="选课通知", kind="academic")
    for q in ["NOT", 'a"b', "(", "补退选 -卡", "a OR b"]:
        store.search_items(conn, q=q)      # 不抛异常即通过


def test_search_escapes_like_wildcards():
    """`%` 不转义就会匹配一切——那是个假数字。"""
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, title="选课通知", kind="academic")
    _, total = store.search_items(conn, q="%")
    assert total == 0


def test_search_filters_by_kind_and_window():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, kind="academic", event_ts=100)
    _insert_item(conn, 2, kind="job", event_ts=200)
    assert store.search_items(conn, kind="job")[1] == 1
    assert store.search_items(conn, since=150)[1] == 1
    assert store.search_items(conn, until=150)[1] == 1


def test_search_is_newest_first():
    """信息流按时间倒着看。⚠️ 与 window_items 的 ASC 不同是**故意的**。"""
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, event_ts=100)
    _insert_item(conn, 2, event_ts=200)
    items, _ = store.search_items(conn)
    assert [i.item_id for i in items] == [2, 1]


def test_source_messages_returns_the_linked_messages():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1)
    _insert_message(conn, 11, content="原文在这里")
    conn.execute("INSERT INTO item_sources (item_id, msg_id) VALUES (1, 11)")
    srcs = store.source_messages(conn, 1)
    assert len(srcs) == 1 and srcs[0].content == "原文在这里"


def test_source_messages_of_unknown_item_is_empty():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    assert store.source_messages(conn, 999) == []


def test_digest_items_are_in_ascending_order_like_the_digest_body():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, event_ts=200)
    _insert_item(conn, 2, event_ts=100)
    conn.execute(
        "INSERT INTO digests (digest_id, window_from, window_to, body_md, model,"
        " prompt_ver, created_at) VALUES (1, 100, 300, '正文', 'm', 'v1', 1)"
    )
    conn.execute("INSERT INTO digest_items (digest_id, item_id) VALUES (1, 1), (1, 2)")
    assert [i.item_id for i in store.digest_items(conn, 1)] == [2, 1]


def test_kind_counts_groups_by_kind():
    conn = sqlite3.connect(":memory:")
    store.ensure_schema(conn)
    _insert_item(conn, 1, kind="academic")
    _insert_item(conn, 2, kind="academic")
    _insert_item(conn, 3, kind="job")
    assert store.kind_counts(conn) == {"academic": 2, "job": 1}
```

> `_insert_message` 若不存在，按本文件既有风格补（逃逸舱内修正，报告写明）。

- [ ] **Step 2：跑测试确认失败**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m pytest tests/test_store.py -q
```
Expected: `AttributeError: module 'vigil.store' has no attribute 'search_items'`

- [ ] **Step 3：在 `store.py` 里插入 `_SEARCH_DDL`**

位置：**紧接 `_DIGEST_ITEMS_DDL` 之后、`SCHEMA_DDL` 之前**（`SCHEMA_DDL` 要引用它）。

```python
# items_fts：搜索索引。**外部内容表**（content='items'）而不是另存一份正文——
# 正文只存 items 一处，索引只存分词位置，省空间也不会两份数据说了不一样的话。
#
# ⚠️ tokenize='trigram' 的理由：中文没有词边界，trigram 按 3 字符滑窗建索引，
# 于是「子串匹配」天然可用，不需要分词器。但它有两条实测出来的脾气：
#   1. **短于 3 字符的查询静默返回 0 条**（不报错）→ 见 search_items 的兜底分支
#   2. 裸查询串会被当 FTS5 语法解析，`NOT`/`(`/`a"b` 直接抛错 → 见 _fts_phrase
_SEARCH_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    title, detail,
    content='items', content_rowid='item_id',
    tokenize='trigram'
);
CREATE TRIGGER IF NOT EXISTS items_fts_ai AFTER INSERT ON items BEGIN
  INSERT INTO items_fts(rowid, title, detail)
  VALUES (new.item_id, new.title, new.detail);
END;
CREATE TRIGGER IF NOT EXISTS items_fts_ad AFTER DELETE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, title, detail)
  VALUES ('delete', old.item_id, old.title, old.detail);
END;
CREATE TRIGGER IF NOT EXISTS items_fts_au AFTER UPDATE ON items BEGIN
  INSERT INTO items_fts(items_fts, rowid, title, detail)
  VALUES ('delete', old.item_id, old.title, old.detail);
  INSERT INTO items_fts(rowid, title, detail)
  VALUES (new.item_id, new.title, new.detail);
END;
"""
```

并把 `SCHEMA_DDL` 改为（注意 `+ _SEARCH_DDL`）：

```python
SCHEMA_DDL = (
    _ITEMS_DDL
    + _SOURCES_DDL
    + _RUNS_DDL
    + _DIGESTS_DDL
    + _DIGEST_ITEMS_DDL
    + _SEARCH_DDL
)
```

- [ ] **Step 4：`ensure_schema` 挂上索引重建**

```python
def ensure_schema(conn: sqlite3.Connection) -> None:
    """建表。幂等——每次 refine 都调，不靠外部迁移工具。

    顺带重建搜索索引：触发器只管建好之后的新数据，**存量行**得靠 rebuild。
    跑在写路径上（refine / digest），代价是 O(条目数)，换来「索引不会
    长期停在过期状态」——搜索返回空结果时，那个空结果才真是「库里没有」。
    """
    conn.executescript(SCHEMA_DDL)
    rebuild_search_index(conn)
    conn.commit()
```

- [ ] **Step 5：把检索层与查询层**追加到 `store.py` 末尾

```python
# FTS5 trigram 的最小可查长度。短于它的查询**不会报错，只会返回空**。
MIN_TRIGRAM = 3


def rebuild_search_index(conn: sqlite3.Connection) -> None:
    """把搜索索引与 items 重建一致。

    触发器建好之后新数据会自动同步；这个函数管的是**存量行**与
    「索引曾经与 items 脱节」的情况。
    """
    conn.execute("INSERT INTO items_fts(items_fts) VALUES ('rebuild')")
    conn.commit()


def _fts_phrase(q: str) -> str:
    """把用户输入包成 FTS5 **短语**查询。

    ⚠️ 不包就会炸（实测）：`NOT`、`a"b`、`(`、`补退选 -卡` 全都让 MATCH 抛
    ``OperationalError``——用户在搜索框里打个引号就是 500。包成短语后，
    这些输入退化成「按字面找这个短语」，语义仍然正确。
    """
    return '"' + q.replace('"', '""') + '"'


def _escape_like(q: str) -> str:
    """LIKE 的通配符转义。不转义的话用户输入的 % 会变成「匹配一切」。"""
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class ApiItem:
    """喂给 Web 的一条条目。列名与 API 契约逐字对应。

    ``actor`` 已在 SQL 里解析成姓名（同 ``pending_messages`` 的口径）；
    ``group_name`` 不在这里解析——群名来自 ``config/groups.toml`` 而不是库，
    由 API 层补上。库返回 id、配置层补名字，这个分工与既有代码一致。
    """

    item_id: int
    kind: str
    title: str
    detail: str | None
    event_ts: int
    deadline_ts: int | None
    group_id: int
    actor: str | None
    place: str | None
    amount: str | None
    links: tuple[str, ...]
    source_count: int


@dataclass(frozen=True)
class SourceRow:
    """一条源消息的原文。Web 的「点回原文」靠它。"""

    msg_id: int
    ts: int
    sender: str
    group_id: int
    content: str


@dataclass(frozen=True)
class DigestSummaryRow:
    digest_id: int
    window_from: int
    window_to: int
    created_at: int
    item_count: int


@dataclass(frozen=True)
class DigestRow:
    digest_id: int
    window_from: int
    window_to: int
    body_md: str
    created_at: int
    item_count: int


_ITEM_COLS = (
    "i.item_id, i.kind, i.title, i.detail, i.event_ts, i.deadline_ts, i.group_id,"
    " COALESCE(NULLIF(sn.group_nick, ''), NULLIF(sn.qq_nick, ''), '') AS actor,"
    " i.place, i.amount, i.links,"
    " (SELECT COUNT(*) FROM item_sources src WHERE src.item_id = i.item_id)"
    "   AS source_count"
)

_ITEM_JOINS = (
    " FROM items i"
    " LEFT JOIN sender_names sn ON sn.group_id = i.group_id AND sn.uid = i.actor_uid"
)


def _parse_links(raw: object) -> tuple[str, ...]:
    """``items.links`` 存的是 JSON 数组文本。

    ⚠️ 解析失败**不抛异常**：这一列是 M1 写的，坏一条不该让整页 500。
    解析不出来就当没有链接（视图少一栏，不是白屏）。
    """
    if not raw:
        return ()
    try:
        data = json.loads(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ()
    if not isinstance(data, list):
        return ()
    return tuple(str(x) for x in data)


def _to_api_item(row: tuple) -> ApiItem:
    (item_id, kind, title, detail, event_ts, deadline_ts, group_id,
     actor, place, amount, links, source_count) = row
    return ApiItem(
        item_id=item_id,
        kind=kind,
        title=title,
        detail=detail,
        event_ts=event_ts,
        deadline_ts=deadline_ts,
        group_id=group_id,
        actor=actor or None,
        place=place,
        amount=amount,
        links=_parse_links(links),
        source_count=int(source_count),
    )


def _item_filters(
    *,
    kind: str | None,
    since: int | None,
    until: int | None,
    group: int | None,
    q: str | None,
) -> tuple[list[str], list[object]]:
    """拼 WHERE 片段。**关键词的两条路径在这里分岔**（trigram / LIKE）。"""
    where: list[str] = []
    params: list[object] = []
    if kind:
        where.append("i.kind = ?")
        params.append(kind)
    if since is not None:
        where.append("i.event_ts >= ?")
        params.append(since)
    if until is not None:
        where.append("i.event_ts < ?")
        params.append(until)
    if group is not None:
        where.append("i.group_id = ?")
        params.append(group)
    if q:
        if len(q) >= MIN_TRIGRAM:
            where.append(
                "i.item_id IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?)"
            )
            params.append(_fts_phrase(q))
        else:
            # ⚠️ trigram tokenizer **对短于 3 字符的查询静默返回 0 条**（实测，
            # 不报错）——而中文双字词（「选课」「讲座」）恰恰是最常见的查询。
            # 没有这一支的话，「搜不到」会被读成「库里没有」，是句假话。
            # items 目前 270 行、年增约两千行，LIKE 全表扫的代价可以忽略。
            like = f"%{_escape_like(q)}%"
            where.append(
                "(i.title LIKE ? ESCAPE '\\'"
                " OR IFNULL(i.detail, '') LIKE ? ESCAPE '\\')"
            )
            params += [like, like]
    return where, params


def search_items(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    since: int | None = None,
    until: int | None = None,
    group: int | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ApiItem], int]:
    """查条目，返回 ``(当页, 符合条件的总数)``。

    排序是 ``event_ts DESC, item_id DESC``（新的在前）——信息流的默认读法。
    ⚠️ 与 ``window_items`` 的 ASC 不同是**故意的**：日报按时间顺着读，
    信息流按时间倒着看。两处都不许「顺手改成一致」。
    """
    where, params = _item_filters(
        kind=kind, since=since, until=until, group=group, q=q
    )
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = int(
        conn.execute(f"SELECT COUNT(*) FROM items i{clause}", params).fetchone()[0]
    )
    rows = conn.execute(
        f"SELECT {_ITEM_COLS}{_ITEM_JOINS}{clause}"
        " ORDER BY i.event_ts DESC, i.item_id DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return [_to_api_item(r) for r in rows], total


def get_item(conn: sqlite3.Connection, item_id: int) -> ApiItem | None:
    """单条条目；不存在返回 None（由调用方决定 404 的形状）。"""
    row = conn.execute(
        f"SELECT {_ITEM_COLS}{_ITEM_JOINS} WHERE i.item_id = ?", (item_id,)
    ).fetchone()
    return _to_api_item(row) if row else None


def source_messages(conn: sqlite3.Connection, item_id: int) -> list[SourceRow]:
    """这条 item 来源消息的**原文**，按 ``(ts, msg_id)`` 升序。

    顺序是当初喂给模型的顺序——回溯时读起来才顺。

    名字不叫 ``item_sources``——那会与**表名**撞车，读代码时分不清
    说的是表还是函数（这里返回的是「消息」，不是「来源行」）。
    """
    rows = conn.execute(
        "SELECT m.msg_id, m.ts,"
        " COALESCE(NULLIF(sn.group_nick, ''), NULLIF(sn.qq_nick, ''), '') AS sender,"
        " m.group_id, IFNULL(m.content, '')"
        " FROM item_sources src"
        " JOIN messages m ON m.msg_id = src.msg_id"
        " LEFT JOIN sender_names sn"
        "        ON sn.group_id = m.group_id AND sn.uid = m.sender_uid"
        " WHERE src.item_id = ?"
        " ORDER BY m.ts ASC, m.msg_id ASC",
        (item_id,),
    ).fetchall()
    return [SourceRow(*r) for r in rows]


def kind_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """每个类目有多少条。类目视图的角标用它。"""
    return {
        str(k): int(n)
        for k, n in conn.execute("SELECT kind, COUNT(*) FROM items GROUP BY kind")
    }


def list_digests(
    conn: sqlite3.Connection, *, limit: int = 30
) -> list[DigestSummaryRow]:
    """日报列表，最近的窗口在前。**不带正文**——列表页用不上，白白撑大响应。"""
    rows = conn.execute(
        "SELECT d.digest_id, d.window_from, d.window_to, d.created_at,"
        " (SELECT COUNT(*) FROM digest_items di WHERE di.digest_id = d.digest_id)"
        " FROM digests d ORDER BY d.window_from DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [DigestSummaryRow(*r) for r in rows]


def get_digest(conn: sqlite3.Connection, digest_id: int) -> DigestRow | None:
    row = conn.execute(
        "SELECT d.digest_id, d.window_from, d.window_to, d.body_md, d.created_at,"
        " (SELECT COUNT(*) FROM digest_items di WHERE di.digest_id = d.digest_id)"
        " FROM digests d WHERE d.digest_id = ?",
        (digest_id,),
    ).fetchone()
    return DigestRow(*row) if row else None


def digest_items(conn: sqlite3.Connection, digest_id: int) -> list[ApiItem]:
    """一篇日报引用的条目，按 ``(event_ts, item_id)`` 升序——与日报正文同序。"""
    rows = conn.execute(
        f"SELECT {_ITEM_COLS}{_ITEM_JOINS}"
        " JOIN digest_items di ON di.item_id = i.item_id"
        " WHERE di.digest_id = ?"
        " ORDER BY i.event_ts ASC, i.item_id ASC",
        (digest_id,),
    ).fetchall()
    return [_to_api_item(r) for r in rows]
```

⚠️ `json` 在 `store.py` 顶部已经 import 过（M1 就用它序列化 `links`），**先确认再动手**。
⚠️ `get_digest` 的 `DigestRow(*row)` 列顺序必须与 `SELECT` 逐字对应——**多加一列就会静默错位**，这是本任务最容易犯的错。

- [ ] **Step 6：跑测试确认通过**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m pytest tests/test_store.py -q
```
Expected: 全绿。

- [ ] **Step 7：全量测试 + 真库建索引**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: 全绿（`ensure_schema` 现在会重建索引，**所有既有测试都跑在这条新代码上**）。

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -c "
import sqlite3
from vigil import store
conn = sqlite3.connect('data/vigil.db')
store.ensure_schema(conn)
print('items:', conn.execute('SELECT COUNT(*) FROM items').fetchone()[0])
for q in ['选课', '兼职', '校园卡', '四六级']:
    _, n = store.search_items(conn, q=q, limit=1)
    print(f'  {q} → {n} 条')
"
```
Expected（与规划期实测一致）：`选课 8 · 兼职 16 · 校园卡 42 · 四六级 16`。
**数字对不上就停下报告**——说明真库或索引有问题。

- [ ] **Step 8：自查后提交**

```bash
cd /d/github/VIGIL && git add vigil/store.py tests/test_store.py \
  && git commit -m "feat(store): FTS5 trigram 搜索索引 + 只读查询层（含短词 LIKE 兜底）" \
  && git show --stat HEAD
```

---

## Task 3（波 3 · Python 链）：只读 FastAPI 服务 + `vigil serve`

**Files:**
- Create: `vigil/api.py`、`tests/test_api.py`
- Modify: `vigil/cli.py`（加 `serve`）

**Interfaces:**
- Consumes: T2 的全部查询函数与 dataclass；`config.Config` / `config.REPO_ROOT`；`categories.load_categories()`
- Produces:
  - `vigil.api.WEB_DIST: pathlib.Path`
  - `vigil.api.MAX_LIMIT: int = 200`
  - `vigil.api.create_app(config: Config) -> FastAPI`

**Dependencies:** Task 2（要用它的查询函数）、Task 4（`web/dist` 要有东西可托管——**没有也能起服务并给 503 提示**，所以不阻塞）
**Touches:** `vigil/api.py`、`vigil/cli.py`、`tests/test_api.py`

---

- [ ] **Step 1：写失败测试** `tests/test_api.py`

```python
"""API 契约测试。

⚠️ 这里测的是**契约形状与边界**，不是「能不能跑通」：
每个字段名、每个状态码都是前端 `web/src/types.ts` 依赖的东西，
改名不会有任何编译错误，只会让页面静默少一栏或整页空掉。
"""

from __future__ import annotations

import datetime as dt
import sqlite3

import pytest
from fastapi.testclient import TestClient

from vigil import store
from vigil.api import create_app


@pytest.fixture()
def client(tmp_path):
    """临时库 + 临时配置。**不碰真库、不碰真 config**。"""
    db = tmp_path / "vigil.db"
    conn = sqlite3.connect(str(db))
    store.ensure_schema(conn)
    ts = int(dt.datetime(2026, 9, 13, 12, 0).timestamp())
    conn.execute(
        "INSERT INTO items (item_id, kind, title, detail, event_ts, deadline_ts,"
        " group_id, actor_uid, place, amount, links, confidence, model, prompt_ver,"
        " created_at) VALUES (1, 'academic', '选课通知', '9月16日截止', ?, NULL,"
        " 12345, 'u1', NULL, NULL, '[\"https://x.test/a\"]', 0.9, 'm', 'v1', 1)",
        (ts,),
    )
    conn.execute(
        "INSERT INTO messages (msg_id, group_id, ts, sender_uid, content)"
        " VALUES (11, 12345, ?, 'u1', '原文在这里')",
        (ts,),
    )
    conn.execute("INSERT INTO item_sources (item_id, msg_id) VALUES (1, 11)")
    conn.commit()
    conn.close()

    cfg = _config_for(db)
    return TestClient(create_app(cfg))


def test_items_returns_the_frozen_field_set(client):
    body = client.get("/api/items").json()
    assert {"items", "total", "limit", "offset"} == set(body)
    item = body["items"][0]
    assert {
        "item_id", "kind", "kind_label", "kind_icon", "title", "detail", "event_ts",
        "deadline_ts", "group_id", "group_name", "actor", "place", "amount",
        "links", "source_count",
    } == set(item)
    assert item["links"] == ["https://x.test/a"]      # links 是数组，不是 JSON 字符串
    assert item["kind_label"] == "学业"                # 类目名解析出来了
    assert item["source_count"] == 1


def test_item_detail_includes_source_messages(client):
    body = client.get("/api/items/1").json()
    assert body["sources"][0]["content"] == "原文在这里"
    assert {"msg_id", "ts", "sender", "group_name", "content"} == set(body["sources"][0])


def test_missing_item_is_404_with_detail(client):
    r = client.get("/api/items/999999")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_api_typo_is_404_not_the_spa_page(client):
    """⭐ `/api/*` 绝不能被 SPA 兜底接走。

    否则 `GET /api/typo` 返回 **200 的 HTML**，前端 `r.json()` 直接炸，
    而真正的 404 被吞掉——排查时会往完全错误的方向找。
    """
    r = client.get("/api/typo")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_categories_carry_counts(client):
    cats = client.get("/api/categories").json()["categories"]
    assert len(cats) == 7
    assert {"slug", "label", "icon", "count"} == set(cats[0])
    assert [c["slug"] for c in cats][0] == "notice"     # 顺序 = config 里的顺序


def test_since_and_until_include_the_named_days(client):
    """⚠️ `until` 必须**包含**该日，否则选了 9/13 搜不到 9/13。"""
    assert client.get("/api/items", params={"since": "2026-09-13"}).json()["total"] == 1
    assert client.get("/api/items", params={"until": "2026-09-13"}).json()["total"] == 1
    assert client.get("/api/items", params={"until": "2026-09-12"}).json()["total"] == 0


def test_bad_date_is_400_not_500(client):
    r = client.get("/api/items", params={"since": "不是日期"})
    assert r.status_code == 400 and "detail" in r.json()


def test_limit_over_max_is_422(client):
    assert client.get("/api/items", params={"limit": 99999}).status_code == 422


def test_spa_returns_503_when_frontend_not_built(client, tmp_path, monkeypatch):
    """前端没构建时不许返回空白页——要明说「去跑 npm run build」。"""
    import vigil.api as api

    monkeypatch.setattr(api, "WEB_DIST", tmp_path / "nope")
    r = client.get("/")
    assert r.status_code == 503
    assert "npm run build" in r.text


def test_static_file_is_served_as_a_file_not_the_spa_page(client, tmp_path, monkeypatch):
    """⭐ PWA 的 sw.js / manifest 必须发**真文件**。

    实测踩到过：`app.mount("/assets", ...)` 只覆盖 /assets 前缀，而
    sw.js / manifest.webmanifest / 图标都在根路径 → 全被 SPA 兜底接走，
    返回 200 的 index.html。浏览器把 HTML 当 manifest 解析、当 SW 注册，
    「添加到主屏」整条路走不通，**而所有状态码都是 200**。
    """
    import vigil.api as api

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>VIGIL 守夜人</title>", encoding="utf-8")
    (dist / "sw.js").write_text("self.define = 1", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.text == "self.define = 1"                  # 不是 index.html
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 404                          # 真没有就 404，不许拿 index.html 顶
    assert client.get("/some/route").text.startswith("<title>VIGIL")   # SPA 兜底仍工作


def test_path_traversal_is_blocked(client, tmp_path, monkeypatch):
    """⚠️ 逃逸测试**必须断言正文**——只看状态码会得到 200，测试是空的。

    规划期实测：只看状态码时，逃逸请求返回 200（其实是 index.html），
    看不出有没有泄露。所以这里断言正文**不含**密钥字样。
    """
    import vigil.api as api

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>VIGIL 守夜人</title>", encoding="utf-8")
    (tmp_path / ".env").write_text("VIGIL_DB_KEY=0123456789abcdef", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    for path in ["/..%2f.env", "/..%2f..%2f.env", "/%2e%2e/%2e%2e/.env"]:
        r = client.get(path)
        assert "VIGIL_DB_KEY" not in r.text, f"{path} 泄露了密钥！"
```

**补充一个阳性对照测试**（证明上面那条不是空守卫）：

```python
def test_traversal_test_has_detection_power(client, tmp_path, monkeypatch):
    """阳性对照：把 .env 放进 dist 再请求，**测试必须能抓到**。

    没有这条，「不泄露」可能只是因为**测试根本读不到东西**。
    """
    import vigil.api as api

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>x</title>", encoding="utf-8")
    (dist / ".env").write_text("VIGIL_DB_KEY=0123456789abcdef", encoding="utf-8")
    monkeypatch.setattr(api, "WEB_DIST", dist)

    assert "VIGIL_DB_KEY" in client.get("/.env").text    # 能读到 → 上一条不是空的
```

> `_config_for(db)` 需要按 `config.Config` 的真实字段构造（读 `vigil/config.py` 的 `Config` dataclass）。群名映射用 `Group`（读 `config.py` 里的定义）。**这是本任务唯一需要自己拼的夹具**，拼错了测试会红——那正是它该有的样子。

- [ ] **Step 2：跑测试确认失败**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m pytest tests/test_api.py -q
```
Expected: `ModuleNotFoundError: No module named 'vigil.api'`

- [ ] **Step 3：建 `vigil/api.py`**

```python
"""只读 JSON API + 前端静态托管。

**只读是机械保证，不是口头约定**：连接一律 ``mode=ro`` 打开，
写操作会被 SQLite 直接拒绝（实测 ``attempt to write a readonly database``）。
这样 Web 这一侧永远不可能改到 `data/vigil.db`。

⚠️ **每请求一条连接**，不复用：FastAPI 的同步端点跑在线程池里，而
``sqlite3.Connection`` 默认不能跨线程。本地文件开连接是微秒级，
省下的复杂度远比省下的那点时间值钱。
"""

from __future__ import annotations

import datetime as dt
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse

from . import store
from .categories import load_categories
from .config import REPO_ROOT, Config

WEB_DIST = REPO_ROOT / "web" / "dist"

MAX_LIMIT = 200


def _parse_day(day: str) -> dt.date:
    try:
        return dt.datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"日期格式应为 YYYY-MM-DD，收到：{day}"
        )


def _day_start(day: str, *, plus_days: int = 0) -> int:
    """``YYYY-MM-DD`` → **本地**当天 00:00 的 epoch 秒。

    ⚠️ 必须用 ``datetime`` 而不是 SQLite 的 ``strftime('%s', ...)``：后者按
    **UTC** 解释同一个日期串，与产品的「本地日」口径差 8 小时（M2 实测记录）。
    """
    d = _parse_day(day) + dt.timedelta(days=plus_days)
    return int(dt.datetime.combine(d, dt.time.min).timestamp())


def _day_of(ts: int) -> str:
    """窗口起点 → 本地日期字符串，与 ``_day_start`` 互逆。"""
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="VIGIL 守夜人", docs_url=None, redoc_url=None)

    db_path = config.output_db
    db_uri = f"file:{db_path.as_posix()}?mode=ro"
    names = {g.id: g.name for g in config.groups}
    cats = load_categories()
    cat_by_slug = {c.slug: c for c in cats}

    def connect() -> sqlite3.Connection:
        return sqlite3.connect(db_uri, uri=True)

    def item_out(it: store.ApiItem) -> dict:
        cat = cat_by_slug.get(it.kind)
        return {
            "item_id": it.item_id,
            "kind": it.kind,
            "kind_label": cat.label if cat else it.kind,
            "kind_icon": cat.icon if cat else "",
            "title": it.title,
            "detail": it.detail,
            "event_ts": it.event_ts,
            # ⚠️ 这里**不做二次核验**，因为未经核验的值在数据层就已经是 NULL
            # （见 vigil/deadline.py）。这正是「把核验提到数据层」的收益：
            # 读取方不需要各自记得再挡一次——那种「每个读者都要记得」的约定
            # 迟早会有人忘（M2 只在日报挡过，Web 差一点就把幻觉日期复活了）。
            "deadline_ts": it.deadline_ts,
            "group_id": it.group_id,
            "group_name": names.get(it.group_id, str(it.group_id)),
            "actor": it.actor,
            "place": it.place,
            "amount": it.amount,
            "links": list(it.links),
            "source_count": it.source_count,
        }

    @app.get("/api/categories")
    def api_categories() -> dict:
        con = connect()
        try:
            counts = store.kind_counts(con)
        finally:
            con.close()
        return {
            "categories": [
                {
                    "slug": c.slug,
                    "label": c.label,
                    "icon": c.icon,
                    "count": counts.get(c.slug, 0),
                }
                for c in cats
            ]
        }

    @app.get("/api/items")
    def api_items(
        kind: str | None = None,
        since: str | None = None,
        until: str | None = None,
        group: int | None = None,
        q: str | None = None,
        limit: int = Query(50, ge=1, le=MAX_LIMIT),
        offset: int = Query(0, ge=0),
    ) -> dict:
        # since/until 都按**包含该日**理解：内部窗口右端取次日 00:00（左闭右开）。
        # 否则选了 9/13 却搜不到 9/13 当天，是最容易让人不信任搜索的错法。
        q = (q or "").strip()
        con = connect()
        try:
            items, total = store.search_items(
                con,
                kind=kind or None,
                since=_day_start(since) if since else None,
                until=_day_start(until, plus_days=1) if until else None,
                group=group,
                q=q or None,
                limit=limit,
                offset=offset,
            )
        finally:
            con.close()
        return {
            "items": [item_out(it) for it in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get("/api/items/{item_id}")
    def api_item(item_id: int) -> dict:
        con = connect()
        try:
            it = store.get_item(con, item_id)
            if it is None:
                raise HTTPException(status_code=404, detail=f"没有这条条目：{item_id}")
            payload = item_out(it)
            payload["sources"] = [
                {
                    "msg_id": s.msg_id,
                    "ts": s.ts,
                    "sender": s.sender,
                    "group_name": names.get(s.group_id, str(s.group_id)),
                    "content": s.content,
                }
                for s in store.source_messages(con, item_id)
            ]
            return payload
        finally:
            con.close()

    @app.get("/api/digests")
    def api_digests(limit: int = Query(30, ge=1, le=MAX_LIMIT)) -> dict:
        con = connect()
        try:
            rows = store.list_digests(con, limit=limit)
        finally:
            con.close()
        return {
            "digests": [
                {
                    "digest_id": r.digest_id,
                    "day": _day_of(r.window_from),
                    "window_from": r.window_from,
                    "window_to": r.window_to,
                    "created_at": r.created_at,
                    "item_count": r.item_count,
                }
                for r in rows
            ]
        }

    @app.get("/api/digests/{digest_id}")
    def api_digest(digest_id: int) -> dict:
        con = connect()
        try:
            row = store.get_digest(con, digest_id)
            if row is None:
                raise HTTPException(status_code=404, detail=f"没有这篇日报：{digest_id}")
            items = store.digest_items(con, digest_id)
        finally:
            con.close()
        return {
            "digest_id": row.digest_id,
            "day": _day_of(row.window_from),
            "window_from": row.window_from,
            "window_to": row.window_to,
            "created_at": row.created_at,
            "item_count": row.item_count,
            "body_md": row.body_md,
            "items": [item_out(it) for it in items],
        }

    index_file = WEB_DIST / "index.html"

    # ⚠️ **不要**用 `app.mount("/assets", StaticFiles(...))` 那一套。
    #
    # 挂载只覆盖 /assets 前缀，而 PWA 要的 `/sw.js`、`/manifest.webmanifest`、
    # `/icon-192.png` 全在**根路径**上——它们会掉进下面的 SPA 兜底，被当成
    # 前端路由返回一份 **200 的 index.html**。实测（真实进程 + curl）：
    #
    #     GET /manifest.webmanifest → 200  712 字节   ← 712 就是 index.html 的大小
    #     GET /sw.js                → 200  712 字节
    #     GET /icon-192.png         → 200  text/html
    #
    # 后果是浏览器把 HTML 当 manifest 解析、把 HTML 当 Service Worker 注册
    # （MIME 不符直接失败），「添加到主屏」整条路走不通——**而所有状态码都是
    # 200，日志上一个异常都没有**。这类缺陷只有真跑进程才现形。
    _MIME = {
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
    dist_root = WEB_DIST.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """静态文件 + SPA 兜底。三件事按序：挡 /api、发真文件、发前端入口。

        ⚠️ 三条边界都必须挡：
        * ``/api/*`` **不能**落进兜底——否则 `GET /api/typo` 会返回 200 的 HTML，
          调用方 ``r.json()`` 直接炸，而真正的 404 被吞掉。
        * **真存在的静态文件必须先发**（见上面 _MIME 的说明）。
        * 前端**没构建**时不许返回空白页，要明说「去跑 npm run build」——
          与日报同一条规矩：只说自己有资格说的话，没构建就说没构建。
        """
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"没有这个端点：/{full_path}")

        if full_path:
            # 这是全文件里唯一一处把**用户输入**拼进文件路径的地方，
            # 所以目录逃逸（`../.env` 之类）必须在这里挡死。
            candidate = (dist_root / full_path).resolve()
            if candidate.is_relative_to(dist_root) and candidate.is_file():
                return FileResponse(
                    candidate, media_type=_MIME.get(candidate.suffix.lower())
                )

        if not index_file.is_file():
            return HTMLResponse(
                "<meta charset='utf-8'>"
                "<body style='font-family:sans-serif;padding:2rem'>"
                "<h1>前端尚未构建</h1>"
                "<p>请在仓库根目录运行：</p>"
                "<pre>cd web &amp;&amp; npm install &amp;&amp; npm run build</pre>"
                "</body>",
                status_code=503,
            )
        return FileResponse(index_file)

    return app
```

> ⚠️ **`WEB_DIST` 必须是模块级变量**（形状如上）：T3 的测试用 `monkeypatch.setattr(api, "WEB_DIST", ...)` 替换它，`spa()` 里必须**每次现读** `WEB_DIST` 与 `dist_root`——**不要把 `dist_root` 冻结在闭包外**，否则测试里替换不生效、三条静态托管测试会变成空守卫。
> 因此 `dist_root` 要写成局部函数内取值，或改为 `spa()` 里 `WEB_DIST.resolve()` 现算。**以测试全绿为准**（逃逸舱内可调，报告写明）。

- [ ] **Step 4：`cli.py` 加 `serve`**

```python
def cmd_serve(args) -> int:
    """起本地只读 Web 服务。手机访问见 spec §4.7（tailscale serve 代理本端口）。"""
    import uvicorn  # 延迟导入：不跑服务的人不该为它付启动成本

    from .api import WEB_DIST, create_app

    config = _load_config_only()
    _require_export_db(config)

    if not (WEB_DIST / "index.html").is_file():
        # 不许静默起一个空白页：明说前端没构建，并给出构建命令
        print(
            f"[注意] 前端还没构建（找不到 {WEB_DIST / 'index.html'}）。\n"
            f"  服务仍会启动，但页面只会显示一行提示。构建：\n"
            f"      cd web && npm install && npm run build"
        )

    app = create_app(config)
    print(f"VIGIL 服务：http://{args.host}:{args.port}")
    if args.host == "127.0.0.1":
        print("  （只监听本机——手机访问见 spec §4.7：tailscale serve 代理本端口）")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0
```

在 `main()` 里注册（放在 `p_digest` 之前）：

```python
    p_serve = sub.add_parser("serve", help="起本地 Web 服务（只读库）")
    p_serve.add_argument("--host", default="127.0.0.1", help="监听地址")
    p_serve.add_argument("--port", type=int, default=8787, help="端口")
    p_serve.set_defaults(func=cmd_serve)
```

- [ ] **Step 5：跑测试**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m pytest tests/test_api.py -q && .venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: 全绿。

- [ ] **Step 6：真进程冒烟（前端已构建的前提下）**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m vigil serve --port 8787 &
sleep 6
curl -s -o /dev/null -w "GET /                    → %{http_code} %{content_type}\n" http://127.0.0.1:8787/
curl -s -o /dev/null -w "GET /api/items?limit=2   → %{http_code}\n" "http://127.0.0.1:8787/api/items?limit=2"
curl -s -o /dev/null -w "GET /api/typo            → %{http_code}（期望 404）\n" http://127.0.0.1:8787/api/typo
curl -s -o /dev/null -w "GET /sw.js               → %{http_code} %{content_type} %{size_download}\n" http://127.0.0.1:8787/sw.js
```
Expected: `/` 200 text/html；`/api/items` 200；`/api/typo` **404**；`/sw.js` **200 text/javascript 且字节数 ≠ index.html 的字节数**（这一条是发现 3 的回归守卫）。
**收工只杀这个 PID**，不要按进程名杀。

- [ ] **Step 7：自查后提交**

```bash
cd /d/github/VIGIL && git add vigil/api.py vigil/cli.py tests/test_api.py \
  && git commit -m "feat(api): 只读 FastAPI 服务 + vigil serve + 静态托管与 SPA 兜底" \
  && git show --stat HEAD
```

---

## Task 4（波 1 · TS 链）：前端骨架 + 共用组件 + PWA

**Files（全部新建）：** `web/` 下的 `package.json` `vite.config.ts` `tsconfig.json` `index.html` `.gitignore` `tools/make_icons.py` `public/*.png` `src/main.tsx` `src/index.css` `src/types.ts` `src/api.ts` `src/format.ts` `src/App.tsx` `src/components/ItemCard.tsx` `src/components/SourceList.tsx` `src/views/Feed.tsx`（**占位版**）`src/views/Categories.tsx`（**占位版**）`src/views/Digests.tsx`（**占位版**）`src/__tests__/format.test.ts` `src/__tests__/api.test.ts`

**Interfaces:**
- Consumes: 计划 §三 的冻结契约
- Produces（**后续三个任务全靠它**）：
  - `types.ts`：`Item` `Source` `ItemDetail` `ItemPage` `Category` `DigestSummary` `DigestDetail`
  - `api.ts`：`fetchItems(query: ItemQuery): Promise<ItemPage>`、`fetchItem(id): Promise<ItemDetail>`、`fetchCategories(): Promise<{categories: Category[]}>`、`fetchDigests(): Promise<{digests: DigestSummary[]}>`、`fetchDigest(id): Promise<DigestDetail>`
  - `format.ts`：`fmtDate(ts): string`、`fmtDateTime(ts): string`、`relTime(ts): string`
  - 组件：`<ItemCard item={Item} />`（自带「点开源消息」）、`<SourceList sources={Source[]} />`
  - `App.tsx` 的 props 约定：`<Feed kind={string} onKind={(k: string) => void} />`、`<Categories onPick={(slug: string) => void} />`、`<Digests />`（**无 props**）

**Dependencies:** 无
**Touches:** `web/package.json` `web/vite.config.ts` `web/tsconfig.json` `web/index.html` `web/.gitignore` `web/tools/make_icons.py` `web/public/**` `web/src/main.tsx` `web/src/index.css` `web/src/types.ts` `web/src/api.ts` `web/src/format.ts` `web/src/App.tsx` `web/src/components/**` `web/src/views/**`（**T4 只写占位版**）`web/src/__tests__/**`

---

- [ ] **Step 1：写 `web/package.json`**（⚠️ **版本号一个字符都不许改**——这是实测装出来的）

```json
{
  "name": "vigil-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "icons": "python tools/make_icons.py"
  },
  "dependencies": {
    "react": "19.3.0",
    "react-dom": "19.3.0",
    "react-markdown": "10.1.0"
  },
  "devDependencies": {
    "@tailwindcss/vite": "4.3.3",
    "@types/react": "19.2.7",
    "@types/react-dom": "19.2.4",
    "@vitejs/plugin-react": "6.1.1",
    "tailwindcss": "4.3.3",
    "typescript": "5.9.3",
    "vite": "8.3.0",
    "vite-plugin-pwa": "1.3.0",
    "vitest": "5.0.1"
  }
}
```

- [ ] **Step 2：先写失败测试** `src/__tests__/format.test.ts` 与 `src/__tests__/api.test.ts`

```ts
import { describe, expect, it } from 'vitest'
import { fmtDate, fmtDateTime, relTime } from '../format'

describe('fmtDate / fmtDateTime', () => {
  it('按本地时区渲染，不是 UTC', () => {
    // 本地 2026-09-13 12:00 —— 用 UTC 解释会偏 8 小时到 9月13日 04:00 或 9月12日
    const ts = Math.floor(new Date(2026, 8, 13, 12, 0).getTime() / 1000)
    expect(fmtDate(ts)).toBe('9月13日')
    expect(fmtDateTime(ts)).toBe('9月13日 12:00')
  })
})

describe('relTime', () => {
  const now = Math.floor(Date.now() / 1000)

  it('一小时内按分钟', () => {
    expect(relTime(now - 120)).toBe('2 分钟前')
  })
  it('一天内按小时', () => {
    expect(relTime(now - 7200)).toBe('2 小时前')
  })
  it('一周内按天', () => {
    expect(relTime(now - 86400 * 3)).toBe('3 天前')
  })
  it('超过一周回落到日期', () => {
    expect(relTime(now - 86400 * 30)).toMatch(/月.*日/)
  })
  it('未来时间不编「-3 分钟前」', () => {
    // 库里存在 1970 脏数据与未来戳；负数分钟会被读成「-1 分钟前」
    expect(relTime(now + 600)).toMatch(/月.*日/)
  })
  it('刚发出不说「0 分钟前」', () => {
    expect(relTime(now - 10)).toBe('1 分钟前')
  })
})
```

```ts
import { describe, expect, it, vi } from 'vitest'
import { fetchItem, fetchItems } from '../api'

describe('fetchItems 的查询串', () => {
  it('丢掉 undefined / 空串，不发出空参数', async () => {
    const spy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 50, offset: 0 }),
    })
    vi.stubGlobal('fetch', spy)
    await fetchItems({ kind: '', q: undefined, limit: 50 })
    const url = String(spy.mock.calls[0][0])
    expect(url).toBe('/api/items?limit=50')
  })

  it('参数照原样带上', async () => {
    const spy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0, limit: 20, offset: 40 }),
    })
    vi.stubGlobal('fetch', spy)
    await fetchItems({ q: '选课', limit: 20, offset: 40 })
    expect(String(spy.mock.calls[0][0])).toBe(
      '/api/items?q=%E9%80%89%E8%AF%BE&limit=20&offset=40',
    )
  })
})

describe('错误处理', () => {
  it('把后端的 detail 当错误消息抛出来', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: '没有这条条目：999' }),
    }))
    await expect(fetchItem(999)).rejects.toThrow('没有这条条目：999')
  })

  it('响应体不是 JSON 时回落到状态码，不吞错', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: async () => { throw new Error('not json') },
    }))
    await expect(fetchItem(1)).rejects.toThrow('HTTP 503')
  })
})
```

- [ ] **Step 3：跑测试确认失败**

```bash
cd /d/github/VIGIL/web && npm install && npm test
```
Expected: FAIL —— `Failed to resolve import "../format"`（文件还不存在）

> ⚠️ **Step 4–11 的每一个文件，代码都在[附录 A](#附录-a前端全部文件已在探针里真装真构建通过逐字照抄不许改写)里，逐字照抄。**
> 附录 A 由 `_gen_frontend_section.py` 从**验证过的文件**生成（vite 8.3 构建 180 模块通过 + 变异反证证明 `tsc` 真在检查类型），不是手抄的。**不要凭下面的要点自己重写**——要点是给你验收「抄对了没有」用的。

- [ ] **Step 4：写 `src/types.ts`**（附录 A.1）

把计划 §3.2 的契约逐字落成 TS（含注释）。**字段名与 `vigil/api.py` 的 `item_out()` 逐字对应**。

- [ ] **Step 5：写 `src/format.ts` 与 `src/api.ts`**（附录 A.2 / A.3）

见本计划 Task 4 的 Produces 签名；`format.ts` 里 `relTime` 必须处理**未来时间**（回落成日期）与**刚发出**（最少 1 分钟）。`api.ts` 的 `getJSON` 在 `!r.ok` 时先试 `body.detail`，取不到回落 `HTTP ${r.status}`——**绝不吞错成空列表**。

- [ ] **Step 6：跑测试确认通过**

```bash
cd /d/github/VIGIL/web && npm test
```
Expected: 全绿。

- [ ] **Step 7：写 `index.html` / `tsconfig.json` / `vite.config.ts` / `src/index.css` / `src/main.tsx` / `.gitignore`**

tsconfig **必须**含 `"allowImportingTsExtensions": true`（否则 `import App from './App.tsx'` 报 `TS5097`——实测踩到）与 `"types": ["vite/client", "vite-plugin-pwa/client"]`。

`vite.config.ts` 要点：
```ts
VitePWA({
  registerType: 'autoUpdate',
  includeAssets: ['icon-192.png', 'icon-512.png'],
  manifest: { /* name/short_name/lang: 'zh-CN'/start_url: '/'
                 display: 'standalone'/background_color/theme_color: '#0b0f14'
                 icons: 192 + 512 + maskable-512 */ },
  workbox: {
    navigateFallback: '/index.html',
    // ⚠️ /api/ 的导航请求不许被兜底成 index.html——那会把一个接口 404
    // 变成一份看起来正常的 HTML，调用方解析失败却看不到原因。
    navigateFallbackDenylist: [/^\/api\//],
  },
}),
```
`server.proxy` 把 `/api` 代理到 `http://127.0.0.1:8787`（开发期免 CORS）。

`src/index.css`：**Tailwind v4 写法，没有 config 文件**：
```css
@import 'tailwindcss';

/* Tailwind v4：主题在这里声明，**没有 tailwind.config.js**
   （v4 是 CSS-first 配置；照 v3 的写法建 config 文件不会被读取）。 */
@theme {
  --color-vigil-bg: #0b0f14;
  --color-vigil-fg: #e6edf3;
}

html { overflow-x: hidden; }
```

- [ ] **Step 8：写图标生成器并生成图标**

`web/tools/make_icons.py`：**纯 stdlib（zlib + struct + CRC32）**，不引 Pillow（本机装不了）。生成 `public/icon-192.png`、`icon-512.png`、`icon-maskable-512.png`（maskable 的主体缩到安全区 62%，免得被 Android 遮罩切掉）。

跑：
```bash
cd /d/github/VIGIL/web && /d/github/VIGIL/.venv/Scripts/python.exe tools/make_icons.py
```
Expected: 三行 `icon-*.png  N×N  N 字节`。

**自检（必须做）**：用 Python 解一遍 PNG，断言 `IHDR` 尺寸正确、IDAT 解压后字节数 == `高 ×(1 + 宽×3)`。规划期实测三个文件分别为 `110,784 / 786,944 / 786,944` 字节。

- [ ] **Step 9：写 `src/components/ItemCard.tsx` 与 `SourceList.tsx`**

`ItemCard` 要点（**这是出口标准第 5 条「点任意 item 看到源消息原文」的载体**）：
- 点击展开；**源消息按需拉取**（`fetchItem`），列表一次 50 条全带原文会把响应撑大好几倍
- 展开后：链接列表 + `<SourceList sources={...} />`
- 错误要显示（`源消息读取失败：…`），加载中要显示（`读取源消息…`）
- **`deadline_ts !== null` 才显示**——NULL 表示源文里没有依据（T1 的成果）
- 用 `!== null` 而不是真值判断：`{0 && <x/>}` 会渲染出 `0`

`SourceList` 要点：发信人 + 时间 + 群名；正文 `whitespace-pre-wrap` **照登不截断**（「不信 LLM」的落地就是让人能自己看原文）；空列表时说「这条没有可回溯的源消息」。

- [ ] **Step 10：写 `src/App.tsx`（外壳）**

三个 tab（信息流 / 类目 / 日报）+ `kind` 筛选状态**提到 App**（这样「类目」页点一个类目跳回信息流时筛选能带过去，Feed 卸载重挂也不丢）。渲染：

```tsx
{tab === 'feed' && <Feed kind={kind} onKind={setKind} />}
{tab === 'cats' && <Categories onPick={(slug) => { setKind(slug); setTab('feed') }} />}
{tab === 'digests' && <Digests />}
```

- [ ] **Step 11：写三个视图的**占位版****（T5/T6 会整体覆盖它们）

```tsx
// src/views/Feed.tsx —— T5 会整体重写这个文件
export default function Feed(_props: { kind: string; onKind: (k: string) => void }) {
  return <p className="text-sm text-white/40">信息流（T5 实现）</p>
}
```
`Categories.tsx` / `Digests.tsx` 同款。

> ⚠️ 占位版必须**签名正确、能被 `tsc` 通过**——否则 T4 的构建门就是红的，而「红的构建门」会让后面所有任务的验收失去意义。

- [ ] **Step 12：构建 + 变异反证（证明构建门不是假的）**

```bash
cd /d/github/VIGIL/web && npm run build; echo "EXIT=$?"
ls dist/ dist/assets/
cat dist/manifest.webmanifest
```
Expected: `EXIT=0`；`dist/` 里有 `index.html`、`assets/`、`manifest.webmanifest`、`sw.js`、`registerSW.js`、三个图标。

**阳性对照（必须做，证明 `tsc` 真在检查）**：往任一 `.tsx` 里塞一行 `const _probe: number = "字符串"`，重跑 `npm run build`，**必须 EXIT≠0 且报 TS2322**；然后删掉它，必须回 EXIT=0。
> 规划期实测过：植入错误 → `error TS2322` + EXIT=1；还原 → EXIT=0。**没有这一步，「构建通过」可能只是因为它什么都没检查。**

⚠️ **不要用 `npm run build 2>&1 | tail`**——管道会把退出码换成 `tail` 的 0，失败会显示成成功（规划期实测踩到过一次）。

- [ ] **Step 13：自查后提交**

```bash
cd /d/github/VIGIL && git add web/ \
  && git commit -m "feat(web): 前端骨架 + 冻结契约类型 + API 客户端 + 共用组件 + PWA 配置" \
  && git show --stat HEAD
```
⚠️ `web/node_modules/` 与 `web/dist/` **必须在 `.gitignore` 里**（波 0 已加根 `.gitignore`，`web/.gitignore` 再兜一层）。提交后 `git show --stat` 里**不该出现**这两个目录的任何文件。

---

## Task 5（波 2 · TS 链）：信息流视图

**Files:** `web/src/views/Feed.tsx`（**整体重写 T4 的占位版**）

**Interfaces:**
- Consumes: `fetchItems` `fetchCategories`（T4）、`ItemCard`（T4）、`Category` `Item` 类型（T4）
- Produces: `export default function Feed(props: { kind: string; onKind: (k: string) => void })`

**Dependencies:** Task 4
**Touches:** `web/src/views/Feed.tsx`

---

- [ ] **Step 1：整体重写 `Feed.tsx`**

⚠️ **代码在附录 A.15**（`web/src/views/Feed.tsx`）——那份是**真装真构建通过**的版本，**逐字照抄**，不要照下面的要点自己重写。下面这些要点是你**验收自己要抄对了**的清单（漏一条就该被打回）：

必须满足下列全部行为：

1. **搜索框 + 防抖 300ms**：中文输入法下每敲一下都发请求，手机上会明显卡顿。
2. **类目 chips**：`全部` + 七个类目（带 icon），点击调 `onKind(slug)`；当前选中的高亮。
3. **请求序号防竞态**：`const seq = useRef(0)`，每次请求 `++seq.current` 存进 `mine`，回来时 `if (mine !== seq.current) return`——**慢的旧请求晚到不许覆盖新结果**。
4. **计数行说清范围**：`共 N 条 · 类目 · 关键词「x」`——别让一个数字看起来像全部。
5. **空结果分情况说**：搜了词 →「没有匹配「x」的条目」；选了类目 →「「学业」下还没有条目」；都没有 →「还没有任何条目」。
   ⚠️ **三种不许合并成一句**：把「搜不到」说成「没有条目」就是又一句没资格说的话。
6. **分页**：`加载更多（还有 N 条）`，用 `offset: items.length` 追加；加载中禁用。
7. **错误可见**：`读取失败：{err}`，且**不清空已有数据**的路径与清空的路径要分清。

- [ ] **Step 2：构建**

```bash
cd /d/github/VIGIL/web && npm run build; echo "EXIT=$?"
```
Expected: `EXIT=0`（**不许看管道后的退出码**）

- [ ] **Step 3：真服务联调（能起 T3 就起）**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m vigil serve --port 8787 &
sleep 6
curl -s -o /dev/null -w "GET / → %{http_code}\n" http://127.0.0.1:8787/
```
然后在**手机或浏览器**里确认：信息流有内容、点条目能展开源消息、搜「选课」有 8 条、搜「校园卡」有 42 条。
（T3 尚未落地时，本条改在阶段④ 冒烟做，报告里写明。）

- [ ] **Step 4：自查后提交**

```bash
cd /d/github/VIGIL && git add web/src/views/Feed.tsx \
  && git commit -m "feat(web): 信息流视图——搜索防抖、类目筛选、分页与空态分情况" \
  && git show --stat HEAD
```

---

## Task 6（波 3 · TS 链）：类目视图 + 日报视图

**Files:** `web/src/views/Categories.tsx`、`web/src/views/Digests.tsx`（**整体重写 T4 的占位版**）

**Interfaces:**
- Consumes: `fetchCategories` `fetchDigests` `fetchDigest`（T4）、`ItemCard`（T4）、`Category` `DigestSummary` `DigestDetail` 类型（T4）
- Produces: `export default function Categories(props: { onPick: (slug: string) => void })`、`export default function Digests()`

**Dependencies:** Task 4
**Touches:** `web/src/views/Categories.tsx`、`web/src/views/Digests.tsx`

---

- [ ] **Step 1：重写 `Categories.tsx`**（⚠️ 代码在**附录 A.16**，逐字照抄）

七个类目卡片（icon + 中文名 + `N 条`），点击 `onPick(slug)`；错误可见；空态说「读取类目…」。
**计数来自 `/api/categories` 的 `count`**，不要另发七个请求。

- [ ] **Step 2：重写 `Digests.tsx`**（⚠️ 代码在**附录 A.17**，逐字照抄）

两个状态：**列表**（`day` + `N 条条目`，点击进入）与**详情**（返回按钮 + `body_md` 渲染 + 关联条目列表）。

要点：
- Markdown 用 `react-markdown` 渲染；**默认不渲染原始 HTML**，所以不用额外 sanitizer。
- `components` 映射里用 `({ children }) => ...`，**不要 `{...props}` 展开**——react-markdown 会传一个 `node` 属性，展开到 DOM 上会触发 React 警告。
- 详情里也要能点开源消息（复用 `<ItemCard>`）——「日报说的每一条都能在 Web 里找到」是 M2 承诺的落地。
- 空列表说「还没有日报。生成：`vigil digest`」。

- [ ] **Step 3：构建**

```bash
cd /d/github/VIGIL/web && npm run build; echo "EXIT=$?"
```
Expected: `EXIT=0`

- [ ] **Step 4：自查后提交**

```bash
cd /d/github/VIGIL && git add web/src/views/Categories.tsx web/src/views/Digests.tsx \
  && git commit -m "feat(web): 类目视图与日报视图（Markdown 渲染 + 关联条目可回溯）" \
  && git show --stat HEAD
```

---

## Task 7（波 4 · 串行）：端到端联调 + 修正

**为什么单独成一个任务**：前三个波里，Python 链与 TS 链**互相没见过面**——它们只共享一份冻结契约。契约漂移、字段名错位、真实响应形状与假设不符，都会在这里现形。**在最终 opus review 之前把它们抓出来**，比等到冒烟便宜得多。

**Files:** 视发现的问题而定（预计 `web/src/**` 与 `vigil/api.py`）
**Interfaces:** Consumes 全部前序任务
**Dependencies:** Task 3、Task 6
**Touches:** `web/src/**`、`vigil/api.py`（**越界到别的文件要报告 controller**）

---

- [ ] **Step 1：构建前端并以真服务跑一遍**

```bash
cd /d/github/VIGIL/web && npm run build && cd /d/github/VIGIL \
  && .venv/Scripts/python.exe -m vigil serve --port 8787 &
sleep 6
```

- [ ] **Step 2：逐条核对契约（**用真响应比对，不看代码猜**）**

```bash
curl -s "http://127.0.0.1:8787/api/items?limit=1" | /d/github/VIGIL/.venv/Scripts/python.exe -m json.tool
curl -s "http://127.0.0.1:8787/api/items/182" | /d/github/VIGIL/.venv/Scripts/python.exe -m json.tool | head -40
curl -s "http://127.0.0.1:8787/api/digests" | /d/github/VIGIL/.venv/Scripts/python.exe -m json.tool | head -20
curl -s "http://127.0.0.1:8787/api/categories" | /d/github/VIGIL/.venv/Scripts/python.exe -m json.tool
```
把每个字段与 `web/src/types.ts` **逐字对照**。**发现任何一处对不上就记下来**——这正是本任务存在的理由。

- [ ] **Step 3：浏览器/手机实机走查（若 T3 已落地）**

逐项确认：信息流有内容 → 点条目展开看到源消息 → 搜「选课」→ 按「学业」筛选 → 日报列表 → 打开一篇 → 日报里点条目再回溯。

- [ ] **Step 4：修掉发现的问题**（**只改 `Touches` 内文件**）

- [ ] **Step 5：全量测试 + 构建**

```bash
cd /d/github/VIGIL && .venv/Scripts/python.exe -m pytest tests/ -q
cd /d/github/VIGIL/web && npm run build; echo "EXIT=$?"; npm test
```
Expected: 全绿。

- [ ] **Step 6：提交**

```bash
cd /d/github/VIGIL && git add web/ vigil/api.py \
  && git commit -m "fix(web): 端到端联调修正——前后端契约逐字段核对" \
  && git show --stat HEAD
```

---

## 六、阶段④ 冒烟 = M3 出口证据

spec §5 的 M3 出口标准，**逐条**在真机真数据上验。**不用隔离数据根**——这次要的就是真库真前端。

| # | 出口标准 | 怎么验 | 现状 |
|---|---|---|---|
| 1 | 手机通过 Tailscale HTTPS 打开 | `tailscale serve https / http://127.0.0.1:8787`，手机浏览器打开 `https://<机器>.<tailnet>.ts.net` | ⚠️ **Tailscale 尚未安装**（用户已定：冒烟前装） |
| 2 | 添加到主屏后独立图标、全屏 | 手机 Safari/Chrome「添加到主屏幕」→ 打开应是独立图标 + 无浏览器地址栏（`display: standalone`） | 待验 |
| 3 | 按七个类目筛选正确 | 类目页点「学业」→ 计数与 `/api/categories` 的 `academic` 数一致（**实测 59**） | 可先离线验 |
| 4 | 中文关键词搜到东西 | 搜「选课」→ **8 条**；搜「校园卡」→ **42 条**（一短一长，覆盖两条代码路径） | 可先离线验 |
| 5 | 点任意 item 看到源消息原文 | 任点一条 → 展开 → 看到原文、发信人、时间 | 可先离线验 |

**先做不需要手机的 3/4/5**（在 PC 浏览器上完成，抓真缺陷），再等 Tailscale 装好后做 1/2。

**Tailscale 未就绪时的降级**（spec §7 R5 的退路）：局域网 `http://<机器IP>:8787` 打开 —— 出口 1 降级为「局域网可访问」，出口 2 相应降级为「普通快捷方式」。**降级必须写进冒烟报告并告知用户**，不许静默换个标准就算通过。

---

## 七、自审三件套

### 7.1 spec 覆盖对照

| spec 章节 | 要求 | 落在哪个任务 |
|---|---|---|
| §4.7 后端 | FastAPI，只读 `data/vigil.db`，5 个端点 | **T3** |
| §4.7 搜索 | FTS5 + trigram 建在 title/detail | **T2**（+ 短词 LIKE 兜底，见发现 1） |
| §4.7 前端 | React + Vite + TS + Tailwind，三块视图 | **T4**（骨架/PWA）、**T5**（信息流）、**T6**（类目+日报） |
| §4.7 可回溯 | 每条 item 可展开看源消息原文 | **T4**（`ItemCard`/`SourceList`）+ **T5**/**T6** 复用 |
| §4.7 构建产物 | `web/dist/` → FastAPI 静态托管，运行时单栈 | **T3**（静态托管）+ **T4**（构建） |
| §4.7 PWA | `vite-plugin-pwa` 生成 manifest + SW | **T4** |
| §4.7 Tailscale | SW 需安全上下文，`tailscale serve` 提供 HTTPS | **阶段④**（环境，非代码） |
| §1.5 磁盘 | npm 缓存重定向 | **波 0**（已完成 ✅） |
| §4.5 脱敏 | 「绝不把群号/uid 发给模型」 | 本里程碑不出网到 LLM；Web 是本地自用，原文照登是出口 5 的要求 |
| §5 M3 出口 | 五条 | **阶段④** |
| **交接文件的必办项** | `items.deadline_ts` 半数不可信 | **T1** ⭐ |

### 7.2 占位符扫描

计划中无 `TBD` / `TODO` / "加适当的错误处理" / "类似 Task N"。
两处显式标注的**逃逸舱内自建夹具**（`tests/test_store.py` 的 `_insert_item`、`tests/test_refine.py` 的 `_msg`/`_extracted`）是**有意为之**：它们必须照该文件既有插桩风格写，原文照抄反而会与文件里已有的辅助函数重名。

### 7.3 跨任务类型一致性（**波级窄审查专核这一项**）

| 名字 | 定义在 | 被谁消费 | 一致？ |
|---|---|---|---|
| `store.ApiItem` 的 12 个字段 | T2 | T3 `item_out()` | ✅ 逐字对应 |
| `item_out()` 的 15 个键 | T3 | T4 `types.ts` 的 `Item` | ✅ 逐字对应 |
| `search_items(kind/since/until/group/q/limit/offset)` | T2 | T3 `api_items` 同名参数 | ✅ |
| `Feed` 的 props `{kind, onKind}` | T4 占位 | T5 重写、T4 `App.tsx` 调用 | ✅ |
| `Categories` 的 props `{onPick}` | T4 占位 | T6 重写、T4 `App.tsx` 调用 | ✅ |
| `Digests` 无 props | T4 占位 | T6 重写、T4 `App.tsx` 调用 | ✅ |
| `ItemCard` 的 props `{item: Item}` | T4 | T5 `Feed`、T6 `Digests` | ✅ |
| `source_messages(conn, item_id)`（**不是** `item_sources`） | T2 | T3 | ✅ 避免与表名撞车 |
| `deadline_supported` 只有一份（`vigil/deadline.py`） | T1 | T1 `digest.py`/`refine.py` | ✅ 有同一性测试守卫 |
| `WEB_DIST` 是**模块级变量**且被 `spa()` 现读 | T3 | T3 的 monkeypatch 测试 | ⚠️ 见 T3 Step 3 的警告 |

### 7.4 已在本计划外完成、**不要重做**的事（规划期实测记录）

- `npm config set cache D:\npm-cache`（波 0，已完成）
- `uv add fastapi uvicorn` + `uv add --group dev httpx`（波 0，已完成）
- 前端全栈真装真构建通过（vite 8.3.0 构建 180 模块，PWA 产物齐全）
- Python 侧在**隔离副本**上跑通：270 既有测试全绿、5 个端点契约端到端、真进程 HTTP 全通过
- 副本验证目录：`_smoke/m3-py-verify/`（git-ignored，**不入库**，可留作复查）
- 前端探针目录：`_smoke/m3-frontend-probe/`（同上）

---

## 附录 A：前端全部文件（**已在探针里真装真构建通过，逐字照抄，不许改写**）

本节由 `docs/superpowers/plans/_gen_frontend_section.py` **从验证过的文件生成**，
不是手抄——手抄会漂移，而漂移的后果是 implementer 抄到一个没验证过的版本。

生成命令（改完探针文件后重跑）：
```bash
python docs/superpowers/plans/_gen_frontend_section.py
```

⚠️ 这些文件在 `_smoke/m3-frontend-probe/` 里通过了 `npm run build`（vite 8.3.0，
180 模块，PWA 产物齐全），并用**变异反证**证明过 `tsc` 真的在检查类型。

### A.1 `web/src/types.ts`（T4）

````ts
// API 契约的 TypeScript 影子。
//
// ⚠️ 这个文件是**冻结契约**的前端一侧：字段名与后端 `vigil/api.py` 的
// 输出逐字对应，改任何一边都必须同时改另一边（波级窄审查专门核这件事）。
// 类型写错不会在构建期报错——它只会让页面静默少一栏，所以字段名不许凭记忆改。

export type Item = {
  item_id: number
  kind: string // slug，如 "academic"
  kind_label: string // 中文，如 "学业"
  kind_icon: string // emoji
  title: string
  detail: string | null
  event_ts: number // Unix 秒
  /** ⚠️ 已过数据层核验：NULL 表示源文里找不到依据，前端**不显示**它 */
  deadline_ts: number | null
  group_id: number
  group_name: string
  actor: string | null
  place: string | null
  amount: string | null
  links: string[]
  source_count: number
}

export type Source = {
  msg_id: number
  ts: number
  sender: string
  group_name: string
  content: string
}

export type ItemDetail = Item & { sources: Source[] }

export type ItemPage = {
  items: Item[]
  total: number
  limit: number
  offset: number
}

export type Category = {
  slug: string
  label: string
  icon: string
  count: number
}

export type DigestSummary = {
  digest_id: number
  day: string // YYYY-MM-DD
  window_from: number
  window_to: number
  created_at: number
  item_count: number
}

export type DigestDetail = DigestSummary & {
  body_md: string
  items: Item[]
}
````

### A.2 `web/src/api.ts`（T4）

````ts
import type {
  Category,
  DigestDetail,
  DigestSummary,
  ItemDetail,
  ItemPage,
} from './types'

async function getJSON<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) {
    // 后端出错时给的是 {"detail": "..."}；拿不到就说状态码，
    // 但**绝不吞掉错误**——静默的空列表会被读成「没有数据」。
    let msg = `HTTP ${r.status}`
    try {
      const body = (await r.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') msg = body.detail
    } catch {
      // 响应不是 JSON（比如前端未构建时的 503 HTML），就用状态码
    }
    throw new Error(msg)
  }
  return (await r.json()) as T
}

export type ItemQuery = {
  kind?: string
  since?: string
  until?: string
  group?: number
  q?: string
  limit?: number
  offset?: number
}

export function fetchItems(query: ItemQuery): Promise<ItemPage> {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  }
  return getJSON<ItemPage>(`/api/items?${p.toString()}`)
}

export const fetchItem = (id: number) => getJSON<ItemDetail>(`/api/items/${id}`)

export const fetchCategories = () =>
  getJSON<{ categories: Category[] }>('/api/categories')

export const fetchDigests = () =>
  getJSON<{ digests: DigestSummary[] }>('/api/digests')

export const fetchDigest = (id: number) =>
  getJSON<DigestDetail>(`/api/digests/${id}`)
````

### A.3 `web/src/format.ts`（T4）

````ts
// 时间格式化。**一律按本地时区**——与 M2 日报的「本地日」口径一致
// （M2 实测：用 UTC 解释同一个日期串会差 8 小时，报出的数就对不上）。

const pad = (n: number) => String(n).padStart(2, '0')

export function fmtDate(ts: number): string {
  const d = new Date(ts * 1000)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

export function fmtDateTime(ts: number): string {
  const d = new Date(ts * 1000)
  return `${d.getMonth() + 1}月${d.getDate()}日 ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function relTime(ts: number): string {
  const diff = Date.now() / 1000 - ts
  if (diff < 0) return fmtDate(ts) // 未来时间（脏数据）不编「-3 分钟前」
  if (diff < 3600) return `${Math.max(1, Math.floor(diff / 60))} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} 天前`
  return fmtDate(ts)
}
````

### A.4 `web/src/index.css`（T4）

````css
@import 'tailwindcss';

/* Tailwind v4：主题在这里声明，**没有 tailwind.config.js**
   （v4 是 CSS-first 配置；照 v3 的写法建 config 文件不会被读取）。 */
@theme {
  --color-vigil-bg: #0b0f14;
  --color-vigil-fg: #e6edf3;
}

html {
  /* 手机上禁掉横向滚动：源消息里偶有长链接，别把整页撑歪 */
  overflow-x: hidden;
}
````

### A.5 `web/src/main.tsx`（T4）

````tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
````

### A.6 `web/src/App.tsx`（T4）

````tsx
import { useState } from 'react'
import Categories from './views/Categories.tsx'
import Digests from './views/Digests.tsx'
import Feed from './views/Feed.tsx'

type Tab = 'feed' | 'cats' | 'digests'

const TABS: { key: Tab; label: string }[] = [
  { key: 'feed', label: '信息流' },
  { key: 'cats', label: '类目' },
  { key: 'digests', label: '日报' },
]

export default function App() {
  const [tab, setTab] = useState<Tab>('feed')
  // 类目筛选状态**提到 App**：这样「类目」页点一个类目跳回信息流时，
  // 筛选条件能带过去，而 Feed 卸载重挂也不会丢。
  const [kind, setKind] = useState('')

  return (
    <div className="min-h-screen bg-vigil-bg text-vigil-fg">
      <header className="sticky top-0 z-10 border-b border-white/10 bg-vigil-bg/90 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center gap-2 px-4 py-3">
          <span className="text-base font-semibold tracking-wide">🏮 VIGIL</span>
          <nav className="ml-auto flex gap-1 text-sm">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setTab(t.key)}
                className={
                  'rounded-lg px-3 py-1.5 transition-colors ' +
                  (tab === t.key
                    ? 'bg-white/10 text-white'
                    : 'text-white/55 active:bg-white/5')
                }
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-4 pb-24">
        {tab === 'feed' && <Feed kind={kind} onKind={setKind} />}
        {tab === 'cats' && (
          <Categories
            onPick={(slug) => {
              setKind(slug)
              setTab('feed')
            }}
          />
        )}
        {tab === 'digests' && <Digests />}
      </main>
    </div>
  )
}
````

### A.7 `web/src/components/SourceList.tsx`（T4）

````tsx
import { fmtDateTime } from '../format.ts'
import type { Source } from '../types.ts'

export default function SourceList({ sources }: { sources: Source[] }) {
  if (sources.length === 0) {
    return (
      <p className="text-xs text-white/40">
        这条没有可回溯的源消息（抽取时没记下来源）。
      </p>
    )
  }
  return (
    <ul className="space-y-2">
      {sources.map((s) => (
        <li key={s.msg_id} className="rounded-lg bg-black/30 p-2">
          <div className="flex flex-wrap gap-x-2 text-xs text-white/45">
            <span>{s.sender || '（未解析出发信人）'}</span>
            <span>{fmtDateTime(s.ts)}</span>
            <span className="ml-auto">{s.group_name}</span>
          </div>
          {/* 原文照登、不截断：「不信 LLM」的落地就是让人能自己看原文 */}
          <p className="mt-1 text-sm whitespace-pre-wrap text-white/85">
            {s.content}
          </p>
        </li>
      ))}
    </ul>
  )
}
````

### A.8 `web/src/components/ItemCard.tsx`（T4）

````tsx
import { useState } from 'react'
import { fetchItem } from '../api.ts'
import { fmtDate, relTime } from '../format.ts'
import type { Item, Source } from '../types.ts'
import SourceList from './SourceList.tsx'

export default function ItemCard({ item }: { item: Item }) {
  const [open, setOpen] = useState(false)
  const [sources, setSources] = useState<Source[] | null>(null)
  const [err, setErr] = useState<string | null>(null)

  function toggle() {
    const next = !open
    setOpen(next)
    // 源消息**按需拉取**：列表一次 50 条，全带上原文会把响应撑大好几倍，
    // 而绝大多数条目用户不会展开。
    if (next && sources === null && err === null) {
      fetchItem(item.item_id)
        .then((d) => setSources(d.sources))
        .catch((e: unknown) =>
          setErr(e instanceof Error ? e.message : String(e)),
        )
    }
  }

  return (
    <li className="rounded-xl bg-white/5 p-3">
      <button onClick={toggle} className="w-full text-left">
        <div className="flex flex-wrap items-center gap-x-2 text-xs text-sky-400">
          <span>
            {item.kind_icon} {item.kind_label}
          </span>
          <span className="text-white/30">·</span>
          <span className="text-white/45">{item.group_name}</span>
          <span className="ml-auto text-white/40">
            {relTime(item.event_ts)}
          </span>
        </div>

        <p className="mt-1 text-[15px] leading-snug font-medium">
          {item.title}
        </p>
        {item.detail !== null && item.detail !== '' && (
          <p className="mt-1 text-sm text-white/70">{item.detail}</p>
        )}

        <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-white/50">
          {/* 截止日只在数据层核验通过时才有值（NULL = 源文里找不到依据）*/}
          {item.deadline_ts !== null && (
            <span className="text-amber-400">
              ⏰ {fmtDate(item.deadline_ts)} 截止
            </span>
          )}
          {item.place !== null && item.place !== '' && (
            <span>📍 {item.place}</span>
          )}
          {item.amount !== null && item.amount !== '' && (
            <span>💰 {item.amount}</span>
          )}
          {item.actor !== null && item.actor !== '' && (
            <span>@{item.actor}</span>
          )}
          {item.source_count > 0 && (
            <span>
              {open ? '▾' : '▸'} {item.source_count} 条源消息
            </span>
          )}
        </div>
      </button>

      {open && (
        <div className="mt-3 border-t border-white/10 pt-3">
          {item.links.length > 0 && (
            <div className="mb-2 flex flex-col gap-1 text-xs">
              {item.links.map((l) => (
                <a
                  key={l}
                  href={l}
                  target="_blank"
                  rel="noreferrer"
                  className="break-all text-sky-400 underline"
                >
                  {l}
                </a>
              ))}
            </div>
          )}
          {err !== null && (
            <p className="text-xs text-red-400">源消息读取失败：{err}</p>
          )}
          {sources === null && err === null && (
            <p className="text-xs text-white/40">读取源消息…</p>
          )}
          {sources !== null && <SourceList sources={sources} />}
        </div>
      )}
    </li>
  )
}
````

### A.9 `web/index.html`（T4）

````html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta
      name="viewport"
      content="width=device-width, initial-scale=1.0, viewport-fit=cover"
    />
    <meta name="theme-color" content="#0b0f14" />
    <link rel="icon" href="/icon-192.png" />
    <link rel="apple-touch-icon" href="/icon-192.png" />
    <title>VIGIL 守夜人</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
````

### A.10 `web/tsconfig.json`（T4）

````json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "noEmit": true,
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "types": ["vite/client", "vite-plugin-pwa/client"]
  },
  "include": ["src", "vite.config.ts"]
}
````

### A.11 `web/vite.config.ts`（T4）

````ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon-192.png', 'icon-512.png'],
      manifest: {
        name: 'VIGIL 守夜人',
        short_name: 'VIGIL',
        description: 'QQ 群信息聚合：通知、学业、活动、生活一页看完',
        lang: 'zh-CN',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        background_color: '#0b0f14',
        theme_color: '#0b0f14',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: 'icon-maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        navigateFallback: '/index.html',
        // ⚠️ /api/ 的导航请求不许被兜底成 index.html——那会把一个接口
        // 404 变成一份看起来正常的 HTML，调用方解析失败却看不到原因。
        navigateFallbackDenylist: [/^\/api\//],
      },
    }),
  ],
  server: {
    // 开发期前端跑 5173、后端跑 8787，靠代理合到一个源上（免 CORS）
    proxy: { '/api': 'http://127.0.0.1:8787' },
  },
})
````

### A.12 `web/package.json`（T4）

````json
{
  "name": "vigil-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "icons": "python tools/make_icons.py"
  },
  "dependencies": {
    "react": "19.3.0",
    "react-dom": "19.3.0",
    "react-markdown": "10.1.0"
  },
  "devDependencies": {
    "@tailwindcss/vite": "4.3.3",
    "@types/react": "19.2.7",
    "@types/react-dom": "19.2.4",
    "@vitejs/plugin-react": "6.1.1",
    "tailwindcss": "4.3.3",
    "typescript": "5.9.3",
    "vite": "8.3.0",
    "vite-plugin-pwa": "1.3.0"
  }
}
````

### A.13 `web/.gitignore`（T4）

````text
node_modules/
dist/
dev-dist/
*.local
````

### A.14 `web/tools/make_icons.py`（T4）

````python
"""生成 PWA 图标（纯 stdlib，无第三方依赖）。

    python web/tools/make_icons.py

为什么不用 Pillow：本机 .venv 没有 Pillow，而为了几个静态 PNG 引一个
图像库不划算。PNG 的最小写入路径（zlib + struct + CRC32）只有几十行，
且**产物可复现**——想要新图标改这里的参数重跑即可，不用手工修图。

设计：深底 + 暖色提灯。这是「守夜人」的字面意象，也保证在小尺寸下
（192px）仍然认得出。maskable 版把主体缩到安全区（内切圆）以内，
免得被 Android 的圆形/方形遮罩切掉。
"""

from __future__ import annotations

import pathlib
import struct
import zlib

BG = (11, 15, 20)          # #0b0f14 与前端 --color-vigil-bg 一致
BODY_HI = (242, 161, 61)   # #f2a13d 灯体亮部
BODY_LO = (200, 68, 38)    # #c84426 灯体暗部
FLAME = (255, 226, 150)    # #ffe296 灯芯

SS = 4  # 超采样倍数：先按 4 倍画再平均，得到抗锯齿边缘


def _rounded_rect(x: float, y: float, cx: float, cy: float,
                  hw: float, hh: float, r: float) -> bool:
    """点 (x,y) 是否落在以 (cx,cy) 为中心、半径 r 的圆角矩形内。"""
    dx = abs(x - cx) - (hw - r)
    dy = abs(y - cy) - (hh - r)
    if dx <= 0 or dy <= 0:
        return abs(x - cx) <= hw and abs(y - cy) <= hh
    return dx * dx + dy * dy <= r * r


def _lantern(nx: float, ny: float) -> tuple[int, int, int]:
    """归一化坐标 (0..1) 处该画什么颜色。nx/ny 已按安全区缩放。"""
    cx, cy = 0.5, 0.52

    # 光晕：越靠近灯体越暖
    d = ((nx - cx) ** 2 + (ny - cy) ** 2) ** 0.5
    glow = max(0.0, 1.0 - d / 0.34) ** 2

    # 灯体：竖长圆角矩形
    body = _rounded_rect(nx, ny, cx, cy, 0.20, 0.26, 0.07)
    # 上下灯盖：稍宽的短横条
    cap_t = _rounded_rect(nx, ny, cx, cy - 0.30, 0.26, 0.035, 0.03)
    cap_b = _rounded_rect(nx, ny, cx, cy + 0.30, 0.26, 0.035, 0.03)
    # 灯芯：灯体中央的椭圆
    flame_d = (((nx - cx) / 0.10) ** 2 + ((ny - cy) / 0.16) ** 2) ** 0.5

    if cap_t or cap_b:
        return BODY_HI
    if flame_d <= 1.0:
        return FLAME
    if body:
        # 灯体做上下渐变，避免死板的纯色块
        t = min(1.0, max(0.0, (ny - (cy - 0.26)) / 0.52))
        return tuple(
            int(BODY_HI[i] + (BODY_LO[i] - BODY_HI[i]) * t) for i in range(3)
        )

    if glow > 0:
        return tuple(
            int(BG[i] + (BODY_HI[i] - BG[i]) * glow * 0.55) for i in range(3)
        )
    return BG


def _render(size: int, scale: float) -> bytes:
    """画一张 size×size 的图。scale 控制主体大小（maskable 用 0.62）。"""
    half = size / 2.0
    rows = bytearray()
    for py in range(size):
        rows.append(0)  # PNG 每行的 filter 字节
        for px in range(size):
            r = g = b = 0
            for sy in range(SS):
                for sx in range(SS):
                    fx = (px + (sx + 0.5) / SS - half) / half
                    fy = (py + (sy + 0.5) / SS - half) / half
                    c = _lantern(fx / scale + 0.5, fy / scale + 0.5)
                    r += c[0]
                    g += c[1]
                    b += c[2]
            n = SS * SS
            rows += bytes((r // n, g // n, b // n))
    return bytes(rows)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path: pathlib.Path, size: int, scale: float = 1.0) -> None:
    raw = _render(size, scale)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    print(f"  {path.name}  {size}×{size}  {len(png):,} 字节")


def main() -> None:
    out = pathlib.Path(__file__).resolve().parent.parent / "public"
    out.mkdir(parents=True, exist_ok=True)
    print(f"生成 PWA 图标 → {out}")
    write_png(out / "icon-192.png", 192)
    write_png(out / "icon-512.png", 512)
    # maskable：主体缩到安全区以内，免得被系统遮罩切掉
    write_png(out / "icon-maskable-512.png", 512, scale=0.62)


if __name__ == "__main__":
    main()
````

### A.15 `web/src/views/Feed.tsx`（T5）

````tsx
import { useEffect, useRef, useState } from 'react'
import { fetchCategories, fetchItems } from '../api.ts'
import ItemCard from '../components/ItemCard.tsx'
import type { Category, Item } from '../types.ts'

const PAGE = 50

export default function Feed({
  kind,
  onKind,
}: {
  kind: string
  onKind: (k: string) => void
}) {
  const [cats, setCats] = useState<Category[]>([])
  const [input, setInput] = useState('')
  const [q, setQ] = useState('')
  const [items, setItems] = useState<Item[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  // 请求序号：慢的旧请求晚于新请求返回时，不许覆盖新结果
  const seq = useRef(0)

  useEffect(() => {
    fetchCategories()
      .then((r) => setCats(r.categories))
      .catch(() => setCats([])) // 类目栏拉不到不该让信息流整页不可用
  }, [])

  // 输入防抖：中文输入法下每敲一下都发请求，手机上会明显卡顿
  useEffect(() => {
    const t = setTimeout(() => setQ(input.trim()), 300)
    return () => clearTimeout(t)
  }, [input])

  useEffect(() => {
    const mine = ++seq.current
    setLoading(true)
    setErr(null)
    fetchItems({ kind: kind || undefined, q: q || undefined, limit: PAGE })
      .then((page) => {
        if (mine !== seq.current) return
        setItems(page.items)
        setTotal(page.total)
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return
        setErr(e instanceof Error ? e.message : String(e))
        setItems([])
        setTotal(0)
      })
      .finally(() => {
        if (mine === seq.current) setLoading(false)
      })
  }, [kind, q])

  function loadMore() {
    const mine = seq.current
    setLoading(true)
    fetchItems({
      kind: kind || undefined,
      q: q || undefined,
      limit: PAGE,
      offset: items.length,
    })
      .then((page) => {
        if (mine !== seq.current) return
        setItems((prev) => [...prev, ...page.items])
      })
      .catch((e: unknown) => {
        if (mine !== seq.current) return
        setErr(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (mine === seq.current) setLoading(false)
      })
  }

  const picked = cats.find((c) => c.slug === kind)

  return (
    <div>
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="搜标题或详情（两个字也能搜）"
        className="w-full rounded-xl bg-white/5 px-3 py-2.5 text-sm outline-none placeholder:text-white/30 focus:bg-white/10"
      />

      <div className="mt-3 -mx-1 flex flex-wrap gap-1.5">
        <Chip active={kind === ''} onClick={() => onKind('')}>
          全部
        </Chip>
        {cats.map((c) => (
          <Chip
            key={c.slug}
            active={kind === c.slug}
            onClick={() => onKind(c.slug)}
          >
            {c.icon} {c.label}
          </Chip>
        ))}
      </div>

      <p className="mt-3 text-xs text-white/40">
        {/* 说清「这句话覆盖的是什么」：带上筛选条件，别让一个数字看起来像全部 */}
        {loading && items.length === 0
          ? '读取中…'
          : `共 ${total} 条${picked ? ` · ${picked.label}` : ''}${q ? ` · 关键词「${q}」` : ''}`}
      </p>

      {err !== null && (
        <p className="mt-3 rounded-lg bg-red-500/10 p-3 text-sm text-red-400">
          读取失败：{err}
        </p>
      )}

      {!loading && err === null && items.length === 0 && (
        <p className="mt-6 text-center text-sm text-white/40">
          {/* 空结果必须说清「搜索范围」，否则会被读成「库里就没有这件事」 */}
          {q !== ''
            ? `没有匹配「${q}」的条目。`
            : picked
              ? `「${picked.label}」下还没有条目。`
              : '还没有任何条目。'}
        </p>
      )}

      <ul className="mt-3 space-y-2">
        {items.map((it) => (
          <ItemCard key={it.item_id} item={it} />
        ))}
      </ul>

      {items.length > 0 && items.length < total && (
        <button
          onClick={loadMore}
          disabled={loading}
          className="mt-4 w-full rounded-xl bg-white/5 py-2.5 text-sm text-white/70 active:bg-white/10 disabled:opacity-40"
        >
          {loading ? '读取中…' : `加载更多（还有 ${total - items.length} 条）`}
        </button>
      )}
    </div>
  )
}

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={
        'rounded-full px-3 py-1 text-xs whitespace-nowrap transition-colors ' +
        (active ? 'bg-sky-500/20 text-sky-300' : 'bg-white/5 text-white/55')
      }
    >
      {children}
    </button>
  )
}
````

### A.16 `web/src/views/Categories.tsx`（T6）

````tsx
import { useEffect, useState } from 'react'
import { fetchCategories } from '../api.ts'
import type { Category } from '../types.ts'

export default function Categories({
  onPick,
}: {
  onPick: (slug: string) => void
}) {
  const [cats, setCats] = useState<Category[]>([])
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fetchCategories()
      .then((r) => setCats(r.categories))
      .catch((e: unknown) =>
        setErr(e instanceof Error ? e.message : String(e)),
      )
  }, [])

  if (err !== null) {
    return (
      <p className="rounded-lg bg-red-500/10 p-3 text-sm text-red-400">
        类目读取失败：{err}
      </p>
    )
  }
  if (cats.length === 0) {
    return <p className="text-sm text-white/40">读取类目…</p>
  }

  return (
    <div>
      <p className="mb-3 text-xs text-white/40">
        七个类目 · 点一个看该类全部条目
      </p>
      <div className="grid grid-cols-2 gap-3">
        {cats.map((c) => (
          <button
            key={c.slug}
            onClick={() => onPick(c.slug)}
            className="rounded-xl bg-white/5 p-4 text-left transition-colors active:bg-white/10"
          >
            <div className="text-2xl">{c.icon}</div>
            <div className="mt-1 font-medium">{c.label}</div>
            <div className="text-xs text-white/45">{c.count} 条</div>
          </button>
        ))}
      </div>
    </div>
  )
}
````

### A.17 `web/src/views/Digests.tsx`（T6）

````tsx
import { useEffect, useState } from 'react'
import Markdown from 'react-markdown'
import { fetchDigest, fetchDigests } from '../api.ts'
import ItemCard from '../components/ItemCard.tsx'
import type { DigestDetail, DigestSummary } from '../types.ts'

export default function Digests() {
  const [list, setList] = useState<DigestSummary[] | null>(null)
  const [cur, setCur] = useState<DigestDetail | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    fetchDigests()
      .then((r) => setList(r.digests))
      .catch((e: unknown) => {
        setErr(e instanceof Error ? e.message : String(e))
        setList([])
      })
  }, [])

  function open(id: number) {
    setErr(null)
    fetchDigest(id)
      .then(setCur)
      .catch((e: unknown) =>
        setErr(e instanceof Error ? e.message : String(e)),
      )
  }

  if (err !== null && cur === null) {
    return (
      <p className="rounded-lg bg-red-500/10 p-3 text-sm text-red-400">
        日报读取失败：{err}
      </p>
    )
  }

  if (cur !== null) {
    return (
      <div>
        <button
          onClick={() => setCur(null)}
          className="mb-3 text-sm text-sky-400 active:opacity-70"
        >
          ‹ 返回日报列表
        </button>

        <article className="rounded-xl bg-white/5 p-4">
          <h1 className="text-lg font-semibold">{cur.day} 日报</h1>
          <div className="mt-3">
            {/* react-markdown 默认**不渲染原始 HTML**，日报正文里的尖括号
                不会变成可执行标记——不额外引 sanitizer 也能安全 */}
            <Markdown
              components={{
                h2: ({ children }) => (
                  <h2 className="mt-4 mb-2 text-base font-semibold text-white/90">
                    {children}
                  </h2>
                ),
                h3: ({ children }) => (
                  <h3 className="mt-3 mb-1 text-sm font-semibold text-white/80">
                    {children}
                  </h3>
                ),
                ul: ({ children }) => (
                  <ul className="my-2 space-y-1.5">{children}</ul>
                ),
                li: ({ children }) => (
                  <li className="text-sm leading-relaxed text-white/75">
                    {children}
                  </li>
                ),
                p: ({ children }) => (
                  <p className="my-1.5 text-sm leading-relaxed text-white/75">
                    {children}
                  </p>
                ),
                strong: ({ children }) => (
                  <strong className="font-semibold text-white/95">
                    {children}
                  </strong>
                ),
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    className="break-all text-sky-400 underline"
                  >
                    {children}
                  </a>
                ),
              }}
            >
              {cur.body_md}
            </Markdown>
          </div>
        </article>

        {cur.items.length > 0 && (
          <>
            <p className="mt-5 mb-2 text-xs text-white/40">
              这篇日报引用的 {cur.items.length} 条条目（点开可看源消息）
            </p>
            <ul className="space-y-2">
              {cur.items.map((it) => (
                <ItemCard key={it.item_id} item={it} />
              ))}
            </ul>
          </>
        )}
      </div>
    )
  }

  if (list === null) {
    return <p className="text-sm text-white/40">读取日报列表…</p>
  }

  if (list.length === 0) {
    return (
      <p className="text-center text-sm text-white/40">
        还没有日报。生成：<code className="text-white/60">vigil digest</code>
      </p>
    )
  }

  return (
    <ul className="space-y-2">
      {list.map((d) => (
        <li key={d.digest_id}>
          <button
            onClick={() => open(d.digest_id)}
            className="w-full rounded-xl bg-white/5 p-4 text-left transition-colors active:bg-white/10"
          >
            <div className="font-medium">{d.day}</div>
            <div className="mt-0.5 text-xs text-white/45">
              {d.item_count} 条条目
            </div>
          </button>
        </li>
      ))}
    </ul>
  )
}
````
