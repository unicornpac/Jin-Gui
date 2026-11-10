<#
.SYNOPSIS
    干净重启《金匮要略》训练系统本地服务。

.DESCRIPTION
    解决一个在 Windows 上反复踩到的坑：
    旧的 uvicorn 进程（尤其是 --reload 留下的子 worker）没被清掉时会继续占着 8000 端口，
    新进程绑定失败即退出，而旧进程照常响应请求 —— 于是「重启成功」其实是假象，
    页面上跑的仍是旧代码，改动看起来「没生效」。

    本脚本按以下顺序执行，任一步失败即停止，不会带着脏状态硬启动：
      1. 找出占用目标端口的进程 + 本项目的 uvicorn 进程（含父子进程树）
      2. 逐个 taskkill /T /F，并等端口真正释放
      3. 用干净的进程启动 uvicorn
      4. 轮询 /ready 直到返回 200
      5. 自检：新进程的启动时间必须晚于最新一次 .py 修改，否则警告跑的是旧代码

.PARAMETER Port
    监听端口，默认 8000。

.PARAMETER Reload
    启用 --reload 热重载。默认关闭：Windows 上 --reload 会漏掉部分写入，
    改完代码仍可能不生效，所以默认走「每次显式重启」这条可预测的路。

.PARAMETER KillAllPython
    杀掉本机所有 python.exe。默认只动本项目相关的进程，
    只有在残留进程识别不出来时才需要这个开关。

.PARAMETER WaitSeconds
    等待 /ready 返回 200 的超时秒数，默认 40。

.PARAMETER Check
    只体检不重启：报告端口占用、进程状态、健康检查结果与代码新鲜度。

.PARAMETER NoWait
    启动后不等待就绪即返回（适合想自己看日志的情况）。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\restart.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\restart.ps1 -Reload

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\restart.ps1 -Check

.NOTES
    2026-11 新增。此前用 --reload + 手动重启，多次因孤儿 worker 占用端口而误判改动未生效。
    本文件必须保存为 UTF-8 with BOM：Windows PowerShell 5.1 读取无 BOM 的 UTF-8 会按 GBK 解析，
    中文字符串会被截断并引发「缺少字符串终止符」之类的假语法错误。
#>
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Reload,
    [switch]$KillAllPython,
    [int]$WaitSeconds = 40,
    [switch]$Check,
    [switch]$NoWait
)

$ErrorActionPreference = 'Stop'

# ---------- 路径与解释器 ----------

$ToolsDir = $PSScriptRoot
$RepoRoot = Split-Path $ToolsDir -Parent
$BackendDir = Join-Path $RepoRoot 'backend'
$AppDir = Join-Path $BackendDir 'app'
$OutLog = Join-Path $BackendDir 'server.log'
$ErrLog = Join-Path $BackendDir 'server.err.log'
$BaseUrl = "http://127.0.0.1:$Port"

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "  OK  $Text" -ForegroundColor Green }
function Write-Warn2([string]$Text) { Write-Host "  !!  $Text" -ForegroundColor Yellow }
function Write-Err2([string]$Text) { Write-Host "  XX  $Text" -ForegroundColor Red }

if (-not (Test-Path $BackendDir)) {
    Write-Err2 "找不到后端目录：$BackendDir"
    exit 1
}

