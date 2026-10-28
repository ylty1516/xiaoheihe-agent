@echo off
schtasks /Delete /TN "xiaoheihe-daily-poll"  /F
schtasks /Delete /TN "xiaoheihe-daily-study" /F
echo 已删除计划任务。
