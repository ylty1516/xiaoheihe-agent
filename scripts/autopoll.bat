@echo off
REM Autostart poll: scan new comments under my own posts and generate reply drafts.
REM Never sends anything - sending still requires explicit approval.
REM Invoked by scheduled task "xiaoheihe-autopoll" (on logon + every 2 hours)
REM through autopoll.vbs so no console window flashes.
setlocal
cd /d "%~dp0.."

if not exist ".data\logs" mkdir ".data\logs"
set LOG=.data\logs\autopoll.log
REM Force UTF-8 so localized output from the CLI never gets mangled.
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

REM %DATE:~0,10% drops the localized weekday suffix (e.g. "Wed") that would
REM otherwise land in the log as mojibake.
echo. >> "%LOG%"
echo ==== %DATE:~0,10% %TIME% start ==== >> "%LOG%"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m xhh_agent.cli.main poll --once --generate-drafts >> "%LOG%" 2>&1
) else (
  py -m xhh_agent.cli.main poll --once --generate-drafts >> "%LOG%" 2>&1
)

echo ==== %DATE:~0,10% %TIME% done exit=%ERRORLEVEL% ==== >> "%LOG%"
endlocal
