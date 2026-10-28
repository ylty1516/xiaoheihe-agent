"""测试夹具。

设计要点：mock 的是 `_raw_request`（唯一做 HTTP 的方法），
而不是 `_request_json`——后者承载了 401 → LoginExpired 的错误映射，
必须被真实代码执行到。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest

from xhh_agent.config import load_config
from xhh_agent.protocol.client import ProtocolClient, RawResponse
from xhh_agent.protocol.session import Session

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_client(payload: dict, status: int = 200) -> ProtocolClient:
    client = ProtocolClient(
        Session(cookie="cookie=secret", heybox_id="83709585"),
        load_config(),
    )

    async def _raw_request(method: str, url: str, **kwargs):
        # 真实响应总带 Date 头，clock 检查依赖它
        date_header = format_datetime(datetime.now(timezone.utc), usegmt=True)
        return RawResponse(status=status, data=payload, headers=(("Date", date_header),))

    client._raw_request = _raw_request  # type: ignore[method-assign]
    return client


@pytest.fixture
def fake_client() -> ProtocolClient:
    return make_client(load_fixture("whoami_ok.json"))


@pytest.fixture
def fake_401_client() -> ProtocolClient:
    return make_client(load_fixture("login_expired.json"), status=401)


@pytest.fixture
def fake_empty_result_client() -> ProtocolClient:
    return make_client(load_fixture("whoami_empty.json"))


# ── 扫码登录夹具 ────────────────────────────────────────────

class _FakeQrClient(ProtocolClient):
    """模拟扫码流程；``_qr_state`` 控制 qr_state 接口的返回。"""

    _qr_state = "wait"

    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        if "get_qrcode_url" in url:
            return RawResponse(
                status=200,
                data={
                    "status": "ok",
                    "result": {
                        "qr_url": "https://www.xiaoheihe.cn/qr?qr=QID123",
                        "expire": 120,
                    },
                },
            )
        if "qr_state" in url:
            if self._qr_state == "ok":
                return RawResponse(
                    status=200,
                    data={"status": "ok", "result": {"error": "ok", "heyboxid": "83709585"}},
                    set_cookies=(
                        "user_pkey=SECRETPKEY; Path=/",
                        "user_heybox_id=83709585; Path=/",
                        "nickname=%E6%B5%8B%E8%AF%95; Path=/",
                    ),
                )
            return RawResponse(status=200, data={"status": "ok", "result": {"error": "wait"}})
        raise AssertionError(f"unexpected url: {url}")


@pytest.fixture
def fake_qr_client() -> ProtocolClient:
    return _FakeQrClient(
        Session(cookie="", heybox_id=""),
        load_config(),
    )


# ── inbox 夹具 ──────────────────────────────────────────────

class _FakeInboxClient(ProtocolClient):
    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        if "list_type=2" in url:
            return RawResponse(status=200, data=load_fixture("inbox_dm.json"))
        if "message_type=16" in url:
            return RawResponse(status=200, data=load_fixture("inbox_mention.json"))
        return RawResponse(status=200, data=load_fixture("inbox_comment.json"))


@pytest.fixture
def fake_inbox_client() -> ProtocolClient:
    return _FakeInboxClient(
        Session(cookie="cookie=secret", heybox_id="83709585"),
        load_config(),
    )


@pytest.fixture
def fake_broken_schema_client() -> ProtocolClient:
    return make_client(load_fixture("whoami_empty.json"))


# ── doctor 夹具：一个四项检查都能通过的 client ──────────────

class _FakeDoctorClient(ProtocolClient):
    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        if "list_type=2" in url:
            return RawResponse(status=200, data=load_fixture("inbox_dm.json"))
        if "message_type=16" in url:
            return RawResponse(status=200, data=load_fixture("inbox_mention.json"))
        if "/bbs/app/user/message" in url:
            return RawResponse(status=200, data=load_fixture("inbox_comment.json"))
        return RawResponse(status=200, data=load_fixture("whoami_ok.json"))

    async def server_time(self) -> int:
        import time as _time

        return int(_time.time())


@pytest.fixture
def fake_doctor_client() -> ProtocolClient:
    return _FakeDoctorClient(
        Session(cookie="cookie=secret", heybox_id="83709585"),
        load_config(),
    )


@pytest.fixture
def fake_expired_client() -> ProtocolClient:
    """登录态失效的 client（doctor 测试用此名）。"""
    return make_client(load_fixture("login_expired.json"), status=401)


# ── 审查修复轮夹具 ──────────────────────────────────────────


def make_fixture_client(fixture_name: str, status: int = 200) -> ProtocolClient:
    """所有请求都返回同一个 fixture 的 client。"""
    return make_client(load_fixture(fixture_name), status=status)


@pytest.fixture
def fake_client_no_user() -> ProtocolClient:
    return make_fixture_client("whoami_no_user.json")


def _fixed(fixture_name: str) -> ProtocolClient:
    return _FixedInboxClient(
        fixture_name,
        Session(cookie="cookie=secret", heybox_id="83709585"),
        load_config(),
    )


@pytest.fixture
def fake_inbox_with_unparseable() -> ProtocolClient:
    return _fixed("inbox_partial.json")


@pytest.fixture
def fake_inbox_all_broken() -> ProtocolClient:
    return _fixed("inbox_unparseable.json")


class _FixedInboxClient(ProtocolClient):
    """三个通道都返回同一份 fixture（用于模拟字段改名）。"""

    def __init__(self, fixture_name: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._fixture_name = fixture_name

    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        return RawResponse(status=200, data=load_fixture(self._fixture_name))


@pytest.fixture
def fake_relogin_client() -> ProtocolClient:
    """cookie 有效但请求缺 web 客户端参数时，服务端回 status=relogin。"""
    return make_client(load_fixture("login_relogin.json"))


# ── 私信发送夹具（捕获请求）──────────────────────────────────

class _CapturingDmClient(ProtocolClient):
    def __init__(self, payload: dict, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._payload = payload
        self.captured: list[tuple] = []

    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        self.captured.append((method, url, kwargs))
        return RawResponse(status=200, data=self._payload)


@pytest.fixture
def fake_dm_client() -> ProtocolClient:
    return _CapturingDmClient(
        {"status": "ok", "result": {"msg_id": "12345"}},
        Session(cookie="cookie=secret", heybox_id="85183285"),
        load_config(),
    )


@pytest.fixture
def fake_dm_client_no_ack() -> ProtocolClient:
    return _CapturingDmClient(
        {"status": "ok", "result": {}},
        Session(cookie="cookie=secret", heybox_id="85183285"),
        load_config(),
    )


# ── 发帖夹具 ────────────────────────────────────────────────

class _CapturingPostClient(ProtocolClient):
    def __init__(self, payload: dict, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._payload = payload
        self.captured: list[tuple] = []

    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        self.captured.append((method, url, kwargs))
        return RawResponse(status=200, data=self._payload)


@pytest.fixture
def fake_post_client() -> ProtocolClient:
    return _CapturingPostClient(
        {"status": "ok", "result": {"link_id": "999888"}},
        Session(cookie="cookie=secret", heybox_id="85183285"),
        load_config(),
    )


@pytest.fixture
def fake_post_client_fail() -> ProtocolClient:
    return _CapturingPostClient(
        {"status": "failed", "msg": "内容含违规信息"},
        Session(cookie="cookie=secret", heybox_id="85183285"),
        load_config(),
    )


# ── 图片上传夹具 ────────────────────────────────────────────

class _FakeCosClient:
    """按路径返回假响应，并记录调用顺序。"""

    def __init__(self, callback_payload: dict) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._callback_payload = callback_payload

    @property
    def heybox_id(self) -> str:
        return "85183285"

    def build_api_url(self, path: str, params=None) -> str:
        return f"https://api.xiaoheihe.cn{path}"

    def _form_headers(self) -> dict:
        return {"Content-Type": "application/x-www-form-urlencoded"}

    async def _request_json(self, method: str, url: str, **kwargs):
        path = url.split("?")[0].replace("https://api.xiaoheihe.cn", "")
        self.calls.append((path, kwargs))
        if "upload/info" in path:
            return {
                "status": "ok",
                "result": {
                    "bucket": "bucket-1250000000",
                    "region": "ap-shanghai",
                    "keys": ["bbs/code.png"],
                },
            }
        if "upload/token" in path:
            return {
                "status": "ok",
                "result": {
                    "startTime": 1700000000,
                    "expiredTime": 1700000300,
                    "credentials": {
                        "tmpSecretId": "AKID",
                        "tmpSecretKey": "SECRET",
                        "sessionToken": "TOKEN",
                    },
                },
            }
        if "upload/callback" in path:
            return {"status": "ok", "result": self._callback_payload}
        raise AssertionError(f"unexpected path: {path}")

    async def _put_cos_object(self, **kwargs) -> None:
        self.calls.append(("PUT_COS", kwargs))


@pytest.fixture
def fake_cos_client() -> _FakeCosClient:
    return _FakeCosClient({"preview_urls": ["https://imgheybox.max-c.com/bbs/code.png"]})


@pytest.fixture
def fake_cos_client_no_url() -> _FakeCosClient:
    return _FakeCosClient({"preview_urls": [], "thumbs": []})


# ── 帖子归属 / 回评论夹具 ───────────────────────────────────

def _link_tree_payload(owner: str) -> dict:
    return {
        "status": "ok",
        "result": {"link": {"linkid": "x", "user": {"userid": owner, "username": "someone"}}},
    }


@pytest.fixture
def fake_link_client() -> ProtocolClient:
    return make_client(_link_tree_payload("83709585"))


@pytest.fixture
def fake_link_client_other() -> ProtocolClient:
    return make_client(_link_tree_payload("47762033"))


@pytest.fixture
def fake_link_client_broken() -> ProtocolClient:
    return make_client({"status": "ok", "result": {}})


class _CapturingReplyClient(ProtocolClient):
    def __init__(self, payload: dict, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._payload = payload
        self.captured: list[tuple] = []

    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        self.captured.append((method, url, kwargs))
        return RawResponse(status=200, data=self._payload)


@pytest.fixture
def fake_reply_client() -> ProtocolClient:
    return _CapturingReplyClient(
        {"status": "ok", "result": {"comment_id": "888"}},
        Session(cookie="cookie=secret", heybox_id="85183285"),
        load_config(),
    )
