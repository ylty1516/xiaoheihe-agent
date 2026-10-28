import logging

import pytest

from xhh_agent.protocol.errors import LoginExpired, SchemaChanged


async def test_whoami_parses_account(fake_client):
    acct = await fake_client.whoami()
    assert acct.heybox_id == "83709585"
    assert acct.username == "测试用户"


async def test_whoami_login_expired(fake_401_client):
    with pytest.raises(LoginExpired):
        await fake_401_client.whoami()


async def test_whoami_missing_fields_raises_schema_changed(fake_empty_result_client):
    """返回空 result 时不能当"匿名用户"，必须报结构变化（审查重点 #3）"""
    with pytest.raises(SchemaChanged):
        await fake_empty_result_client.whoami()


def test_url_building_never_logged_with_hkey(fake_client, caplog):
    """任何日志都不能含 hkey 值（审查重点 #1）"""
    caplog.set_level(logging.DEBUG)
    fake_client.build_api_url("/bbs/app/user/message", {"heybox_id": "1"})
    assert "hkey=" not in caplog.text
