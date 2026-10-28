# Remove the "xiaoheihe-autopoll" scheduled task.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall-autostart.ps1

$ErrorActionPreference = 'Stop'
$name = 'xiaoheihe-autopoll'

if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "Removed scheduled task: $name"
} else {
    Write-Host "Nothing to remove: $name is not registered"
}
