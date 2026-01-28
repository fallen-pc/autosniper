$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$pythonPath = Join-Path $repoRoot ".venv\\Scripts\\python.exe"
if (-not (Test-Path $pythonPath)) {
    $pythonPath = "python"
}

$logDir = Join-Path $repoRoot "logs"
if (-not (Test-Path $logDir)) {
    New-Item -Path $logDir -ItemType Directory | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir ("autotrader_scrape_{0}.log" -f $timestamp)

$argsList = @(
    "autotrader_isolated/scrape_first_page.py",
    "--all-pages",
    "--playwright-headful",
    "--playwright-browser", "chrome",
    "--storage-state", "autotrader_isolated/output/storage_state.json",
    "--cookie-file", "autotrader_isolated/output/autotrader_cookie.txt",
    "--page-retries", "3",
    "--page-retry-delay", "10"
)

Push-Location $repoRoot
try {
    & $pythonPath @argsList *> $logFile
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
