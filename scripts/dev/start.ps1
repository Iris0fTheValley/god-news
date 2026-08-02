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
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
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

function Stop-Descendants([int]$ParentId) {
    $children = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ParentProcessId -eq $ParentId }
    foreach ($child in $children) {
        Stop-Descendants ([int]$child.ProcessId)
        Stop-Process -Id ([int]$child.ProcessId) -Force -ErrorAction SilentlyContinue
    }
}

function Stop-ProcessTree([System.Diagnostics.Process]$Process) {
    if ($null -eq $Process -or $Process.HasExited) { return }
    Stop-Descendants $Process.Id
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
}

Require-Command "uv"
Require-Command "pnpm"
Require-Command "node"
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
$python = Join-Path $root ".venv\Scripts\python.exe"
$node = (Get-Command node).Source
$vite = Join-Path $root "frontend\node_modules\vite\bin\vite.js"
$viteArgument = "node_modules/vite/bin/vite.js"
$prepareFrontendAssets = Join-Path $root "frontend\scripts\build\prepare-template-lab-assets.mjs"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python environment is missing: $python"
}
if (-not (Test-Path -LiteralPath $vite)) {
    throw "Frontend Vite entry point is missing: $vite"
}
$appModule = if ($OfflineDemo) { "god_news.demo.app:app" } else { "god_news.main:app" }
$commandPath = Join-Path $stateDirectory "dev-backend-command.json"
$commandArgument = "data/dev-backend-command.json"
$restartExitCode = 75

function Start-Backend {
    $env:GOD_NEWS_RUNTIME_CONTROL_ENABLED = "true"
    $env:GOD_NEWS_RUNTIME_CONTROL_SUPERVISED = "true"
    $env:GOD_NEWS_RUNTIME_CONTROL_COMMAND_PATH = $commandPath
    return Start-Process -FilePath $python `
        -ArgumentList @(
            "scripts/dev/run_backend.py",
            "--app",
            $appModule,
            "--host",
            $ApiHost,
            "--port",
            "$ApiPort",
            "--command-path",
            $commandArgument
        ) `
        -WorkingDirectory $root `
        -NoNewWindow `
        -PassThru
}

function Start-Frontend {
    & $node $prepareFrontendAssets
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to prepare Template Lab browser assets."
    }
    return Start-Process -FilePath $node `
        -ArgumentList @($viteArgument, "--host", $UiHost, "--port", "$UiPort") `
        -WorkingDirectory (Join-Path $root "frontend") `
        -RedirectStandardOutput (Join-Path $logDirectory "frontend-$timestamp.out.log") `
        -RedirectStandardError (Join-Path $logDirectory "frontend-$timestamp.err.log") `
        -NoNewWindow `
        -PassThru
}

function Write-ProcessState(
    [System.Diagnostics.Process]$Backend,
    [System.Diagnostics.Process]$Frontend
) {
    @{
        repository_root = $root
        started_at = [DateTimeOffset]::Now.ToString("O")
        api_uri = $apiUri
        ui_uri = $uiUri
        backend_pid = $Backend.Id
        backend_started_at = ([DateTimeOffset]$Backend.StartTime).ToString("O")
        frontend_pid = $Frontend.Id
        frontend_started_at = ([DateTimeOffset]$Frontend.StartTime).ToString("O")
    } | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
}

$backend = $null
$frontend = $null
try {
    $backend = Start-Backend
    Wait-Http $apiUri 45 $backend
    $frontend = Start-Frontend
    Wait-Http $uiUri 45 $frontend
    Write-ProcessState $backend $frontend

    Write-Host ""
    Write-Host "god-news backend: $apiUri" -ForegroundColor Green
    Write-Host "god-news frontend: $uiUri" -ForegroundColor Green
    if ($OfflineDemo) { Write-Host "Mode: deterministic offline demo" -ForegroundColor Yellow }
    Write-Host "Backend logs stay in this window." -ForegroundColor Cyan
    Write-Host "Close this window or press Ctrl+C to stop god-news." -ForegroundColor Cyan
    if (-not $NoBrowser) { Start-Process $uiUri }

    while ($true) {
        $backend.WaitForExit()
        $exitCode = $backend.ExitCode
        $requestedAction = $null
        if (Test-Path -LiteralPath $commandPath) {
            try {
                $requestedAction = (
                    Get-Content -Raw -LiteralPath $commandPath |
                        ConvertFrom-Json
                ).action
            }
            catch {
                Write-Warning "Ignoring an invalid backend supervisor command."
            }
            Remove-Item -LiteralPath $commandPath -Force -ErrorAction SilentlyContinue
        }
        $restartRequested = $exitCode -eq $restartExitCode -or $requestedAction -eq "restart"
        if (-not $restartRequested) {
            if ($exitCode -ne 0) {
                Write-Warning "Backend exited with code $exitCode."
            }
            break
        }
        Write-Host ""
        Write-Host "Restart requested. Starting a fresh backend process..." -ForegroundColor Yellow
        $backend = Start-Backend
        Wait-Http $apiUri 45 $backend
        Write-ProcessState $backend $frontend
        Write-Host "Backend restarted successfully." -ForegroundColor Green
    }
}
finally {
    Stop-ProcessTree $backend
    Stop-ProcessTree $frontend
    Remove-Item -LiteralPath $commandPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
}
