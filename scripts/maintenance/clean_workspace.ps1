[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

# Only ignored, reproducible state is in scope. Runtime databases, model caches,
# production outputs, virtual environments, and package installations are
# intentionally excluded.
$targets = @(
    ".coverage",
    ".coverage.*",
    "htmlcov",
    "coverage",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "scripts",
    "src",
    "tests",
    "frontend/public/template-lab",
    "frontend/dist",
    "frontend/playwright-report",
    "frontend/test-results",
    "frontend/coverage",
    "video/build",
    "video/dist",
    "video/coverage"
)

if ($PSCmdlet.ShouldProcess($root, "remove ignored caches, test reports, staged demo assets, and logs")) {
    & git -C $root clean -fdX -- @targets
    if ($LASTEXITCODE -ne 0) {
        throw "Git failed to clean reproducible workspace state."
    }

    # Active development services keep their current log files open on Windows.
    # Clean logs one file at a time so an expected lock does not turn successful
    # cache cleanup into a false failure. Locked files remain ignored and will be
    # removed by the next run after the owning process exits.
    $logsRoot = Join-Path $root "logs"
    if (Test-Path -LiteralPath $logsRoot) {
        $resolvedLogsRoot = (Resolve-Path -LiteralPath $logsRoot).Path
        $rootPrefix = $root.TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        ) + [System.IO.Path]::DirectorySeparatorChar
        if (-not $resolvedLogsRoot.StartsWith(
            $rootPrefix,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Refusing to clean logs outside the repository root: $resolvedLogsRoot"
        }

        $lockedLogs = [System.Collections.Generic.List[string]]::new()
        Get-ChildItem -LiteralPath $resolvedLogsRoot -Recurse -File -Force |
            ForEach-Object {
                try {
                    Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
                }
                catch [System.IO.IOException] {
                    $lockedLogs.Add($_.FullName)
                }
                catch [System.UnauthorizedAccessException] {
                    $lockedLogs.Add($_.FullName)
                }
            }

        Get-ChildItem -LiteralPath $resolvedLogsRoot -Recurse -Directory -Force |
            Sort-Object { $_.FullName.Length } -Descending |
            ForEach-Object {
                if ((Get-ChildItem -LiteralPath $_.FullName -Force | Measure-Object).Count -eq 0) {
                    Remove-Item -LiteralPath $_.FullName -Force
                }
            }

        if ((Get-ChildItem -LiteralPath $resolvedLogsRoot -Force | Measure-Object).Count -eq 0) {
            Remove-Item -LiteralPath $resolvedLogsRoot -Force
        }

        if ($lockedLogs.Count -gt 0) {
            Write-Warning (
                "Skipped {0} active log file(s); stop the owning service and rerun cleanup to remove them." -f
                $lockedLogs.Count
            )
        }
    }
}
