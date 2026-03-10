$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$baseDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$runtimeDir = Join-Path $baseDir 'runtime'
$pidFile = Join-Path $runtimeDir 'bridge.pid'
$logsDir = Join-Path $runtimeDir 'logs'
$outLog = Join-Path $logsDir 'bridge.out.log'
$errLog = Join-Path $logsDir 'bridge.err.log'

if (Test-Path $pidFile) {
    $bridgePid = [int](Get-Content -Raw $pidFile).Trim()
    try {
        $proc = Get-Process -Id $bridgePid -ErrorAction Stop
        Write-Host "Bridge status: RUNNING"
        Write-Host "PID: $bridgePid"
        Write-Host "Started: $($proc.StartTime)"
    } catch {
        Write-Host "Bridge status: STALE PID FILE"
        Write-Host "PID file points to missing process: $bridgePid"
    }
} else {
    Write-Host 'Bridge status: STOPPED'
}

Write-Host "Out log: $outLog"
Write-Host "Err log: $errLog"

if (Test-Path $outLog) {
    Write-Host ''
    Write-Host 'Last output lines:'
    Get-Content $outLog -Tail 10 -Encoding utf8
}

if (Test-Path $errLog) {
    Write-Host ''
    Write-Host 'Last error lines:'
    Get-Content $errLog -Tail 10 -Encoding utf8
}
