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

$storageState = Join-Path $repoRoot "autotrader_isolated\\output\\storage_state.json"
$cookieFile = Join-Path $repoRoot "autotrader_isolated\\output\\autotrader_cookie.txt"
if (-not (Test-Path $storageState)) {
    Write-Error "Missing storage_state.json at $storageState. Autotrader scrape requires a logged-in storage state."
    exit 1
}
if (-not (Test-Path $cookieFile)) {
    Write-Error "Missing autotrader_cookie.txt at $cookieFile. Autotrader scrape requires a valid cookie file."
    exit 1
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir ("autotrader_scrape_{0}.log" -f $timestamp)

$argsList = @(
    "autotrader_isolated/scrape_first_page.py",
    "--all-pages",
    "--playwright-headful",
    "--playwright-browser", "chrome",
    "--storage-state", $storageState,
    "--cookie-file", $cookieFile,
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
