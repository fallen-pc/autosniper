param(
    [string]$TaskName = "AutoSniper Local Repair Ledger Refresh",
    [string]$DailyTime = "13:00"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$refreshCmd = Join-Path $root "scripts\run_repair_ledger_refresh.cmd"
if (-not (Test-Path -LiteralPath $refreshCmd)) {
    throw "Missing repair ledger refresh wrapper: $refreshCmd"
}

$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -Daily -At $DailyTime
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -WakeToRun `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$refreshCmd`"" -WorkingDirectory $root

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "Registered '$TaskName' at $DailyTime daily."
