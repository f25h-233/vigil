<#
.SYNOPSIS
  幂等注册 VIGIL 每日管线任务。

.DESCRIPTION
  「幂等」在这里是硬要求不是洁癖：这个脚本要被反复执行（换了路径、
  改了时间、重装机器），而 schtasks /create 在任务已存在时会失败。
  先删后建——而且删除用 -ErrorAction SilentlyContinue，因为「本来就没有」
  不是错误。

  为什么不用 XML 导入（schtasks /create /xml）：XML 要手写一整套
  Task Scheduler schema，字段名一旦拼错报的是无关的错误码。命令行开关
  少得多，而且 /tr /sc /st 这三个就是我们要的全部。

  为什么用 -Force（覆盖）而不是先判断存在性再建：判断与建立之间有窗口，
  而 /f 本身就是原子的"有则覆盖"。少一次查询，少一类竞态。

.PARAMETER Time
  每日触发时间，HH:mm，默认 08:00。

  为什么是早上 08:00：`vigil digest` 的默认日期是**昨天**
  （vigil/digest.py 的 yesterday()）。早上跑，昨天已经是一个完整的、
  不会再变的窗口；若放在深夜 23:00 跑，"昨天"指的是前天，会重复处理
  一个已经出过日报的日子。
#>
[CmdletBinding()]
param(
    [string]$TaskName = "VIGIL每日管线",
    [string]$Time = "08:00",
    [string]$RepoPath = "D:\github\VIGIL"
)

$ErrorActionPreference = "Stop"

$script = Join-Path $RepoPath "scripts\vigil-daily.cmd"
if (-not (Test-Path -LiteralPath $script)) {
    throw "找不到入口脚本：$script"
}

Write-Host "[1/3] 删除同名旧任务（若存在）…"
# ⚠️ 只写 `2>$null` 挡不住：PowerShell 5.1 在 $ErrorActionPreference="Stop" 下会把
# 原生命令的 stderr 升格成终止性错误（NativeCommandError），于是「任务本来就不存在」
# 这个正常情形会当场中断脚本（实测：注册一个全新任务时脚本在第 1 步就死了）。
# 这一段把 EAP 临时降为 SilentlyContinue —— 正是上面 .DESCRIPTION 里说的
# 「删除用 SilentlyContinue，因为『本来就没有』不是错误」。用完立刻还原。
$eapBackup = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
schtasks /delete /tn $TaskName /f 2>$null | Out-Null
$ErrorActionPreference = $eapBackup

Write-Host "[2/3] 注册任务：$TaskName 每日 $Time"
$args = @(
    "/create",
    "/tn", $TaskName,
    "/tr", "`"$script`"",
    "/sc", "DAILY",
    "/st", $Time,
    "/rl", "LIMITED",
    "/f"
)
$out = & schtasks @args 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "schtasks /create 失败（退出码 $LASTEXITCODE）：`n$out"
}
Write-Host $out

# ⚠️ schtasks /create 建出来的任务默认带这三条笔记本杀手（实测本机
# PCSystemType=2，是笔记本）：
#   DisallowStartIfOnBatteries=true   → 电池上根本不启动
#   StopIfGoingOnBatteries=true       → 跑到一半拔电源就被杀
#   StartWhenAvailable 缺省 false     → 到点时机器在睡眠，这次直接跳过且永不补跑
# 三条的共同点：**完全没有日志**，因为任务根本没起来。而 M4 存在的全部理由
# 就是"无人值守下的静默失败"。schtasks 命令行没有开关能改这三条，所以用
# cmdlet 补——注意这跟"手写 Task Scheduler XML schema"是两回事，
# `New-ScheduledTaskSettingsSet` 是强类型的 cmdlet 参数，没有拼字段名的风险。
#
# ⚠️ 刻意**不加** -WakeToRun：那会主动唤醒用户的笔记本，是可感知的打扰；
# -StartWhenAvailable 已经能做到"机器一可用就补跑"，且不惊醒任何人。
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable
Set-ScheduledTask -TaskName $TaskName -Settings $settings | Out-Null

Write-Host "[3/3] 回读任务定义，确认真的写进去了："
schtasks /query /tn $TaskName /v /fo LIST

# ⚠️ 必须看到这三行的值都变成我们想要的。StartWhenAvailable 在 /xml 里
# 出现即为 true（缺省时该元素不输出），所以判据是"元素存在"。
#
# ⚠️ 必须 -join 成单个字符串再判：schtasks 的输出是多行，PowerShell 会把它
# 捕获成**数组**，而数组上的 -notmatch 返回的是"不匹配的那些元素"（几乎永远
# 非空）⇒ 那条判据会无条件误报「StartWhenAvailable 没设上」。实测过。
$xml = (schtasks /query /tn $TaskName /xml) -join "`n"
if ($xml -match '<DisallowStartIfOnBatteries>true') { throw "电池限制没改掉" }
if ($xml -match '<StopIfGoingOnBatteries>true')    { throw "拔电源就被杀，没改掉" }
if ($xml -notmatch '<StartWhenAvailable>true')     { throw "StartWhenAvailable 没设上" }
Write-Host "电源与漏跑设置已确认"

Write-Host ""
Write-Host "完成。任务名：$TaskName"
Write-Host "手工跑一次（不等触发器）：schtasks /run /tn `"$TaskName`""
Write-Host "看上次结果：Get-ScheduledTaskInfo -TaskName `"$TaskName`" | Format-List LastRunTime,LastTaskResult,NextRunTime"
