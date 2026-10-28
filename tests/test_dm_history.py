"""私信历史拉取。

字段名和发送时不一样：发出去用 `msg`，查回来是 `content`；
时间叫 `send_time` 且是毫秒；消息唯一标识是 `seq`。
"""

import pytest


async def test_fetch_dm_history_parses_messages(fake_dm_history_client):
    history = await fake_dm_history_client.fetch_dm_history("84812994", limit=5)
    assert len(history) == 2
    assert history[0].content == "在不在"
    assert history[0].sender_id == "85183285"
    assert history[0].msg_type == 6
    # send_time 是毫秒，统一归一到秒
    assert history[0].timestamp == 1793171471
    assert history[0].seq == "2115340585080733696"


async def test_fetch_dm_history_marks_mine(fake_dm_history_client):
    """要区分谁说的——不然会把对方的话当成自己说的。"""
    history = await fake_dm_history_client.fetch_dm_history("84812994")
    assert history[0].is_mine is True     # sender_id 是本账号
    assert history[1].is_mine is False


async def test_fetch_dm_history_requires_user_id(fake_dm_history_client):
    with pytest.raises(ValueError, match="user_id"):
        await fake_dm_history_client.fetch_dm_history("")


async def test_fetch_dm_history_schema_change(fake_dm_history_client_broken):
    from xhh_agent.protocol.errors import SchemaChanged

    with pytest.raises(SchemaChanged):
        await fake_dm_history_client_broken.fetch_dm_history("84812994")
