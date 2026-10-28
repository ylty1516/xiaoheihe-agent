"""删除帖子与草稿。

不可逆操作：CLI 层必须要求 --yes，且 dry-run 先展示要删的是哪条。
"""

import pytest


async def test_delete_link_posts_expected_form(fake_delete_client):
    from xhh_agent.protocol.client import LINK_DELETE_PATH

    result = await fake_delete_client.delete_link("195231648")
    assert result.ok

    method, url, kwargs = fake_delete_client.captured[-1]
    assert method == "POST"
    assert LINK_DELETE_PATH in url
    assert "link_id=195231648" in kwargs["data"]


async def test_delete_link_requires_id(fake_delete_client):
    with pytest.raises(ValueError, match="link_id"):
        await fake_delete_client.delete_link("")


async def test_delete_link_failure_raises(fake_delete_client_fail):
    from xhh_agent.protocol.errors import TransportError

    with pytest.raises(TransportError, match="删除"):
        await fake_delete_client_fail.delete_link("1")


async def test_change_status_uses_query_params(fake_delete_client):
    from xhh_agent.protocol.client import LINK_CHANGE_STATUS_PATH

    await fake_delete_client.change_link_status("195231648", status=0)
    method, url, _ = fake_delete_client.captured[-1]
    assert method == "GET"
    assert LINK_CHANGE_STATUS_PATH in url
    assert "link_id=195231648" in url
    assert "status=0" in url
