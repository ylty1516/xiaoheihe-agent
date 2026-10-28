@echo off
REM Double-click entry point: re-launches itself elevated, then registers the
REM xiaoheihe-autopoll task. Registering a task in the root task folder needs
REM administrator rights, which is the only reason UAC is involved.
setlocal
net session >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
  echo Requesting administrator privileges...
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
  exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-autostart.ps1"
echo.
pause
endlocal
