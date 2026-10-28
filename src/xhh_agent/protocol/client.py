"""协议层客户端：唯一发起网络请求的模块。

P0 阶段**不包含任何发送能力**——没有 ``submit_*`` / ``reply_*`` / ``send_*``。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

import aiohttp

from xhh_agent.config import Config

from .errors import LoginExpired, SchemaChanged, TransportError
from .models import Account, InboxItem, InboxPage, QrPollResult, QrTicket
from .session import Session
from .signer import create_signed_params

logger = logging.getLogger(__name__)

API_ORIGIN = "https://api.xiaoheihe.cn"
WEB_ORIGIN = "https://www.xiaoheihe.cn"

QRCODE_URL_PATH = "/account/get_qrcode_url/"
QR_STATE_PATH = "/account/qr_state/"
MESSAGE_PATH = "/bbs/app/user/message"

#: 评论类消息的 message_type。移植自上游 fetch_comment_messages。
COMMENT_MESSAGE_TYPES = {"1", "2"}

#: 回复目标 ID 的候选字段名（上游用深度搜索）。
_REPLY_ID_KEYS = (
    "comment_id",
    "commentid",
    "commentId",
    "comment_a_id",
    "replyid",
    "reply_id",
    "cid",
)

_TAG_RE = re.compile(r"<[^>]+>")

#: 登录需要保留的 cookie。移植自上游 LOGIN_COOKIE_NAMES。
LOGIN_COOKIE_NAMES = {
    "user_pkey",
    "user_heybox_id",
    "heybox_id",
    "avatar",
    "level",
    "nickname",
    "x_xhh_tokenid",
}

#: 用户资料入口。P0 只用它验证会话有效性。
#: 注意：``username`` 为尽力而为解析，真实字段名需真机验收校正；
#: 取不到 username 不影响 whoami 的核心目的（确认会话未失效）。
WHOAMI_PATH = "/bbs/web/profile/post/links"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_EXPIRED_RE = re.compile(r"登录|login|unauthorized|\b401\b", flags=re.I)


@dataclass(frozen=True)
class RawResponse:
    """一次 HTTP 响应的最小表示。

    ``set_cookies`` 单独保存原始头：``dict(headers)`` 会把多个 ``Set-Cookie``
    合并成一个，登录时会丢掉除第一条以外的所有 cookie。
    """

    status: int
    data: Any
    set_cookies: tuple[str, ...] = ()
    headers: tuple[tuple[str, str], ...] = ()


def is_login_expired(data: Any) -> bool:
    """移植自上游 ``is_login_expired_response``。"""
    if not isinstance(data, dict):
        return False
    status = str(data.get("status") or "")
    text = " ".join(str(data.get(key) or "") for key in ("status", "msg", "message", "error"))
    return status in {"unauthorized", "login_required"} or bool(_EXPIRED_RE.search(text))


def _error_message(data: Any, fallback: str) -> str:
    if isinstance(data, dict):
        for key in ("msg", "message", "error"):
            value = data.get(key)
            if value:
                return str(value)
    return fallback


def _parse_cookie_value(cookie_header: str, name: str) -> str:
    parsed = SimpleCookie()
    try:
        parsed.load(str(cookie_header or ""))
    except Exception:
        return ""
    morsel = parsed.get(name)
    return morsel.value.strip() if morsel else ""


def _cookie_header_from_values(values: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in values.items() if name and value)


def _merge_cookie_headers(*headers: str) -> str:
    values: dict[str, str] = {}
    for header in headers:
        parsed = SimpleCookie()
        try:
            parsed.load(str(header or ""))
        except Exception:
            continue
        for name, morsel in parsed.items():
            value = str(morsel.value or "")
            if value:
                values[name] = value
    return _cookie_header_from_values(values)


def _strip_html(value: str) -> str:
    return _TAG_RE.sub("", value).replace("&nbsp;", " ").strip()


def _link_id_of(message: dict[str, Any]) -> str:
    for key in ("link", "target"):
        container = message.get(key)
        if isinstance(container, dict):
            for field in ("linkid", "link_id"):
                if container.get(field):
                    return str(container[field])
    for field in ("linkid", "link_id"):
        if message.get(field):
            return str(message[field])
    return ""


def _message_text(message: dict[str, Any]) -> str:
    for key in ("comment_a_text", "comment_text", "msg", "text", "content"):
        value = message.get(key)
        if value:
            return _strip_html(str(value))
    return ""


def _message_timestamp(message: dict[str, Any]) -> int:
    raw = message.get("timestamp") or message.get("time")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise SchemaChanged(f"消息时间戳不是数字：{raw!r}") from None
    if value <= 0:
        raise SchemaChanged(f"消息时间戳无效：{raw!r}")
    # 兼容毫秒
    return int(value / 1000) if value > 100_000_000_000 else int(value)


def _find_deep(node: Any, keys: tuple[str, ...], depth: int = 3) -> str:
    """深度优先查找第一个非空字段。上游用同类做法应对嵌套结构差异。"""
    if depth < 0:
        return ""
    if isinstance(node, dict):
        for key in keys:
            value = node.get(key)
            if value:
                return str(value)
        for value in node.values():
            found = _find_deep(value, keys, depth - 1)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_deep(item, keys, depth - 1)
            if found:
                return found
    return ""


def _collect_login_cookie(set_cookies: tuple[str, ...], existing: str) -> str:
    """从 Set-Cookie 头收集登录所需的 cookie。移植自上游行为。"""
    values: dict[str, str] = {}
    for header in set_cookies:
        parsed = SimpleCookie()
        try:
            parsed.load(header)
        except Exception:
            continue
        for name, morsel in parsed.items():
            if name in LOGIN_COOKIE_NAMES and str(morsel.value or ""):
                values[name] = morsel.value

    merged = _merge_cookie_headers(existing, _cookie_header_from_values(values))

    filtered: dict[str, str] = {}
    parsed = SimpleCookie()
    try:
        parsed.load(merged)
        for name, morsel in parsed.items():
            if name in LOGIN_COOKIE_NAMES and str(morsel.value or ""):
                filtered[name] = morsel.value
    except Exception:
        return merged
    return _cookie_header_from_values(filtered)


class ProtocolClient:
    def __init__(self, session: Session, config: Config) -> None:
        self.session = session
        self.config = config
        self._http: aiohttp.ClientSession | None = None

    # ── 基础设施 ────────────────────────────────────────────

    @property
    def heybox_id(self) -> str:
        return self.session.heybox_id

    def build_api_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        """拼接带签名的 API URL。

        注意：**不要把这个方法的返回值打进日志**——query 里有 hkey。
        """
        query: dict[str, Any] = dict(params or {})
        query.update(create_signed_params(path))
        if self.heybox_id:
            query.setdefault("heybox_id", self.heybox_id)
        return f"{API_ORIGIN}{path}?{urlencode(query)}"

    async def _get_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                headers={
                    "Cookie": self.session.cookie,
                    "User-Agent": _UA,
                    "Referer": "https://www.xiaoheihe.cn/",
                },
            )
        return self._http

    async def _raw_request(
        self, method: str, url: str, **kwargs: Any
    ) -> RawResponse:
        """唯一真正发出 HTTP 的入口。测试替换这个方法。"""
        http = await self._get_http()
        async with http.request(method, url, **kwargs) as response:
            try:
                data = await response.json(content_type=None)
            except Exception:
                text = await response.text()
                raise TransportError(
                    f"{method} {url.split('?')[0]} 返回非 JSON（HTTP {response.status}）"
                    f"：{text[:200]}"
                ) from None
            return RawResponse(
                status=response.status,
                data=data,
                set_cookies=tuple(response.headers.getall("Set-Cookie", [])),
                headers=tuple(response.headers.items()),
            )

    async def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        raw = await self._raw_request(method, url, **kwargs)
        data, status = raw.data, raw.status
        path = url.split("?")[0]
        if is_login_expired(data) or status == 401:
            raise LoginExpired(f"{path} 提示登录态失效，请运行 'xhh login' 重新登录")
        if status >= 400:
            raise TransportError(f"{path} 请求失败：HTTP {status}")
        if not isinstance(data, dict):
            raise SchemaChanged(f"{path} 返回结构变更：顶层不是对象")
        return data

    # ── 接口 ────────────────────────────────────────────────

    async def whoami(self) -> Account:
        url = self.build_api_url(WHOAMI_PATH, {"offset": 0, "limit": 1})
        data = await self._request_json("GET", url)

        result = data.get("result")
        if not isinstance(result, dict) or not result:
            raise SchemaChanged(
                f"{WHOAMI_PATH} 返回空 result。可能是接口结构变更，"
                "而不是账号无效——请核对后更新解析逻辑。"
            )

        user = result.get("user") if isinstance(result.get("user"), dict) else {}
        # 审查 I3：不能拿本地 session 的 heybox_id 拼一个"会话有效"的结论——那是自证。
        heybox_id = str(user.get("heybox_id") or "") if user else ""
        if not heybox_id:
            raise SchemaChanged(
                f"{WHOAMI_PATH} 响应中没有 user.heybox_id。这是接口结构变更，"
                "不能据此判定会话有效。"
            )

        level_info = user.get("level_info") if isinstance(user.get("level_info"), dict) else {}
        try:
            level = int(level_info.get("level") or 0)
        except (TypeError, ValueError):
            level = 0

        return Account(
            heybox_id=heybox_id,
            username=str(user.get("username") or ""),
            level=level,
        )

    async def server_time(self) -> int | None:
        """取服务端时间（HTTP ``Date`` 头）。

        拿不到就返回 ``None``，**绝不回退本地时间**：一个时间自检在测不到时
        报 OK，比没有自检更糟——它会主动给用户一个错误的安心结论。
        """
        url = self.build_api_url(
            MESSAGE_PATH,
            {"message_type": "", "list_type": "0", "offset": "0", "limit": "1"},
        )
        raw = await self._raw_request("GET", url)
        for key, value in raw.headers:
            if str(key).lower() == "date":
                try:
                    return int(parsedate_to_datetime(value).timestamp())
                except (TypeError, ValueError):
                    return None
        return None

    # ── 收件箱（只读，P0 不回复任何内容）───────────────────

    async def fetch_inbox(self, *, limit: int = 20) -> InboxPage:
        """拉取三类消息：评论 / @提及 / 私信。

        自己的消息会被过滤掉——不回复自己是最低要求。

        逐条解析失败的消息**不会静默消失**：会计入 ``dropped`` 并告警；
        若全部解析失败（典型信号是接口字段改名），直接抛 ``SchemaChanged``。
        否则调用方会看到 ``count: 0`` 和退出码 0，误以为“没人找我”。
        """
        items: list[InboxItem] = []
        dropped = 0

        for channel, message_type in (("comment", ""), ("mention", "16")):
            got, lost = await self._fetch_message_channel(message_type, channel, limit)
            items.extend(got)
            dropped += lost

        got, lost = await self._fetch_direct_message_channel(limit)
        items.extend(got)
        dropped += lost

        total = len(items) + dropped
        if total and not items:
            raise SchemaChanged(
                f"{MESSAGE_PATH} 返回了 {total} 条消息，但全部因字段缺失无法解析。"
                "这是接口结构变更，不是'没有未读'——请核对后更新解析逻辑。"
            )
        if dropped:
            logger.warning(
                "%d 条消息因字段缺失被跳过（接口可能已变更，建议跑 xhh doctor）",
                dropped,
            )

        return InboxPage(
            items=[item for item in items if item.sender_id != self.heybox_id],
            dropped=dropped,
        )

    async def _fetch_message_list(
        self, *, message_type: str, limit: int, list_type: str = "0"
    ) -> list[dict[str, Any]]:
        url = self.build_api_url(
            MESSAGE_PATH,
            {
                "message_type": message_type,
                "list_type": list_type,
                "offset": "0",
                "limit": str(limit),
            },
        )
        data = await self._request_json("GET", url)
        result = data.get("result")
        if not isinstance(result, dict) or "messages" not in result:
            raise SchemaChanged(
                f"{MESSAGE_PATH} 响应缺少 result.messages。这是接口结构变更，"
                "不是'没有新消息'——请核对后再更新解析逻辑。"
            )
        messages = result.get("messages")
        if not isinstance(messages, list):
            raise SchemaChanged(f"{MESSAGE_PATH} 的 result.messages 不是数组")
        return [message for message in messages if isinstance(message, dict)]

    async def _fetch_message_channel(
        self, message_type: str, channel: str, limit: int
    ) -> tuple[list[InboxItem], int]:
        items: list[InboxItem] = []
        dropped = 0
        for message in await self._fetch_message_list(message_type=message_type, limit=limit):
            if channel == "comment" and str(
                message.get("message_type") or ""
            ) not in COMMENT_MESSAGE_TYPES:
                # 点赞/关注等非评论通知，不出现在评论区通道，也不算丢弃
                continue
            item = self._to_comment_item(message, channel)
            if item is None:
                dropped += 1
            else:
                items.append(item)
        return items, dropped

    async def _fetch_direct_message_channel(self, limit: int) -> tuple[list[InboxItem], int]:
        items: list[InboxItem] = []
        dropped = 0
        messages = await self._fetch_message_list(
            message_type="", limit=limit, list_type="2"
        )
        for message in messages:
            if str(message.get("entry") or "") != "message":
                continue
            item = self._to_dm_item(message)
            if item is None:
                dropped += 1
            else:
                items.append(item)
        return items, dropped

    def _to_comment_item(self, message: dict[str, Any], channel: str) -> InboxItem | None:
        link_id = _link_id_of(message)
        reply_id = _find_deep(message, _REPLY_ID_KEYS)
        if not link_id or not reply_id:
            # 没有回复目标就无法回复，跳过而不是崩溃
            return None

        user = message.get("user_a") if isinstance(message.get("user_a"), dict) else {}
        sender_id = str(user.get("heybox_id") or user.get("userid") or "")
        sender_name = str(user.get("username") or user.get("nickname") or sender_id)

        # message_id 缺失时兜底。注意：同一 reply 下的多条消息会撞键，
        # 所以 raw_message_type 必须保留，供 P2 的幂等键区分。
        message_id = str(message.get("message_id") or "") or f"{link_id}:{reply_id}"

        return InboxItem(
            channel=channel,
            message_id=message_id,
            sender_id=sender_id,
            sender_name=sender_name,
            text=_message_text(message),
            timestamp=_message_timestamp(message),
            raw_message_type=str(message.get("message_type") or ""),
            link_id=link_id,
            reply_id=reply_id,
            root_id=reply_id,
        )

    def _to_dm_item(self, message: dict[str, Any]) -> InboxItem | None:
        user = message.get("user_a") if isinstance(message.get("user_a"), dict) else {}
        sender_id = str(user.get("heybox_id") or user.get("userid") or "")
        if not sender_id:
            return None
        sender_name = str(user.get("username") or user.get("nickname") or sender_id)
        timestamp = _message_timestamp(message)
        message_id = str(message.get("message_id") or "") or f"dm:{sender_id}:{timestamp}"

        return InboxItem(
            channel="dm",
            message_id=message_id,
            sender_id=sender_id,
            sender_name=sender_name,
            text=_message_text(message),
            timestamp=timestamp,
            raw_message_type=str(message.get("message_type") or ""),
        )

    def build_login_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        """登录接口不走签名，因此单独一个 URL 构造方法。"""
        query = urlencode(params or {})
        return f"{WEB_ORIGIN}{path}?{query}" if query else f"{WEB_ORIGIN}{path}"

    async def request_qr_login(self) -> QrTicket:
        url = self.build_login_url(QRCODE_URL_PATH, {"app": "web", "_notip": "true"})
        data = await self._request_json("GET", url)
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        qr_url = str(result.get("qr_url") or "")
        if not qr_url:
            raise SchemaChanged(f"{QRCODE_URL_PATH} 未返回 qr_url，接口可能已变更")
        qr_id = str(dict(parse_qsl(urlparse(qr_url).query)).get("qr") or "")
        if not qr_id:
            raise SchemaChanged(f"{QRCODE_URL_PATH} 返回的 qr_url 不含 qr 参数")
        try:
            expire = int(result.get("expire") or 120)
        except (TypeError, ValueError):
            expire = 120
        return QrTicket(qr=qr_id, qr_url=qr_url, expire=expire)

    async def poll_qr_login(self, qr: str) -> QrPollResult:
        if not qr:
            raise SchemaChanged("poll_qr_login 需要 qr 参数")
        url = self.build_login_url(QR_STATE_PATH, {"qr": qr, "app": "web"})
        raw = await self._raw_request("GET", url)
        data = raw.data
        if not isinstance(data, dict):
            raise SchemaChanged(f"{QR_STATE_PATH} 返回结构变更：顶层不是对象")
        if data.get("status") != "ok":
            raise TransportError(
                f"{QR_STATE_PATH} 请求失败：{_error_message(data, 'unknown')}"
            )

        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        state = str(result.get("error") or "wait")
        message = str(result.get("error_msg") or "")

        if state in {"wait", "ready"}:
            return QrPollResult(status="pending", message=message)
        if state in {"cancel", "canceled", "denied"}:
            return QrPollResult(status="denied", message=message or "已取消")
        if state in {"timeout", "expired"}:
            return QrPollResult(status="expired", message=message or "二维码已过期")
        if state != "ok":
            return QrPollResult(status="error", message=message or f"未知状态: {state}")

        cookie = _collect_login_cookie(raw.set_cookies, self.session.cookie)
        heybox_id = (
            str(result.get("heyboxid") or "")
            or _parse_cookie_value(cookie, "heybox_id")
            or _parse_cookie_value(cookie, "user_heybox_id")
        )
        if not cookie:
            raise SchemaChanged("扫码成功但未收到登录 cookie，接口可能已变更")
        if not heybox_id:
            raise SchemaChanged("扫码成功但未拿到 heybox_id，接口可能已变更")

        return QrPollResult(
            status="ok",
            session=Session(
                cookie=cookie,
                heybox_id=heybox_id,
                device_id=self.session.device_id,
            ),
        )

    async def login_and_save(
        self,
        store: Any,
        *,
        ticket: QrTicket | None = None,
        interval_seconds: float = 1.5,
        max_wait_seconds: float | None = None,
    ) -> QrPollResult:
        """完整扫码流程：取码 → 轮询 → 成功后落盘。

        ``ticket`` 可传入已展示给用户的二维码，避免重复取码。
        """
        ticket = ticket or await self.request_qr_login()
        deadline = time.monotonic() + (max_wait_seconds or float(ticket.expire))
        while time.monotonic() < deadline:
            result = await self.poll_qr_login(ticket.qr)
            if result.status == "ok":
                assert result.session is not None
                store.save(result.session)
                logger.info("登录成功，会话已保存（heybox_id=%s）", result.session.heybox_id)
                return result
            if result.status in {"denied", "expired", "error"}:
                return result
            await asyncio.sleep(interval_seconds)
        return QrPollResult(status="expired", message="扫码超时")

    async def close(self) -> None:
        if self._http is not None and not self._http.closed:
            await self._http.close()
        self._http = None

    async def __aenter__(self) -> "ProtocolClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
