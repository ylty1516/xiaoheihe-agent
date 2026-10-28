"""协议层异常。

构造这些异常时**只允许**携带接口路径与 HTTP 状态码。
绝不允许携带完整 URL（query 里有 hkey）或 Cookie 原值——
异常会被打进日志、也可能出现在 agent 的上下文里。
"""

from __future__ import annotations


class XhhError(Exception):
    """所有协议层异常的基类。"""


class LoginExpired(XhhError):
    """会话缺失或失效。CLI 以退出码 3 结束。"""


class SchemaChanged(XhhError):
    """接口返回结构变化。

    宁可抛出这个，也不要静默返回空列表——空列表会让人误以为"没人找我"。
    """


class TransportError(XhhError):
    """网络或 HTTP 层失败。"""


class RateLimited(XhhError):
    """被平台限流。"""
