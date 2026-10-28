@echo off
REM 每天挑两篇高质量帖子存笔记
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m xhh_agent.cli.main study --count 2
) else (
  py -m xhh_agent.cli.main study --count 2
)
