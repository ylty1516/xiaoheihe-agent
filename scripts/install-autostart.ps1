# Register the "xiaoheihe-autopoll" scheduled task.
# Triggers: at logon + repeat every 2 hours (runs on battery too).
# The task only scans comments and generates drafts - it never sends replies.
#
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-autostart.ps1
# Remove: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall-autostart.ps1

$ErrorActionPreference = 'Stop'

$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$vbs  = Join-Path $root 'scripts\autopoll.vbs'
$name = 'xiaoheihe-autopoll'

if (-not (Test-Path $vbs)) { throw "missing launcher: $vbs" }

# Idempotent: drop any previous registration first.
Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute 'wscript.exe' `
                                  -Argument "//nologo `"$vbs`"" `
                                  -WorkingDirectory $root

$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn)
)

# -Once with a repetition interval needs an explicit duration. Task Scheduler
# rejects [TimeSpan]::MaxValue (P99999999D is out of range), so use ~27 years:
# effectively "repeat forever" for a personal tool.
$rep = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(3) `
                                -RepetitionInterval (New-TimeSpan -Hours 2) `
                                -RepetitionDuration (New-TimeSpan -Days 9999)
$triggers += $rep

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $name `
                       -Action $action `
                       -Trigger $triggers `
                       -Settings $settings `
                       -Description 'Xiaoheihe agent: scan own-post comments and generate reply drafts (never sends).' `
                       -Force | Out-Null

$task = Get-ScheduledTask -TaskName $name
$info = Get-ScheduledTaskInfo -TaskName $name
Write-Host "Registered: $($task.TaskName)  state=$($task.State)"
foreach ($t in $task.Triggers) {
    if ($t.Repetition.Interval) {
        Write-Host "  trigger: $($t.CimClass.CimClassName) every $($t.Repetition.Interval)"
    } else {
        Write-Host "  trigger: $($t.CimClass.CimClassName)"
    }
}
Write-Host "  log: $(Join-Path $root '.data\logs\autopoll.log')"
Write-Host "  next run: $($info.NextRunTime)"
