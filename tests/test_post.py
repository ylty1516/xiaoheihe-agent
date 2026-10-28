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


async def test_article_mode_uses_html_block(fake_post_client):
    """文章（link_tag=11）才支持富文本，block 类型必须是 html。"""
    await fake_post_client.submit_post(
        title="标题", content="<p>正文</p>", draft=True, topic_ids=("1",), mode="article"
    )
    _, _, kwargs = fake_post_client.captured[-1]
    body = kwargs["data"]
    assert "%22type%22" in body
    assert "html" in body
    assert "link_tag=11" in body


async def test_dynamic_mode_uses_text_block(fake_post_client):
    """普通动态只能纯文本，用 html 会把标签原样显示出来。"""
    await fake_post_client.submit_post(
        title="标题", content="纯文本正文", draft=True, topic_ids=("1",), mode="dynamic"
    )
    _, _, kwargs = fake_post_client.captured[-1]
    body = kwargs["data"]
    assert "text" in body and "html" not in body
    assert "link_tag=27" in body


async def test_article_fields_required_for_article(fake_post_client):
    """文章模式缺这四个字段会回"错误的帖子类型#0001"。"""
    await fake_post_client.submit_post(
        title="标题", content="<p>正文</p>", draft=True, topic_ids=("1",), mode="article"
    )
    _, _, kwargs = fake_post_client.captured[-1]
    body = kwargs["data"]
    for field in ("declaration=1", "original=1", "extra_declaration=-1", "words_count="):
        assert field in body, f"缺少 {field}"


async def test_dynamic_mode_omits_article_fields(fake_post_client):
    await fake_post_client.submit_post(
        title="标题", content="纯文本", draft=True, topic_ids=("1",), mode="dynamic"
    )
    _, _, kwargs = fake_post_client.captured[-1]
    body = kwargs["data"]
    for field in ("declaration=", "extra_declaration="):
        assert field not in body


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


async def test_edit_mode_sends_link_id_and_edit_flag(fake_post_client):
    """改已发布的帖子：要带 link_id 和 edit=1，否则会新建一条。"""
    await fake_post_client.submit_post(
        title="标题", content="<p>改过的正文</p>", draft=False,
        topic_ids=("1",), mode="article", edit_link_id="195232074",
    )
    body = fake_post_client.captured[-1][2]["data"]
    assert "link_id=195232074" in body
    assert "edit=1" in body
