# 按需使用的命令参考

示例使用已安装的 `xhh`；Windows 可替换为 `py -m xhh_agent.cli.main`。
按任务挑选，不要求依序执行。参数以本机 `--help` 为准。

## 查询与诊断

```powershell
xhh whoami
xhh doctor
xhh inbox -n 20
xhh hot -n 5
xhh hot --board games --format json
xhh hot --board discussions
xhh topic-posts "用户指定的游戏或话题" -n 8
xhh topic-posts "当前话题" --sort comment_num --time-range 1d --format json
```

查指定内容时不必先看热搜，数量只是示例。`doctor` 用于确认或诊断账号链路，
不是本地改稿的前置条件。会话失效时提示 `xhh login`，不显示 cookie。
hot 默认请求刷新，可用 `--no-refresh` 允许上游缓存；topic-posts 默认近24小时、最新发布，
可切换 create_date / award_num / comment_num / default 排序及 7d、30d 等时间范围。
近24小时按真实发布时间本地过滤，无日期条目不混入。JSON 保留来源和采集时间，数据是有限样本，
旧高互动帖不等于实时热点；面板自动更新与来源规则见项目 `docs/discovery.md`。

## 拟稿、预览和发布

本地 Markdown 可直接写入，不必先上传草稿。需要 App 草稿或转换预览时：

```powershell
xhh draft --md 稿子.md --title "标题" --html-out .data/preview.html
xhh draft --md 短帖.md --title "标题" --profile short
```

不完整稿件可先存草稿；正式发布才按所选规格拦截不合格内容。WebUI 草稿的规格保存到
同名 `.meta.json`，CLI 和检查脚本读取同一选择，显式 `--profile` 优先。

```powershell
py scripts/check_post.py 稿子.md
py scripts/check_post.py 短帖.md --profile short
py scripts/check_post.py 无图稿.md --profile flexible
xhh publish --md 稿子.md --title "标题" --topic "对应话题" --profile article --yes
xhh publish --md 短帖.md --title "标题" --profile short --yes
```

`article` 沿用至少 1000 字、3 张图的长文偏好；`short` 不设长文门槛和必配图，超过 800 字仅提醒；
`flexible` 不设目标篇幅和配图数。后两者的表情与口头禅密度仅提醒，空内容仍不能发布。
`--allow-short` 保留兼容，优先选匹配用途的规格。

`publish` 会公开，先核对授权。`--tag` 接真实话题 ID，`--topic` 可按名称解析，不猜 ID。
CLI 当前以 article 富文本格式提交，包括短帖。**内容规格 short 不代表平台 dynamic 模式**。
只有底层协议 `mode="dynamic"` 才是纯文本动态，不能塞 HTML；CLI 没有 `--mode` 参数。

成功后核对 link_id、公开状态、分区和图片转存。结果不明先查状态，不因缺回执再次发布。
实际游戏帖宜挂对应游戏分区，特定值班的固定分区不套到其他题材。

## 评论

```powershell
xhh poll --once
xhh queue list
xhh queue show <id>
xhh reply --queue-id <id> --text "拟好的回复"
xhh reply --queue-id <id> --text "已获授权的回复" --send
```

需要新评论时才 poll，已有队列 ID 可直接 show。先读原帖、被回复上文、评论和人工标记。
默认 dry-run；发送对象、内容和权限清楚且已获授权时发送，不反复确认同一份已确认的草稿。

## 私信与删除

```powershell
xhh dm --to <user_id> --text "草稿"
xhh dm --to <user_id> --text "已获授权的内容" --send
xhh delete --link-id <id>
xhh delete --link-id <id> --yes
```

私信收件人可从 inbox 的 sender_id 获取，不凭昵称猜 ID。
删除先核对对象和授权；仅获准删草稿时不能删除真实帖子。

## 内容记忆与学习

批量规划或维护长期内容时可使用：

```powershell
py scripts/editorial.py audit
py scripts/editorial.py init .data/post-new.md
py scripts/editorial.py plan .data/post-new.md
py scripts/editorial.py review .data/post-new.md
py scripts/editorial.py library --query "需要的写法"
```

`--require-brief` 只用于要求完整选题卡的任务，例如原有长文值班，不拦普通短帖或局部润色。
有价值的样本完成分析后再 `editorial.py learn`，不把普通浏览自动升级为学习任务。
重复与习惯提醒是编辑线索，不证明事实正确，也不强迫改变用户指定结构。
