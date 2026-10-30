# 注意：这个文件必须存成 UTF-8 with BOM。
# PowerShell 5.1 会把无 BOM 的 UTF-8 当 ANSI 读，中文注释会把脚本撑坏。
#
# 把 "heihe" 命令挂到当前用户的 PATH 上，这样在任意 PowerShell 里
# 直接敲 heihe auto 就能起面板。
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-heihe.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-heihe.ps1 -Remove
#
# 只改 **当前用户** 的 PATH（HKCU），不碰系统 PATH，不需要管理员。
# 改完要新开一个 PowerShell 窗口才生效。

param([switch]$Remove)

$ErrorActionPreference = 'Stop'

$binDir = (Resolve-Path (Join-Path $PSScriptRoot '..\bin')).Path
$current = [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not $current) { $current = '' }

$parts = $current -split ';' | Where-Object { $_ -and $_.Trim() -ne '' }
$has = $parts | Where-Object { $_.TrimEnd('\') -ieq $binDir.TrimEnd('\') }

if ($Remove) {
    if (-not $has) {
        Write-Host "PATH 里没有 $binDir，不用删。"
        exit 0
    }
    $kept = $parts | Where-Object { $_.TrimEnd('\') -ine $binDir.TrimEnd('\') }
    [Environment]::SetEnvironmentVariable('Path', ($kept -join ';'), 'User')
    Write-Host "已从用户 PATH 移除：$binDir"
    exit 0
}

if (-not (Test-Path (Join-Path $binDir 'heihe.cmd'))) {
    throw "找不到 heihe.cmd：$binDir"
}

if ($has) {
    Write-Host "用户 PATH 里已经有：$binDir"
} else {
    $updated = (($parts + $binDir) -join ';')
    [Environment]::SetEnvironmentVariable('Path', $updated, 'User')
    Write-Host "已加入用户 PATH：$binDir"
}

Write-Host ''
Write-Host '新开一个 PowerShell，然后试：'
Write-Host '  heihe auto'
Write-Host ''
Write-Host '想撤销：scripts\install-heihe.ps1 -Remove'
