"""协议层客户端：唯一发起网络请求的模块。

P0 阶段**不包含任何发送能力**——没有 ``submit_*`` / ``reply_*`` / ``send_*``。
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlencode

import aiohttp

from xhh_agent.config import Config

from .errors import LoginExpired, SchemaChanged, TransportError
from .models import Account
from .session import Session
from .signer import create_signed_params

logger = logging.getLogger(__name__)

API_ORIGIN = "https://api.xiaoheihe.cn"

#: 用户资料入口。P0 只用它验证会话有效性。
#: 注意：``username`` 为尽力而为解析，真实字段名需真机验收校正；
#: 取不到 username 不影响 whoami 的核心目的（确认会话未失效）。
WHOAMI_PATH = "/bbs/web/profile/post/links"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_EXPIRED_RE = re.compile(r"登录|login|unauthorized|401", flags=re.I)


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
    ) -> tuple[int, dict[str, str], Any]:
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
            return response.status, dict(response.headers), data

    async def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        status, _headers, data = await self._raw_request(method, url, **kwargs)
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
        heybox_id = str(user.get("heybox_id") or self.heybox_id or "")
        if not heybox_id:
            raise SchemaChanged(f"{WHOAMI_PATH} 响应中缺少 heybox_id，解析逻辑需更新")

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

    async def close(self) -> None:
        if self._http is not None and not self._http.closed:
            await self._http.close()
        self._http = None

    async def __aenter__(self) -> "ProtocolClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
