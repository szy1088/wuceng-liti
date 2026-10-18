<#
  龙回头 · 定时任务 / 开机自启

  两种方式，按需要选：

  【A】开机自启（推荐，不需要管理员）
       把一个快捷方式放进「启动」文件夹，登录后自动在后台跑 server.py。
       网站自带定时推送（策略参数 → 微信推送 → 交易日自动推送时刻），
       所以只要服务开着，到点就会扫描并推送。

  【B】独立定时任务（需要管理员 / UAC）
       用 Windows 任务计划程序，每周一至周五定点跑一次
       「龙回头扫描 → 推送微信」，不依赖网站是否开着。
       脚本内部还会再校验一次「今天是否真的是交易日」，节假日不会误推。

  用法：
     powershell -ExecutionPolicy Bypass -File task.ps1 -Action status
     powershell -ExecutionPolicy Bypass -File task.ps1 -Action autostart-install
     powershell -ExecutionPolicy Bypass -File task.ps1 -Action autostart-uninstall
     powershell -ExecutionPolicy Bypass -File task.ps1 -Action install -At 15:05
     powershell -ExecutionPolicy Bypass -File task.ps1 -Action uninstall
     powershell -ExecutionPolicy Bypass -File task.ps1 -Action run
#>
param(
    [ValidateSet('status', 'install', 'uninstall', 'run',
                 'autostart-install', 'autostart-uninstall',
                 'server-autostart-install',
                 'watchdog-install', 'watchdog-uninstall', 'watchdog-status',
                 'watchdog-pause', 'watchdog-resume')]
    [string]$Action = 'status',

    [string]$At = '15:05',
    [int]$MinScore = 65,
    [int]$Top = 8,
    [string]$TaskName = 'LongHuitou-WeChatPush'
)

# 原生命令（schtasks）往 stderr 写东西时，不要当成终止性错误
$ErrorActionPreference = 'Continue'
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pushScript = Join-Path $root 'scan_push.py'
$serverScript = Join-Path $root 'server.py'
$watchdogScript = Join-Path $root 'watchdog.py'
$logDir = Join-Path $root 'logs'
$pauseFile = Join-Path (Join-Path $root 'data') 'watchdog.off'
$wdPidFile = Join-Path (Join-Path $root 'data') 'watchdog.pid'
$shortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'LongHuitou.lnk'
$wdShortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'LongHuitouWatchdog.lnk'

function Test-Elevated {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-Python {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $real = ''
        try {
            $real = (& $py.Source -3 -c "import sys; print(sys.executable)" 2>$null |
                     Select-Object -First 1)
        } catch { $real = '' }
        return @{ Exe = $py.Source; Prefix = @('-3'); Real = "$real".Trim() }
    }
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) {
        return @{ Exe = $py.Source; Prefix = @(); Real = $py.Source }
    }
    throw '未找到 Python 3。请先安装 Python 3 并加入 PATH。'
}

function Get-PythonW {
    <# 优先返回 pythonw.exe（后台运行不弹黑窗口），没有就退回 python/py #>
    $py = Get-Python
    if ($py.Real) {
        $cand = Join-Path (Split-Path $py.Real) 'pythonw.exe'
        if (Test-Path $cand) { return @{ Exe = $cand; Prefix = @() } }
    }
    return @{ Exe = $py.Exe; Prefix = $py.Prefix }
}

