# 龙回头 · 停止网站服务
#
# 注意：如果装了守护进程（task.ps1 -Action watchdog-install），
# 直接杀进程是没用的 —— 守护会在 10 秒内把它重新拉起来。
# 所以这里会先让守护「待机」，再停服务；用 start.ps1 启动时会自动解除待机。
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 8766
if ($env:LHT_PORT) { $port = [int]$env:LHT_PORT }
$pauseFile = Join-Path (Join-Path $projectRoot 'data') 'watchdog.off'

# 1) 让守护待机
$wd = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'python*' -and "$($_.CommandLine)" -like '*watchdog.py*' -and
                       "$($_.CommandLine)" -notlike '*--status*' })
if ($wd.Count -gt 0) {
    $dir = Split-Path $pauseFile -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    New-Item -ItemType File -Path $pauseFile -Force | Out-Null
    Write-Host ('守护进程 {0} 个已进入待机（不会再把服务拉起来）。' -f $wd.Count) -ForegroundColor DarkGray
} else {
    Write-Host '未检测到守护进程，跳过待机。' -ForegroundColor DarkGray
}

# 2) 停服务
$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $conns) {
    Write-Host ('端口 {0} 上没有正在运行的服务。' -f $port) -ForegroundColor Yellow
} else {
    foreach ($c in $conns) {
        $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host ('停止 {0} (PID {1})' -f $proc.ProcessName, $proc.Id) -ForegroundColor Yellow
            Stop-Process -Id $proc.Id -Force
        }
    }
    Write-Host '已停止。' -ForegroundColor Green
}

if ($wd.Count -gt 0) {
    Write-Host ''
    Write-Host '提示：守护现在处于待机状态，网站不会自动重启。' -ForegroundColor DarkGray
    Write-Host ('      恢复：powershell -File start.ps1' ) -ForegroundColor DarkGray
    Write-Host '            或 powershell -File task.ps1 -Action watchdog-resume' -ForegroundColor DarkGray
}
