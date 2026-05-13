param(
    [string]$BackupZip,
    [string]$BackupDir = $env:AUTOSNIPER_BACKUP_DIR
)

$ErrorActionPreference = "Stop"

function Resolve-LatestBackupZip {
    param([string]$Directory)

    if ([string]::IsNullOrWhiteSpace($Directory)) {
        throw "Provide -BackupZip or set/pass -BackupDir."
    }

    $resolvedDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Directory)
    if (-not (Test-Path -LiteralPath $resolvedDir)) {
        throw "Backup directory does not exist: $resolvedDir"
    }

    $latest = Get-ChildItem -LiteralPath $resolvedDir -Filter "autosniper-runtime-*.zip" |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    if ($null -eq $latest) {
        throw "No autosniper-runtime-*.zip backups found in: $resolvedDir"
    }

    return $latest.FullName
}

if ([string]::IsNullOrWhiteSpace($BackupZip)) {
    $BackupZip = Resolve-LatestBackupZip -Directory $BackupDir
} else {
    $BackupZip = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($BackupZip)
}

if (-not (Test-Path -LiteralPath $BackupZip)) {
    throw "Backup zip does not exist: $BackupZip"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$extractRoot = Join-Path $env:TEMP "autosniper-backup-verify-$timestamp"

if (Test-Path -LiteralPath $extractRoot) {
    Remove-Item -LiteralPath $extractRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null

try {
    Expand-Archive -LiteralPath $BackupZip -DestinationPath $extractRoot -Force

    $requiredFiles = @(
        "CSV_data/scrapers/sold_cars.csv",
        "CSV_data/restricted/sold_cars_restricted.csv",
        "CSV_data/ai/ai_listing_valuations.csv",
        "backup_manifest.txt"
    )

    $optionalFiles = @(
        "status/metrics.json",
        "output/health/scraper_health.json"
    )

    $missingRequired = New-Object System.Collections.Generic.List[string]
    foreach ($relativePath in $requiredFiles) {
        $fullPath = Join-Path $extractRoot $relativePath
        if (-not (Test-Path -LiteralPath $fullPath)) {
            $missingRequired.Add($relativePath)
        }
    }

    if ($missingRequired.Count -gt 0) {
        Write-Host "Backup verification failed. Missing required files:"
        foreach ($path in $missingRequired) {
            Write-Host "- $path"
        }
        exit 1
    }

    $csvChecks = @(
        @{ Name = "sold_cars"; Path = "CSV_data/scrapers/sold_cars.csv"; MinRows = 1 },
        @{ Name = "sold_cars_restricted"; Path = "CSV_data/restricted/sold_cars_restricted.csv"; MinRows = 1 },
        @{ Name = "ai_listing_valuations"; Path = "CSV_data/ai/ai_listing_valuations.csv"; MinRows = 0 }
    )

    foreach ($check in $csvChecks) {
        $fullPath = Join-Path $extractRoot $check.Path
        $rows = Import-Csv -LiteralPath $fullPath
        $rowCount = @($rows).Count
        if ($rowCount -lt [int]$check.MinRows) {
            throw "$($check.Name) row count is too low: $rowCount"
        }
        Write-Host "$($check.Name): $rowCount rows"
    }

    Write-Host "Optional files:"
    foreach ($relativePath in $optionalFiles) {
        $fullPath = Join-Path $extractRoot $relativePath
        if (Test-Path -LiteralPath $fullPath) {
            Write-Host "- present: $relativePath"
        } else {
            Write-Host "- missing: $relativePath"
        }
    }

    Write-Host "Backup verification passed:"
    Write-Host $BackupZip
} finally {
    if (Test-Path -LiteralPath $extractRoot) {
        Remove-Item -LiteralPath $extractRoot -Recurse -Force
    }
}
