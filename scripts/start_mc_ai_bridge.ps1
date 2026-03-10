param(
    [string]$LogPath,
    [switch]$Background
)

$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$baseDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
$script = Join-Path $baseDir 'app\mc_ai_bridge.py'
$config = Join-Path $baseDir 'config\bridge_config.json'
$runtimeDir = Join-Path $baseDir 'runtime'
$logsDir = Join-Path $runtimeDir 'logs'
$outLog = Join-Path $logsDir 'bridge.out.log'
$errLog = Join-Path $logsDir 'bridge.err.log'
$pidFile = Join-Path $runtimeDir 'bridge.pid'

New-Item -ItemType Directory -Force -Path $logsDir | Out-Null

function Rotate-LogFile {
    param(
        [string]$Path,
        [string]$Stamp
    )

    if (-not (Test-Path $Path)) {
        return
    }

    $item = Get-Item $Path
    if ($item.Length -le 0) {
        Remove-Item $Path -Force -ErrorAction SilentlyContinue
        return
    }

    $rotated = Join-Path $item.DirectoryName ("{0}.{1}{2}" -f $item.BaseName, $Stamp, $item.Extension)
    Move-Item $Path $rotated -Force
}

if (-not (Test-Path $python)) { throw "Python not found: $python" }
if (-not (Test-Path $script)) { throw "Bridge script not found: $script" }
if (-not (Test-Path $config)) { throw "Bridge config not found: $config" }

if (-not $LogPath) {
    $LogPath = Read-Host "Enter path to latest.log"
}
if (-not (Test-Path $LogPath)) {
    throw "Log file not found: $LogPath"
}

$args = @(
    ('"{0}"' -f $script),
    ('"{0}"' -f $LogPath),
    '--config',
    ('"{0}"' -f $config),
    '--state',
    ('"{0}"' -f (Join-Path $runtimeDir 'mc_ai_bridge_state.json'))
)

$rotationStamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Rotate-LogFile -Path $outLog -Stamp $rotationStamp
Rotate-LogFile -Path $errLog -Stamp $rotationStamp

if ($Background) {
    if (Test-Path $pidFile) {
        try {
            $existingPid = [int](Get-Content -Raw $pidFile).Trim()
            $existing = Get-Process -Id $existingPid -ErrorAction Stop
            Write-Host "Bridge already running (PID $existingPid). Stop it first if you want to restart." -ForegroundColor Yellow
            exit 0
        } catch {
            Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        }
    }

    $proc = Start-Process -FilePath $python -ArgumentList $args -WorkingDirectory $baseDir -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -WindowStyle Hidden
    Set-Content -Path $pidFile -Value $proc.Id -Encoding ascii
    Write-Host "MC AI bridge started in background." -ForegroundColor Green
    Write-Host "PID: $($proc.Id)"
    Write-Host "Out log: $outLog"
    Write-Host "Err log: $errLog"
    return
}

Write-Host "Starting MC AI bridge..." -ForegroundColor Green
Write-Host "Log: $LogPath"
Write-Host "Config: $config"
Write-Host "Out log: $outLog"
Write-Host "Err log: $errLog"
Write-Host "Press Ctrl+C to stop."
Write-Host ""

& $python @args 2>&1 | Tee-Object -FilePath $outLog -Append
