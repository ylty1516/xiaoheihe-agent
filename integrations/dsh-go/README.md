# DSH Go 手机原生适配

适配 [ccch1mneyyy/dsh-Go](https://github.com/ccch1mneyyy/dsh-Go)，参照其原生插件规范，基准提交 `d44f9607b69bc284a733e554805f283b30471e7a`。

手机输入框上方有「自动成稿」「保存素材」两个胶囊。写一句要求后点自动成稿；留空则从游戏热榜选题。也可把输入框随记归档，稍后点素材直接成稿。创作台可从「全部功能」或对话插件面板打开，自动刷新任务，支持预览、复制、暂停、继续、取消及切换人设，或交给聊天助手继续配图和处理。

按钮默认只生成本地稿，不把点按误当公开发布授权。自动发布仍按已有账号约定由助手执行 `xhh autopilot ... --publish --yes`，任务检查和结果不明禁止重发的逻辑共用 Python 后端。

适配器版本 **0.2.0**，配合 Python 后端 **0.6.0**。人设列表只显示名称与修订，不下发私人描述；切换影响后续任务。继续任务不会为仍在运行的任务重复启动，结果待核对的任务仍不可重发。

## 在手机本机引擎安装

在 DSH Go 的 Linux 环境内执行，Python 至少 3.11、Node 至少 22.19；需要 Git、pip、venv。若 Ubuntu 缺少 venv，先安装发行版的 `python3-venv` 软件包。

```sh
git clone --branch master https://github.com/ylty1516/xiaoheihe-agent.git
cd xiaoheihe-agent
python3 -m venv .venv
.venv/bin/python -m pip install -e .
dsh plugin --profile web add "$PWD/integrations/dsh-go"
.venv/bin/xhh auto --no-open --root "$PWD"
```

保留最后的服务进程；也可使用当前主机已有的进程管理器运行。模型沿用项目本机配置，或在启动服务前设置 `XHH_LLM_BASE_URL`、`XHH_LLM_MODEL`、`XHH_LLM_API_KEY`。DSH 聊天模型的密钥不会被插件自动读取。发起社区查询前先 `xhh login`；已有资料成稿可以不登录。账号与密钥留在当前主机，不写进插件清单。

已有安装：`git pull --ff-only` 后重新执行 `.venv/bin/python -m pip install -e .`，再重启小黑盒服务和 DSH 引擎。

项目放在哪里都可以，安装后的插件链接不能删除。更新 `lib/` 代码后按 DSH Go 说明重启引擎；Python 代码更新后重启小黑盒服务。

## 远程连接电脑

插件代码和小黑盒后端必须装在同一个 DSH 主机上，连接的是主机的 `127.0.0.1:8765`，不是手机的回环地址。可通过 SSH 使用电脑主机；原生胶囊和面板还要求该主机具备 DSH Go 原生桥接。只有普通 DSH/DSHarness Remote 而没有桥接时，不能保证这些原生入口显示，可直接在聊天中调用现有 CLI。

已有后端监听其他端口时，在 DSH 引擎环境设置 `XHH_WEBUI_URL=http://127.0.0.1:端口`。仅允许回环地址，不要把带账号权限的 WebUI 绑定到 `0.0.0.0` 或映射到公网。手机本机引擎与电脑是两套会话、文件与模型配置，不自动复制凭据。

## 图片和实际验证范围

等待生图时点「交给助手」，助手按当前宿主提供的工具与已有授权接续。DSH Go 本身不等于拥有 Codex 的内置生图能力，也不保证提供 `image2.5`；没有生图工具时保留正文与待配图任务。

适配采用 v1 原生 JSON 组件，不依赖 WebView 或桌面宽度。已用上游 SDK 的 `--load` 检查原生清单、处理器和全部面板位置，并用 Node 测试验证真实 HTTP 契约、重复点按、断网与订阅释放；没有在 Android 真机安装 APK 验证。

```sh
node --test integrations/dsh-go/test/*.test.js
# 在 dsh-Go 仓库检出上述基准提交后：
node /path/to/dsh-Go/sdk/plugin-kit/bin/check.mjs integrations/dsh-go --load
```
