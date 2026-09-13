# QQ 群信息聚合整理 —— GitHub 方案调研

调研日期：2026-09-13 ｜ 数据来源：GitHub API（star 数/更新时间均为当日实抓，原始数据 `gh_raw.jsonl` / `gh_repo.jsonl`）

---

## 0. 先回答那个决定性的问题：能不能用你自己的 QQ 号？

**能。而且"机器人进群"这个障碍在自建方案里根本不存在。**

必须区分两条完全不同的路线：

| | 官方机器人平台 | 自建协议端 |
|---|---|---|
| 代表 | 腾讯 q.qq.com / QQ 频道机器人 (`tencent-connect/botpy`) | NapCatQQ / Lagrange.Core / LLOneBot |
| 身份 | **独立的机器人身份**，不是人 | **就是一个普通 QQ 号**，扫哪个码就是哪个号 |
| 进群 | 需群主批准、且群要开通机器人服务 | 不需要任何人批准——那个号本来就在群里 |
| 你的顾虑 | ✅ 成立，排除 | ❌ 不适用 |

NapCatQQ 的自述就是 **"Modern protocol-side framework"（协议端框架）**——"协议端"这个词本身就说明它不是机器人账号体系，而是"用某个 QQ 号登录"。

**所以：用自己的号 = 你就是机器人，进群问题自动消失。**

### 但要付三笔代价

**① 占掉"电脑端"登录位**
QQ 官方多端策略：手机 + 电脑可以同时在线，但**同一号只能有一个电脑端**。

| 部署位置 | 手机 QQ | 电脑 QQ |
|---|---|---|
| NapCat 跑在自己 PC | 正常 | ❌ 同号登不了（互踢） |
| NapCat 跑在服务器/旧机器 | 正常 | ❌ 电脑端登同号会踢掉 NapCat |
| LLOneBot（插件形态，跑在你自己的 QQ 客户端里） | 正常 | ✅ 照常聊 |

**② 风控 / 封号风险（最要紧）**
第三方协议端不是腾讯官方。有先例：`mamoe/mirai`（14810★，已被腾讯法务施压，2024-09 归档）、`Mrs4s/go-cqhttp`（10631★，停更）。社区共识是**用小号**。你打算用大号的话，这是本方案最大且无法替你消除的风险。

**③ 群友观感**
只读监听不发言基本无感；一旦让机器人往群里发日报/总结，群友会看到，也可能被管理员盯上。

---

## 1. 结论先行

GitHub 上**没有**"QQ 群信息聚合"的开箱即用成品（和 Telegram 生态不同——那边有 `groupultra/telegram-search` 4098★ 这种直接可用的）。

现实可行的是一条**三层流水线**，需要自己拼：

```
接入层（把消息从 QQ 里拿出来） → 处理层（整理/总结） → 呈现层（在一处看）
```

---

## 2. 接入层：把 QQ 群消息拿出来

