param(
    [Parameter(Mandatory = $true)]
    [string]$EventJsonFile,

    [string]$SessionId,

    [string]$AgentId = 'mc-helper',

    [int]$MaxReplyChars = 80,

    [int]$TimeoutSeconds = 90
)

$ErrorActionPreference = 'Stop'
$baseDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$configPath = Join-Path $baseDir 'config\bridge_config.json'
$promptPath = Join-Path $baseDir 'config\reply_prompt.txt'

$event = Get-Content -Raw -Encoding UTF8 $EventJsonFile | ConvertFrom-Json
$messageText = [string]$event.message
if ($messageText.StartsWith('test', [System.StringComparison]::OrdinalIgnoreCase)) {
    $messageText = $messageText.Substring(4).Trim()
}
if (-not $messageText) {
    $messageText = 'hello'
}

$config = $null
if (Test-Path $configPath) {
    $config = Get-Content -Raw -Encoding UTF8 $configPath | ConvertFrom-Json
}
$botStyle = $config.botStyle
$promptText = ((Get-Content -Raw -Encoding UTF8 $promptPath) -replace "`r?`n", ' ' -replace '\s+', ' ').Trim()

$payload = @{
    player = [string]$event.player
    message = $messageText
    max_reply_chars = $MaxReplyChars
    style = $botStyle
} | ConvertTo-Json -Compress -Depth 6

$prompt = $promptText.TrimEnd() + ' TASK=' + $payload

$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:LC_ALL = 'C.UTF-8'
$env:LANG = 'C.UTF-8'

$helperPy = Join-Path $baseDir 'scripts\invoke_mc_helper.py'
$tmpPrompt = [System.IO.Path]::GetTempFileName()
$tmpParsed = [System.IO.Path]::GetTempFileName()
try {
    Set-Content -Path $tmpPrompt -Value $prompt -Encoding UTF8
    & "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe" $helperPy $AgentId $TimeoutSeconds $tmpPrompt $tmpParsed
    $parsed = Get-Content -Raw -Encoding UTF8 $tmpParsed
}
finally {
    Remove-Item $tmpPrompt -Force -ErrorAction SilentlyContinue
    Remove-Item $tmpParsed -Force -ErrorAction SilentlyContinue
}

$parsed
