# 每日任务检查（尚非自动完成）

`xhh daily --enable --refresh` 开启并读取真实每日进度；`xhh daily` 查看本地今日记录，`xhh daily --disable` 停止后台检查。后台服务上线时检查一次，之后每小时检查；仅已开启的项目执行。查询只读取小黑盒任务列表，不新增分享、点赞、评论或发帖。

2026-11-03，当前账号返回四项每日任务：签到、分享任意帖子到社交平台、分享评论到社交平台、分享游戏详情到社交平台。清单随平台和账号改变，以每次真实响应为准。任务仅在平台返回`finish`时标记完成，未知状态、空列表、登录失效不会误报完成。

## 当前阻碍

项目现有会话是网页版登录态；原生App签到还需要App登录凭据与原生签名实现，当前没有接通。本次一次真实签到请求返回“非法的请求”，再次读取状态仍为waiting，因此不算签到成功。不会反复提交失败请求，不实现收费补签，不收集或在聊天中传输密码、Cookie。

另外三项需要真实对外分享；现有每日GitHub发帖授权不等于指定了微信、QQ等分享接收人。未实际分享时，不上报虚构的分享成功事件。当前没有接入原生App授权和真实分享渠道，不能宣称全自动做完每日任务。

[原生实现参考](https://github.com/Cansiny0320/heybox-daily/blob/main/src/client.ts)使用独立的原生签名与App会话；这里只研究协议，不运行其分享事件模拟或上传用户凭据到托管服务。读取接口的原始抓包说明见[任务列表文档](https://github.com/wentaoabcd/QinglongCheckinScripts/blob/main/docs/heybox-api.md)。

## 查看状态

CLI输出、`GET /api/daily-tasks`以及DSH Go创作台显示平台确认的进度。`POST /api/daily-tasks`（JSON对象）刷新平台状态，并检查浏览器Origin；GET只读本地快照，不在手机每次轮询时请求上游。每日报告存`.data/daily-tasks/YYYY-MM-DD.json`，失败清除旧的成功摘要，跨日不沿用昨天的完成记录。后台只读开关在`.data/daily-tasks-settings.json`，默认关闭，用户启用后持久保留。

该监测不依赖Codex保持运行，依赖本机小黑盒后端；每日文章的配图和写作调度仍按原来的桌面自动任务执行。
