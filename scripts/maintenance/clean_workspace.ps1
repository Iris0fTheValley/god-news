[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

# Only ignored, reproducible state is in scope. Runtime databases, model caches,
# production outputs, virtual environments, and package installations are
# intentionally excluded.
$targets = @(
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "src",
    "tests",
    "frontend/public/template-lab",
    "frontend/dist",
    "frontend/playwright-report",
    "frontend/test-results",
    "video/build",
    "video/dist",
    "logs"
)

if ($PSCmdlet.ShouldProcess($root, "remove ignored caches, test reports, staged demo assets, and logs")) {
    & git -C $root clean -fdX -- @targets
    if ($LASTEXITCODE -ne 0) {
        throw "Git failed to clean reproducible workspace state."
    }
}
