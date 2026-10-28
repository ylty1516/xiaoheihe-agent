# xiaoheihe-agent

让 AI agent 用**你自己的**小黑盒账号发帖、回评论、回私信 ——
像一个真的在用这个号的人，而不是一个自动回复机器人。

> **状态：P0 已通过真机验收，P3 的发送链路已打通，P1/P2 未开始。**
> 设计规格见 [`docs/superpowers/specs/`](docs/superpowers/specs/)，
> 实现计划见 [`docs/superpowers/plans/`](docs/superpowers/plans/)。

---

## 这个项目要做什么

四个方向，也是后续主要投入的地方：

| # | 方向 | 说明 | 状态 |
|---|---|---|---|
| 1 | **自动发帖** | agent 写稿 → 转成小黑盒能正确渲染的 HTML → 存草稿或发布 | 待做 |
| 2 | **回评论** | 别人评论你的帖子、@你时，生成并发出回复 | 待做 |
| 3 | **回私信** | 一对一会话，回答别人的问题 | 发送已通，决策/历史待做 |
| 4 | **自己帖子的互动** | 自家帖子下的评论回复与维护 | 待做 |

共同目标不是"能自动发东西"，而是**发出来看不出是机器** —— 见下一节。

## 「像真人一样」到底指什么

这是本项目的核心质量要求，但它**有边界**。为了"像人"而越过边界，是这条路上最容易出的事。

**要做到的：**

- 语气像人：句子长短有变化、不写"综上所述"、不列整齐的三点式清单、会用口语和省略
- 像人一样有保留：不确定就说不确定，不顺杆爬，不假装什么都知道
- 有分寸：别人的负面反馈、交易邀约、要求承诺的对话，交给人处理而不是硬答（规格 §5.7 第二道门）

**不能越过的：**

- **不编造第一人称经历。** AI 可以写"我觉得这作战斗偏慢"，不能写"我上周打了 40 小时"。判定标准是一句话：这件事是否实际发生过、且 AI 无从知晓？（规格 §2 C4）
- **不否认 AI 身份。** 不会每条都标注 AI（那会把这个号变成 AI 号），但被直接问到就必须承认（规格 §2 C1）
- **不批量。** 逐条乱回是最快暴露机器的行为，也最容易招人反感。所有通道都有写死在代码里的频率上限

「像真人」是**表达方式**的追求，不是**事实层面**的伪装。这两件事分开，项目才站得住。

## 三条硬约束（写在代码里，不是建议）

1. **不批量** —— 频率上限写死在 `HARD_LIMITS`，环境变量只能调低不能调高
2. **幂等优先** —— 同一条消息绝不回复两次。宁可漏回，不可重发
3. **不编造经历 / 不否认 AI 身份** —— 见上一节

## 能力与接口

小黑盒没有覆盖社区互动的开放 API（官方只提供 SDK 与机器人协议）。本项目基于 Web 端非公开接口实现：

| 能力 | 接口 | 状态 |
|---|---|---|
| 读消息（评论 / @ / 私信入口） | `GET /bbs/app/user/message` | ✅ 已验证 |
| 扫码登录 | `/account/get_qrcode_url/` + `/account/qr_state/` | ✅ 已验证 |
| 回评论 | `POST /bbs/app/comment/create` | 未实现 |
| 发帖 / 存草稿 | `POST /bbs/app/api/link/post` | 未实现 |
| 发私信 | `POST /chatroom/v2/msg/user`（`msg_type=6`） | ✅ 已验证 |
| 拉私信历史 | `GET /chatroom/v2/msg/user` | 未实现 |

关键前提：所有签名接口都要求一组 **web 客户端标识参数**（`os_type`/`app`/`client_type`/`version`/`x_app` 等 9 个）。缺了它们，服务端会对有效的 Cookie 回 `status=relogin` —— 表现为"登录成功了但什么都拉不到"。

## 技术选型

