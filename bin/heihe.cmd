@echo off
REM heihe - short command for the xiaoheihe agent.
REM   heihe auto         start the local web panel and open the browser
REM   heihe doctor       run the four self checks
REM   heihe hot -n 5     show the hot list
REM   heihe publish ...  publish a post (needs --yes)
REM
REM Keep this file ASCII-only: cmd.exe parses batch files with the OEM code page,
REM so UTF-8 Chinese comments break it. All real logic lives in Python.

setlocal
set "PROJECT=%~dp0.."
cd /d "%PROJECT%"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m xhh_agent.cli.main %*
) else (
  py -m xhh_agent.cli.main %*
)
exit /b %ERRORLEVEL%
