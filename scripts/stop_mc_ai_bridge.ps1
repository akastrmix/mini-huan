$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$baseDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pidFile = Join-Path $baseDir 'runtime\bridge.pid'

if (-not (Test-Path $pidFile)) {
    Write-Host 'Bridge is not running (no pid file found).'
    exit 0
}

$bridgePid = [int](Get-Content -Raw $pidFile).Trim()
try {
    Stop-Process -Id $bridgePid -Force -ErrorAction Stop
    Write-Host "Stopped bridge process $bridgePid"
} catch {
    Write-Host "Bridge pid file existed, but process $bridgePid was not running."
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