function Resolve-Python {
    $candidates = @(
        'C:\Python311\python.exe',
        (Join-Path $BackendDir '.venv\Scripts\python.exe'),
        'C:\anaconda3\python.exe'
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

$PythonExe = Resolve-Python
if (-not $PythonExe) {
    Write-Err2 '找不到可用的 python.exe（试过 C:\Python311、.venv、anaconda、PATH）'
    exit 1
}

# ---------- 进程与端口探测 ----------

function Get-ListenerPids([int]$TargetPort) {
    $found = @()
    try {
        $conns = @(Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue)
        if ($conns.Count -gt 0) {
            foreach ($c in $conns) { $found += [int]$c.OwningProcess }
        }
    } catch {
        # 老系统没有 Get-NetTCPConnection 时退回 netstat
        $lines = @(netstat -ano | Select-String ":$TargetPort\s" | Select-String 'LISTENING')
        foreach ($l in $lines) {
            $parts = @($l.ToString().Trim() -split '\s+')
            if ($parts.Count -ge 5) { $found += [int]$parts[$parts.Count - 1] }
        }
    }
    return @($found | Where-Object { $_ -gt 0 } | Sort-Object -Unique)
}

function Get-ProjectPythonPids([int]$TargetPort) {
    # 本项目的特征：命令行里是 uvicorn、入口是 app.main:app、端口与目标端口一致
    $found = @()
    try {
        $procs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue)
        foreach ($p in $procs) {
            $cmd = [string]$p.CommandLine
            # 收紧条件：入口是 app.main:app 且端口与本次重启的目标端口一致，
            # 避免把别的项目里同名入口的 uvicorn 一起杀掉。
            if ($cmd -match 'uvicorn' -and $cmd -match 'app\.main:app' -and $cmd -match "--port\s+$TargetPort(\s|$)") {
                $found += [int]$p.ProcessId
            }
        }
    } catch {
        Write-Warn2 "读取进程命令行失败，跳过项目进程扫描：$($_.Exception.Message)"
    }
    return @($found | Sort-Object -Unique)
}

function Get-AllPythonPids {
    $found = @()
    foreach ($p in @(Get-Process -Name python -ErrorAction SilentlyContinue)) { $found += [int]$p.Id }
    return @($found | Sort-Object -Unique)
}

function Get-ProcInfo([int]$ProcId) {
    $p = Get-Process -Id $ProcId -ErrorAction SilentlyContinue
    if (-not $p) { return $null }
    $cmd = ''
    try {
        $c = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -ErrorAction SilentlyContinue
        if ($c) { $cmd = [string]$c.CommandLine }
    } catch { }
    return New-Object psobject -Property @{
        Id          = $ProcId
        Name        = $p.Name
        StartTime   = $p.StartTime
        CommandLine = $cmd
    }
}

function Test-PortFree([int]$TargetPort) {
    $pids = @(Get-ListenerPids $TargetPort)
    return ($pids.Count -eq 0)
}

function Get-HealthSnapshot {
    try {
        $r = Invoke-WebRequest -Uri "$BaseUrl/ready" -TimeoutSec 4 -UseBasicParsing
        return New-Object psobject -Property @{
            Ok     = ($r.StatusCode -eq 200)
            Status = [int]$r.StatusCode
            Body   = [string]$r.Content
        }
    } catch {
        $code = 0
        $body = $_.Exception.Message
        $resp = $null
        try { $resp = $_.Exception.Response } catch { $resp = $null }
        if ($resp -ne $null) { $code = [int]$resp.StatusCode }
        return New-Object psobject -Property @{
            Ok     = $false
            Status = $code
            Body   = $body
        }
    }
}

function Get-NewestPyFile {
    if (-not (Test-Path $AppDir)) { return $null }
    $files = @(Get-ChildItem $AppDir -Recurse -File -Filter *.py -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending)
    if ($files.Count -eq 0) { return $null }
    return $files[0]
}

# ---------- 只体检模式 ----------

if ($Check) {
    Write-Step "体检（端口 $Port，不重启）"
    Write-Host "  仓库:     $RepoRoot"
    Write-Host "  解释器:   $PythonExe"

    $listeners = @(Get-ListenerPids $Port)
    if ($listeners.Count -eq 0) {
        Write-Warn2 "端口 $Port 当前没有监听进程（服务未启动）"
    } else {
        foreach ($procId in $listeners) {
            $info = Get-ProcInfo $procId
            if ($info -ne $null) {
                Write-Host "  端口监听: PID=$($info.Id) $($info.Name) 启动于 $($info.StartTime)"
                Write-Host "             $($info.CommandLine)"
            } else {
                Write-Warn2 "端口 $Port 被 PID=$procId 占用，但读不到进程详情"
            }
        }
    }

    $stray = @(Get-ProjectPythonPids $Port)
    $extra = @($stray | Where-Object { $listeners -notcontains $_ })
    if ($extra.Count -gt 0) {
        Write-Warn2 "发现未占用端口但仍在运行的项目进程：$($extra -join ', ')"
    }

    $health = Get-HealthSnapshot
    if ($health.Ok) {
        Write-Ok "/ready -> $($health.Status) $($health.Body)"
    } else {
        Write-Warn2 "/ready 不可用（$($health.Status)）：$($health.Body)"
    }

    $newest = Get-NewestPyFile
    if (($newest -ne $null) -and ($listeners.Count -gt 0)) {
        $proc = Get-Process -Id $listeners[0] -ErrorAction SilentlyContinue
        if ($proc -ne $null) {
            if ($proc.StartTime.ToUniversalTime() -lt $newest.LastWriteTimeUtc.AddSeconds(-2)) {
                Write-Warn2 "进程启动早于最新代码修改（$($newest.Name) @ $($newest.LastWriteTime)）—— 当前跑的是旧代码"
            } else {
                Write-Ok "代码新鲜度正常（最新 .py: $($newest.Name) @ $($newest.LastWriteTime)）"
            }
        }
    }
    exit 0
}

# ---------- 停服务 ----------

function Stop-PidTree([int]$ProcId) {
    $info = Get-ProcInfo $ProcId
    if ($info -eq $null) { return $false }
    Write-Host "    结束 PID=$($info.Id)（$($info.Name)）" -ForegroundColor DarkGray
    if ($info.CommandLine -ne '') {
        Write-Host "      $($info.CommandLine)" -ForegroundColor DarkGray
    }
    & taskkill /PID $ProcId /T /F 2>&1 | Out-Null
    return $true
}

Write-Step "停止旧服务（端口 $Port）"

if ($KillAllPython) {
    Write-Warn2 '已启用 -KillAllPython：本机所有 python.exe 都会被结束'
}

# --reload 模式下，父进程会因为子进程退出而立刻再拉起一个。
# 所以不能只杀一轮：循环「收集 -> 杀 -> 复查」，直到端口和项目进程都干净为止。
$released = $false
$foreignPids = @()
for ($round = 1; $round -le 6; $round++) {
    $killTargets = @()
    # 占用端口的进程必须确认是 python 才动：否则可能误杀别的程序
    foreach ($procId in @(Get-ListenerPids $Port)) {
        $li = Get-ProcInfo $procId
        if (($li -ne $null) -and ($li.Name -ne 'python') -and (-not $KillAllPython)) {
            if ($foreignPids -notcontains $procId) {
                $foreignPids += $procId
                Write-Warn2 "端口 $Port 被非 python 进程占用：PID=$procId $($li.Name)，已跳过不杀"
                if ($li.CommandLine -ne '') { Write-Host "      $($li.CommandLine)" -ForegroundColor DarkGray }
            }
        } else {
            $killTargets += $procId
        }
    }
    $killTargets += @(Get-ProjectPythonPids $Port)
    if ($KillAllPython) { $killTargets += @(Get-AllPythonPids) }
    $killTargets = @($killTargets | Where-Object { $_ -gt 0 } | Sort-Object -Unique)

    if ($killTargets.Count -eq 0) {
        if ($round -eq 1) { Write-Ok '没有需要结束的进程' }
    } else {
        if ($round -gt 1) {
            Write-Host "    第 $round 轮：又发现 $($killTargets.Count) 个进程（reload 父进程重启了子进程）" -ForegroundColor DarkGray
        }
        foreach ($procId in $killTargets) { Stop-PidTree $procId | Out-Null }
    }

    # 留一点时间给可能的 respawn，再复查
    Start-Sleep -Milliseconds 400
    $leftPids = @(Get-ProjectPythonPids $Port)
    if ((Test-PortFree $Port) -and ($leftPids.Count -eq 0)) { $released = $true; break }
    if ($leftPids.Count -gt 0) {
        Write-Host "    仍在运行：$($leftPids -join ', ')" -ForegroundColor DarkGray
    }
    if ($foreignPids.Count -gt 0) { break }  # 端口被非 python 占着，再循环也没用
}

if (-not $released) {
    $still = @(Get-ListenerPids $Port)
    if ($foreignPids.Count -gt 0) {
        Write-Err2 "端口 $Port 被非 python 进程占用（PID: $($foreignPids -join ', ')），本脚本不会去杀它"
        Write-Host '  处理建议：确认那个进程是什么，关掉它，或换 -Port 用别的端口' -ForegroundColor Yellow
    } else {
        Write-Err2 "端口 $Port 仍被占用（PID: $($still -join ', ')），放弃启动以免又跑成旧进程"
        Write-Host '  处理建议：' -ForegroundColor Yellow
        Write-Host '    1) 再跑一次本脚本；或' -ForegroundColor Yellow
        Write-Host '    2) powershell -File tools\restart.ps1 -KillAllPython' -ForegroundColor Yellow
    }
    exit 1
}
Write-Ok "端口 $Port 已释放"

# ---------- 启动 ----------

Write-Step '启动服务'

$uvicornArgs = @(
    '-m', 'uvicorn', 'app.main:app',
    '--host', '0.0.0.0',
    '--port', "$Port"
)
if ($Reload) {
    $uvicornArgs += @('--reload', '--reload-dir', 'app')
    Write-Warn2 '已启用 --reload：Windows 上可能漏写文件，改完代码请用 -Check 确认生效'
}

# 先清日志，避免把上一次的输出误认成本次的
if (Test-Path $OutLog) { Remove-Item $OutLog -Force -ErrorAction SilentlyContinue }
if (Test-Path $ErrLog) { Remove-Item $ErrLog -Force -ErrorAction SilentlyContinue }

$startedAt = Get-Date
$proc = $null
try {
    $proc = Start-Process -FilePath $PythonExe `
        -ArgumentList $uvicornArgs `
        -WorkingDirectory $BackendDir `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -WindowStyle Hidden `
        -PassThru
} catch {
    Write-Err2 "启动失败：$($_.Exception.Message)"
    exit 1
}

if ($proc -eq $null) {
    Write-Err2 '启动失败：Start-Process 没有返回进程对象'
    exit 1
}

Write-Ok "已拉起 PID=$($proc.Id)"
Write-Host "     日志: $OutLog" -ForegroundColor DarkGray
Write-Host "            $ErrLog" -ForegroundColor DarkGray

if ($NoWait) {
    Write-Warn2 '已跳过就绪等待（-NoWait）'
    exit 0
}

# ---------- 等就绪 ----------

Write-Step "等待 /ready（最多 $WaitSeconds 秒）"

$ready = $false
$deadline = (Get-Date).AddSeconds($WaitSeconds)
$lastBody = ''
while ((Get-Date) -lt $deadline) {
    $proc.Refresh()
    if ($proc.HasExited) {
        Write-Err2 "进程已退出（ExitCode=$($proc.ExitCode)）"
        break
    }
    $health = Get-HealthSnapshot
    $lastBody = $health.Body
    if ($health.Ok) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}

if (-not $ready) {
    Write-Err2 '服务未能就绪'
    if ($proc.HasExited) {
        Write-Host '  --- server.err.log ---' -ForegroundColor Yellow
        if (Test-Path $ErrLog) {
            foreach ($line in @(Get-Content $ErrLog -Tail 30)) { Write-Host "  $line" -ForegroundColor DarkYellow }
        }
        Write-Host '  --- server.log ---' -ForegroundColor Yellow
        if (Test-Path $OutLog) {
            foreach ($line in @(Get-Content $OutLog -Tail 10)) { Write-Host "  $line" -ForegroundColor DarkYellow }
        }
    } else {
        Write-Warn2 "进程仍在运行但未响应 /ready，最后返回：$lastBody"
        if (Test-PortFree $Port) {
            Write-Host '  端口检查：空闲（进程可能还没开始监听）' -ForegroundColor Yellow
        } else {
            Write-Host '  端口检查：已占用' -ForegroundColor Yellow
        }
    }
    exit 1
}

$elapsed = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 1)
Write-Ok "/ready -> $lastBody（耗时 ${elapsed}s）"

