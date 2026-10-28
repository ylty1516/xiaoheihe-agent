"""发帖带图：外部图片必须先转存到小黑盒 CDN。

Steam 的图直接外链大概率被防盗链拦，所以要走转存接口。
"""

import pytest


async def test_copy_image_returns_cdn_url(fake_copy_client):
    result = await fake_copy_client.copy_image_by_url("https://cdn.akamai.steamstatic.com/x.jpg")
    assert result["url"].startswith("https://imgheybox.max-c.com/")


async def test_copy_image_rejects_non_http(fake_copy_client):
    with pytest.raises(ValueError, match="http"):
        await fake_copy_client.copy_image_by_url("not-a-url")


async def test_submit_replaces_external_img_with_cdn(fake_post_client_with_images):
    """HTML 里的外部图片要换成 CDN 地址，并补上宽高属性。"""
    html = '<p>正文</p><img src="https://cdn.akamai.steamstatic.com/x.jpg"/>'
    await fake_post_client_with_images.submit_post(
        title="标题", content=html, draft=True, topic_ids=("1",), mode="article"
    )
    body = fake_post_client_with_images.captured[-1][2]["data"]
    text_json = __import__("urllib.parse", fromlist=["unquote_plus"]).unquote_plus(body)
    assert "imgheybox.max-c.com" in text_json
    assert "cdn.akamai.steamstatic.com" not in text_json
    assert "data-width" in text_json or "width" in text_json


async def test_submit_keeps_already_heybox_images(fake_post_client_with_images):
    """已经是小黑盒 CDN 的图片不该再转存一次。"""
    html = '<p>x</p><img src="https://imgheybox.max-c.com/bbs/a.jpg"/>'
    await fake_post_client_with_images.submit_post(
        title="标题", content=html, draft=True, topic_ids=("1",), mode="article"
    )
    assert fake_post_client_with_images.copy_calls == 0


async def test_submit_appends_image_blocks(fake_post_client_with_images):
    """图片还要作为独立 img block 提交，否则 web 端排版认不出来。"""
    html = '<p>x</p><img src="https://cdn.akamai.steamstatic.com/x.jpg"/>'
    await fake_post_client_with_images.submit_post(
        title="标题", content=html, draft=True, topic_ids=("1",), mode="article"
    )
    body = fake_post_client_with_images.captured[-1][2]["data"]
    text_json = __import__("urllib.parse", fromlist=["unquote_plus"]).unquote_plus(body)
    assert '"type": "img"' in text_json or '"type":"img"' in text_json
