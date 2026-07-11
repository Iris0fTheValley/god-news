[CmdletBinding()]
param(
    [string]$ApiHost = "127.0.0.1",
    [ValidateRange(1, 65535)][int]$ApiPort = 8000,
    [string]$UiHost = "127.0.0.1",
    [ValidateRange(1, 65535)][int]$UiPort = 5173,
    [switch]$SkipInstall,
    [switch]$OfflineDemo,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$stateDirectory = Join-Path $root "data"
$statePath = Join-Path $stateDirectory "dev-processes.json"
$logDirectory = Join-Path $root "logs\dev"

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' is not available on PATH."
    }
}

function Test-Http([string]$Uri) {
    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    }
    catch {
        return $false
    }
}

function Wait-Http([string]$Uri, [int]$Seconds, [System.Diagnostics.Process]$Process) {
    $deadline = [DateTimeOffset]::Now.AddSeconds($Seconds)
    while ([DateTimeOffset]::Now -lt $deadline) {
        if ($Process.HasExited) {
            throw "Process $($Process.Id) exited before $Uri became reachable."
        }
        if (Test-Http $Uri) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "Timed out waiting for $Uri."
}

Require-Command "uv"
Require-Command "pnpm"
Set-Location $root

$apiUri = "http://${ApiHost}:${ApiPort}/api/v1/health/live"
$uiUri = "http://${UiHost}:${UiPort}/"
if ((Test-Http $apiUri) -and (Test-Http $uiUri)) {
    Write-Host "god-news is already running at $uiUri" -ForegroundColor Green
    if (-not $NoBrowser) { Start-Process $uiUri }
    exit 0
}

if (-not $SkipInstall) {
    if (-not (Test-Path (Join-Path $root ".venv"))) {
        & uv sync --all-extras
        if ($LASTEXITCODE -ne 0) { throw "uv sync failed." }
    }
    if (-not (Test-Path (Join-Path $root "node_modules"))) {
        & pnpm install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw "pnpm install failed." }
    }
}

New-Item -ItemType Directory -Path $stateDirectory, $logDirectory -Force | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$uv = (Get-Command uv).Source
$pnpm = (Get-Command pnpm).Source
$appModule = if ($OfflineDemo) { "god_news.testing_app:app" } else { "god_news.main:app" }

$backend = Start-Process -FilePath $uv `
    -ArgumentList @("run", "uvicorn", $appModule, "--host", $ApiHost, "--port", "$ApiPort") `
    -WorkingDirectory $root `
    -RedirectStandardOutput (Join-Path $logDirectory "backend-$timestamp.out.log") `
    -RedirectStandardError (Join-Path $logDirectory "backend-$timestamp.err.log") `
    -WindowStyle Hidden -PassThru

try {
    Wait-Http $apiUri 45 $backend
    $frontend = Start-Process -FilePath $pnpm `
        -ArgumentList @("--filter", "@god-news/frontend", "dev", "--", "--host", $UiHost, "--port", "$UiPort") `
        -WorkingDirectory $root `
        -RedirectStandardOutput (Join-Path $logDirectory "frontend-$timestamp.out.log") `
        -RedirectStandardError (Join-Path $logDirectory "frontend-$timestamp.err.log") `
        -WindowStyle Hidden -PassThru
    Wait-Http $uiUri 45 $frontend
}
catch {
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
    throw
}

@{
    repository_root = $root
    started_at = [DateTimeOffset]::Now.ToString("O")
    api_uri = $apiUri
    ui_uri = $uiUri
    backend_pid = $backend.Id
    backend_started_at = ([DateTimeOffset]$backend.StartTime).ToString("O")
    frontend_pid = $frontend.Id
    frontend_started_at = ([DateTimeOffset]$frontend.StartTime).ToString("O")
} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8

Write-Host "god-news backend: $apiUri" -ForegroundColor Green
Write-Host "god-news frontend: $uiUri" -ForegroundColor Green
if ($OfflineDemo) { Write-Host "Mode: deterministic offline demo" -ForegroundColor Yellow }
Write-Host "Stop with: .\scripts\stop.ps1"
if (-not $NoBrowser) { Start-Process $uiUri }
