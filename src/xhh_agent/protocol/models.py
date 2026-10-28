"""协议层数据模型。全部 frozen，避免解析后被意外改写。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Account:
    heybox_id: str
    username: str
    level: int = 0


@dataclass(frozen=True)
class InboxItem:
    """一条待处理的消息。

    ``raw_message_type`` 必须保留：``message_id`` 可能被上游兜底成
    ``f"{link_id}:{reply_id}"``，同一个 reply 下的"赞"和"回复"会撞键，
    P2 的幂等键需要靠它区分。
    """

    channel: str                 # comment | mention | dm
    message_id: str
    sender_id: str
    sender_name: str
    text: str
    timestamp: int
    raw_message_type: str
    link_id: str | None = None
    reply_id: str | None = None
    root_id: str | None = None


@dataclass(frozen=True)
class InboxPage:
    items: list[InboxItem] = field(default_factory=list)
    has_more: bool = False
    #: 因为字段缺失而无法解析的消息数。不为 0 说明接口结构可能变了，
    #: 必须让调用方看得见——静默丢弃会让人误以为"没人找我"。
    dropped: int = 0


@dataclass(frozen=True)
class QrTicket:
    qr: str
    qr_url: str
    expire: int


@dataclass(frozen=True)
class QrPollResult:
    status: str                  # pending | ok
    session: object | None = None
    message: str = ""
