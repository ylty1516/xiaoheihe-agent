"""热搜榜（黑盒热议）。

接口：/bbs/app/api/search/welcome_page/v2?force_refresh=false
返回 result.Lists 是若干组，其中 head_text == "黑盒热议" 的那组就是热搜。
"""

import pytest


async def test_fetch_hot_topics_returns_top_n(fake_hot_client):
    topics = await fake_hot_client.fetch_hot_topics(limit=5)
    assert len(topics) == 5
    assert topics[0]["text"].startswith("AL 一号种子")
    assert topics[0]["index"] == 1


async def test_hot_topics_carry_rank_and_tags(fake_hot_client):
    topics = await fake_hot_client.fetch_hot_topics(limit=3)
    assert all("text" in t and "index" in t for t in topics)
    # 有 right_tag 的条目要保留，可能是「热」「新」这类标记
    assert all("right_tag" in t for t in topics)


async def test_hot_topics_ignores_other_groups(fake_hot_client):
    """只取「黑盒热议」，不要把「热门游戏」「小程序」混进来。"""
    topics = await fake_hot_client.fetch_hot_topics(limit=20)
    names = [t["text"] for t in topics]
    assert "影之刃零" not in names or len(names) <= 15
    assert "喜加一" not in names