# ---------- 自检：确认跑的是新代码 ----------

$newest = Get-NewestPyFile
if ($newest -ne $null) {
    $proc.Refresh()
    $procStartUtc = $proc.StartTime.ToUniversalTime()
    if ($procStartUtc -lt $newest.LastWriteTimeUtc.AddSeconds(-2)) {
        Write-Warn2 "进程启动早于最新代码修改（$($newest.FullName) @ $($newest.LastWriteTime)）"
        Write-Warn2 '请重新运行本脚本，否则页面上跑的是旧代码'
    } else {
        Write-Ok "代码新鲜度正常（最新 .py: $($newest.Name) @ $($newest.LastWriteTime)）"
    }
}

# ---------- 汇总 ----------

Write-Step '完成'
Write-Host "  管理端:  $BaseUrl"
Write-Host "  首页:    $BaseUrl/user"
Write-Host "  训练页:  $BaseUrl/train"
Write-Host "  API文档: $BaseUrl/docs"
if (-not $Reload) {
    Write-Host '  热重载已关闭：改完 .py 请重新运行本脚本；改 HTML/JS 直接刷新页面即可' -ForegroundColor DarkGray
}
Write-Host '  体检:    powershell -File tools\restart.ps1 -Check' -ForegroundColor DarkGray
exit 0
