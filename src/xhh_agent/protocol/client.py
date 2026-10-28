"""协议层客户端：唯一发起网络请求的模块。

P0 阶段**不包含任何发送能力**——没有 ``submit_*`` / ``reply_*`` / ``send_*``。
"""

from __future__ import annotations

import asyncio
import json
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
from .models import (
    Account,
    DmMessage,
    FeedPost,
    InboxItem,
    InboxPage,
    PostResult,
    QrPollResult,
    QrTicket,
    SendResult,
)
from .session import Session
from .signer import create_signed_params

logger = logging.getLogger(__name__)

API_ORIGIN = "https://api.xiaoheihe.cn"
WEB_ORIGIN = "https://www.xiaoheihe.cn"

#: 服务端靠这组参数识别"合法的 web 客户端"。
#: 缺了它们，``/bbs/app/user/message`` 会返回 ``status=relogin``，
#: 即使 cookie 完全有效——表现为"登录了但什么都拉不到"。
#: 取自上游 ``build_api_url`` 的默认值。
WEB_CLIENT_PARAMS: dict[str, str] = {
    "os_type": "web",
    "app": "heybox",
    "client_type": "web",
    "version": "999.0.4",
    "web_version": "2.5",
    "x_client_type": "web",
    "x_app": "heybox_website",
    "x_os_type": "Windows",
    "device_info": "Chrome",
}

QRCODE_URL_PATH = "/account/get_qrcode_url/"
QR_STATE_PATH = "/account/qr_state/"
MESSAGE_PATH = "/bbs/app/user/message"
DIRECT_MESSAGE_PATH = "/chatroom/v2/msg/user"
POST_PATH = "/bbs/app/api/link/post"
COMMENT_CREATE_PATH = "/bbs/app/comment/create"
LINK_TREE_PATH = "/bbs/app/link/tree"
FEEDS_PATH = "/bbs/app/feeds"
TOPIC_SEARCH_PATH = "/bbs/app/api/post_editor/topic_selection/search"
LINK_DELETE_PATH = "/bbs/app/link/delete"
LINK_CHANGE_STATUS_PATH = "/bbs/app/link/change/status"

IMAGE_COPY_PATH = "/bbs/app/api/qcloud/cos/copy/image/by/url"

#: HTML 里的 <img src="...">。发帖前要把外部图片换成小黑盒 CDN 地址，
#: 否则会被防盗链拦掉，帖子里只剩裂图。
_IMG_TAG_RE = re.compile(r'<img[^>]*?src="([^"]+)"[^>]*>', re.IGNORECASE)

#: 默认话题：PC游戏。实测有效，发帖必须有话题否则回"请添加分区"。
DEFAULT_TOPIC_IDS = ("1",)

#: 草稿没有分区时服务端可能拒，上游塞这个默认分区。
DEFAULT_TOPIC_ID = "58144"
LINK_TAG_DEFAULT_TOPIC = 28
LINK_TAG_NORMAL = 27
#: 默认发"文章"类型（11）。xiaoheihe-cli 的默认值，可正常发布。
LINK_TAG_ARTICLE = 11

#: 私信正文长度上限。规格 §5.7：回复上限 200 字，这里留宽一点供人工使用。
DM_MAX_LENGTH = 500

#: 评论回复长度上限（规格 §5.7）。评论区不是发帖区，长篇大论不像人说话。
REPLY_MAX_LENGTH = 200

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


def _link_title_of(message: dict[str, Any]) -> str:
    link = message.get("link") if isinstance(message.get("link"), dict) else {}
    return str(link.get("title") or "").strip()


