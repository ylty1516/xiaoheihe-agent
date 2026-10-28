"""热搜榜（黑盒热议）。

接口：/bbs/app/api/search/welcome_page/v2?force_refresh=false
返回 result.Lists 是若干组，其中 head_text == "黑盒热议" 的那组就是热搜。
"""

import pytest


async def test_fetch_hot_topics_returns_top_n(fake_hot_client):
    """真实热搜榜是「无标题」那组：游戏名和热议混排。"""
    topics = await fake_hot_client.fetch_hot_topics(limit=5)
    assert len(topics) == 5
    assert topics[0]["text"] == "影之刃零"
    assert topics[0]["index"] == 1
    # AL 在真实榜单里是第 4，不是第 1（「黑盒热议」子榜里才是第 1）
    assert next(t for t in topics if "AL" in t["text"])["index"] == 4


async def test_hot_topics_carry_rank_and_tags(fake_hot_client):
    topics = await fake_hot_client.fetch_hot_topics(limit=3)
    assert all("text" in t and "index" in t for t in topics)
    # 有 right_tag 的条目要保留，可能是「热」「新」这类标记
    assert all("right_tag" in t for t in topics)


async def test_hot_topics_ignores_small_program_group(fake_hot_client):
    """「小程序」那组（喜加一之类）不能混进来。"""
    topics = await fake_hot_client.fetch_hot_topics(limit=20)
    assert "喜加一" not in [t["text"] for t in topics]
