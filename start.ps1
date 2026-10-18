$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$port = 8766
if ($env:LHT_PORT) { $port = [int]$env:LHT_PORT }
$pauseFile = Join-Path (Join-Path $projectRoot 'data') 'watchdog.off'

# 解除守护待机（如果之前用 stop.ps1 停过服务）
if (Test-Path $pauseFile) {
    Remove-Item $pauseFile -Force
    Write-Host '已解除守护待机，服务会持续被守护。' -ForegroundColor DarkGray
}

$python = Get-Command py -ErrorAction SilentlyContinue
$pythonArgs = @()
if ($python) {
    $pythonArgs = @('-3', 'server.py')
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { throw '未找到 Python 3。请安装 Python 3 后重试。' }
    $pythonArgs = @('server.py')
}

Write-Host '龙回头 · 五层立体短线交易系统' -ForegroundColor Cyan
Write-Host ('启动地址 : http://127.0.0.1:{0}' -f $port)
Write-Host '按 Ctrl+C 停止当前窗口的服务'
Write-Host '（若守护进程在跑，Ctrl+C 后它会自动在后台把服务拉起来；' -ForegroundColor DarkGray
Write-Host '  想彻底停掉请用 stop.ps1）' -ForegroundColor DarkGray
Write-Host ''

Start-Job { Start-Sleep -Seconds 2; Start-Process ("http://127.0.0.1:{0}" -f $using:port) } | Out-Null

Push-Location $projectRoot
try {
    & $python.Source @pythonArgs
} finally {
    Pop-Location
}
