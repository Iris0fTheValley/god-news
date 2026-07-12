[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$statePath = Join-Path $root "data\dev-processes.json"
if (-not (Test-Path -LiteralPath $statePath)) {
    Write-Host "No god-news development process state was found."
    exit 0
}

$state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
if ($state.repository_root -ne $root) {
    throw "Process state belongs to a different repository; refusing to stop it."
}
function Stop-Descendants([int]$ParentId) {
    $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $ParentId }
    foreach ($child in $children) {
        Stop-Descendants ([int]$child.ProcessId)
        Stop-Process -Id ([int]$child.ProcessId) -Force -ErrorAction SilentlyContinue
    }
}

function Stop-ProcessTree([int]$ProcessId, [DateTimeOffset]$ExpectedStart) {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) { return }
    $actualStart = [DateTimeOffset]$process.StartTime
    if ([Math]::Abs(($actualStart - $ExpectedStart).TotalSeconds) -gt 2) {
        Write-Warning "PID $ProcessId has been reused; refusing to stop an unrelated process."
        return
    }
    Stop-Descendants $ProcessId
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

Stop-ProcessTree ([int]$state.frontend_pid) ([DateTimeOffset]::Parse($state.frontend_started_at))
Stop-ProcessTree ([int]$state.backend_pid) ([DateTimeOffset]::Parse($state.backend_started_at))
Remove-Item -LiteralPath $statePath -Force
Write-Host "god-news development services stopped." -ForegroundColor Green
