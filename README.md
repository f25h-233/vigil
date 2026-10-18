# VIGIL · 守夜人

> **V**igilant **I**nformation **G**athering & **I**nsight **L**ayer
> 守望式信息聚合与洞察层

大学里的信息散在一堆 QQ 群里：通知、学业、活动、二手、失物、兼职……每天手动翻太累，
而且**漏掉一条可能是几万块的奖学金，也可能是全宿舍都在问的那件事**。

VIGIL 替你值夜班。你睡觉的时候它盯着指定的群，天亮时把整理好的一页交给你。

```
    23:47  你在写作业
    00:12  群里发了一条「国家奖学金材料周三截止」
    01:30  VIGIL 读到它，判成「通知公告」，算出死线
    07:58  你起床，日报第一行就是它
```

---

## 它能做什么

| | 一句话 |
|---|---|
| **一页看完** | 每天一份日报：通知 / 学业 / 活动 / 生活 分好类，按死线排好序 |
| **不再漏** | 自动抽取时间与地点，`deadline` 与事件时序有**机器闸门**把关（倒挂的死线进不来） |
| **按天看** | 日历视图：把截止日摊到月历上，一眼看出**哪几天有事、哪几天空** |
| **按人看** | 想知道某个同学 / 班委发过什么？`persons.toml` 录一个 uin，网页上一点就筛出来 |
| **随手纠** | 界面里改分类、软删、撤销——**都记在人工干预层**，`refine` 与日报**两处**都认 |
| **随处看** | 手机装成 PWA（Tailscale 内网 HTTPS），锁屏上一眼扫完 |
| **断网也看** | 离线快照：**电脑关机后手机仍能看**——最近 5 天信息流 + 全量日历 + 最近 5 篇日报 + 类目/人物表；离线时写操作置灰并直说「需要联网」 |
| **能取图** | 本地已缓存的图片能取出来（`vigil media`；不做 OCR，见「边界」） |
| **几套皮** | 默认 / Material Design / 粗野主义 / 蒸汽波 / 毛玻璃，外加一个**彩蛋**（见下） |

## 应用场景

- **班级群 + 年级群 + 社团群 + 二手群**：几十个群在刷，真正要看的每天不到十条。
- **一个人值夜班**：白天没空翻群，晚上不想翻记录，但**错过就没了**（报名截止、停水、补考安排）。
- **只想看某几件事**：网页上按类目 + 按人**叠加筛选**（交集），比如「生活类 ∧ 宿管阿姨发的」。
- **睡前扫一眼这周**：日历上哪几天有死线、哪几天干净，比翻十条通知快。
- **想知道这台电脑到底在盯什么**：`config/groups.toml` 里一行一个群，看得见、改得动、可导出。

## 特点（这个项目的性格）

- **只读**。不登录、不发言、不占用 QQ 登录位——直接读 QQ NT 的本地加密库。
  代价是非实时（靠轮询 + 手动唤起），而那个代价正好匹配「一天几次」的使用节奏。
- **看得见每一件事**。网页上**没有**它偷偷藏起来的东西：改了什么、删了什么、撤销了什么，都在一个 append-only 的事件表里。
- **只说自己有资格说的话**。日报读不出来时它会说"没读到"，而不是编一版看起来漂亮的。
- **删除是软的**。界面上消失，**库里的行仍在**，而且不会被重抽复活。
- **不发明**。每个里程碑都要过「计划 → 实现 → 双层审查（含变异反证）→ 真实数据冒烟」，
  计划里被实测推翻的每一处都留在文档里（`## ⚠️ 执行期勘误`）。**它宁可少说，不肯说错。**

---

## 🜂 彩蛋：Project ARGUS

主题切换里有第六个选项。它不叫名字，**而是一段乱码**——几秒之后才显出真名。

选中它，整个界面变成一台**终端**：纯黑底、等宽字、`ARGUS:~$` 提示符、`[1]信息流 [2]类目 [3]日报 [4]配置 [5]日历`。
左上角是它的徽记（**三个空环 + 分叉支干 + 两条弧线**）与大号 **ARGUS**，下面一行小字：

