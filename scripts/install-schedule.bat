@echo off
setlocal
set ROOT=%~dp0..
echo 正在注册计划任务...
schtasks /Create /TN "xiaoheihe-daily-poll"  /TR "\"%ROOT%\scripts\daily-poll.bat\""  /SC DAILY /ST 09:00 /F
schtasks /Create /TN "xiaoheihe-daily-study" /TR "\"%ROOT%\scripts\daily-study.bat\"" /SC DAILY /ST 21:00 /F
echo.
echo 已注册：
echo   09:00  xiaoheihe-daily-poll   （扫新评论 + 生成回复草稿，不发送）
echo   21:00  xiaoheihe-daily-study  （挑两篇帖子存笔记）
echo.
echo 查看：schtasks /Query /TN "xiaoheihe-daily-poll"
echo 删除：scripts\uninstall-schedule.bat
endlocal
