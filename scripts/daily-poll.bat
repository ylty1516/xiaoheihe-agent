@echo off
REM Daily comment scan: generate reply drafts for new comments under my own posts.
REM Never sends anything. Invoked by the "xiaoheihe-daily-poll" scheduled task
REM through run-hidden.vbs, so there is no console window - output must go to a log.
setlocal
cd /d "%~dp0.."

if not exist ".data\logs" mkdir ".data\logs"
set LOG=.data\logs\daily-poll.log
REM Force UTF-8 so localized CLI output never turns into mojibake in the log.
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

REM %DATE:~0,10% drops the localized weekday suffix, which would be mojibake.
echo. >> "%LOG%"
echo ==== %DATE:~0,10% %TIME% start ==== >> "%LOG%"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m xhh_agent.cli.main poll --once --generate-drafts >> "%LOG%" 2>&1
) else (
  py -m xhh_agent.cli.main poll --once --generate-drafts >> "%LOG%" 2>&1
)

echo ==== %DATE:~0,10% %TIME% done exit=%ERRORLEVEL% ==== >> "%LOG%"
endlocal