def _message_text_of(message: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = message.get(key)
        if value:
            return _strip_html(str(value))
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


@dataclass(frozen=True)
class DmRequest:
    """一条待发送的私信请求。``url`` 里带 hkey，打印时必须脱敏。"""

    to_user_id: str
    text: str
    url: str
    body: dict[str, str]
    headers: dict[str, str]


def _link_tag_for(topics: list[str]) -> int:
    """帖子类型跟着分区走。

    实测组合错误会直接被拒：
    - 无分区 → 服务端回"请添加分区"，所以草稿能过、正式发布不行
    - 文章型(11) 配分区 → 回"错误的动态类型"
    """
    if not topics:
        return LINK_TAG_ARTICLE
    if topics == [DEFAULT_TOPIC_ID]:
        return LINK_TAG_DEFAULT_TOPIC
    return LINK_TAG_NORMAL


class ProtocolClient:
    def __init__(self, session: Session, config: Config) -> None:
        self.session = session
        self.config = config
        self._http: aiohttp.ClientSession | None = None
        self._ack_id: int | None = None

    # ── 基础设施 ────────────────────────────────────────────

    @property
    def heybox_id(self) -> str:
        return self.session.heybox_id

    def build_api_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        """拼接带签名的 API URL。

        顺序很重要：web 客户端参数 → device_id / heybox_id → 调用方参数 → 签名。
        这样调用方可以显式覆盖默认值（上游用同样的 update 顺序）。

        注意：**不要把这个方法的返回值打进日志**——query 里有 hkey。
        """
        query: dict[str, Any] = dict(WEB_CLIENT_PARAMS)
        if self.session.device_id:
            query["device_id"] = self.session.device_id
        if self.heybox_id:
            query["heybox_id"] = self.heybox_id
        if params:
            query.update({key: value for key, value in params.items() if value is not None})
        query.update(create_signed_params(path))
        return f"{API_ORIGIN}{path}?{urlencode(query)}"

    async def _get_http(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                headers={
                    "Cookie": self.session.cookie,
                    "User-Agent": _UA,
                    "Referer": f"{WEB_ORIGIN}/",
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
        """用消息接口验证会话有效。

        为什么不查"用户资料"接口：那个接口（``/bbs/web/profile/post/links``）
        实测返回 ``status=failed`` 且 result 为空，无法区分"会话失效"和"接口变了"。
        消息接口是本项目真正依赖的接口，能拉到数据才算有效——这是最实在的证据。
        """
        url = self.build_api_url(
            MESSAGE_PATH,
            {"message_type": "", "list_type": "0", "offset": "0", "limit": "1"},
        )
        data = await self._request_json("GET", url)

        result = data.get("result")
        if not isinstance(result, dict) or "messages" not in result:
            raise SchemaChanged(
                f"{MESSAGE_PATH} 响应缺少 result.messages——这是接口结构变更，"
                "不能据此判定会话有效。"
            )

        return Account(heybox_id=self.heybox_id, username="", level=0)

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

    async def search_topics(self, query: str) -> list[dict[str, Any]]:
        """搜话题（= 发帖时的"分区"）。参数名是 ``q`` 不是 keyword。"""
        keyword = str(query or "").strip()
        if not keyword:
            raise ValueError("搜索话题需要关键词")
        url = self.build_api_url(
            TOPIC_SEARCH_PATH, {"heybox_id": self.heybox_id, "q": keyword}
        )
        data = await self._request_json("GET", url)
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        items = result.get("search_result")
        if not isinstance(items, list):
            raise SchemaChanged(f"{TOPIC_SEARCH_PATH} 响应缺 search_result")
        return [
            {
                "topic_id": str(item.get("topic_id") or ""),
                "name": str(item.get("name") or ""),
            }
            for item in items
            if isinstance(item, dict) and item.get("topic_id")
        ]

    async def fetch_feed_posts(self, *, limit: int = 30) -> list[FeedPost]:
        """拉首页推荐流，返回帖子摘要列表。用于逛帖学习。"""
        url = self.build_api_url(
            FEEDS_PATH,
            {"offset": "0", "pull": "0", "heybox_id": self.heybox_id},
        )
        data = await self._request_json("GET", url)
        result = data.get("result")
        if not isinstance(result, dict):
            raise SchemaChanged(f"{FEEDS_PATH} 响应缺 result")

        raw = result.get("links") or result.get("feeds") or result.get("list")
        if not isinstance(raw, list):
            raise SchemaChanged(f"{FEEDS_PATH} 响应里找不到帖子列表")

        posts: list[FeedPost] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            link = item.get("link") if isinstance(item.get("link"), dict) else item
            link_id = str(link.get("linkid") or link.get("link_id") or "").strip()
            if not link_id:
                continue
            user = link.get("user") if isinstance(link.get("user"), dict) else {}
            topics = link.get("topics") if isinstance(link.get("topics"), list) else []
            posts.append(
                FeedPost(
                    link_id=link_id,
                    title=str(link.get("title") or ""),
                    description=_strip_html(
                        str(link.get("description") or link.get("text") or "")
                    ),
                    author_name=str(user.get("username") or user.get("nickname") or ""),
                    up=int(link.get("up") or 0),
                    comment_num=int(link.get("comment_num") or 0),
                    topics=tuple(
                        str(t.get("name"))
                        for t in topics
                        if isinstance(t, dict) and t.get("name")
                    ),
                )
            )
        return posts[:limit]

    async def fetch_post_detail(self, link_id: str) -> dict[str, Any]:
        """拉一篇帖子的详情。正文可能只有摘要（接口限制）。"""
        url = self.build_api_url(
            LINK_TREE_PATH,
            {
                "h_src": "",
                "link_id": str(link_id),
                "is_first": "1",
                "page": "1",
                "index": "1",
                "limit": "3",
                "owner_only": "0",
                "heybox_id": self.heybox_id,
            },
        )
        data = await self._request_json("GET", url)
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        link = result.get("link") if isinstance(result.get("link"), dict) else {}
        if not link:
            raise SchemaChanged(f"{LINK_TREE_PATH} 没返回帖子内容，link_id={link_id}")
        user = link.get("user") if isinstance(link.get("user"), dict) else {}
        topics = link.get("topics") if isinstance(link.get("topics"), list) else []
        return {
            "link_id": str(link.get("linkid") or link_id),
            "title": str(link.get("title") or ""),
            "description": _strip_html(str(link.get("description") or "")),
            "content": _strip_html(str(link.get("text") or link.get("content") or "")),
            "author_name": str(user.get("username") or ""),
            "up": int(link.get("up") or 0),
            "comment_num": int(link.get("comment_num") or 0),
            "topics": [str(t.get("name")) for t in topics if isinstance(t, dict)],
        }

    async def fetch_dm_history(
        self, to_user_id: str, *, limit: int = 20
    ) -> list[DmMessage]:
        """拉与某个用户的私信历史。

        实测字段：``content``（不是 ``msg``）、``send_time``(毫秒)、``seq``。
        结构变了就抛 SchemaChanged，不要静默返回空列表。
        """
        target = str(to_user_id or "").strip()
        if not target:
            raise ValueError("拉私信历史需要 user_id")
        if not self.heybox_id:
            raise ValueError("缺少 heybox_id，请先登录")

        url = self.build_api_url(
            DIRECT_MESSAGE_PATH,
            {
                "to_user_id": target,
                "offset": "0",
                "limit": str(max(1, min(int(limit or 20), 50))),
                "heybox_id": self.heybox_id,
            },
        )
        data = await self._request_json("GET", url)
        result = data.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("list"), list):
            raise SchemaChanged(
                f"{DIRECT_MESSAGE_PATH} 响应缺 result.list，接口可能已变更"
            )

        messages: list[DmMessage] = []
        for raw in result["list"]:
            if not isinstance(raw, dict):
                continue
            try:
                send_time = int(raw.get("send_time") or 0)
            except (TypeError, ValueError):
                raise SchemaChanged(f"私信 send_time 不是数字：{raw.get('send_time')!r}") from None
            if send_time <= 0:
                raise SchemaChanged("私信缺少 send_time")
            sender = str(raw.get("sender_id") or "")
            messages.append(
                DmMessage(
                    seq=str(raw.get("seq") or ""),
                    sender_id=sender,
                    content=str(raw.get("content") or ""),
                    timestamp=int(send_time / 1000) if send_time > 100_000_000_000 else send_time,
                    msg_type=int(raw.get("msg_type") or 0),
                    is_mine=sender == self.heybox_id,
                )
            )
        return messages

    async def copy_image_by_url(self, image_url: str) -> dict[str, Any]:
        """把外部图片转存到小黑盒 CDN，返回 {url, width, height}。

        Steam / 官网的图直接外链基本会被盗链拦截，必须走这一步。
        """
        source = str(image_url or "").strip()
        if not source.lower().startswith(("http://", "https://")):
            raise ValueError(f"只支持 http(s) 图片地址：{source!r}")
        url = self.build_api_url(
            IMAGE_COPY_PATH,
            {
                "heybox_id": self.heybox_id,
                "target_url": source,
                "watermark": "false",
            },
        )
        data = await self._request_json("GET", url)
        if data.get("status") != "ok":
            raise TransportError(f"图片转存失败：{_error_message(data, 'unknown')}")
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        copied = str(result.get("url") or result.get("preview_url") or "")
        if not copied:
            raise SchemaChanged("图片转存响应缺少 url")
        try:
            width = int(result.get("width") or 0)
            height = int(result.get("height") or 0)
        except (TypeError, ValueError):
            width, height = 0, 0
        if not width or not height:
            # 转存接口不给尺寸时自己量：小黑盒排版依赖宽高，0 会显示异常
            width, height = await self._probe_remote_size(copied)
        return {"url": copied, "width": width, "height": height}

    async def _probe_remote_size(self, image_url: str) -> tuple[int, int]:
        """下载图片读一下尺寸。读不到就返回 (0, 0)，不阻断发帖。"""
        try:
            import io

            from PIL import Image

            timeout = aiohttp.ClientTimeout(total=25)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(image_url) as response:
                    if response.status >= 400:
                        return (0, 0)
                    payload = await response.read()
            with Image.open(io.BytesIO(payload)) as image:
                return image.size
        except Exception:  # noqa: BLE001 - 尺寸只是排版元数据
            return (0, 0)

    async def _prepare_images_in_html(
        self, html: str
    ) -> tuple[str, list[dict[str, Any]]]:
        """把 HTML 里的外部图片转存到 CDN，返回 (新 HTML, 图片列表)。

        已经是小黑盒 CDN 的图不重复转存。
        """
        images: list[dict[str, Any]] = []
        parts: list[str] = []
        position = 0
        for match in _IMG_TAG_RE.finditer(html):
            src = match.group(1)
            if "max-c.com" in src:
                continue
            parts.append(html[position : match.start()])
            try:
                info = await self.copy_image_by_url(src)
            except XhhError as exc:
                raise TransportError(f"图片转存失败（{src[:60]}）：{exc}") from exc
            images.append(info)
            width = info.get("width") or 0
            height = info.get("height") or 0
            parts.append(
                f'<img data-description="" data-height="{height}" '
                f'data-original="{info["url"]}" data-type="image" '
                f'data-width="{width}"/>'
            )
            position = match.end()
        parts.append(html[position:])
        return "".join(parts), images

    async def delete_link(self, link_id: str) -> SendResult:
        """删除一条已发布的帖子。**不可逆**。

        URL 里看到的 ``link_id`` 可能是 hex（如 ``5e8e72b8b427``），
        但删除接口只认数字 id。直接传 hex 会回"帖子不存在"，
        所以先查一次详情把数字 id 取出来。
        """
        target = str(link_id or "").strip()
        if not target:
            raise ValueError("缺少 link_id")
        if not target.isdigit():
            detail = await self.fetch_post_detail(target)
            numeric = str(detail.get("link_id") or "")
            if not numeric.isdigit():
                raise SchemaChanged(
                    f"无法从 {target} 取到数字 link_id，删除接口需要数字 id"
                )
            target = numeric
        url = self.build_api_url(LINK_DELETE_PATH, {"heybox_id": self.heybox_id})
        data = await self._request_json(
            "POST", url, data=urlencode({"link_id": target}), headers=self._form_headers()
        )
        if data.get("status") != "ok":
            raise TransportError(f"删除帖子失败：{_error_message(data, 'unknown')}")
        return SendResult(ok=True)

    async def change_link_status(self, link_id: str, *, status: int = 0) -> SendResult:
        """改帖子状态。``status=0`` 用于删草稿或下架已发布内容。"""
        target = str(link_id or "").strip()
        if not target:
            raise ValueError("缺少 link_id")
        url = self.build_api_url(
            LINK_CHANGE_STATUS_PATH,
            {"heybox_id": self.heybox_id, "link_id": target, "status": str(int(status))},
        )
        data = await self._request_json("GET", url)
        if data.get("status") != "ok":
            raise TransportError(f"修改帖子状态失败：{_error_message(data, 'unknown')}")
        return SendResult(ok=True)

    async def fetch_link_owner(self, link_id: str) -> str:
        """查帖子的作者 userid。用于判断"这是不是我自己的帖子"。"""
        url = self.build_api_url(
            LINK_TREE_PATH,
            {
                "h_src": "",
                "link_id": str(link_id).strip(),
                "is_first": "1",
                "page": "1",
                "index": "1",
                "limit": "1",
                "owner_only": "0",
                "heybox_id": self.heybox_id,
            },
        )
        data = await self._request_json("GET", url)
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        link = result.get("link") if isinstance(result.get("link"), dict) else {}
        user = link.get("user") if isinstance(link.get("user"), dict) else {}
        owner = str(
            user.get("userid") or user.get("heybox_id") or user.get("user_id") or ""
        )
        if not owner:
            raise SchemaChanged(f"{LINK_TREE_PATH} 响应里找不到帖子作者，无法判断归属")
        return owner

    async def is_own_post(self, link_id: str) -> bool:
        """是不是自己发的帖子。

        查不到归属就返回 False —— 保守处理。去别人帖子下刷评论比漏回一条
        严重得多，所以这里的失败方向必须是"不回"。
        """
        try:
            return (await self.fetch_link_owner(link_id)) == self.heybox_id
        except Exception:  # noqa: BLE001 - 任何失败都判定为"不是我的"
            logger.debug("帖子归属查询失败，按『不是自己的帖子』处理：%s", link_id)
            return False

    async def reply_comment(
        self,
        *,
        link_id: str,
        reply_id: str,
        root_id: str,
        text: str,
        image_urls: tuple[str, ...] = (),
    ) -> SendResult:
        """回复评论。``reply_id`` 是被回复的那条评论，``root_id`` 是楼层根。"""
        content = str(text or "").strip()
        if not content:
            raise ValueError("评论内容为空，已取消")
        if len(content) > REPLY_MAX_LENGTH:
            raise ValueError(
                f"评论内容过长（{len(content)} 字，上限 {REPLY_MAX_LENGTH}）"
            )

        body: dict[str, str] = {
            "is_cy": "0",
            "link_id": str(link_id).strip(),
            "reply_id": str(reply_id).strip(),
            "root_id": str(root_id or reply_id).strip(),
            "text": content,
        }
        images = [str(u).strip() for u in image_urls if str(u).strip()]
        if images:
            body["imgs"] = ",".join(images)

        url = self.build_api_url(COMMENT_CREATE_PATH, {"heybox_id": self.heybox_id})
        data = await self._request_json(
            "POST", url, data=urlencode(body), headers=self._form_headers()
        )
        if data.get("status") != "ok":
            raise TransportError(f"评论发送失败：{_error_message(data, 'unknown')}")

        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        ack_id = str(result.get("comment_id") or result.get("commentid") or "")
        return SendResult(ok=True, ack_id=ack_id)

    async def _put_cos_object(
        self,
        *,
        data: bytes,
        bucket: str,
        region: str,
        key: str,
        mimetype: str,
        token: dict[str, Any],
    ) -> None:
        """把字节直传腾讯云 COS。独立 session：这是对第三方域名的请求。"""
        from .cos_upload import cos_authorization, cos_quote

        credentials = token.get("credentials") if isinstance(token.get("credentials"), dict) else {}
        secret_id = str(credentials.get("tmpSecretId") or "")
        secret_key = str(credentials.get("tmpSecretKey") or "")
        session_token = str(credentials.get("sessionToken") or "")
        if not secret_id or not secret_key or not session_token:
            raise SchemaChanged("图片上传授权响应缺少临时凭证")

        now = int(time.time())
        try:
            start_time = int(token.get("startTime") or max(0, now - 60))
            end_time = int(token.get("expiredTime") or (now + 300))
        except (TypeError, ValueError):
            start_time, end_time = max(0, now - 60), now + 300

        host = f"{bucket}.cos.{region}.myqcloud.com"
        object_path = "/" + key.lstrip("/")
        headers = {
            "Host": host,
            "Content-Type": mimetype,
            "x-cos-security-token": session_token,
        }
        headers["Authorization"] = cos_authorization(
            secret_id=secret_id,
            secret_key=secret_key,
            method="PUT",
            path=object_path,
            headers=headers,
            start_time=start_time,
            end_time=end_time,
        )
        url = f"https://{host}{cos_quote(object_path)}"

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.put(url, data=data, headers=headers) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise TransportError(
                        f"COS 图片上传失败：HTTP {response.status}，{text[:200]}"
                    )

    async def submit_post(
        self,
        *,
        title: str,
        content: str,
        draft: bool = True,
        topic_ids: tuple[str, ...] = (),
        desc: str = "",
        mode: str = "article",
        edit_link_id: str = "",
    ) -> PostResult:
        """发帖或存草稿。

        两种模式，都是实测过才写进来的：

        **article（默认，link_tag=11）** —— 富文本文章，支持 HTML 标签、
        图片、外链。需要有效的 ``topic_ids`` 以及文章声明字段。

        **dynamic（link_tag=27）** —— 普通动态，只能放纯文本。塞 HTML 会把
        标签原样显示出来（实测踩过）。

        两种模式都**必须**带 ``topic_ids``，否则服务端回"请添加分区"。
        话题 ID 要用 ``search_topics(q=...)`` 查真实值，别抄网上的数字——
        我用过 58144，它是不存在的，一直报"错误的帖子类型"。
        """
        clean_title = str(title or "").strip()
        clean_body = str(content or "").strip()
        if not clean_title:
            raise ValueError("帖子标题为空")
        if not clean_body:
            raise ValueError("帖子正文为空")
        if len(clean_title) > 100:
            raise ValueError(f"标题过长（{len(clean_title)} 字，上限 100）")
        if mode not in {"article", "dynamic"}:
            raise ValueError(f"不支持的 mode: {mode}")

        topics = [str(t).strip() for t in topic_ids if str(t).strip()]
        is_article = mode == "article"

        # 外部图片先转存到小黑盒 CDN，否则帖子里是裂图
        body_html, images = await self._prepare_images_in_html(clean_body)
        blocks: list[dict[str, Any]] = [
            {"type": "html" if is_article else "text", "text": body_html}
        ]
        # 图片同时作为独立 img block 提交（web 端排版依赖这个）
        for image in images:
            blocks.append(
                {
                    "type": "img",
                    "url": image["url"],
                    "width": image.get("width") or 0,
                    "height": image.get("height") or 0,
                }
            )

        body: dict[str, str] = {
            "title": clean_title,
            "desc": (str(desc or "").strip() or clean_title)[:100],
            "post_type": "1",
            "text": json.dumps(blocks, ensure_ascii=False),
            "link_tag": str(LINK_TAG_ARTICLE if is_article else LINK_TAG_NORMAL),
        }
        if topics:
            body["topic_ids"] = ",".join(topics)
        if is_article:
            # 文章必需的四件套。缺了会回"错误的帖子类型#0001"
            body["words_count"] = str(len(body_html))
            body["original"] = "1"
            body["declaration"] = "1"
            body["extra_declaration"] = "-1"
        if draft:
            body["draft"] = "1"
            body["view_limit"] = "1"
        if edit_link_id:
            # 改已有帖子：带 link_id + edit=1，否则会变成新建一条
            body["link_id"] = str(edit_link_id).strip()
            body["edit"] = "1"

        url = self.build_api_url(POST_PATH, {"heybox_id": self.heybox_id})
        data = await self._request_json(
            "POST", url, data=urlencode(body), headers=self._form_headers()
        )
        if data.get("status") != "ok":
            raise TransportError(f"发帖失败：{_error_message(data, 'unknown')}")

        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        return PostResult(
            ok=True,
            link_id=str(result.get("link_id") or result.get("linkid") or ""),
            is_draft=draft,
        )

    def _form_headers(self) -> dict[str, str]:
        """表单提交的头。Cookie 在 session 默认头里，这里不重复带。"""
        return {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Origin": WEB_ORIGIN,
            "Referer": f"{WEB_ORIGIN}/",
        }

    def _next_ack_id(self) -> int:
        """发送回执序号。上游初值是时间戳取模，逐次自增。"""
        if self._ack_id is None:
            self._ack_id = int(time.time() * 1000) % 1_000_000_000
        self._ack_id += 1
        return self._ack_id

    def build_dm_request(self, to_user_id: str, text: str) -> "DmRequest":
        """构造私信请求但**不发送**。dry-run 与真发共用它，避免两边逻辑漂移。"""
        target = str(to_user_id or "").strip()
        content = str(text or "").strip()
        if not target:
            raise ValueError("缺少收件人 user_id")
        if not content:
            raise ValueError("私信内容为空，已取消发送")
        if len(content) > DM_MAX_LENGTH:
            raise ValueError(f"私信内容过长（{len(content)} 字，上限 {DM_MAX_LENGTH}）")

        url = self.build_api_url(
            DIRECT_MESSAGE_PATH,
            {"to_user_id": target, "heybox_id": self.heybox_id},
        )
        body = {
            "heybox_ack_id": str(self._next_ack_id()),
            "img": "",
            "msg": content,
            "msg_type": "6",
        }
        return DmRequest(
            to_user_id=target,
            text=content,
            url=url,
            body=body,
            headers=self._form_headers(),
        )

    async def send_dm(self, to_user_id: str, text: str) -> SendResult:
        """发一条私信。

        这是本项目第一个**写操作**。调用方负责确认内容与收件人——
        发出去不可撤回。``xhh dm`` 默认 dry-run 就是为了先看清这两样。
        """
        target = str(to_user_id or "").strip()
        content = str(text or "").strip()
        if not target:
            raise ValueError("缺少收件人 user_id")
        if not content:
            raise ValueError("私信内容为空，已取消发送")
        if len(content) > DM_MAX_LENGTH:
            raise ValueError(f"私信内容过长（{len(content)} 字，上限 {DM_MAX_LENGTH}）")

        request = self.build_dm_request(target, content)
        data = await self._request_json(
            "POST",
            request.url,
            data=urlencode(request.body),
            headers=request.headers,
        )

        if data.get("status") != "ok":
            raise TransportError(f"私信发送失败：{_error_message(data, 'unknown')}")

        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        ack_id = str(
            result.get("heychat_ack_id") or result.get("msg_id") or result.get("msg_seq") or ""
        )
        if not ack_id:
            raise TransportError(
                "私信发送未返回 ack（heychat_ack_id/msg_id/msg_seq 均为空），"
                "无法确认是否送达——不要假定成功。"
            )
        return SendResult(ok=True, ack_id=ack_id)

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
            link_title=_link_title_of(message),
            replied_text=_message_text_of(message, ("comment_b_text",)),
        )

    def _to_dm_item(self, message: dict[str, Any]) -> InboxItem | None:
        """解析一条私信会话入口。

        实测结构：``user_a`` 只有 ``username`` / ``avartar`` / ``border``，**没有 id**。
        对方的 user_id 实际在 ``message_id`` 字段里（仅当 ``entry == "message"``）。
        拿不到这个 id，P3 就无法把私信发回去。
        """
        user = message.get("user_a") if isinstance(message.get("user_a"), dict) else {}
        sender_name = str(user.get("username") or user.get("nickname") or "")

        peer_id = ""
        if str(message.get("entry") or "") == "message":
            peer_id = str(message.get("message_id") or "")
        if not peer_id:
            peer_id = str(user.get("heybox_id") or user.get("userid") or "")
        if not peer_id:
            return None

        return InboxItem(
            channel="dm",
            message_id=f"dm:{peer_id}",
            sender_id=peer_id,
            sender_name=sender_name or peer_id,
            text=_message_text(message),
            timestamp=_message_timestamp(message),
            raw_message_type=str(message.get("message_type") or message.get("entry") or ""),
        )

    def build_login_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        """登录接口的 URL。

        与 :meth:`build_api_url` 的唯一差别是**不带签名参数**，
        域名相同（``api.xiaoheihe.cn``）。写成 ``www.xiaoheihe.cn`` 会 404。
        """
        query = urlencode(params or {})
        return f"{API_ORIGIN}{path}?{query}" if query else f"{API_ORIGIN}{path}"

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