> **睡亦警觉，眼观六路**

它还能听懂一句话。在提示符后面敲：

```
/color green     /color white     /color #ff8800
```

整套界面的颜色——**包括徽记与字标**——跟着变。太暗的颜色会被拒（在纯黑底上读不出来，它会直说）。

> 名字取自希腊神话里那个**从不闭上所有眼睛**的巨人。守夜人该有的样子。

---

## 技术路线（路线 C：本地数据库旁路）

```
QQ NT 本地加密库 → 密钥提取 → 群号过滤 → 增量解密/索引 → LLM 抽取 → 日报 + 网页
                   qq-win-db-key          qqcli-rs
```

**为什么走这条路**：常规 NapCat 部署会与 PC 端 QQ 互踢（同一账号只能有一个电脑端在线），
而路线 C 零登录冲突。若只想处理关心的几个群，2.94 GiB 的库可缩到几 MB，全量也变秒级。

详见 [`docs/FEASIBILITY.md`](docs/FEASIBILITY.md) §六；本机落地记录
见 [`docs/SETUP-ROUTE-C.md`](docs/SETUP-ROUTE-C.md)。

## 边界（明确不做）

多用户 / 权限、overlay 跨机器合并、已删条目的物理清理、主题自定义色板、图片 OCR、富消息段解析、增量导出。

- **Web 侧绝不写 `data/vigil.db`**：连接一律 `mode=ro` 打开，写操作被 SQLite 直接拒绝；
  Web 可写 `config/` 与人工干预层。这条是机械保证——测试里逐字节比对主库指纹。
- **图片只取本地已有的**：本地库的消息体里存着图片的缓存文件名，`vigil media` 依此取本机已落盘的图片文件；
  **文件没下载到本地就取不到**（本群实测只有约 7% 的图片消息有本地文件），且不做 OCR、不解析富消息段。
- **噪声过滤线已归档**（用户 2026-09-17 裁定，`repass --apply` 永久不执行）⇒ 涉及噪声 / 广告先读
  [`docs/superpowers/specs/2026-09-17-vigil-filtering-archive.md`](docs/superpowers/specs/2026-09-17-vigil-filtering-archive.md)。

---

## 里程碑

前七轮按编号推进；此后**模板已定型，第三条工作线另起一版 spec，不承接里程碑编号**
（与 M1–M4 / M5–M7 并列）。

| | 范围 | 状态 |
|---|---|---|
| M1 | 抽取分类（refine engine） | 完成 |
| M2 | 日报合成 | 完成 |
| M3 | Web + PWA | 完成 |
| M4 | 自动化（任务计划 / 日志 / 退出码） | 完成 |
| M5 | items 的正确性与可筛选性 | 完成 |
| M6 | 配置从文件走到界面 | 完成 |
| M7 | 外观：语义化颜色 + 六套主题 + 动效 + 持久化 + PWA 更新链路 | 完成（2026-09-29 收尾） |
| 第三版 spec | 日历（按天可视化截止日）+ 离线快照（关机后手机仍能看） | 完成并推送（2026-10-11） |

每一轮 = 一轮「计划 → 实现 → 双层审查 → 冒烟 → 收尾」。设计与实施计划在 `docs/superpowers/` 下，
跨会话的接力文件是 [`docs/superpowers/progress/vigil-progress.md`](docs/superpowers/progress/vigil-progress.md)。

## 怎么跑

前置：仓库根 `.env` 里有 `VIGIL_DB_KEY` 与 `SILICONFLOW_API_KEY`；`uv` 在 PATH 上；QQ 在跑。

