# CLI 使用指南

[返回仓库首页](../README.md)

适用于后端 v0.8.0。日常创作建议先用 [WebUI 快速入门](../README.md#安装)；下面保留命令行入口、迁移和旧工作流说明。

## 环境与命令入口

需要 Python 3.11+。安装时不必激活环境，Windows 可直接执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\xhh.exe auto
```

下文使用 `xhh` 简写；Windows 激活 `.venv\Scripts\Activate.ps1` 后使用，或将它替换成 `.\.venv\Scripts\xhh.exe`。macOS / Linux 对应 `.venv/bin/xhh`。`heihe` 是同一入口的别名。

已有仓库附带的 `bin\heihe.cmd` 也可启动。若希望在任意 PowerShell 窗口直接输入 `heihe`，可选安装当前用户 PATH 入口：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-heihe.ps1
```

脚本只修改当前用户 PATH，需新开终端生效；同一脚本加 `-Remove` 可撤销。不要求安装此入口才能使用 WebUI。

## 登录与只读检查

```sh
xhh login
xhh whoami
xhh doctor
xhh inbox --limit 10
```

二维码需要小黑盒 App 扫描，不能当网页链接打开。网页登录用于社区读取和发布；App 每日任务使用[单独的本机短信授权](daily-tasks.md)，无需把验证码交给 agent。

## 成稿、分区与发布

```sh
# 保存到平台草稿箱，不公开；此命令仍需账号登录
xhh draft --md article.md --title "文章标题" --topic GitHub --topic AI --html-out preview.html

# 仅在已经授权公开本篇时执行
xhh publish --md article.md --title "文章标题" --topic GitHub --topic AI --yes

# 已有资料直接成稿，只保存本地；仍需配置文本模型
xhh autopilot run --instruction "把这些资料整理成软件教程" --subject software --genre tutorial --material-file material.txt --images none
```

WebUI 本地保存与 `xhh draft` 不同：本地编辑不需要账号，后者会写入平台草稿箱。分区可重复传 `--topic`，使用真实名称或 ID；`--tag` 适合已知 ID。新创作默认 GitHub＋AI，显式选择覆盖默认值，具体继承规则见[发布分区](publishing-topics.md)。

规格可用 `--profile article`、`short`、`flexible`。未显式传入时读取草稿已保存的选择，否则沿用长文偏好。长文至少 1000 字、3 张图；短帖与按需不强制图片，空稿不能公开。切换规格不会跳过重复、来源、频率或授权检查。

自动任务的进度与配图接续：

```sh
xhh autopilot list
xhh autopilot status --id <任务ID>
xhh autopilot images --id <任务ID>
xhh autopilot attach --id <任务ID> --image-id <配图ID> --file <图片路径>
xhh autopilot resume --id <任务ID>
```

提前授权自动发布使用 `xhh autopilot run ... --publish --yes`；默认只成稿。独立 WebUI 不直接调用聊天生图工具，没有宿主接续时会等待图片。单次 CLI 退出不等于后台常驻，详见[自动成稿](autopilot.md)。

## 发现选题与学习

```sh
xhh hot --board all
xhh hot --board games
xhh hot --board discussions
xhh topic-posts "GitHub" --limit 8
xhh study --count 2
xhh study --list
```

热度来自平台取回的样本，不代表全网完整榜单。学习命令保存笔记，不点赞、不评论；写作范围可按需要选择游戏、硬件、软件与 AI，详见[领域与写法](writing-range.md)。

```powershell
py scripts/editorial.py audit
py scripts/style_profile.py compare article.md
py scripts/check_post.py article.md --profile short
```

内容记忆和结构对照用于提醒重复习惯，不保证语义新颖。旧文补录、学习卡和局部改写见[写作流程](editorial-workflow.md)。

## 评论与私信

```sh
xhh poll --once
xhh queue list
xhh queue show 3
# 看过内容并授权发送后执行
xhh reply --queue-id 3 --text "回复内容" --send
```

`reply` 默认 dry-run，`--send` 才提交；`--generate` 可用已配置模型生成候选回复。只处理自己帖子下的评论，受队列决策、幂等与频率限制。发帖授权不自动扩展成回复或私信授权。

`xhh dm --history --to <用户ID>` 读取私信历史；发送另需 `--text` 和 `--send`。删除入口见 `xhh delete --help`，不可逆操作需明确授权。

## 后台与每日任务

Windows 后端常驻的安装、状态、停止与移除：

```powershell
powershell -NoProfile -File scripts/background.ps1 -Action Install
powershell -NoProfile -File scripts/background.ps1 -Action Status
powershell -NoProfile -File scripts/background.ps1 -Action Stop
powershell -NoProfile -File scripts/background.ps1 -Action Remove
```

后端常驻不会自动新建每日发帖计划。定时文章仍需宿主任务、授权和可用的模型/生图工具；App 每日任务需要 Node.js 24+ 及独立 App 授权，详见[后台说明](background.md)和[任务说明](daily-tasks.md)。

```sh
xhh daily --refresh
xhh daily login
xhh daily run --yes
xhh daily --auto --yes
xhh daily --disable
```

`--auto --yes` 开启后台自动执行，需保持后端运行。分享采用 App 流程事件上报，不向微信/QQ发送消息；未适配任务不会记为完成。

<details>
<summary>旧评论扫描、学习与发帖值班工作流</summary>

`scripts/install-schedule.bat` 注册旧的 Windows 任务，`scripts/uninstall-schedule.bat` 取消。它与新版常驻安装器、宿主每日创作计划彼此独立，不应为启用每日签到而重复安装。

| 旧任务 | 原计划 | 行为 |
| --- | --- | --- |
| `daily-poll` | 09:00 | 扫描评论并生成回复草稿，不发送。 |
| `daily-study` | 21:00 | 读取高质量帖子并保存笔记。 |

旧发帖值班的排期工具：

```powershell
py scripts/post_slot.py check
py scripts/post_slot.py status
# 仅在确认发布成功后登记实际 link_id
py scripts/post_slot.py record --link-id <实际帖子ID>
```

代码硬上限为每天最多 3 篇、至少间隔 2 小时、09:00–23:00。**硬上限不是用户授权额度**：已约定每天一篇时，仍按一篇执行。旧《影之刃零》值班的题材与流程不作为新创作默认值，见[值班手册](posting-duty.md)。

</details>

## 迁移到新机器

1. 克隆仓库并重建虚拟环境，不复制旧机器的 `.venv`、`node_modules` 或后台任务。
2. 在新机器本地重新配置模型、扫码登录；需要 App 任务时安装组件并完成该机短信授权。不要把密钥、Cookie、验证码放进 Git 或公开产出目录。
3. 迁移需要的草稿、素材、人设与学习记录时，先备份原文件；账号会话与机器路径分开处理，不直接覆盖整份 `.data/`。
4. 先检查本地预览、模型连通与只读账号状态，再按授权配置常驻和定时任务。DSH Go 的插件与后端装在同一主机，手机与电脑不自动同步凭据。

版本要求以 [pyproject.toml](../pyproject.toml)、[手机插件](../integrations/dsh-go/package.json)和 [App 组件](../integrations/heybox-app/package.json)为准；CI 当前覆盖 Python 3.12 的 Windows / Linux、手机插件 SDK 与 Node.js 24 的 App 流程，不等于所有系统组合都经过真实账号验证。

## 常见问题

| 现象 | 先检查什么 |
| --- | --- |
| Windows 输入 `python` 没反应 | 用 `py --version` 确认启动器，或显式调用已安装的 Python 3.11+；不同机器的 PATH 配置不同。 |
| `xhh` 找不到 | 用虚拟环境内完整路径，或在当前终端激活该环境；安装用户 PATH 入口后需新开终端。 |
| 端口已占用 | 手动 `auto` 会尝试后续端口并提示；Windows 常驻固定等待 8765，日志见 `.data/logs/background.log`。 |
| 有正文，一直等待配图 | 查看 `autopilot images`；需要有生图工具的宿主生成并回填，独立后端不会在聊天里自行生图。 |
| 手机面板未显示 | 确认插件和后端同主机，并具备 DSH Go 原生桥接；普通远程 CLI 不保证原生胶囊显示。 |
| 连接 App 后仍有任务未完成 | 回读平台实际清单；未知任务保留待处理，网页版任务 11 与 App 任务 31 不可混用。 |
| 定时创作没执行 | 检查宿主任务状态、电脑是否睡眠、Codex 是否运行；只有后端在线不足以生成每日文章。 |
| 发布返回超时或结果不明 | 先核对账号实际帖子和本地任务记录，不重复执行发布命令。 |

旧 pi 工作流若报 `Background children require the host npm package` / `does not provide @earendil-works/chord`，先核对已安装宿主与其依赖版本，按宿主文档修复，不盲目固定历史依赖版本。`Unknown subagent model` 则检查实际可用 provider/model；主代理能用的模型不代表子流程自动获得同一鉴权。修复后先做不公开发布的验证。
