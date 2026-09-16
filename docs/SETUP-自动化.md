# 自动化：任务计划每日跑一遍管线

> 实测日期：2026-09-16 ｜ 本文的命令都在本机实跑过；注册脚本还**反复跑了两遍**验证幂等
> （证据：`schtasks /query` 原文）。`.cmd` 段额外在 **OEM 936 控制台**下重跑过一遍，
> 确认换代码页也不影响它。

---

## 一、它是什么

Windows 任务计划里的一条任务，名字固定 **`VIGIL每日管线`**，默认每天 **08:00**
跑一次 `vigil daily`——它把三个阶段串起来跑：

```
export   →   refine   →   digest
解密导出    抽取结构化    合成日报
```

入口是 `scripts\vigil-daily.cmd`（为什么用 `.cmd` 而不是 `.ps1` 见文末§十）。

产物：

| 路径 | 内容 |
|---|---|
| `docs/digests/<昨天>.md` | 日报正文 |
| `data/logs/vigil-YYYY-MM-DD.log` | 本次运行的完整日志 |
| `data/logs/LAST-ERROR.txt` | **只在失败时出现**；每次运行开始前会被先删掉 |

**为什么是早上 08:00**：`vigil digest` 的默认日期是**昨天**。早上跑，昨天已经是一个
完整的、不会再变的窗口；若放在深夜 23:00 跑，"昨天"指的是前天，会重复处理一个
已经出过日报的日子。

---

## 二、前置条件（三条，缺一条就跑不出东西）

1. **`.env` 里有密钥**：`VIGIL_DB_KEY`（QQ 本地库解密密钥）与 `SILICONFLOW_API_KEY`
   （模型调用）。任务计划跑的时候**不会加载你 shell 里的环境变量**，它读的是仓库根目录的
   `.env` 文件。
2. **`uv` 在 PATH 上**：`.cmd` 里那一句就是 `uv run vigil daily`。检查：

   ```powershell
   uv --version
   ```
3. **QQ 在跑**：管线读的是 QQ 的本地库，QQ 不跑，本地库就没有新消息（不会报错，只是日报内容空）。

---

## 三、安装（注册任务）

先 `cd` 到仓库根目录——脚本里用的是相对路径 `scripts/register-task.ps1`，
直接在新开的 PowerShell 里粘贴下面第二行会找不到文件：

```powershell
cd D:\github\VIGIL
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/register-task.ps1
```

预期输出两步：`[1/2] 注册任务`、`[2/2] 回读任务定义`，
最后一段是 `schtasks /query /v /fo LIST` 的原文，里面应能找到：

```
TaskName:                             \VIGIL每日管线
Task To Run:                          D:\github\VIGIL\scripts\vigil-daily.cmd
Schedule Type:                        Daily
Start Time:                           8:00:00
Next Run Time:                        2026/9/17 8:00:00
```

最后一行应是 `电源与漏跑设置已确认`（脚本自查了下面「笔记本」那三条；`Power Management`
那一行从默认的 `Stop On Battery Mode, No Start On Batteries` 变成了空）。
自查不通过时脚本会**报错退出**，不会留下一个"看起来注册成功了、其实一在电池上就永远不跑"的任务。

**这个脚本是幂等的**——靠 `schtasks /create /f` 覆盖（"有则覆盖"是原子的），
重复跑不会报错，任务定义逐字节一致。换了路径、改了时间、重装了机器，直接再跑一遍就行。

> ⚠️ 脚本**不会先删掉旧任务**再建。这不是省事：先删再建的话，`/create` 一旦失败
> （最容易踩的是 `-Time` 格式写错，比如 `8:0`），机器上就**一条任务都不剩**，
> 而报错里只有 schtasks 自己那一句——"你的自动化已经没了"这件事不在报错里。
> 现在这样，建失败时旧任务原样留着，明天照跑。

