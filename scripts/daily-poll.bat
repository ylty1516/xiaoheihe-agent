@echo off
REM 每天扫一次自己帖子下的新评论，并用模型生成回复草稿（不发送）
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m xhh_agent.cli.main poll --once --generate-drafts
) else (
  py -m xhh_agent.cli.main poll --once --generate-drafts
)
