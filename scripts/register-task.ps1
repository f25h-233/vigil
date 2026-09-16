<#
.SYNOPSIS
  幂等注册 VIGIL 每日管线任务。

.DESCRIPTION
  「幂等」在这里是硬要求不是洁癖：这个脚本要被反复执行（换了路径、
  改了时间、重装机器），而 schtasks /create 在任务已存在时会失败。
  靠 /f 覆盖即可，**不先删**（见下面"为什么用 -Force"那段）。

  为什么不用 XML 导入（schtasks /create /xml）：XML 要手写一整套
  Task Scheduler schema，字段名一旦拼错报的是无关的错误码。命令行开关
  少得多，而且 /tr /sc /st 这三个就是我们要的全部。

  为什么用 -Force（覆盖）而不是先判断存在性再建，更不是先删再建：
  判断与建立之间有窗口，而 /f 本身就是原子的"有则覆盖"——少一次查询，
  少一类竞态。**尤其不能先删**：先无条件 delete 再 create，create 一旦失败
  （比如 -Time 传了个非法值），机器上就一条任务都不剩，而报错里只有一句
  schtasks 自己的错误——"你的自动化已经没了"这件事不在报错里。参数打错
  一个字，夜里就不会有人替你跑。

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

# ⚠️ 这里**不删**旧任务，直接靠下面的 /create /f 覆盖（/f = 有则覆盖，原子）。
# 先删再建会把"create 失败"从"旧任务原样保留"恶化成"机器上什么都没有"，
# 而后者在报错里看不出来——请见 .DESCRIPTION 里"尤其不能先删"那段。
Write-Host "[1/2] 注册任务：$TaskName 每日 $Time"
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
# 就是"无人值守下的静默失败"。schtasks 命令行没有开关能改这三条，所以用 cmdlet 补。
#
# ⚠️ 刻意**不加** -WakeToRun：那会主动唤醒用户的笔记本，是可感知的打扰；
# -StartWhenAvailable 已经能做到"机器一可用就补跑"，且不惊醒任何人。
#
# ⚠️ 用**先读后改**，不要 `New-ScheduledTaskSettingsSet` + `Set-ScheduledTask -Settings`：
# 后者是**整体替换**，实测会顺带把 `Task version` 从 1.2 顶到 1.3 并打开
# `UseUnifiedSchedulingEngine`——两个我们没选过的漂移。而它们在"只在用户登录时运行 +
# StartWhenAvailable"这个组合下的行为，本轮没有任何实测证据。
# 我们没选过的东西不该出现在关键路径上：M4 的出口标准就压在"任务真的会自己跑起来"。
#
# ⚠️ 属性名写错在 CimInstance 上**不会报错**（只会静默多出一个谁也不看的属性），
# 所以下面那条 XML 回读自查是必需的——它正是为这个兜底的。
$task = Get-ScheduledTask -TaskName $TaskName
$task.Settings.DisallowStartIfOnBatteries = $false
$task.Settings.StopIfGoingOnBatteries     = $false
$task.Settings.StartWhenAvailable         = $true
Set-ScheduledTask -TaskName $TaskName -Settings $task.Settings | Out-Null

Write-Host "[2/2] 回读任务定义，确认真的写进去了："
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
