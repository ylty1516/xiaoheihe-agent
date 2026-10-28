"""测试夹具。

设计要点：mock 的是 `_raw_request`（唯一做 HTTP 的方法），
而不是 `_request_json`——后者承载了 401 → LoginExpired 的错误映射，
必须被真实代码执行到。
"""

from __future__ import annotations

import json
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
        return RawResponse(status=status, data=payload)

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