| 项目 | ★ | 语言 | 更新 | 平台 | 说明 |
|---|---|---|---|---|---|
| [NapNeko/NapCatQQ](https://github.com/NapNeko/NapCatQQ) | 10580 | TS | 2026-09-09 | **PC** Win/Linux/macOS/Docker；有 **Web** 配置面板；安卓可 Termux | 当前主流协议端，生态最大 |
| [LLOneBot/LLOneBot](https://github.com/LLOneBot/LLOneBot) | 3605 | TS | 2026-09-11 | **PC**（插件形态） | ⚠️ README 显示已改名 "LLBot / Lucky Lillia Bot" 并转向 LagrangeV2，**形态是否仍是插件需先确认** |
| [LagrangeDev/Lagrange.Core](https://github.com/LagrangeDev/Lagrange.Core) | 2981 | C# | 2026-09-07 | 跨平台 **PC**/服务器 | 纯协议实现，不依赖 QQ 客户端 |
| [Mrs4s/go-cqhttp](https://github.com/Mrs4s/go-cqhttp) | 10631 | Go | 2026-07-10 | 服务器 | ⛔ 已停更，别新用 |
| [mamoe/mirai](https://github.com/mamoe/mirai) | 14810 | Kotlin | 2024-09-23 | JVM | ⛔ 已归档，别用 |

## 3. 处理层：整理 & 总结

| 项目 | ★ | 语言 | 更新 | 平台 | 说明 |
|---|---|---|---|---|---|
| [AstrBotDevs/AstrBot](https://github.com/AstrBotDevs/AstrBot) | 40414 | Python | 2026-09-12 | **Web 管理面板** + 服务端 | 最活跃的 LLM Bot 框架，NapCat 官方点名"完美适配" |
| **[SXP-Simon/astrbot_plugin_qq_group_daily_analysis](https://github.com/SXP-Simon/astrbot_plugin_qq_group_daily_analysis)** | 472 | Python | 2026-09-11 | 输出**海报图/网页链接**（手机可看） | ⭐ **最对口**：自动总结群聊、提取信息、生成海报，自带管理后台可看历史报告 |
| [langbot-app/LangBot](https://github.com/langbot-app/LangBot) | 17760 | Python | 2026-09-12 | 服务端 + Web | 原 QChatGPT，多平台 Agent 机器人平台 |
| [nonebot/nonebot2](https://github.com/nonebot/nonebot2) | 7711 | Python | 2026-09-12 | 服务端 | 需要自己写插件，灵活但工作量大 |
| [koishijs/koishi](https://github.com/koishijs/koishi) | 6196 | TS | 2026-08-28 | **桌面客户端** + Web | 有图形化插件市场，上手友好 |
| [HibiKier/zhenxun_bot](https://github.com/HibiKier/zhenxun_bot) | 3838 | Python | 2026-09-07 | 服务端 | 真寻 bot，功能型 |
| [mgsky1/FG-plugin](https://github.com/mgsky1/FG-plugin) | 16 | Python | 2022-04-01 | 服务端 | NoneBot2 插件：基于每日聊天记录生成总结（老，参考用） |
| [BeaconCat/Renecon](https://github.com/BeaconCat/Renecon) | 0 | JS | 2026-07-07 | **Web GUI** | 基于 NapCat 的群消息监听+归档+LLM 汇总+飞书推送，全图形配置（新项目，风险高） |

## 4. 呈现层：在一处看（通用信息聚合，非 QQ 专用）

| 项目 | ★ | 更新 | 平台 | 说明 |
|---|---|---|---|---|
| [RSSNext/Folo](https://github.com/RSSNext/Folo) | 38951 | 2026-09-12 | **Web / Win / macOS / Linux / Android / iOS / 浏览器扩展** | 全平台 RSS 阅读器，可作统一信息流 |
| [DIYgod/RSSHub](https://github.com/DIYgod/RSSHub) | 46164 | 2026-09-13 | 服务端 Docker | 万物皆可 RSS，但 **QQ 群无现成路由**，需自己写 |
| [ourongxing/newsnow](https://github.com/ourongxing/newsnow) | 21694 | 2026-07-07 | **Web** / Docker | 实时热榜聚合 |
| [LYX9527/what-happen](https://github.com/LYX9527/what-happen) | 319 | 2026-04-22 | **Web**（适配手机） | 新闻聚合，按时间线 |
| [FreshRSS/FreshRSS](https://github.com/FreshRSS/FreshRSS) | 16000 | 2026-09-12 | 服务端 + **Web** | 经典自建 RSS |
| [miniflux/v2](https://github.com/miniflux/v2) | 9682 | 2026-09-12 | 服务端 + **Web** | 轻量 RSS |

## 5. 推送到手机

| 项目 | ★ | 更新 | 平台 |
|---|---|---|---|
| [binwiederhier/ntfy](https://github.com/binwiederhier/ntfy) | 34185 | 2026-09-10 | 服务端 + **Android / iOS / Web / CLI** |
| [gotify/server](https://github.com/gotify/server) | 15883 | 2026-09-12 | 服务端 + **Android / Web** |
| [easychen/pushdeer](https://github.com/easychen/pushdeer) | 5022 | 2026-01-16 | 服务端 + **iOS / Android / Web** |
| [Finb/bark](https://github.com/Finb/bark) | 9078 | 2026-09-04 | 服务端 + **iOS** |

## 6. 旁路：不登录、不发言，事后导出分析

若不想让号被程序接管，可考虑直接解密本地聊天记录数据库：

| 项目 | ★ | 更新 | 平台 | 说明 |
|---|---|---|---|---|
| [shuakami/qq-chat-exporter](https://github.com/shuakami/qq-chat-exporter) | 5117 | 2026-09-11 | **PC** | QQ 聊天记录导出（NTQQ），支持 TXT/JSON ⚠️ 基于 NapCat，仍需协议端 |
| [QQBackup/QQDecrypt](https://github.com/QQBackup/QQDecrypt) | 230 | 2026-08-12 | **PC** | PCQQ/QQ NT 数据库解密教程 —— 真正「不登录」路线，可行性需自测 |
| [Hakuuyosei/QQHistoryExport](https://github.com/Hakuuyosei/QQHistoryExport) | 300 | 2024-01-20 | **安卓** | 安卓设备 QQ 记录导出，支持 PDF |
| [roadwide/qqmessageoutput](https://github.com/roadwide/qqmessageoutput) | 251 | 2024-03-13 | **安卓** | 安卓 QQ 聊天记录导出 |
| [DingHanyang/chatLog](https://github.com/DingHanyang/chatLog) | 215 | 2023-06-11 | PC | QQ 群聊天记录分析（老） |

## 7. 校园场景彩蛋

| 项目 | ★ | 更新 | 平台 | 说明 |
|---|---|---|---|---|
| [ClassIsland/ClassIsland](https://github.com/ClassIsland/ClassIsland) | 2784 | 2026-09-07 | **Windows** | 课表软件 |
| [lukeyancn/CyberTechRep](https://github.com/lukeyancn/CyberTechRep) | 0 | 2026-09-10 | Windows（ClassIsland 插件） | QQ 群消息接管：通知/作业识别、学科分类、文件归档、悬浮窗展示（新项目） |

## 8. 其他平台的同类成品（可参考思路，非 QQ）

| 项目 | ★ | 平台 | 说明 |
|---|---|---|---|
| [groupultra/telegram-search](https://github.com/groupultra/telegram-search) | 4098 | Web/PC | Telegram 聊天记录导出 + 模糊搜索 ← **QQ 侧缺的正是这个** |
| [sjzar/chatlog](https://github.com/sjzar/chatlog) | 9192 | PC | 微信聊天记录 |
| [ops120/wechat-local-viewer](https://github.com/ops120/wechat-local-viewer) | 139 | PC | 微信本地记录查看，纯本地零依赖 |
| [Wxw-Gu/TraceMemo](https://github.com/Wxw-Gu/TraceMemo) | 416 | 桌面 | 微信 AI 知识与分析工作台（原名 WechatExplorer） |

## 9. 通用自动化编排（想搭复杂流水线时用）

| 项目 | ★ | 更新 | 平台 |
|---|---|---|---|
| [n8n-io/n8n](https://github.com/n8n-io/n8n) | 204140 | 2026-09-13 | 服务端 + **Web** |
| [huginn/huginn](https://github.com/huginn/huginn) | 49936 | 2026-09-12 | 服务端 + **Web** |
| [node-red/node-red](https://github.com/node-red/node-red) | 23650 | 2026-09-09 | 服务端 + **Web** |

---

## 10. 落到「大学一堆群」的推荐路径

**最小可行组合（推荐）**
```
NapCatQQ（接入，跑在常开机器上）
   └─ AstrBot（框架，Web 面板配置）
        └─ astrbot_plugin_qq_group_daily_analysis（每日群聊总结 → 海报/网页）
```
- 用**你自己的号**，不需要任何群主批准
- 手机 QQ 照常用
- 只读监听 + 定时出总结，不在群里发言 → 群友无感
- 唯一风险：大号被风控（无法消除，自己权衡）

**若不想让号被接管**：走 §6 的本地数据库解密导出，定期把记录灌给 LLM 总结。代价是不实时。

**若群消息之外还想要统一信息流**：加装 Folo（全平台阅读器）+ RSSHub。
