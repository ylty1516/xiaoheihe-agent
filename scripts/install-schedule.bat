@echo off
REM 双击入口：自动提权后注册两个每日计划任务。
REM 注册根路径的计划任务需要管理员权限，所以会弹一次 UAC 确认。
setlocal
net session >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
  echo Requesting administrator privileges...
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
  exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-schedule.ps1"
echo.
pause
endlocal
