param(
    [string]$TaskPrefix = "AutoSniper",
    [string]$DailyTime = "09:00"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$dailyCmd = Join-Path $root "scripts\run_daily.cmd"
$hourlyCmd = Join-Path $root "scripts\run_hourly_monitor.cmd"

if (-not (Test-Path $dailyCmd)) {
    throw "Missing daily command wrapper: $dailyCmd"
}

if (-not (Test-Path $hourlyCmd)) {
    throw "Missing hourly command wrapper: $hourlyCmd"
}

$dailyTaskName = "$TaskPrefix Daily Pipeline"
$hourlyTaskName = "$TaskPrefix Hourly Active Monitor"

$dailyCommand = "cmd.exe /c `"$dailyCmd`""
$hourlyCommand = "cmd.exe /c `"$hourlyCmd`""

schtasks /Create /TN $dailyTaskName /TR $dailyCommand /SC DAILY /ST $DailyTime /F | Out-Null
schtasks /Create /TN $hourlyTaskName /TR $hourlyCommand /SC HOURLY /MO 1 /F | Out-Null

Write-Host "Registered scheduled tasks:"
Write-Host "- $dailyTaskName at $DailyTime daily"
Write-Host "- $hourlyTaskName every hour"
