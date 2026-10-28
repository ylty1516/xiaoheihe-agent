"""xiaoheihe-agent：让 AI agent 通过自己的小黑盒账号发帖与回复。

模块划分（严格单向依赖，下层不知道上层存在）：

    protocol  ←  content  ←  automation  ←  cli
        ↑           ↑            ↑
        └───────────┴── store ───┘

- protocol   协议层：签名、登录、HTTP 请求、接口封装。唯一碰网络的模块。
- content    排版层：Markdown → 小黑盒 HTML、图片处理。
- automation 编排层：轮询、幂等去重、频率闸门、回复生成。
- store      状态层：SQLite。幂等表、审核队列、发送记录。
- cli        入口层：命令行。
"""

__version__ = "0.3.0"
