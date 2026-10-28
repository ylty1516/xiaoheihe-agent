"""协议层：唯一允许发起网络请求的模块。

职责：
- 签名参数生成（hkey / _time / nonce）
- 扫码登录与 Cookie 会话持久化
- 接口封装：读消息、读私信、发帖、发评论、发私信
- 把接口原始 JSON 归一化成内部 dataclass

约束：
- 不含任何业务判断（不决定"该不该回"、"回什么"）
- 不含重试策略以外的编排逻辑
- 改造自 xhh_client.py（Apache-2.0）

参照：docs/superpowers/specs/*-design.md 第 3 节
"""
