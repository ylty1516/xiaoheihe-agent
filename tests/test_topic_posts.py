"""按话题搜帖子，取高赞高评论的，用来判断社区在聊什么。

这是发帖前最重要的一步：**看别人怎么写，而不是自己搜新闻**。
自己搜的"最新消息"很容易过时，社区高赞帖在聊的才是真热点。
"""

import pytest


async def test_search_topic_posts_returns_sorted_by_engagement(fake_search_client):
    posts = await fake_search_client.search_topic_posts("GTA6", limit=5)
    assert len(posts) == 5
    # 按评论数降序
    counts = [p["comment_num"] for p in posts]
    assert counts == sorted(counts, reverse=True)


async def test_search_topic_posts_strips_highlight_tags(fake_search_client):
    """搜索结果标题里带 <em> 高亮标签，要清掉。"""
    posts = await fake_search_client.search_topic_posts("GTA6", limit=3)
    for p in posts:
        assert "<em>" not in p["title"]
        assert "</em>" not in p["title"]


async def test_search_topic_posts_carries_link_id(fake_search_client):
    posts = await fake_search_client.search_topic_posts("GTA6", limit=3)
    assert all(p["link_id"] for p in posts)


async def test_search_topic_posts_rejects_empty_query(fake_search_client):
    with pytest.raises(ValueError, match="关键词"):
        await fake_search_client.search_topic_posts("")
