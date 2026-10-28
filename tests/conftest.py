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
        Session(cookie="cookie=secret", heybox_id="10000001"),
        load_config(),
    )


@pytest.fixture
def fake_dm_client_no_ack() -> ProtocolClient:
    return _CapturingDmClient(
        {"status": "ok", "result": {}},
        Session(cookie="cookie=secret", heybox_id="10000001"),
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
        Session(cookie="cookie=secret", heybox_id="10000001"),
        load_config(),
    )


@pytest.fixture
def fake_post_client_fail() -> ProtocolClient:
    return _CapturingPostClient(
        {"status": "failed", "msg": "内容含违规信息"},
        Session(cookie="cookie=secret", heybox_id="10000001"),
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
        return "10000001"

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
        Session(cookie="cookie=secret", heybox_id="10000001"),
        load_config(),
    )


# ── 私信历史夹具 ────────────────────────────────────────────

class _FakeDmHistoryClient(ProtocolClient):
    def __init__(self, payload: dict, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._payload = payload

    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        return RawResponse(status=200, data=self._payload)


def _dm_history_payload() -> dict:
    return {
        "status": "ok",
        "result": {
            "list": [
                {
                    "sender_id": 85183285,
                    "content": "在不在",
                    "msg_type": 6,
                    "send_time": 1793171471267,
                    "seq": "2115340585080733696",
                },
                {
                    "sender_id": 84812994,
                    "content": "在的，啥事",
                    "msg_type": 6,
                    "send_time": 1793171500000,
                    "seq": "2115340585080733697",
                },
            ]
        },
    }


@pytest.fixture
def fake_dm_history_client() -> ProtocolClient:
    return _FakeDmHistoryClient(
        _dm_history_payload(),
        Session(cookie="cookie=secret", heybox_id="85183285"),
        load_config(),
    )


@pytest.fixture
def fake_dm_history_client_broken() -> ProtocolClient:
    return _FakeDmHistoryClient(
        {"status": "ok", "result": {}},
        Session(cookie="cookie=secret", heybox_id="85183285"),
        load_config(),
    )


# ── 逛帖夹具 ────────────────────────────────────────────────

class _FakeFeedClient:
    heybox_id = "10000001"

    def __init__(self, posts: list[dict]) -> None:
        self._posts = posts

    def build_api_url(self, path, params=None):
        return f"https://api.xiaoheihe.cn{path}"

    async def fetch_feed_posts(self, *, limit=20):
        from xhh_agent.protocol.models import FeedPost

        return [
            FeedPost(
                link_id=str(p["linkid"]),
                title=p["title"],
                description=p["description"],
                author_name=p.get("author", "某人"),
                up=p.get("up", 0),
                comment_num=p.get("comment_num", 0),
            )
            for p in self._posts
        ]

    async def fetch_post_detail(self, link_id: str):
        return {
            "link_id": link_id,
            "title": f"帖子 {link_id}",
            "content": "正文内容" * 100,
            "topics": ["PC游戏"],
        }


@pytest.fixture
def fake_feed_client() -> _FakeFeedClient:
    return _FakeFeedClient(
        [
            {"linkid": 1, "title": "高质量帖", "description": "长描述 " * 80, "up": 500, "comment_num": 60},
            {"linkid": 2, "title": "普通帖", "description": "长描述 " * 80, "up": 5, "comment_num": 1},
        ]
    )


# ── 删除夹具 ────────────────────────────────────────────────

class _CapturingDeleteClient(ProtocolClient):
    def __init__(self, payload: dict, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._payload = payload
        self.captured: list[tuple] = []

    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        self.captured.append((method, url, kwargs))
        return RawResponse(status=200, data=self._payload)


@pytest.fixture
def fake_delete_client() -> ProtocolClient:
    return _CapturingDeleteClient(
        {"status": "ok", "result": {}},
        Session(cookie="cookie=secret", heybox_id="10000001"),
        load_config(),
    )


@pytest.fixture
def fake_delete_client_fail() -> ProtocolClient:
    return _CapturingDeleteClient(
        {"status": "failed", "msg": "无权限删除"},
        Session(cookie="cookie=secret", heybox_id="10000001"),
        load_config(),
    )


class _MixedDeleteClient(ProtocolClient):
    """link/tree 返回数字 id，delete 返回 ok。"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.captured: list[tuple] = []

    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        self.captured.append((method, url, kwargs))
        if "link/tree" in url:
            return RawResponse(
                status=200,
                data={
                    "status": "ok",
                    "result": {
                        "link": {
                            "linkid": 195232074,
                            "title": "开个坑，随便聊聊游戏",
                            "user": {"username": "me", "userid": "10000001"},
                        }
                    },
                },
            )
        return RawResponse(status=200, data={"status": "ok", "result": {}})


@pytest.fixture
def fake_delete_client_mixed() -> ProtocolClient:
    return _MixedDeleteClient(
        Session(cookie="cookie=secret", heybox_id="10000001"),
        load_config(),
    )


# ── LLM 夹具 ────────────────────────────────────────────────

class _FakeLlmClient:
    def __init__(self, replies: list[str]) -> None:
        self._replies = replies
        self.calls: list[dict] = []

    async def complete(self, *, prompt: str, model: str) -> str:
        self.calls.append({"prompt": prompt, "model": model})
        return self._replies[min(len(self.calls) - 1, len(self._replies) - 1)]


@pytest.fixture
def fake_llm_client() -> _FakeLlmClient:
    return _FakeLlmClient(["3k 就能拿下？我一直以为得 4k 往上喵~"])


@pytest.fixture
def fake_llm_client_bad_then_good() -> _FakeLlmClient:
    return _FakeLlmClient(
        ["我上周也买了，打了 40 小时喵~", "3k 就能拿下？得看版本喵~"]
    )


@pytest.fixture
def fake_llm_client_always_bad() -> _FakeLlmClient:
    return _FakeLlmClient(["综上所述，这个方案不错喵~"])


# ── 发帖带图夹具 ────────────────────────────────────────────

class _FakeCopyClient(ProtocolClient):
    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        if "cos/copy/image" in url:
            return RawResponse(
                status=200,
                data={
                    "status": "ok",
                    "result": {
                        "url": "https://imgheybox.max-c.com/bbs/copied.jpg",
                        "width": 1280,
                        "height": 720,
                    },
                },
            )
        return RawResponse(status=200, data={"status": "ok", "result": {}})


@pytest.fixture
def fake_copy_client() -> ProtocolClient:
    return _FakeCopyClient(
        Session(cookie="cookie=secret", heybox_id="10000001"), load_config()
    )


class _CapturingPostClientWithImages(ProtocolClient):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.captured: list[tuple] = []
        self.copy_calls = 0

    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        if "cos/copy/image" in url:
            self.copy_calls += 1
            return RawResponse(
                status=200,
                data={
                    "status": "ok",
                    "result": {
                        "url": "https://imgheybox.max-c.com/bbs/copied.jpg",
                        "width": 1280,
                        "height": 720,
                    },
                },
            )
        self.captured.append((method, url, kwargs))
        return RawResponse(status=200, data={"status": "ok", "result": {"link_id": "123"}})


@pytest.fixture
def fake_post_client_with_images() -> ProtocolClient:
    return _CapturingPostClientWithImages(
        Session(cookie="cookie=secret", heybox_id="10000001"), load_config()
    )


# ── 热搜榜夹具 ──────────────────────────────────────────────

def _hot_payload() -> dict:
    return {
        "status": "ok",
        "result": {
            "Lists": [
                {"head_text": "", "items": [{"text": "影之刃零", "index_color": "#f00"}]},
                {
                    "head_text": "黑盒热议",
                    "items": [
                        {"text": "AL 一号种子出局菲姐送头等舱", "right_tag": "热", "index_color": "#f00"},
                        {"text": "梁其伟推荐影之刃零回退617.42驱动", "right_tag": "", "index_color": "#f60"},
                        {"text": "T1艾克活动下架全额退款补至臻", "right_tag": "", "index_color": "#f60"},
                        {"text": "小黑盒购影之刃零获永久头像框", "right_tag": "新", "index_color": "#f90"},
                        {"text": "蜜雪冰城全面换用悦鲜活鲜奶", "right_tag": "", "index_color": "#f90"},
                        {"text": "Epic高管批评Steam封闭生态", "right_tag": "", "index_color": "#999"},
                    ],
                },
                {"head_text": "小程序", "items": [{"text": "喜加一"}]},
            ]
        },
    }


class _FakeHotClient(ProtocolClient):
    async def _raw_request(self, method: str, url: str, **kwargs):  # type: ignore[override]
        return RawResponse(status=200, data=_hot_payload())


@pytest.fixture
def fake_hot_client() -> ProtocolClient:
    return _FakeHotClient(
        Session(cookie="cookie=secret", heybox_id="10000001"), load_config()
    )
