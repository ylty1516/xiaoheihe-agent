import logging

import pytest

from xhh_agent.protocol.errors import LoginExpired, SchemaChanged


async def test_whoami_returns_session_account(fake_client):
    acct = await fake_client.whoami()
    assert acct.heybox_id == "83709585"


async def test_whoami_login_expired(fake_401_client):
    with pytest.raises(LoginExpired):
        await fake_401_client.whoami()


async def test_whoami_relogin_status_is_login_expired(fake_relogin_client):
    """实测：cookie 有效但请求缺 web 客户端参数时，服务端回 status=relogin。
    这必须被识别成登录失效，而不是"没消息"。"""
    with pytest.raises(LoginExpired):
        await fake_relogin_client.whoami()


async def test_whoami_missing_messages_raises_schema_changed(fake_client_no_user):
    """result 里没有 messages 说明接口结构变了，不能当成"会话有效"。"""
    with pytest.raises(SchemaChanged):
        await fake_client_no_user.whoami()


def test_url_building_never_logged_with_hkey(fake_client, caplog):
    """任何日志都不能含 hkey 值（审查重点 #1）"""
    caplog.set_level(logging.DEBUG)
    fake_client.build_api_url("/bbs/app/user/message", {"heybox_id": "1"})
    assert "hkey=" not in caplog.text


def test_login_expired_ignores_unrelated_401_prefix():
    """审查 I4：'4011' 这类错误码不能被当成 HTTP 401。"""
    from xhh_agent.protocol.client import is_login_expired

    assert not is_login_expired({"status": "error", "msg": "内部错误 code 4011"})


def test_login_expired_still_matches_real_cases():
    from xhh_agent.protocol.client import is_login_expired

    assert is_login_expired({"status": "unauthorized"})
    assert is_login_expired({"status": "relogin"})
    assert is_login_expired({"msg": "请先登录"})
    assert is_login_expired({"status": "error", "msg": "invalid login"})


def test_api_url_carries_web_client_params(fake_client):
    """服务端靠这组参数识别"这是合法的 web 客户端"。

    实测缺了它们，/bbs/app/user/message 会返回 status=relogin，
    即使 cookie 完全有效。
    """
    url = fake_client.build_api_url("/bbs/app/user/message", {"limit": "1"})
    expected = {
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
    for key, value in expected.items():
        assert f"{key}={value}" in url, f"缺少 {key}={value}"
    assert "device_id=" in url


def test_api_url_explicit_params_override_defaults(fake_client):
    """调用方传入的 params 必须能覆盖默认值（上游用 update 顺序保证）。"""
    url = fake_client.build_api_url("/x/y", {"os_type": "android"})
    assert "os_type=android" in url
    assert "os_type=web" not in url