| 层 | 方案 | 来源 | 许可证 |
|---|---|---|---|
| 协议层 | 改造 `xhh_client.py` | [advent259141/astrbot_plugin_xiaoheihe_adapter](https://github.com/advent259141/astrbot_plugin_xiaoheihe_adapter) | Apache-2.0 |
| 排版层 | Markdown → 小黑盒 HTML | [opxqo/xiaoheihe-cli](https://github.com/opxqo/xiaoheihe-cli) | MIT |
| 编排层 | 自研 | — | MIT |

签名在纯 Python 里算，**不需要 Playwright 或浏览器**。代价是平台改签名算法时要跟进修补（缓解措施见规格 §7.2）。

## 当前进度

| 阶段 | 内容 | 状态 |
|---|---|---|
| **P0** | 协议基础层：登录 / `whoami` / `doctor` / 只读 `inbox` | ✅ 真机验收通过（58 测试） |
| **P1** | 发帖：Markdown → HTML 转换、存草稿 | 未开始 |
| **P2** | 回评论：幂等表、频率闸门、回复决策三道门、审核队列 | 未开始 |
| **P3** | 私信：发送（✅ 已通）、历史拉取、决策门 | 部分 |

## 快速开始

需要 Python 3.11+（Windows 下用 `py`，不要用 `python` —— 那是 Microsoft Store 的假 shim）。

```bash
py -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev]"

xhh login          # 扫码登录，会话落 .data/session.json
xhh doctor         # 自检：会话 / 时钟 / 签名 / 收件箱
xhh inbox -f table # 只读看未读消息
xhh dm --to <user_id> --text "内容"         # dry-run，只打印请求
xhh dm --to <user_id> --text "内容" --send  # 真发
```

`xhh login` 会生成二维码图片并用系统看图程序打开 —— 用**小黑盒 App 扫一扫**扫屏幕。
那个二维码内容**不是网页**，粘进浏览器只会跳到"该功能需要登录使用"。

## 在 Pi / agent 里怎么用

仓库里带了一份 Pi skill：`skills/xiaoheihe-heybox/SKILL.md`。

```bash
cp -r skills/xiaoheihe-heybox ~/.agents/skills/
```

装好之后可以直接跟 agent 说：

- 「看看有没有新评论」→ 跑 `poll`、读队列、按语境写回复、dry-run 给你看
- 「发个帖子，主题是 xxx」→ 写稿、存草稿、给你预览
- 「给 xxx 发条私信」→ dry-run 确认后发送

skill 里写死了几条铁律，其中最重要的是：**发送前必须让你看过内容**，
以及**标了强制人工的条目（投诉/交易/质疑是否 AI）agent 不许自己回**。

## 迁移到新机器

### 要带走的东西

| 文件 | 含凭据 | 怎么处理 |
|---|---|---|
| 代码 | 否 | `git clone` |
| `voice/profile.md` | 否（含个人风格设定） | 手动复制 |
| `.env` | 否（只有偏好，不含 cookie） | 手动复制或重建 |
| `.data/session.json` | **是，等于账号密码** | **不要带**，新机器重新扫码 |
| `.data/xhh.db` | 否（互动历史与幂等记录） | 可选，带过去能保留已处理标记 |

**凭据不要搬运。** `session.json` 里的 cookie 就是完整登录态，走聊天工具、U 盘、
网盘传一遍就多一个泄露面。新机器上跑一次 `login` 扫个码，一分钟的事。

### 安装

Windows：

```bash
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

> Windows 上必须用 `py`，**不要用 `python`** —— 那是 Microsoft Store 的假 shim，
> 执行后什么都不做，也不报错。macOS / Linux 上则没有 `py` 这个命令。

### 验证

```bash
xhh login        # 扫码
xhh doctor       # 四项应全 OK
xhh inbox -n 3   # 能看到消息就说明通了
```

如果提示 `xhh: command not found`，说明脚本装到了 Python 的 `Scripts/` 目录但没进 PATH。
用模块路径代替：

```bash
py -m xhh_agent.cli.main doctor       # Windows
python3 -m xhh_agent.cli.main doctor  # macOS / Linux
```

### 部署 skill

```bash
cp -r skills/xiaoheihe-heybox ~/.agents/skills/
```

### 已验证的依赖版本

2026-10-28 在**全新虚拟环境**里验证通过（133 测试全绿）：

| 包 | 版本 |
|---|---|
| aiohttp | 3.14.1 |
| markdown | 3.11.2 |
| pygments | 2.20.0 |
| pillow | 12.2.0 |
| qrcode | 8.2 |
| requests | 2.34.2 |
| pytest | 9.1.1 |
| pytest-asyncio | 1.4.1 |

`pyproject.toml` 里给的是区间（下界是验证过的最低版本，上界防大版本破坏）。
装到区间外又出问题的话，优先按上表回退。

### 平台差异

| 项目 | Windows | macOS / Linux |
|---|---|---|
| Python 命令 | `py` | `python3` |
| 打开二维码图片 | `os.startfile` | `open` / `xdg-open` |
| 会话文件权限 | `chmod` 只影响只读位，实际依赖目录 ACL | `0600` 真实生效 |
| 控制台编码 | 默认 GBK，CLI 已在入口强制 UTF-8 | 通常已是 UTF-8 |

## 目录结构

```
src/xhh_agent/
├── config.py     配置加载（频率硬上限夹取）
├── protocol/     协议层：签名、登录、HTTP、接口封装（唯一碰网络）
├── content/      排版层：Markdown → 小黑盒 HTML（P1）
├── automation/   编排层：轮询、幂等、闸门、回复决策（P2）
├── store/        状态层：SQLite 幂等表 / 审核队列 / 发送记录（P2）
└── cli/          login · whoami · doctor · inbox · dm · draft · publish
                  poll · queue · reply
```

依赖方向严格单向：`cli → automation → {content, store}`，`protocol` 不 import 上层。

## 凭据安全

Cookie 等价于账号密码。因此：

- 只存在 `.data/session.json`，不进环境变量、不进命令行参数、不进日志
- 文件以 `0600` 创建（先创建后写入，不存在 0644 窗口）
- `Session.__repr__` 不含 cookie，`Config` 里压根没有 cookie 字段

**Windows 上的残余风险**：Windows 忽略 POSIX 权限位，`chmod` 只影响只读属性。
`.data/session.json` 实际可被同机其他用户读取，安全性依赖目录 ACL。
如果你的项目盘不是 per-user ACL 的分区，请注意这一点。

## 风险声明

本项目使用非公开接口，**违反平台用户协议的可能性很高**。可能的后果包括但不限于：
账号被限流、被禁言、被封禁，内容被删除。

如果你还没决定要不要这么做，先问自己三个问题：

- 这是不是你的主号
- 账号上有没有你舍不得丢的东西
- 你能不能接受它某天突然没了

如果答案是"不能"，建议只用**存草稿**能力，发布动作自己点。

作者不对使用后果负责。

## 不做什么

- 多账号 / 矩阵运营
- 批量私信、涨粉、营销
- 采集他人数据、爬取他人主页
- 对抗风控（不伪造设备指纹、不轮换 UA、不代理池）