function Test-Healthy([int]$Port) {
    try {
        $r = Invoke-WebRequest ("http://127.0.0.1:{0}/api/ping" -f $Port) `
             -UseBasicParsing -TimeoutSec 5
        return ($r.StatusCode -eq 200 -and $r.Content -match 'longhuitou')
    } catch { return $false }
}

function Get-WatchdogPids {
    <# 找出所有正在跑 watchdog.py 的 python 进程（主守护 + 保镖） #>
    $out = @()
    try {
        $procs = Get-CimInstance Win32_Process -ErrorAction Stop |
                 Where-Object { $_.Name -like 'python*' }
    } catch { return $out }
    foreach ($p in $procs) {
        $cmd = "$($p.CommandLine)"
        if ($cmd -like '*watchdog.py*' -and $cmd -notlike '*--status*') {
            $out += [int]$p.ProcessId
        }
    }
    return $out
}

function Get-PrimaryPid {
    <# 从 data\watchdog.pid 读出主守护 PID，并确认它真的还在 #>
    $f = Join-Path (Join-Path $root 'data') 'watchdog.pid'
    if (-not (Test-Path $f)) { return 0 }
    $raw = (Get-Content $f -Raw -ErrorAction SilentlyContinue)
    $v = 0
    if (-not [int]::TryParse("$raw".Trim(), [ref]$v)) { return 0 }
    if (Get-Process -Id $v -ErrorAction SilentlyContinue) { return $v }
    return 0
}

function Get-GuardPid {
    $f = Join-Path (Join-Path $root 'data') 'watchdog.guard.pid'
    if (-not (Test-Path $f)) { return 0 }
    $raw = (Get-Content $f -Raw -ErrorAction SilentlyContinue)
    $v = 0
    if (-not [int]::TryParse("$raw".Trim(), [ref]$v)) { return 0 }
    if (Get-Process -Id $v -ErrorAction SilentlyContinue) { return $v }
    return 0
}

function Invoke-Elevated([string[]]$ExtraArgs) {
    $exe = (Get-Process -Id $PID).Path
    if (-not $exe) { $exe = 'powershell.exe' }
    $all = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $PSCommandPath) + $ExtraArgs
    Write-Host '需要管理员权限，正在请求提升（会弹出 UAC 确认框）…' -ForegroundColor Yellow
    Start-Process -FilePath $exe -Verb RunAs -Wait -ArgumentList $all
}

function Invoke-Schtasks([string[]]$SchtasksArgs) {
    $out = & schtasks @SchtasksArgs 2>&1 | Out-String
    return @{ Ok = ($LASTEXITCODE -eq 0); Text = ($out -split "`r?`n") }
}

switch ($Action) {

    # ---------------- 守护常驻（无需管理员，推荐） ----------------
    'watchdog-install' {
        if (-not (Test-Path $watchdogScript)) { throw "找不到 watchdog.py：$watchdogScript" }
        $pyw = Get-PythonW

        # 1) 「启动」文件夹快捷方式：登录后自动拉起守护
        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut($wdShortcutPath)
        $lnk.TargetPath = $pyw.Exe
        $lnk.Arguments = '"{0}"' -f $watchdogScript
        $lnk.WorkingDirectory = $root
        $lnk.WindowStyle = 7
        $lnk.Description = '龙回头 · 服务守护进程'
        $lnk.Save()
        Write-Host '① 启动文件夹快捷方式：已创建' -ForegroundColor Green
        Write-Host ('   {0}' -f $wdShortcutPath) -ForegroundColor DarkGray

        # 2) HKCU 的 Run 注册表项：第二条独立保险，守护自己也会定期自检补写
        $r = & $pyw.Exe @($pyw.Prefix) $watchdogScript --ensure-autostart 2>&1 | Out-String
        Write-Host ('② 注册表自启项：{0}' -f "$r".Trim()) -ForegroundColor Green

        # 3) 立刻把「主守护 + 保镖」跑起来
        if ((Get-PrimaryPid) -gt 0) {
            Write-Host ('③ 主守护已在运行（PID {0}）' -f (Get-PrimaryPid)) -ForegroundColor Green
        } else {
            Start-Process -FilePath $pyw.Exe -ArgumentList ('"{0}"' -f $watchdogScript) `
                          -WorkingDirectory $root -WindowStyle Hidden
            Start-Sleep -Seconds 5
            if ((Get-PrimaryPid) -gt 0) {
                Write-Host ('③ 主守护已启动（PID {0}）' -f (Get-PrimaryPid)) -ForegroundColor Green
            } else {
                Write-Host '③ 主守护似乎没起来，请看 logs\watchdog.log' -ForegroundColor Yellow
            }
        }
        Start-Sleep -Seconds 3
        if ((Get-GuardPid) -gt 0) {
            Write-Host ('④ 保镖已启动（PID {0}）—— 主守护被杀也会被它拉回来' -f (Get-GuardPid)) -ForegroundColor Green
        } else {
            Write-Host '④ 保镖尚未出现，主守护会在下一轮补拉起（最多 5 秒）' -ForegroundColor DarkGray
        }

        Write-Host ''
        Write-Host '守护已就位：' -ForegroundColor Cyan
        Write-Host '  · 主守护每 5 秒探活 http://127.0.0.1:8766/api/ping，' -ForegroundColor Cyan
        Write-Host '    连续 2 次失败就清理僵死进程并重新拉起 server.py；' -ForegroundColor Cyan
        Write-Host '  · 保镖看住主守护，谁死了另一个负责拉回来；' -ForegroundColor Cyan
        Write-Host '  · 两层开机自启（启动文件夹 + 注册表 Run），被删了会自动补写。' -ForegroundColor Cyan
        Write-Host '  查看状态：powershell -ExecutionPolicy Bypass -File task.ps1 -Action watchdog-status'
        Write-Host '  查看日志：logs\watchdog.log  ·  服务日志：logs\server.log'
        Write-Host '  临时停护：powershell -ExecutionPolicy Bypass -File task.ps1 -Action watchdog-pause'
    }

    'watchdog-uninstall' {
        if (Test-Path $wdShortcutPath) {
            Remove-Item $wdShortcutPath -Force
            Write-Host '已删除「启动」文件夹快捷方式。' -ForegroundColor Green
        } else {
            Write-Host '「启动」文件夹里本来就没有。' -ForegroundColor Yellow
        }

        $pyw = Get-PythonW
        $r = & $pyw.Exe @($pyw.Prefix) $watchdogScript --remove-autostart 2>&1 | Out-String
        Write-Host ('注册表自启项：{0}' -f "$r".Trim())

        # 主守护 + 保镖一起停掉
        $pids = Get-WatchdogPids
        if ($pids.Count -gt 0) {
            foreach ($p in $pids) {
                Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
            }
            Write-Host ('已停止守护进程 {0} 个（PID {1}）。' -f $pids.Count, ($pids -join ', ')) -ForegroundColor Green
        } else {
            Write-Host '守护进程本来就不在跑。' -ForegroundColor Yellow
        }
        Remove-Item $wdPidFile -Force -ErrorAction SilentlyContinue
        Remove-Item (Join-Path (Split-Path $wdPidFile -Parent) 'watchdog.guard.pid') -Force -ErrorAction SilentlyContinue
        Write-Host '注意：这只会拆掉守护，不会停掉网站服务本身。' -ForegroundColor DarkGray
        Write-Host '      要停网站：powershell -File stop.ps1' -ForegroundColor DarkGray
    }

    'watchdog-status' {
        $port = 8766
        if ($env:LHT_PORT) { $port = [int]$env:LHT_PORT }

        Write-Host '=== 守护进程 ===' -ForegroundColor Cyan
        $pp = Get-PrimaryPid
        $gp = Get-GuardPid
        if ($pp -gt 0) {
            Write-Host ('  主守护（看服务）  ：运行中 PID {0}' -f $pp) -ForegroundColor Green
        } else {
            Write-Host '  主守护（看服务）  ：未运行' -ForegroundColor Yellow
        }
        if ($gp -gt 0) {
            Write-Host ('  保镖（看主守护）  ：运行中 PID {0}' -f $gp) -ForegroundColor Green
        } else {
            Write-Host '  保镖（看主守护）  ：未运行' -ForegroundColor Yellow
        }
        if (($pp -le 0) -and ($gp -le 0)) {
            Write-Host '  安装：powershell -ExecutionPolicy Bypass -File task.ps1 -Action watchdog-install' -ForegroundColor DarkGray
        }

        Write-Host ''
        Write-Host '=== 网站服务 ===' -ForegroundColor Cyan
        if (Test-Healthy $port) {
            Write-Host ('  健康：http://127.0.0.1:{0}/api/ping 正常响应' -f $port) -ForegroundColor Green
        } else {
            Write-Host ('  不健康：/api/ping 无响应（守护约 10 秒内会拉起）' -f $port) -ForegroundColor Yellow
        }

        Write-Host ''
        Write-Host '=== 自启项 ===' -ForegroundColor Cyan
        if (Test-Path $wdShortcutPath) {
            Write-Host '  启动文件夹  ：已设置' -ForegroundColor Green
        } else {
            Write-Host '  启动文件夹  ：未设置' -ForegroundColor Yellow
        }
        $runVal = ''
        try {
            $runVal = (Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' `
                       -Name 'LongHuitouWatchdog' -ErrorAction Stop).LongHuitouWatchdog
        } catch { $runVal = '' }
        if ($runVal) {
            Write-Host '  注册表 Run   ：已设置' -ForegroundColor Green
            Write-Host ('    {0}' -f $runVal) -ForegroundColor DarkGray
        } else {
            Write-Host '  注册表 Run   ：未设置' -ForegroundColor Yellow
        }

        Write-Host ''
        Write-Host '=== 待机开关 ===' -ForegroundColor Cyan
        if (Test-Path $pauseFile) {
            Write-Host '  已待机（data\watchdog.off 存在），不会自动拉起服务' -ForegroundColor Yellow
        } else {
            Write-Host '  正常守护中' -ForegroundColor Green
        }

        Write-Host ''
        Write-Host '=== 云端保活 ===' -ForegroundColor Cyan
        $kaFile = Join-Path (Join-Path $root 'data') 'keepalive.json'
        $kaState = Join-Path (Join-Path $root 'data') 'keepalive.state'
        $ka = $null
        if (Test-Path $kaFile) {
            # 用 ReadAllText 而不是 Get-Content：它会自动识别并剥掉 BOM。
            # 用户用 PowerShell / 记事本保存这个文件时很容易带上 BOM，
            # 而带 BOM 的 JSON 用普通 utf-8 解析会直接失败（这个坑已经踩过一次）。
            try { $ka = [System.IO.File]::ReadAllText($kaFile) | ConvertFrom-Json } catch { $ka = $null }
        }
        if ((-not $ka) -or (-not $ka.enabled)) {
            Write-Host '  未启用（没有 data\keepalive.json，或 enabled 不是 true）' -ForegroundColor DarkGray
            Write-Host '  提示：复制 keepalive.example.json 到 data\keepalive.json 即可开启' -ForegroundColor DarkGray
        } else {
            Write-Host ('  目标：{0}' -f $ka.url) -ForegroundColor Green
            $kaMins = [math]::Round(([double]$ka.interval_seconds) / 60, 0)
            $kaWd = ''
            if ($ka.weekdays_only) { $kaWd = '（仅工作日）' }
            Write-Host ('  频率：每 {0} 分钟一次{1}' -f $kaMins, $kaWd)
            Write-Host ('  时段：{0}' -f (($ka.windows) -join '、'))
            Write-Host '  作用：交易时段定时唤醒，避免你打开时正好赶上约 1 分钟的冷启动' -ForegroundColor DarkGray
            if (Test-Path $kaState) {
                try {
                    $st = [System.IO.File]::ReadAllText($kaState) | ConvertFrom-Json
                    $epoch = [datetime]::SpecifyKind([datetime]'1970-01-01', [DateTimeKind]::Utc)
                    $when = $epoch.ToLocalTime().AddSeconds([double]$st.at).ToString('MM-dd HH:mm')
                    if ($st.ok) {
                        Write-Host ('  最近：成功 {0}（{1}）' -f $st.detail, $when) -ForegroundColor Green
                    } else {
                        Write-Host ('  最近：失败 {0}（{1}）' -f $st.detail, $when) -ForegroundColor Yellow
                    }
                } catch {
                    Write-Host '  最近：状态文件无法解析' -ForegroundColor DarkGray
                }
            } else {
                Write-Host '  最近：还没执行过（守护会在进入时段后自动开始）' -ForegroundColor DarkGray
            }
        }

        Write-Host ''
        Write-Host '=== 守护日志（最后 12 行） ===' -ForegroundColor Cyan
        $wdLog = Join-Path $logDir 'watchdog.log'
        if (Test-Path $wdLog) {
            Get-Content $wdLog -Tail 12 -Encoding UTF8 | ForEach-Object { Write-Host ('  ' + $_) }
        } else {
            Write-Host '  暂无日志。' -ForegroundColor DarkGray
        }
    }

    'watchdog-pause' {
        $dir = Split-Path $pauseFile -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
        New-Item -ItemType File -Path $pauseFile -Force | Out-Null
        Write-Host '守护已进入待机：不会再自动拉起 server.py。' -ForegroundColor Yellow
        Write-Host '恢复：powershell -ExecutionPolicy Bypass -File task.ps1 -Action watchdog-resume'
    }

    'watchdog-resume' {
        if (Test-Path $pauseFile) {
            Remove-Item $pauseFile -Force
            Write-Host '守护已恢复，会继续保证服务在线。' -ForegroundColor Green
        } else {
            Write-Host '守护本来就没有待机。' -ForegroundColor Yellow
        }
    }

    # ---------------- 兼容旧名字：现在指向守护安装（能力更强） ----------------
    'autostart-install' {
        Write-Host '（autostart-install 现在会安装守护进程，比原来更稳）' -ForegroundColor DarkGray
        & $PSCommandPath -Action 'watchdog-install'
    }

    # ---------------- 只做开机自启（没有守护，进程被杀不会自动拉起） ----------------
    'server-autostart-install' {
        if (-not (Test-Path $serverScript)) { throw "找不到 server.py：$serverScript" }
        $py = Get-Python

        # 优先用 pythonw.exe：后台运行，不会弹黑窗口
        $pyw = ''
        if ($py.Real) {
            $cand = Join-Path (Split-Path $py.Real) 'pythonw.exe'
            if (Test-Path $cand) { $pyw = $cand }
        }
        if ((-not $pyw) -and (Test-Path $py.Real)) { $pyw = '' }

        if ($pyw) {
            $exe = $pyw
            $argsText = '"{0}"' -f $serverScript
        } else {
            # 退而求其次：py 启动器 + 最小化窗口
            $exe = $py.Exe
            $argsText = (($py.Prefix + @("`"$serverScript`"")) -join ' ')
        }

        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut($shortcutPath)
        $lnk.TargetPath = $exe
        $lnk.Arguments = $argsText
        $lnk.WorkingDirectory = $root
        $lnk.WindowStyle = 7                      # 最小化
        $lnk.Description = '龙回头 · 五层立体短线交易系统（后台服务）'
        $lnk.Save()

        Write-Host '已加入开机自启。' -ForegroundColor Green
        Write-Host ('  快捷方式：{0}' -f $shortcutPath)
        Write-Host ('  目标    ：{0} {1}' -f $exe, $argsText) -ForegroundColor DarkGray
        Write-Host '  下次登录后会自动在后台启动，网站内的定时推送随之生效。'
    }

    'autostart-uninstall' {
        $hit = $false
        foreach ($p in @($shortcutPath, $wdShortcutPath)) {
            if (Test-Path $p) {
                Remove-Item $p -Force
                Write-Host ('已删除：{0}' -f (Split-Path $p -Leaf)) -ForegroundColor Green
                $hit = $true
            }
        }
        $pids = Get-WatchdogPids
        if ($pids.Count -gt 0) {
            foreach ($p in $pids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
            Write-Host ('已停止守护进程 {0} 个（PID {1}）。' -f $pids.Count, ($pids -join ', ')) -ForegroundColor Green
            $hit = $true
        }
        Remove-Item $wdPidFile -Force -ErrorAction SilentlyContinue
        Remove-Item (Join-Path (Split-Path $wdPidFile -Parent) 'watchdog.guard.pid') -Force -ErrorAction SilentlyContinue
        if (-not $hit) { Write-Host '开机自启本来就没有设置。' -ForegroundColor Yellow }
    }

    # ---------------- 独立定时任务（需要管理员） ----------------
    'install' {
        if (-not (Test-Path $pushScript)) { throw "找不到 scan_push.py：$pushScript" }

        if (-not (Test-Elevated)) {
            Invoke-Elevated @('-Action', 'install', '-At', $At, '-MinScore', "$MinScore",
                              '-Top', "$Top", '-TaskName', $TaskName)
            Write-Host '提升后的窗口已结束；若未成功，可改用免管理员的：' -ForegroundColor DarkGray
            Write-Host '  powershell -File task.ps1 -Action autostart-install' -ForegroundColor DarkGray
            return
        }

        $py = Get-Python
        $argLine = '"{0}" {1} "{2}" --min-score {3} --top {4} --quiet' -f `
            $py.Exe, ($py.Prefix -join ' '), $pushScript, $MinScore, $Top

        $r = Invoke-Schtasks @('/Create', '/F', '/TN', "$TaskName", '/TR', "$argLine",
                               '/SC', 'WEEKLY', '/D', 'MON,TUE,WED,THU,FRI', '/ST', $At)
        if ($r.Ok) {
            Write-Host ('已注册定时任务：{0}' -f $TaskName) -ForegroundColor Green
            Write-Host ('  触发：每周一至周五 {0}（脚本内再校验交易日，节假日跳过）' -f $At)
            Write-Host ('  命令：{0}' -f $argLine) -ForegroundColor DarkGray
            Write-Host ''
            Write-Host '  立即跑一次：powershell -File task.ps1 -Action run'
            Write-Host '  查看状态  ：powershell -File task.ps1 -Action status'
        } else {
            Write-Host '注册失败：' -ForegroundColor Red
            $r.Text | Where-Object { $_.Trim() } | ForEach-Object { Write-Host ('  ' + $_.Trim()) }
        }
    }

    'uninstall' {
        $q = Invoke-Schtasks @('/Query', '/TN', "$TaskName")
        if (-not $q.Ok) {
            Write-Host ('任务 {0} 不存在。' -f $TaskName) -ForegroundColor Yellow
            return
        }
        if (-not (Test-Elevated)) {
            Invoke-Elevated @('-Action', 'uninstall', '-TaskName', $TaskName)
            return
        }
        $r = Invoke-Schtasks @('/Delete', '/F', '/TN', "$TaskName")
        if ($r.Ok) {
            Write-Host ('已删除定时任务：{0}' -f $TaskName) -ForegroundColor Green
        } else {
            Write-Host '删除失败：' -ForegroundColor Red
            $r.Text | Where-Object { $_.Trim() } | ForEach-Object { Write-Host ('  ' + $_.Trim()) }
        }
    }

    'status' {
        $port = 8766
        if ($env:LHT_PORT) { $port = [int]$env:LHT_PORT }

        Write-Host '=== 守护进程（保证网站随时可用） ===' -ForegroundColor Cyan
        $pp = Get-PrimaryPid
        $gp = Get-GuardPid
        if ($pp -gt 0) {
            Write-Host ('  主守护  ：运行中 PID {0}' -f $pp) -ForegroundColor Green
        } else {
            Write-Host '  主守护  ：未运行' -ForegroundColor Yellow
        }
        if ($gp -gt 0) {
            Write-Host ('  保镖    ：运行中 PID {0}' -f $gp) -ForegroundColor Green
        } else {
            Write-Host '  保镖    ：未运行' -ForegroundColor Yellow
        }
        if (($pp -le 0) -and ($gp -le 0)) {
            Write-Host '  安装：powershell -File task.ps1 -Action watchdog-install' -ForegroundColor DarkGray
        }

        Write-Host ''
        Write-Host '=== 网站服务 ===' -ForegroundColor Cyan
        if (Test-Healthy $port) {
            Write-Host ('  健康：http://127.0.0.1:{0}/api/ping 正常响应' -f $port) -ForegroundColor Green
        } else {
            $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($conns) {
                Write-Host ('  端口 {0} 被 PID {1} 占着，但 /api/ping 不健康' -f $port, $conns[0].OwningProcess) -ForegroundColor Yellow
            } else {
                Write-Host ('  未运行（端口 {0}）' -f $port) -ForegroundColor Yellow
                Write-Host '  手动启动：powershell -File start.ps1' -ForegroundColor DarkGray
            }
        }

        Write-Host ''
        Write-Host '=== 开机自启 ===' -ForegroundColor Cyan
        if (Test-Path $wdShortcutPath) {
            Write-Host '  启动文件夹（守护）：已设置' -ForegroundColor Green
        } else {
            Write-Host '  启动文件夹（守护）：未设置' -ForegroundColor Yellow
        }
        if (Test-Path $shortcutPath) {
            Write-Host '  启动文件夹（仅服务）：已设置' -ForegroundColor DarkGray
        }
        $runVal = ''
        try {
            $runVal = (Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' `
                       -Name 'LongHuitouWatchdog' -ErrorAction Stop).LongHuitouWatchdog
        } catch { $runVal = '' }
        if ($runVal) {
            Write-Host '  注册表 Run（守护） ：已设置' -ForegroundColor Green
        } else {
            Write-Host '  注册表 Run（守护） ：未设置' -ForegroundColor Yellow
        }
        if ((-not (Test-Path $wdShortcutPath)) -and (-not $runVal)) {
            Write-Host '  设置：powershell -File task.ps1 -Action watchdog-install' -ForegroundColor DarkGray
        }

        Write-Host ''
        Write-Host '=== 定时任务 ===' -ForegroundColor Cyan
        $q = Invoke-Schtasks @('/Query', '/TN', "$TaskName", '/FO', 'LIST', '/V')
        if ($q.Ok) {
            $q.Text | Where-Object {
                $_ -match 'TaskName|任务名|Next Run|下次运行|Status|状态|Task To Run|要运行的任务|Start Time|开始时间|Last Run|上次运行'
            } | ForEach-Object { Write-Host ('  ' + $_.Trim()) }
        } else {
            Write-Host ('  未注册（{0}）' -f $TaskName) -ForegroundColor Yellow
            Write-Host '  注册：powershell -File task.ps1 -Action install' -ForegroundColor DarkGray
        }
    }

    'run' {
        if (-not (Test-Path $pushScript)) { throw "找不到 scan_push.py：$pushScript" }
        $py = Get-Python
        Write-Host '立刻执行一次扫描并推送…' -ForegroundColor Cyan
        & $py.Exe @($py.Prefix) $pushScript --min-score $MinScore --top $Top
        Write-Host ('退出码：{0}' -f $LASTEXITCODE) -ForegroundColor DarkGray
    }
}
