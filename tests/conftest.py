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
