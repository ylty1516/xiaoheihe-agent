"""帖子归属判断 + 回评论。"""

import pytest


async def test_fetch_link_owner_returns_userid(fake_link_client):
    assert await fake_link_client.fetch_link_owner("194358228") == "83709585"


async def test_is_own_post_true(fake_link_client):
    assert await fake_link_client.is_own_post("194358228") is True


async def test_is_own_post_false(fake_link_client_other):
    assert await fake_link_client_other.is_own_post("180990240") is False


async def test_is_own_post_returns_false_on_error(fake_link_client_broken):
    """查不到归属时保守处理：当成"不是我的帖子"，宁可不回。

    去别人帖子下面刷评论，比漏回一条严重得多。
    """
    assert await fake_link_client_broken.is_own_post("x") is False


async def test_reply_comment_posts_expected_form(fake_reply_client):
    from xhh_agent.protocol.client import COMMENT_CREATE_PATH

    result = await fake_reply_client.reply_comment(
        link_id="194358228", reply_id="978556905", root_id="978556905", text="我也这么觉得喵"
    )
    assert result.ok

    method, url, kwargs = fake_reply_client.captured[-1]
    assert method == "POST"
    assert COMMENT_CREATE_PATH in url
    body = kwargs["data"]
    assert "link_id=194358228" in body
    assert "reply_id=978556905" in body
    assert "root_id=978556905" in body
    assert "is_cy=0" in body


async def test_reply_comment_with_emoji_text(fake_reply_client):
    """原生文本表情直接写在正文里。"""
    await fake_reply_client.reply_comment(
        link_id="1", reply_id="2", root_id="2", text="好的喵[cube_笑cry]"
    )
    _, _, kwargs = fake_reply_client.captured[-1]
    assert "cube_" in kwargs["data"]


async def test_reply_comment_rejects_empty(fake_reply_client):
    with pytest.raises(ValueError, match="内容"):
        await fake_reply_client.reply_comment(link_id="1", reply_id="2", root_id="2", text="  ")


async def test_reply_comment_rejects_overlong(fake_reply_client):
    with pytest.raises(ValueError, match="过长"):
        await fake_reply_client.reply_comment(
            link_id="1", reply_id="2", root_id="2", text="字" * 201
        )
