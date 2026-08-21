param(
    [string]$BackupDir = $env:AUTOSNIPER_BACKUP_DIR,
    [switch]$IncludeAutotraderSession
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

if ([string]::IsNullOrWhiteSpace($BackupDir)) {
    throw "Backup directory is required. Set AUTOSNIPER_BACKUP_DIR or pass -BackupDir."
}

$BackupDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($BackupDir)
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$zipPath = Join-Path $BackupDir "autosniper-runtime-$timestamp.zip"
$stageRoot = Join-Path $env:TEMP "autosniper-runtime-backup-$timestamp"

$relativePaths = @(
    "CSV_data/scrapers",
    "CSV_data/restricted",
    "CSV_data/ai",
    "CSV_data/model_audit",
    "CSV_data/reports",
    "status",
    "output/health",
    "logs/scheduled"
)

if ($IncludeAutotraderSession) {
    $relativePaths += "autotrader_isolated/output"
}

$existingPaths = New-Object System.Collections.Generic.List[string]
$missingPaths = New-Object System.Collections.Generic.List[string]

foreach ($relativePath in $relativePaths) {
    $fullPath = Join-Path $RepoRoot $relativePath
    if (Test-Path -LiteralPath $fullPath) {
        $existingPaths.Add($fullPath)
    } else {
        $missingPaths.Add($relativePath)
    }
}

if ($existingPaths.Count -eq 0) {
    throw "No runtime folders were found to back up."
}

if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $stageRoot | Out-Null

$manifestLines = @(
    "AutoSniper runtime backup",
    "created_at=$((Get-Date).ToString("o"))",
    "repo_root=$RepoRoot",
    "zip_path=$zipPath",
    "include_autotrader_session=$IncludeAutotraderSession",
    "",
    "included_paths:"
)

foreach ($path in $existingPaths) {
    $manifestLines += "- $path"
}

$manifestLines += ""
$manifestLines += "missing_paths:"
foreach ($path in $missingPaths) {
    $manifestLines += "- $path"
}

Set-Content -Path (Join-Path $stageRoot "backup_manifest.txt") -Value $manifestLines -Encoding UTF8

foreach ($relativePath in $relativePaths) {
    $sourcePath = Join-Path $RepoRoot $relativePath
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        continue
    }
    $targetPath = Join-Path $stageRoot $relativePath
    $targetParent = Split-Path -Parent $targetPath
    New-Item -ItemType Directory -Force -Path $targetParent | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Recurse -Force
}

Compress-Archive -Path (Join-Path $stageRoot "*") -DestinationPath $zipPath -CompressionLevel Optimal -Force

Remove-Item -LiteralPath $stageRoot -Recurse -Force

$zipItem = Get-Item -LiteralPath $zipPath

Write-Host "Backup created:"
Write-Host $zipItem.FullName
Write-Host ("Size MB: {0:N2}" -f ($zipItem.Length / 1MB))
if ($missingPaths.Count -gt 0) {
    Write-Host "Skipped missing paths:"
    foreach ($path in $missingPaths) {
        Write-Host "- $path"
    }
}
