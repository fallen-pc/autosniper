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

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$dailyTrigger = New-ScheduledTaskTrigger -Daily -At $DailyTime
$hourlyTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(13) -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 72) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive

$dailyAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$dailyCmd`"" -WorkingDirectory $root
$hourlyAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$hourlyCmd`"" -WorkingDirectory $root

Register-ScheduledTask -TaskName $dailyTaskName -Action $dailyAction -Trigger $dailyTrigger -Settings $settings -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName $hourlyTaskName -Action $hourlyAction -Trigger $hourlyTrigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Registered scheduled tasks:"
Write-Host "- $dailyTaskName at $DailyTime daily"
Write-Host "- $hourlyTaskName every hour"