```bash
uv run vigil daily        # 管线：export → refine → digest（任务计划「VIGIL每日管线」每天 08:00 跑 scripts/vigil-daily.cmd）

# ⚠️ 网页服务由任务计划「VIGIL网页服务」登录自启，scripts/serve_supervisor.py 看护。
# 别手工起（端口被占会 bind 10048）；重启姿势见 docs/SETUP-自动化.md §十一。
uv run vigil serve --host 127.0.0.1 --port 8787

cd web && npm run dev     # 前端 5173，/api 代理到 8787
cd web && npm test        # 前端测试
cd web && npm run build   # ⚠️ 构建即上线：8787 托管的就是 web/dist

tailscale serve --bg 8787 # 手机入口（HTTPS）
```

### 常用子命令

```bash
uv run vigil groups                     # 列出 QQ 本地库里所有群（含是否已纳入）
uv run vigil config export --out cfg.toml   # 配置包导出（M6 交付物，网页「配置」页也用它）
uv run vigil config import cfg.toml --dry-run  # 导入（--dry-run 只校验不写）
uv run vigil media --group <群号>       # 列本地**已落盘**的图片（见「边界」：没下载到本地就取不到）
uv run vigil deadline-audit             # 截止日核验：源文里找不到依据的死线（默认只报告，--apply 才写库）
uv run vigil downgrade                  # 字段降级：把不再过闸门的 place/deadline_ts 置 NULL（默认只出清单）
uv run vigil who / read / refine / digest / repass   # 各子步骤单独跑（repass 见「边界」：已归档）
```

两个仪器（只读，在仓库根跑；中文输出在 GBK 控制台需要 `PYTHONIOENCODING=utf-8`）：

```bash
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe vigil_exit_check.py                        # 机械判据
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe vigil_acceptance.py --n 100 --m 20 > 抽样.md # 人工验收的抽样材料
```

自动化与运维（退出码约定、任务计划注册、故障排查、漏天补跑）见
[`docs/SETUP-自动化.md`](docs/SETUP-自动化.md)，补跑脚本是 `scripts/digest_backfill.py`。

### 日报归档（**本机数据，不入库**）

`docs/digests/*.md` 是归档日报，内容是私密信息 ⇒ **已排除在版本控制之外**（`.gitignore`），
其历史也已在 2026-10-18 从版本库中重写清除。
它在本机照常生成、照常读；那条「文件集合与库里 `digests` 的窗口日期集合逐字节相等」的不变量
因此退化为**本机**性质。

⚠️ 口径：这里的「窗口日期」= **本机时区（UTC+8）下 `day_of(window_from)`**，**不是 UTC**
——用 UTC 读整张表会左移一天，从而得出"集合差两天"的**假红**。

## 授权

**GPL-3.0-or-later**（GNU General Public License v3.0 或更新版本），全文见 [`LICENSE`](LICENSE)。

```
VIGIL · 守夜人 —— 本机常驻的 QQ 群信息聚合器
Copyright (C) 2026  f25h-233

本程序是自由软件：你可以按自由软件基金会发布的 GNU 通用公共许可证条款
（第三版或你选择的任何更新版本）再分发和/或修改它。

本程序的发布是希望它有用，但**没有任何担保**——甚至没有对适销性或
特定用途适用性的默示担保。详见 GNU 通用公共许可证。

你应该已经收到一份 GNU 通用公共许可证的副本；
如果没有，见 <https://www.gnu.org/licenses/>。
```

为什么是 GPL 而不是 MIT：这个项目**替你读你在意的群**，你理应能查它到底做了什么、
能在自己机器上改、能把这版改成的东西原样传下去。GPL 保证派生版本继续对使用者开放，
而不是变成某个云服务里看不见的一层。

> 许可覆盖的是**代码**。数据产物 `data/`（主库、人工干预层、日志、缓存）与
> `docs/digests/` 不在版本库里（见 `.gitignore`）；本仓库另收有 `config/*.toml` 等配置样例。

## 目录

