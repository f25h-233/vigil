<#
.SYNOPSIS
  幂等注册 VIGIL 网页服务（登录自启）。规矩与 register-task.ps1 相同。

.DESCRIPTION
  与每日管线任务（"VIGIL每日管线"，Daily 08:00）是两条独立的链：
    · 每日管线：到点跑一轮 export → refine → digest，跑完就退出；
    · 本任务：登录时起 `vigil serve`（127.0.0.1:8787），**设计为一直挂着**，
      挂在 Tailscale 的 `tailscale serve` 转发后面，手机随时能开。
      没有它，关机/重启之后手机打开就是 HTTP 502（2026-09-21 实测的原话：
      "为什么我打开网页端，显示 HTTP 502" —— 502 来自 Tailscale 那层
      还活着的转发，它背后的 127.0.0.1:8787 上什么都没在听）。

  为什么是「登录时」（ONLOGON）而不是「开机时」（ONSTART）：
    ONSTART 默认以 SYSTEM 身份跑，而 `uv` 在用户 PATH 上；更本质的是，
    这个服务本来就是给「登录后的人」看的（与每日管线同一条理由：
    没登录时 QQ 也不在，数据也不会更新）。所以 ONLOGON + Interactive
    only 是正确形态，不是将就。

  为什么**创建**走 PowerShell cmdlet 而不是 schtasks：
    `schtasks /create /sc ONLOGON` 在本机免提权下**必然拒绝**（实测
    2026-09-21："ERROR: Access is denied."，补 /ru 也一样）——不带 /ru
    时它建的是「任何用户登录」的机器级触发器。`Register-ScheduledTask
    -AtLogOn -User <自己>` 建的是用户级任务，免提权可用；实测产出仍是
    Task version 1.2，与每日管线任务同一个计划引擎（没有
    UseUnifiedSchedulingEngine 漂移）。「有则覆盖」由 -Force 承担，
    **依然不先删**（理由同 register-task.ps1）。

  ⚠️ 三条设置必须显式覆盖。它们与每日管线任务那三条（电池/漏跑）**不同**，
     各有一个具体的坏法：

  1. ExecutionTimeLimit → PT0S（不限时）。**这条最要命**：schtasks /create
     的默认是 72 小时 —— 一个"设计为永远运行"的服务会在第三天被任务计划
     **静默杀掉**，看起来像随机崩溃，而且它还会被下面的重启设置"复活"，
     于是表现成"每隔三天抖一次"，最难查的那一类。
  2. DisallowStartIfOnBatteries / StopIfGoingOnBatteries → false。
     网页服务没有理由因为拔电源就停（本机实测是笔记本，PCSystemType=2）。
  3. RestartOnFailure（引擎自带的「崩溃后重启」）→ **不设，而且要把旧定义
     里的清掉**。实测（2026-09-21）：taskkill 杀掉服务进程后，任务如实记了
     失败（结果 1），但过了重启间隔 2.5 倍的时间也没有任何重启——旧引擎的
     重启只覆盖「任务起不来」（如程序路径不存在），不覆盖「action 退出非零」。
     真正的自愈在 `scripts/serve_supervisor.py` 的监督循环里（实测验证：
     杀掉服务进程后约 40~65 秒服务自己回来；端口被占住时也会等一分钟
     重试，实测恢复过）。
     本脚本会把该设置**移除**：一个没人能指望的"安全网"比没有更糟——
     它读起来像兜底，实际不兜底。

  ⚠️ 与 register-task.ps1 相同的两条纪律（理由在那里写全了，不重复）：
    · 只 /create /f 覆盖，**不先删**——create 失败时旧任务原样保留；
    · 设置用「先读后改」，不用 New-ScheduledTaskSettingsSet 整体替换
      （实测会把 Task version 顶到 1.3 并打开 UseUnifiedSchedulingEngine
      两个没选过的漂移）；属性名写错在 CimInstance 上**不报错**，
      所以下面的 XML 回读自查是必需的。

