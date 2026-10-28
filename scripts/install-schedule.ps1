# Register the two daily tasks (comments poll at 09:00, study at 21:00).
# Both run through run-hidden.vbs so no console window appears.
#
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-schedule.ps1
# Remove: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall-schedule.ps1

$ErrorActionPreference = 'Stop'

$root   = Resolve-Path (Join-Path $PSScriptRoot '..')
$vbs    = Join-Path $root 'scripts\run-hidden.vbs'
if (-not (Test-Path $vbs)) { throw "missing launcher: $vbs" }

$tasks = @(
    @{ Name = 'xiaoheihe-daily-poll';  Bat = 'daily-poll.bat';  At = '09:00'; Desc = 'Xiaoheihe: scan own-post comments and generate reply drafts (never sends).' },
    @{ Name = 'xiaoheihe-daily-study'; Bat = 'daily-study.bat'; At = '21:00'; Desc = 'Xiaoheihe: collect two high-quality community posts into notes.' }
)

foreach ($t in $tasks) {
    $bat = Join-Path $root "scripts\$($t.Bat)"
    if (-not (Test-Path $bat)) { throw "missing script: $bat" }

    Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false -ErrorAction SilentlyContinue

    $action = New-ScheduledTaskAction -Execute 'wscript.exe' `
                                      -Argument "//nologo `"$vbs`" `"$bat`"" `
                                      -WorkingDirectory $root
    $trigger = New-ScheduledTaskTrigger -Daily -At $t.At
    $settings = New-ScheduledTaskSettingsSet `
        -MultipleInstances IgnoreNew `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries

    Register-ScheduledTask -TaskName $t.Name `
                           -Action $action `
                           -Trigger $trigger `
                           -Settings $settings `
                           -Description $t.Desc `
                           -Force | Out-Null

    $info = Get-ScheduledTaskInfo -TaskName $t.Name
    Write-Host "Registered: $($t.Name)  daily at $($t.At)  next=$($info.NextRunTime)"
}