| 路径 | 内容 |
|---|---|
| `vigil/` | Python 包（入口 `cli.py`）。管线：`daily.py` 每日编排、`export.py` 导出、`store.py` 落库、`refine.py` 抽取、`digest.py` 日报；读侧：`qqdb.py` 读 QQ 库、`reader.py` 正文读取、`senders.py` 发信人解析、`media.py` 本地图片引用、`prefilter.py` 候选预筛、`deadline.py` 死线抽取、`text.py` / `redact.py` 文本与脱敏；服务：`api.py` 只读 JSON API、`overrides.py` 人工干预层、`reorder.py` / `repass.py` / `categories.py` / `config.py` / `configpack.py` / `groups_snapshot.py` / `jobs.py` 配置面、`llm.py` 模型调用、`lock.py` 单实例锁、`logs.py` 日志轮转 |
| `web/` | 前端：React 19 + Vite + Tailwind v4 + PWA。视图 `src/views/`（`Feed` / `Categories` / `Digests` / `Settings` / `Calendar`）；`src/snapshot.ts` 离线快照、`src/connectivity.ts` 在线探测、`src/swUpdate.ts` PWA 更新链路（`web/dist` 不入库，但 8787 托管的就是它） |
| `web/src/index.css` | **主题层**：六套主题的 token（`--v-*`）× 动效 × 壁纸；`@theme inline` 把原始变量接进 Tailwind |
| `scripts/` | 任务计划注册、服务监督器 `serve_supervisor.py`、漏天补跑 `digest_backfill.py` |
| `tests/` | 后端测试（`uv run pytest`） |
| `config/` | 四份 toml：`groups.toml`（群与分级）、`persons.toml`（人物筛选）、`categories.toml`、`llm.toml` |
| `data/` | 本地数据（**不入库**）：主库 `vigil.db`、人工干预层 `overrides.db`、群清单快照 `groups-snapshot.json`、`logs/`、`cache/`，以及 `.bak-*` 备份 |
| `docs/` | 调研与可行性、运维文档、`superpowers/`（spec / plan / progress） |

## 文档索引

| 文件 | 内容 |
|---|---|
| [`docs/FEASIBILITY.md`](docs/FEASIBILITY.md) | 可行性评估、三条路线对比、本机数据库实测、路线 C 耗时估算与工具链、密钥提取环节补录 |
| [`docs/REPORT.md`](docs/REPORT.md) | GitHub 方案全景调研（接入层 / 处理层 / 呈现层，star 与更新日期均为 2026-09-13 实抓） |
| [`docs/SETUP-ROUTE-C.md`](docs/SETUP-ROUTE-C.md) | 路线 C 本机落地记录：工具链落位、环境改动（junction）、密钥提取步骤 |
| [`docs/DATA-NOTES.md`](docs/DATA-NOTES.md) | QQ 库结构笔记：加密方式、坏页、列义、发信人解析、正文提取、图片通知为何拿不到 |
| [`docs/SETUP-自动化.md`](docs/SETUP-自动化.md) | 自动化：任务计划、退出码约定、日志轮转、网页服务自启与自愈、漏天补跑 |
| `docs/superpowers/specs/` | 各轮设计：`2026-09-13-…`（M1–M4 冻结版）、`2026-09-16-vigil-m5-m7-design.md`（M5–M7）、`2026-09-17-vigil-filtering-archive.md`（噪声线归档）、`2026-10-10-vigil-calendar-offline-design.md`（第三版：日历 + 离线快照，不承接里程碑编号） |
| `docs/superpowers/plans/` | 各轮实施计划（M1–M7 + 第三版日历/离线），正文后多附 `## ⚠️ 执行期勘误` |
| [`docs/superpowers/progress/vigil-progress.md`](docs/superpowers/progress/vigil-progress.md) | 接力文件：跨会话现状、不变量、下一步 |
| `docs/raw/` | 原始抓取证据（GitHub API 响应、仓库页面 HTML、调研脚本） |

## 现状

M1–M7 已完成（M7 于 2026-09-29 收尾）；**第三版 spec（日历 + 离线快照）已完成并推送（2026-10-11）**。

测试数字（截至第三版收尾）：后端 `uv run pytest` = **850 passed**；
前端 `cd web && npm test` = **26 个测试文件 / 244 passed**。