> ⚠️ 任务默认是 **Interactive only**（`Logon Mode` 那一行）：**只在你的账户登录时才跑**。
> 注销/重启后没人登录，它不会自己启动。想要不登录也跑，得改成"不管用户是否登录都运行"，
> 那需要把账户密码存进任务计划（`schtasks /create /ru ... /rp ...`）——本管线没走这条路，
> 因为把密码写进任务定义里不划算。

> 🔋 **笔记本 / 睡眠：两条漏跑已经替你关掉了**（本机实测 `PCSystemType=2`，就是笔记本）。
> `schtasks /create` 建出来的任务默认带三条"笔记本杀手"，**它们的共同点是完全没有日志——
> 因为任务根本没起来**：
>
> | 默认设置 | 后果 |
> |---|---|
> | `DisallowStartIfOnBatteries=true` | 08:00 时机器在用电池 → **不启动** |
> | `StopIfGoingOnBatteries=true` | 跑到一半拔电源 → **任务被杀** |
> | `StartWhenAvailable=false` | 08:00 时机器在睡眠 → **这次跳过，且永不补跑** |
>
> 注册脚本已经用 cmdlet 把这三条改掉（`schtasks` 命令行**没有**开关能改它们）：
> 前两条关掉，**`StartWhenAvailable` 打开——机器一可用就补跑**（睡眠错过的那次会补上）。
>
> 自查（三行都应是下面的值）：
>
> ```powershell
> schtasks /query /tn "VIGIL每日管线" /xml | Select-String "Batteries|StartWhenAvailable"
> # 期望：
> #   <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
> #   <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
> #   <StartWhenAvailable>true</StartWhenAvailable>
> # （StartWhenAvailable 缺省为 false，所以"元素不出现"就是没设上）
> ```
>
> ⚠️ **没有**开 `WakeToRun`：那会主动唤醒你的笔记本，是可感知的打扰。
> `StartWhenAvailable` 已经能做到"机器一可用就补跑"，且不惊醒任何人。
> 代价是：**机器整夜关机/睡眠时，08:00 那次不会准点跑，而是等你下次开机/唤醒后补跑。**
> 结果一样会落到 `docs/digests/`，只是时间不是你起床前。
>
> **这仍然满足「挂机 24 小时产出一篇日报」，而且是刻意的取舍**：
> 机器开着（含睡眠）时，`StartWhenAvailable` 会在它一可用时补跑——08:00 在睡眠，
> 你打开盖子那一刻它就跑了；机器**关机**时任何任务都跑不了，这是物理约束不是缺陷，
> 开机后照样补跑、照样产出。不开 `WakeToRun` 是因为它会**主动把笔记本唤醒**
> （风扇转、屏幕亮、半夜响）——换来的只是"早几小时跑完"；日报本来就是给人白天看的，
> 早上九点跑和八点跑没有区别。

---

## 四、改时间 / 改路径

```powershell
cd D:\github\VIGIL

# 改成每天早上 07:30
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/register-task.ps1 -Time 07:30

# 仓库搬到了别处（换了盘/换了目录）：先 cd 到新位置，再把新位置传给 -RepoPath
cd E:\code\VIGIL
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/register-task.ps1 -RepoPath "E:\code\VIGIL"
```

时间格式是 `HH:mm`；写错了脚本会报错退出，**旧任务原样保留**（见上一节那条提醒）。
改完立刻生效，不用重启什么。

`-RepoPath` 指向哪儿，任务就指向那儿的 `scripts\vigil-daily.cmd`；而那个 `.cmd` 会**从自己所在的位置**
推出仓库根（不硬编码路径），所以整条链跟着走——搬完仓库不用再改第三处。
（实测：把仓库复制到另一个路径、用 `-RepoPath` 注册，任务指向副本的 `.cmd`；跑那个副本，
它读写的是副本自己的 `data\logs\`，原仓库一个字没动。）

---

## 五、看它跑没跑（从粗到细三条）

```powershell
cd D:\github\VIGIL   # ② ③ 用的是相对路径，先回到仓库根

# ① 任务计划自己记的账：上次什么时候跑的、结果码是多少、下次什么时候跑
Get-ScheduledTaskInfo -TaskName "VIGIL每日管线" | Format-List LastRunTime,LastTaskResult,NextRunTime

