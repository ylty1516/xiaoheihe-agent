"""发帖：存草稿 vs 正式发布。

P1 阶段默认只存草稿——发布是不可逆动作，格式没验证前不该往公开区里发。
"""

import json

import pytest


async def test_draft_posts_to_link_post(fake_post_client):
    from xhh_agent.protocol.client import POST_PATH

    result = await fake_post_client.submit_post(
        title="测试标题", content="<p>正文</p>", draft=True
    )
    assert result.ok

    method, url, kwargs = fake_post_client.captured[-1]
    assert method == "POST"
    assert POST_PATH in url
    body = kwargs["data"]
    assert "title=" in body
    assert "post_type=1" in body
    assert "draft=1" in body
    assert "view_limit=1" in body


async def test_publish_has_no_draft_flag(fake_post_client):
    await fake_post_client.submit_post(title="标题", content="<p>正文</p>", draft=False)
    _, _, kwargs = fake_post_client.captured[-1]
    body = kwargs["data"]
    assert "draft=1" not in body
    assert "%22draft%22" not in body


async def test_html_is_wrapped_in_blocks(fake_post_client):
    await fake_post_client.submit_post(title="标题", content="<p>正文</p>", draft=True)
    _, _, kwargs = fake_post_client.captured[-1]
    body = kwargs["data"]
    # text 字段是 JSON 化的 block 数组，且 type 必须是 text 不是 html
    assert "%22type%22" in body
    assert "%22type%22%3A+%22text%22" in body or '"type": "text"' in body


async def test_article_only_fields_not_sent_for_normal_post(fake_post_client):
    """declaration/original 是文章(post_type=2)的字段。

    塞进普通动态，正式发布会回"错误的帖子类型#0001"——
    草稿模式下服务端宽容，所以这个错只在真发布时暴露。
    """
    await fake_post_client.submit_post(title="标题", content="<p>正文</p>", draft=True)
    _, _, kwargs = fake_post_client.captured[-1]
    body = kwargs["data"]
    for field in ("declaration=", "original=", "extra_declaration="):
        assert field not in body, f"不该发送 {field}"
    assert "link_tag=11" in body


async def test_publish_omits_draft_and_view_limit(fake_post_client):
    """正式发布的字段集里没有 draft / view_limit。"""
    await fake_post_client.submit_post(title="标题", content="<p>正文</p>", draft=False)
    _, _, kwargs = fake_post_client.captured[-1]
    body = kwargs["data"]
    assert "draft=" not in body
    assert "view_limit=" not in body


async def test_empty_title_rejected(fake_post_client):
    with pytest.raises(ValueError, match="标题"):
        await fake_post_client.submit_post(title="   ", content="<p>x</p>")


async def test_empty_html_rejected(fake_post_client):
    with pytest.raises(ValueError, match="正文"):
        await fake_post_client.submit_post(title="标题", content="  ")


async def test_failed_status_raises(fake_post_client_fail):
    from xhh_agent.protocol.errors import TransportError

    with pytest.raises(TransportError, match="发帖"):
        await fake_post_client_fail.submit_post(title="标题", content="<p>x</p>")
