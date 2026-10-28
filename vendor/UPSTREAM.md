# 上游依赖溯源

本项目复用两个开源项目的代码。修改上游代码时必须在此登记，便于接口改版时比对更新。

---

## 1. advent259141/astrbot_plugin_xiaoheihe_adapter

- **用途**：协议层底座（签名、扫码登录、HTTP 接口封装）
- **原文件**：`xhh_client.py`（约 101 KB）
- **目标位置**：`src/xhh_agent/protocol/`
- **许可证**：Apache-2.0
- **义务**：保留版权声明与 NOTICE，修改过的文件需标注修改说明

**将复用的部分**：
- `create_signed_params(path)` — `hkey` / `_time` / `nonce` 生成
- `request_qr_login` / `poll_qr_login` — 纯 HTTP 扫码登录
- `submit_comment` — `POST /bbs/app/comment/create`
- `submit_direct_message` — `POST /chatroom/v2/msg/user`，`msg_type=6`
- `submit_post` — `POST /bbs/app/api/link/post`
- `fetch_comment_messages` / `fetch_direct_message_entries` — 读消息
- COS 图片上传流程

**不复用的部分**（与 AstrBot 插件框架耦合）：
- `__init__(config: dict)` 构造函数
- 插件 logger、错误类型
- 会话/事件分发逻辑

**待办**：clone 上游后 pin 到具体 commit，把 commit hash 补记在此。

---

## 2. opxqo/xiaoheihe-cli

- **用途**：排版层 —— Markdown → 小黑盒兼容 HTML
- **原文件**：`markdown_converter.py`（约 36 KB）
- **目标位置**：`src/xhh_agent/content/`
- **许可证**：MIT
- **义务**：保留版权声明

**为什么值得复用**：小黑盒的 HTML 白名单窄，代码块和表格容易塌。上游有一个专门的
问题报告 `docs/server-publish-format-report-2026-04-15.md` 记录了踩过的坑，
这些经验比代码本身更值钱。

---

## 3. k1m0206/better-XiaoHeiHe

- **用途**：**仅作参数核对参考**，不复制代码
- **形态**：浏览器扩展（JS）
- **价值**：`src/content.js` 里是前端真实提交的参数，字段名和取值可直接对照

---

## 许可证兼容性

| 上游 | 许可证 | 与本项目（MIT）兼容 |
|---|---|---|
| advent259141/… | Apache-2.0 | 是（需保留声明 + 标注修改） |
| opxqo/xiaoheihe-cli | MIT | 是 |
| k1m0206/better-XiaoHeiHe | 见上游仓库 | 仅参考参数，不复制 |

Apache-2.0 → MIT 是单向兼容：可以引入 Apache-2.0 代码到 MIT 项目中，但被引入的
文件需保留 Apache-2.0 声明，整体分发时需附带 NOTICE。