# ② 当天有没有日志、有没有错误标记
ls data/logs/

# ③ 日志尾部 40 行（真正的过程在这里）
Get-Content data/logs/vigil-*.log -Tail 40
```

`LastTaskResult` 的含义与下表的退出码一致（任务计划把退出码原样记在这里）。

---

## 六、失败了怎么读

先看 `data/logs/LAST-ERROR.txt`：**第一行是失败摘要，后面附日志尾部**。
再看 `data/logs/vigil-*.log` 的尾部。

**退出码含义表：**

| 退出码 | 含义 |
|---|---|
| `0` | 三阶段全过 |
| `1` | 有阶段失败或不完整（见 `LAST-ERROR.txt`） |
| `2` | 已有实例在跑，本次直接退出（**不是错误**，见§七） |
| 其它 | 看日志；若连日志都没有，说明 Python 没起来（`.cmd` 的英文兜底句就是这种情况） |

> ⚠️ **`2` 不一定是"已有实例在跑"**：`argparse` 参数写错时也返回 `2`。
> 所以看到 `2` 先确认参数没写错——我们的参数解析走 `parse_args`，那条路径**不经过锁**。
> 手工跑一遍就能区分：跑起来立刻退出、日志里没东西 ⇒ 是参数问题；
> 日志（或锁文件）说"已有实例在跑" ⇒ 才是并发保护。

> ℹ️ **`LAST-ERROR.txt` 第一行的日期前缀跟控制台代码页走**：正文是英文（永远可读），
> 但 `%DATE%` 展开出来的日期在非 UTF-8 代码页的机器上是 GBK 字节，用 UTF-8 读会显示乱码。
> 本机系统 OEMCP = 65001，所以是 UTF-8。乱码只影响那个日期，不影响正文。

---

## 七、为什么会有「已有实例在跑」（退出码 2）

上一次还没跑完（QQ 库很大、模型慢、网络卡）时，到点又触发了一次——**这一次不会叠加**，
它会发现锁被占着，立刻退出，返回 `2`。这是**有意的**：

> 两个 refine 同时跑会产出重复条目并白烧两份 token。

所以退出码 `2` 的正确处置是**什么都不做**，等下一轮。它不是故障，是并发保护生效了。
（`0` 与 `2` 是"无需人管"，`1` 与其它才是"要人来看"——这正是把 `2` 单列出来、
而不是复用一个 `1` 的原因。）

---

## 八、卸载

```powershell
schtasks /delete /tn "VIGIL每日管线" /f
```

产物（`docs/digests/`、`data/logs/`）不会跟着删——那是你的记录。

---

## 九、日志轮转

`data/logs/` 下的日志**保留 30 天，超期的自动删除**（由 Python 侧在每次运行时清理）。
`LAST-ERROR.txt` 不参与轮转：它一次运行只可能被写一次，且下次运行开头就被删掉。
手工清理也完全可以：`data/logs/` 里没有任何东西是别的模块依赖的。

---

## 十、两个设计选择（免得当成疏漏）

1. **入口为什么是 `.cmd` 而不是 `.ps1`**：`.ps1` 需要 `-ExecutionPolicy Bypass` 才能跑，
   而执行策略是**机器级**设置——组策略、企业策略或用户改过都可能让它变。任务计划配好的
   东西不该因为一条机器策略就静默不跑。`.cmd` 由 `cmd.exe` 直接执行，没有这层变量。
2. **`.cmd` 里为什么一句中文都没有**：`cmd.exe` 按 OEM 代码页**逐字节**解析文件，
   中文注释在 GBK 机器上会变乱码字节，而 `echo` 到文件的内容会**带着真实字节**落盘，
   括号/管道符混在中文里还可能被解析成命令分隔符。所以人类可读的中文全部交给 Python 写，
   `.cmd` 里只留 ASCII。（实测：在 `chcp 936` 下跑同一个 `.cmd`，正文照样正确。）
