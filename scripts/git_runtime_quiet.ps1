$ErrorActionPreference = "Stop"

param(
    [ValidateSet("quiet", "unquiet", "status")]
    [string]$Mode = "quiet"
)

$patterns = @(
    "CSV_data/scrapers/*.csv",
    "CSV_data/ai/*.csv",
    "CSV_data/model_audit/*.csv",
    "CSV_data/archives/active_snapshots/*.csv",
    "CSV_data/archives/sold_backups/*.csv",
    "CSV_data/restricted/active_vehicle_details_restricted.csv",
    "CSV_data/restricted/sold_cars_restricted.csv",
    "CSV_data/restricted/restricted_group_map.csv",
    "CSV_data/restricted/audit/*.csv",
    "output/governance/*",
    "output/pdf/*"
)

function Get-TrackedRuntimeFiles {
    $files = @()
    foreach ($pattern in $patterns) {
        $matches = git ls-files -- $pattern
        foreach ($match in $matches) {
            if ($match) {
                $files += $match
            }
        }
    }
    $files | Sort-Object -Unique
}

$files = @(Get-TrackedRuntimeFiles)

if ($files.Count -eq 0) {
    Write-Host "No tracked runtime files matched."
    exit 0
}

if ($Mode -eq "status") {
    $skipped = git ls-files -v -- $files | Where-Object { $_ -match "^S " }
    Write-Host ("Tracked runtime files: {0}" -f $files.Count)
    Write-Host ("Quieted with skip-worktree: {0}" -f @($skipped).Count)
    exit 0
}

foreach ($file in $files) {
    if ($Mode -eq "quiet") {
        git update-index --skip-worktree -- $file
    } else {
        git update-index --no-skip-worktree -- $file
    }
}

if ($Mode -eq "quiet") {
    Write-Host ("Quieted {0} tracked runtime file(s). Use scripts\git_runtime_quiet.ps1 -Mode unquiet before intentional data commits." -f $files.Count)
} else {
    Write-Host ("Unquieted {0} tracked runtime file(s)." -f $files.Count)
}