.PARAMETER RepoPath
  仓库根目录。任务指向 <RepoPath>\scripts\vigil-serve.cmd。

.EXAMPLE
  cd D:\github\VIGIL
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/register-serve-task.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = "VIGIL网页服务",
    [string]$RepoPath = "D:\github\VIGIL"
)

$ErrorActionPreference = "Stop"

$entry = Join-Path $RepoPath "scripts\vigil-serve.cmd"
if (-not (Test-Path -LiteralPath $entry)) {
    throw "找不到入口脚本：$entry"
}

Write-Host "[1/3] 注册任务：$TaskName（登录时启动）"
# ⚠️ 创建走 cmdlet（理由见 .DESCRIPTION「为什么创建走 cmdlet」一段）：
# schtasks /sc ONLOGON 免提权必被拒；-AtLogOn -User <自己> 是用户级任务。
# /f 的「有则覆盖」语义由 -Force 承担，依然不先删。
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$action = New-ScheduledTaskAction -Execute $entry
Register-ScheduledTask -TaskName $TaskName -Trigger $trigger -Action $action -Force | Out-Null
Write-Host "   触发器：$env:USERNAME 登录时；动作：$entry"

Write-Host "[2/3] 清点设置（覆盖默认 / 摘除无效项），并回读任务定义自查："
$task = Get-ScheduledTask -TaskName $TaskName
$task.Settings.DisallowStartIfOnBatteries = $false
$task.Settings.StopIfGoingOnBatteries     = $false
$task.Settings.ExecutionTimeLimit         = "PT0S"
# 清掉引擎自带的 RestartOnFailure（理由见 .DESCRIPTION 第 3 条：实测无效）。
# 早期版本的本脚本设过它；重跑一次就把定义摘干净，让定义与文档一致。
$task.Settings.RestartCount               = 0
Set-ScheduledTask -TaskName $TaskName -Settings $task.Settings | Out-Null

schtasks /query /tn $TaskName /v /fo LIST

# ⚠️ 必须 -join 成单个字符串再判：schtasks 的输出是多行，PowerShell 会把它
# 捕获成**数组**，而数组上的 -notmatch 返回的是"不匹配的那些元素"（几乎永远
# 非空）⇒ 判据会无条件误报。实测教训，与 register-task.ps1 同一条。
$xml = (schtasks /query /tn $TaskName /xml) -join "`n"
if ($xml -match '<DisallowStartIfOnBatteries>true') { throw "电池限制没改掉" }
if ($xml -match '<StopIfGoingOnBatteries>true')    { throw "拔电源就被杀，没改掉" }
if ($xml -notmatch '<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>') {
    throw "ExecutionTimeLimit 不是 PT0S——默认 72 小时会静默杀掉长驻服务"
}
if ($xml -match '<RestartOnFailure>') {
    throw "RestartOnFailure 还在定义里——它实测无效（见 .DESCRIPTION），应以缺席出现"
}
Write-Host "电源 / 不限时 / 引擎重启已清（真正重试在 scripts/serve_supervisor.py），已确认"

Write-Host "[3/3] 完成。任务名：$TaskName"
Write-Host "手工起一次（不等登录）：schtasks /run /tn `"$TaskName`""
Write-Host "验证：curl.exe -s -o NUL -w `"%{http_code}`" http://127.0.0.1:8787/   （期望 200）"
Write-Host "看上次结果：Get-ScheduledTaskInfo -TaskName `"$TaskName`" | Format-List LastRunTime,LastTaskResult,NextRunTime"
Write-Host "重启服务：taskkill 掉 netstat -ano 里 8787 的 PID —— 监督器约 1 分钟内自动拉起。"
Write-Host "（不建议用 schtasks /end 当重启：实测它可能留下孤儿 serve 进程占着 8787；真留下了就按 PID 杀掉。）"
