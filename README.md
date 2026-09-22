# VIGIL · 守夜人

> **V**igilant **I**nformation **G**athering & **I**nsight **L**ayer
> 守望式信息聚合与洞察层

大学里的信息散在一堆 QQ 群里，每天手动翻太累。VIGIL 替你值夜班——
你睡觉的时候它盯着指定的群，天亮时把整理好的东西交给你。

## 定位

本机常驻的 QQ 群消息聚合器：**只读监听 → 索引存档 → 定时 / 手动唤起 → 抽取条目 → 日报与网页一页看完**。

## 技术路线（路线 C：本地数据库旁路）

**不登录、不发言、不占用 QQ 登录位**——直接读取 QQ NT 的本地加密数据库。

```
QQ NT 本地加密库 → 密钥提取 → 群号过滤 → 增量解密/索引 → LLM 抽取 → 日报 + 网页
                   qq-win-db-key          qqcli-rs
```

**为什么走这条路**：常规 NapCat 部署会与 PC 端 QQ 互踢（同一账号只能有一个电脑端在线），
而路线 C 零登录冲突。代价是非实时——靠轮询 + 手动唤起，正好匹配「一天几次」的使用节奏。
若只想处理关心的几个群，2.94 GiB 的库可缩到几 MB，全量也变秒级。

详见 [`docs/FEASIBILITY.md`](docs/FEASIBILITY.md) §六；本机落地记录（工具链落位、junction、密钥提取）
见 [`docs/SETUP-ROUTE-C.md`](docs/SETUP-ROUTE-C.md)。

## 里程碑

| | 范围 | 状态 |
|---|---|---|
| M1 | 抽取分类（refine engine） | 完成 |
| M2 | 日报合成 | 完成 |
| M3 | Web + PWA | 完成 |
| M4 | 自动化（任务计划 / 日志 / 退出码） | 完成 |
| M5 | items 的正确性与可筛选性 | 完成 |
| M6 | 配置从文件走到界面（11 个任务） | 完成并推送 |
| M7 | 外观：语义化颜色 + 五套主题 + 持久化 + PWA 更新链路 | **进行中** |

每个里程碑 = 一轮「计划 → 实现 → 双层审查 → 冒烟 → 收尾」，设计与实施计划都在
`docs/superpowers/` 下。跨会话的接力文件是
[`docs/superpowers/progress/vigil-progress.md`](docs/superpowers/progress/vigil-progress.md)。

## 边界（这个项目的性格）

- **只读 QQ**：不登录、不发言、不写 QQ 的任何数据。
- **Web 侧绝不写 `data/vigil.db`**：连接一律 `mode=ro` 打开，写操作被 SQLite 直接拒绝；
  Web 可写 `config/` 与「人工干预层」。这条是机械保证——测试里逐字节比对主库指纹。
- **删除是软删**：界面上消失，**库里的行仍在**，且不会被重抽复活。改类目 / 软删 / 撤销
  都写「人工干预层」（append-only 的事件表 `data/overrides.db`），`refine` 与日报读路径都读它。
- **明确不做**：多用户 / 权限、overlay 跨机器合并、已删条目的物理清理、主题自定义色板、
  图片 OCR、富消息段解析、增量导出。
- **噪声过滤线已归档**（用户 2026-09-17 裁定，`repass --apply` 永久不执行）：
  涉及噪声 / 广告的问题先读
  [`docs/superpowers/specs/2026-09-17-vigil-filtering-archive.md`](docs/superpowers/specs/2026-09-17-vigil-filtering-archive.md)。

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

两个仪器（只读，在仓库根跑）：

```bash
.venv/Scripts/python.exe vigil_exit_check.py                             # 机械判据
.venv/Scripts/python.exe vigil_acceptance.py --n 100 --m 20 > 抽样.md    # 人工验收的抽样材料
```

自动化与运维（退出码约定、任务计划注册、故障排查、漏天补跑）见
[`docs/SETUP-自动化.md`](docs/SETUP-自动化.md)，补跑脚本是 `scripts/digest_backfill.py`。

`docs/digests/*.md` 是归档日报：文件集合与库里 `digests` 的窗口日期集合**逐字节相等**，
`.gitattributes` 用 `text eol=lf` 让这条不变量对 git 免疫。

## 目录

| 路径 | 内容 |
|---|---|
| `vigil/` | Python 包：`cli.py` 命令行、`daily.py` 每日管线、`qqdb.py` 读 QQ 库、`export.py` 导出、`store.py` 落库、`refine.py` 抽取、`digest.py` 日报、`api.py` 只读 JSON API、`overrides.py` 人工干预层；配置面 `config.py` / `categories.py` / `configpack.py` / `groups_snapshot.py` / `jobs.py` / `reorder.py` / `repass.py` |
| `web/` | 前端：React 19 + Vite + Tailwind v4 + PWA（`web/dist` 不入库，但 8787 托管的就是它） |
| `scripts/` | 任务计划注册（`register-task.ps1` / `register-serve-task.ps1`）、服务监督器 `serve_supervisor.py`、漏天补跑 `digest_backfill.py` |
| `tests/` | 后端测试（`uv run pytest`） |
| `config/` | 四份 toml：`groups.toml`（群与分级）、`persons.toml`、`categories.toml`、`llm.toml` |
| `data/` | 本地数据（**不入库**）：主库 `vigil.db`、人工干预层 `overrides.db`、`logs/`、`cache/` |
| `docs/` | 调研与可行性、运维文档、日报归档、`superpowers/`（spec / plan / progress） |

## 文档索引

| 文件 | 内容 |
|---|---|
| [`docs/FEASIBILITY.md`](docs/FEASIBILITY.md) | 可行性评估、三条路线对比、本机数据库实测、路线 C 耗时估算与工具链、密钥提取环节补录 |
| [`docs/REPORT.md`](docs/REPORT.md) | GitHub 方案全景调研（接入层 / 处理层 / 呈现层，star 与更新日期均为 2026-09-13 实抓） |
| [`docs/SETUP-ROUTE-C.md`](docs/SETUP-ROUTE-C.md) | 路线 C 本机落地记录：工具链落位、环境改动（junction）、密钥提取步骤 |
| [`docs/DATA-NOTES.md`](docs/DATA-NOTES.md) | QQ 库结构笔记：加密方式、坏页、列义、发信人解析、正文提取、图片通知为何拿不到 |
| [`docs/SETUP-自动化.md`](docs/SETUP-自动化.md) | 自动化：任务计划、退出码约定、日志轮转、网页服务自启与自愈、漏天补跑 |
| `docs/superpowers/specs/` | 各里程碑设计（`2026-09-13-vigil-product-layer-design.md` 为 M1–M4 冻结版；`2026-09-16-vigil-m5-m7-design.md` 含 M7 范围与出口证据） |
| `docs/superpowers/plans/` | 各里程碑实施计划（M1–M7），正文后多附执行期勘误 |
| [`docs/superpowers/progress/vigil-progress.md`](docs/superpowers/progress/vigil-progress.md) | 接力文件：跨会话现状、不变量、下一步 |
| `docs/raw/` | 原始抓取证据（GitHub API 响应、仓库页面 HTML、调研脚本） |

## 现状

M1–M6 已完成（M6「配置从文件走到界面」11 个任务，2026-09-22 收尾并推送）。
**M7「外观」进行中**——语义化颜色、五套主题、视图状态持久化、PWA 更新链路。

测试数字（**截至 M6 收尾**；M7 进行中，这两个数都会变）：后端 `uv run pytest` **844 passed**，
前端 `cd web && npm test` **55 passed**。
