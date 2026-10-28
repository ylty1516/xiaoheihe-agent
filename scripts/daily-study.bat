@echo off
REM Daily study: collect two high-quality community posts into notes.
REM Invoked by the "xiaoheihe-daily-study" scheduled task through run-hidden.vbs,
REM so there is no console window - output must go to a log.
setlocal
cd /d "%~dp0.."

if not exist ".data\logs" mkdir ".data\logs"
set LOG=.data\logs\daily-study.log
REM Force UTF-8 so localized CLI output never turns into mojibake in the log.
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

REM %DATE:~0,10% drops the localized weekday suffix, which would be mojibake.
echo. >> "%LOG%"
echo ==== %DATE:~0,10% %TIME% start ==== >> "%LOG%"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m xhh_agent.cli.main study --count 2 >> "%LOG%" 2>&1
) else (
  py -m xhh_agent.cli.main study --count 2 >> "%LOG%" 2>&1
)

echo ==== %DATE:~0,10% %TIME% done exit=%ERRORLEVEL% ==== >> "%LOG%"
endlocal
