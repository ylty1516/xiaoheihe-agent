@echo off
REM 删除两个每日计划任务（同样需要管理员权限）。
setlocal
net session >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
  echo Requesting administrator privileges...
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
  exit /b
)

powershell -NoProfile -Command "Unregister-ScheduledTask -TaskName 'xiaoheihe-daily-poll','xiaoheihe-daily-study' -Confirm:$false -ErrorAction SilentlyContinue; Write-Host 'Removed: xiaoheihe-daily-poll, xiaoheihe-daily-study'"
echo.
pause
endlocal
