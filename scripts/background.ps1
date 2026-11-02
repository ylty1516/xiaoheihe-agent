param(
    [ValidateSet('Install','Status','Start','Stop','Remove')]
    [string]$Action = 'Status',
    [ValidateRange(1,65535)][int]$Port = 8765
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$name = 'xiaoheihe-backend'
if ($Action -eq 'Install') {
    # Resolve the already installed interpreter, never the Windows Store alias.
    $pythonPath = (& py -c 'import sys; print(sys.executable)').Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Python is unavailable' }
    $pythonwPath = Join-Path (Split-Path $pythonPath) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonwPath)) { throw 'pythonw.exe is unavailable' }
    & $pythonPath -c 'import xhh_agent, aiohttp'
    if ($LASTEXITCODE -ne 0) { throw 'Install xhh-agent into this Python first' }
    $scriptPath = Join-Path $root 'scripts\background.py'
    $command = New-ScheduledTaskAction -Execute $pythonwPath -WorkingDirectory $root `
        -Argument "`"$scriptPath`" --root `"$root`" --port $Port"
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $name -Action $command -Settings $settings `
        -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $userId) -Principal $principal `
        -Description 'Local Heybox backend; no new posts or replies are created by this launcher.' -Force | Out-Null
    Start-ScheduledTask -TaskName $name
} elseif ($Action -eq 'Start') {
    Start-ScheduledTask -TaskName $name
} elseif ($Action -eq 'Stop' -or $Action -eq 'Remove') {
    Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($Action -eq 'Remove') { Unregister-ScheduledTask -TaskName $name -Confirm:$false }
}
$task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $name
    Write-Output "Backend task: $($task.State); last result: $($info.LastTaskResult)"
} else { Write-Output 'Backend task: not installed' }
try {
    $state = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/state" -TimeoutSec 5
    Write-Output "Backend responding: $([bool]($state.PSObject.Properties.Name -contains 'slot'))"
} catch { Write-Output 'Backend responding: false' }
Write-Output "Log: $root\.data\logs\background.log"
