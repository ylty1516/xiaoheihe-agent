import pytest

from xhh_agent.protocol.errors import SchemaChanged


async def test_parses_comment_mention_and_dm(fake_inbox_client):
    page = await fake_inbox_client.fetch_inbox(limit=20)
    channels = {i.channel for i in page.items}
    assert channels == {"comment", "mention", "dm"}
    assert all(i.message_id for i in page.items)
    assert all(i.timestamp > 0 for i in page.items)


async def test_preserves_raw_message_type(fake_inbox_client):
    """审查重点 #5：message_id 可能被兜底成 link_id:reply_id，
    同一 reply 下的'赞'和'回复'会撞键。必须保留 message_type 供 P2 区分。"""
    page = await fake_inbox_client.fetch_inbox()
    assert all(i.raw_message_type for i in page.items)


async def test_filters_out_own_messages(fake_inbox_client):
    monkeypatch_self = fake_inbox_client.heybox_id
    page = await fake_inbox_client.fetch_inbox()
    assert all(i.sender_id != monkeypatch_self for i in page.items)


async def test_schema_change_raises_not_empty(fake_broken_schema_client):
    """字段改名时必须报错，不能静默返回空列表（审查重点 #3）"""
    with pytest.raises(SchemaChanged):
        await fake_broken_schema_client.fetch_inbox()


async def test_skips_items_without_reply_target(fake_inbox_client):
    """没有 link_id/reply_id 的消息无法回复，应跳过而不是崩溃"""
    page = await fake_inbox_client.fetch_inbox()
    assert all(i.link_id for i in page.items if i.channel != "dm")


async def test_message_id_falls_back_when_missing(fake_inbox_client):
    """第二条评论没有 message_id，应兜底为 link_id:reply_id 而不是空字符串"""
    page = await fake_inbox_client.fetch_inbox()
    ids = [i.message_id for i in page.items if i.channel == "comment"]
    assert len(ids) == 2
    assert ids[1] == "abc123:9002"


async def test_dropped_messages_are_counted_not_silently_swallowed(fake_inbox_with_unparseable):
    """审查 C1：字段改名导致的逐条解析失败必须被计数，
    否则 `count: 0` + 退出码 0 会让 agent 汇报"没人找我"。"""
    page = await fake_inbox_with_unparseable.fetch_inbox()
    assert page.dropped > 0


async def test_all_messages_unparseable_raises_schema_changed(fake_inbox_all_broken):
    """所有消息都解析不出来，说明是接口结构变了，不是"没有未读"。"""
    from xhh_agent.protocol.errors import SchemaChanged

    with pytest.raises(SchemaChanged):
        await fake_inbox_all_broken.fetch_inbox()


async def test_dm_peer_id_comes_from_message_id(fake_inbox_client):
    """实测：私信会话的 user_a 只有 username/avartar，没有 id。
    对方 user_id 在 message_id 字段里（当 entry=message 时）。
    拿不到这个 id，P3 就没法把私信发回去。"""
    page = await fake_inbox_client.fetch_inbox()
    dm = [i for i in page.items if i.channel == "dm"]
    assert len(dm) == 1
    assert dm[0].sender_id == "34166294"
    assert dm[0].sender_name == "_Altria_"


# ── 发送私信（P3 最小片段）──────────────────────────────────

async def test_send_dm_posts_expected_form(fake_dm_client):
    from xhh_agent.protocol.client import DIRECT_MESSAGE_PATH

    result = await fake_dm_client.send_dm("84812994", "在不在")
    assert result.ok
    assert result.ack_id == "12345"

    method, url, kwargs = fake_dm_client.captured[-1]
    assert method == "POST"
    assert DIRECT_MESSAGE_PATH in url
    assert "to_user_id=84812994" in url
    assert "msg_type=6" not in url          # msg_type 在 body 里，不在 query

    body = kwargs["data"]
    assert "msg=" in body and "%E5%9C%A8%E4%B8%8D%E5%9C%A8" in body   # "在不在"
    assert "msg_type=6" in body
    assert "heybox_ack_id=" in body
    assert kwargs["headers"]["Content-Type"].startswith("application/x-www-form-urlencoded")


async def test_send_dm_requires_ack(fake_dm_client_no_ack):
    from xhh_agent.protocol.errors import TransportError

    with pytest.raises(TransportError, match="ack"):
        await fake_dm_client_no_ack.send_dm("84812994", "在不在")


async def test_send_dm_rejects_empty_text(fake_dm_client):
    with pytest.raises(ValueError, match="内容为空"):
        await fake_dm_client.send_dm("84812994", "   ")


async def test_send_dm_rejects_missing_target(fake_dm_client):
    with pytest.raises(ValueError, match="收件人"):
        await fake_dm_client.send_dm("", "在不在")


async def test_send_dm_rejects_overlong_text(fake_dm_client):
    with pytest.raises(ValueError, match="过长"):
        await fake_dm_client.send_dm("84812994", "x" * 501)
