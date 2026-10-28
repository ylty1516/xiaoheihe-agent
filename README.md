# xiaoheihe-agent

让 AI agent 通过**自己的**小黑盒账号发帖、回复评论、回复私信。

> **状态：设计阶段，无可运行代码。**
> 本仓库目前只有架构规格与骨架。功能实现需先审阅
> [`docs/superpowers/specs/`](docs/superpowers/specs/) 下的规格文档。

---

## 这个项目解决什么

小黑盒没有开放的发帖/互动 API。官方只提供 SDK 和机器人协议（`docs.xiaoheihe.cn`），
不覆盖社区发帖。所以本项目基于 Web 端接口实现三条能力：

| 能力 | 接口 | 风险 |
|---|---|---|
| 发帖 / 存草稿 | `/bbs/app/api/link/post` | 中 |
| 回复评论 / @我 | `/bbs/app/comment/create` | 中 |
| 回复私信 | `/chatroom/v2/msg/user` (POST) | **高** |

三条链路都不是公开接口。它们随时可能改版、加签名、封 Cookie。

## 三条设计红线

这三条不是建议，是项目的硬约束：

1. **不否认 AI 身份。** 账号由真人与 AI 混合运营。不在每条内容上标注 AI（那会
   把账号变成 AI 号），但被直接问到时必须承认。
2. **不替真人编造经历。** AI 可以写观点、评测、攻略、推荐，不能写"我今天去店里试了"。
   判定：这句话是否声称了一件实际发生过、且 AI 无从知晓的事？
3. **不批量。** 任何通道都有硬性频率闸门。批量发帖/批量私信是风控首要打击特征，
   也是这个项目最可能造成实际后果的地方。
4. **幂等优先。** 同一个消息 ID 绝不回复两次。宁可漏回，不可重发。

第 1、2 条的完整定义见规格 §2 C1 / C4。

## 不做什么

- 不做多账号 / 矩阵运营
- 不做批量私信营销
- 不做爬虫采集他人数据
- 不做绕过平台风控的对抗（不改设备指纹、不伪造 UA 池）

## 技术选型

| 层 | 方案 | 来源 | 许可证 |
|---|---|---|---|
| 协议层 | 改造 `xhh_client.py` | [advent259141/astrbot_plugin_xiaoheihe_adapter](https://github.com/advent259141/astrbot_plugin_xiaoheihe_adapter) | Apache-2.0 |
| 排版层 | Markdown → 小黑盒 HTML | [opxqo/xiaoheihe-cli](https://github.com/opxqo/xiaoheihe-cli) | MIT |
| 编排层 | 自研 | — | — |

选 Python + 纯 HTTP 而非 Playwright：不需要常驻 Chromium，agent 启动即可工作，
资源开销小一个量级。代价是签名逻辑失效时需要跟进修补。

## 目录结构

```
src/xhh_agent/
├── protocol/     # 协议层：签名、登录、HTTP 请求、接口封装
├── content/      # 排版层：Markdown 转换、图片处理、字数校验
├── automation/   # 编排层：轮询、去重、频率闸门、回复生成
├── store/        # 状态层：幂等表、审核队列、发送记录
└── cli/          # 命令行入口
```

## 开发环境

需要 Python 3.11+（开发用 3.13.5）。

```bash
# Windows 下注意：用 py，不要用 python（后者是 Microsoft Store 的假 shim）
py -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev]"
```

## 风险声明

本项目使用非公开接口，**违反平台用户协议的可能性很高**。可能的后果包括但不限于：
账号被限流、被禁言、被封禁，内容被删除。

作者不对使用后果负责。请自行评估：
- 这是不是你的主号
- 账号上有没有你舍不得丢的东西
- 你能不能接受它某天突然没了

如果答案是"不能"，建议只用**存草稿**能力，发布动作自己点。
