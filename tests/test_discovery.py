"""Freshness, provenance, ordering and caching for read-only topic discovery."""

import asyncio
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp.test_utils import TestClient, TestServer

from xhh_agent.config import load_config
from xhh_agent.protocol.errors import SchemaChanged, TransportError
from xhh_agent.webui.discovery import Discovery


async def test_hot_board_uses_forced_refresh_and_preserves_game_board(fake_hot_client, monkeypatch):
    urls = []

    async def request(method, url):
        urls.append(parse_qs(urlsplit(url).query))
        return {
            "result": {
                "Lists": [
                    {"head_text": "", "items": [{"text": "综合事件"}]},
                    {
                        "head_text": "热门游戏",
                        "items": [{"text": "游戏A"}, {"text": " 游戏A "}, {"text": "游戏B"}],
                    },
                ]
            }
        }

    monkeypatch.setattr(fake_hot_client, "_request_json", request)
    data = await fake_hot_client.fetch_hot_board(board="games")
    assert urls[0]["force_refresh"] == ["true"]
    assert data["source_board"] == "games" and not data["fallback"]
    assert [(x["text"], x["index"]) for x in data["items"]] == [("游戏A", 1), ("游戏B", 3)]


async def test_fallback_is_explicit_and_never_mislabels_games(fake_hot_client, monkeypatch):
    async def request(*args):
        return {
            "result": {
                "Lists": [
                    {"head_text": "", "items": [None, {}, {"text": ""}]},
                    {"head_text": "黑盒热议", "items": [{"text": "讨论A"}]},
                ]
            }
        }

    monkeypatch.setattr(fake_hot_client, "_request_json", request)
    data = await fake_hot_client.fetch_hot_board()
    assert data["fallback"] and data["source_board"] == "discussions"
    with pytest.raises(SchemaChanged):
        await fake_hot_client.fetch_hot_board(board="games")


async def test_latest_and_likes_do_not_get_resorted_by_comment_count(
    fake_search_client, monkeypatch
):
    def item(id, age, likes, comments):
        return {
            "info": {
                "linkid": id,
                "title": "<em>测试</em>帖子",
                "create_at": 1800000000 - age,
                "link_award_num": likes,
                "up": 0,
                "comment_num": comments,
            }
        }

    async def request(*args):
        return {
            "result": {
                "items": [
                    item("old", 500, 80, 900),
                    item("new", 10, 5, 0),
                    item("liked", 200, 100, 3),
                ]
            }
        }

    monkeypatch.setattr(fake_search_client, "_request_json", request)
    assert [
        p["link_id"]
        for p in await fake_search_client.search_topic_posts(
            "测试", sort="create_date", time_range=""
        )
    ] == ["new", "liked", "old"]
    assert [
        p["link_id"]
        for p in await fake_search_client.search_topic_posts(
            "测试", sort="award_num", time_range=""
        )
    ] == ["liked", "old", "new"]
    assert [
        p["link_id"]
        for p in await fake_search_client.search_topic_posts("测试", sort="default", time_range="")
    ] == ["old", "new", "liked"]


async def test_24h_enforces_dates_and_combines_recent_and_popular_samples(
    fake_search_client, monkeypatch
):
    import xhh_agent.protocol.client as module

    now = 1800000000
    seen = []
    monkeypatch.setattr(module.time, "time", lambda: now)

    def item(id, stamp, likes=0):
        return {
            "info": {
                "linkid": id,
                "title": id,
                "create_at": stamp,
                "link_award_num": likes,
                "topics": [{"name": "游戏B", "topic_id": "23", "game_type": "pc"}],
            }
        }

    async def request(method, url):
        query = parse_qs(urlsplit(url).query)
        seen.append(query)
        items = [
            item("old", now - 86401, 99),
            item("dated", now - 600, 8),
            item("undated", None),
            item("future", now + 3600),
        ]
        if query["sort_filter"] == ["create_date"]:
            items = [item("latest", (now - 60) * 1000, 1), item("dated", now - 600, 8)]
        return {"result": {"items": items}}

    monkeypatch.setattr(fake_search_client, "_request_json", request)
    posts = await fake_search_client.search_topic_posts("游戏B", sort="award_num", time_range="1d")
    assert [p["link_id"] for p in posts] == ["dated", "latest"]
    assert posts[1]["published_at"] == now - 60
    assert posts[0]["topics"][0]["name"] == "游戏B"
    assert len(seen) == 2 and all(q["time_range"] == ["7d"] for q in seen)


@pytest.mark.parametrize("kwargs", [{"sort": "random"}, {"time_range": "today"}])
async def test_bad_search_options_fail_before_request(fake_search_client, monkeypatch, kwargs):
    async def forbidden(*args):
        pytest.fail("invalid options must not be sent upstream")

    monkeypatch.setattr(fake_search_client, "_request_json", forbidden)
    with pytest.raises(ValueError):
        await fake_search_client.search_topic_posts("测试", **kwargs)


class Source:
    def __init__(self):
        self.calls, self.closed = 0, 0
        self.topics = ["游戏A", "游戏B"]
        self.fail = False
        self.source_board = None

    async def fetch_hot_board(self, *, board, **kwargs):
        self.calls += 1
        if self.fail:
            raise TransportError("do not echo secret transport details")
        return {
            "items": [
                {"text": name, "index": i, "right_tag": ""} for i, name in enumerate(self.topics, 1)
            ],
            "source_board": self.source_board or board,
            "board": board,
            "source": "测试榜",
            "fallback": bool(self.source_board),
            "fetched_at": self.calls,
        }

    async def search_topic_posts(self, query, **kwargs):
        self.calls += 1
        return []

    async def close(self):
        self.closed += 1


async def test_cache_keeps_acquisition_time_and_rank_changes_are_comparable():
    source, tick = Source(), [0]
    service = Discovery(lambda: source, clock=lambda: tick[0])
    first = await service.get({"action": "hot"})
    cached = await service.get({"action": "hot"})
    assert source.calls == 1 and cached["cached"] and cached["fetched_at"] == first["fetched_at"]
    assert all(x["movement"] == "initial" for x in first["items"])
    tick[0] = 61
    source.topics = ["游戏B", "游戏C", "游戏A"]
    changed = await service.get({"action": "hot"})
    assert [(x["movement"], x["change"]) for x in changed["items"]] == [
        ("up", 1),
        ("new", None),
        ("down", -2),
    ]
    assert changed["compared_at"] == first["fetched_at"]
    source.source_board = "discussions"
    fallback = await service.get({"action": "hot", "refresh": True})
    assert fallback["compared_at"] is None and all(
        x["movement"] == "initial" for x in fallback["items"]
    )


async def test_failure_keeps_last_success_visible_and_does_not_leak_errors():
    source = Source()
    service = Discovery(lambda: source)
    good = await service.get({"action": "hot"})
    source.fail = True
    stale = await service.get({"action": "hot", "refresh": True})
    assert stale["stale"] and stale["warning"] and stale["fetched_at"] == good["fetched_at"]
    assert stale["items"] == good["items"] and "secret" not in json.dumps(stale)
    assert source.closed == 2
    assert (await service.get({"action": "hot"}))["stale"]
    source.fail = False
    assert not (await service.get({"action": "hot", "refresh": True}))["stale"]


async def test_simultaneous_refreshes_share_one_request():
    source, started, finish = Source(), asyncio.Event(), asyncio.Event()
    original = source.fetch_hot_board

    async def blocked(**kwargs):
        started.set()
        await finish.wait()
        return await original(**kwargs)

    source.fetch_hot_board = blocked
    service = Discovery(lambda: source)
    one = asyncio.create_task(service.get({"action": "hot", "refresh": True}))
    await started.wait()
    two = asyncio.create_task(service.get({"action": "hot", "refresh": True}))
    await asyncio.sleep(0)
    finish.set()
    results = await asyncio.gather(one, two)
    assert source.calls == 1 and sum(x["cached"] for x in results) == 1


async def test_cache_keys_separate_search_views_and_remain_bounded():
    source = Source()
    service = Discovery(lambda: source)
    await service.get({"action": "hot", "board": "all"})
    await service.get({"action": "hot", "board": "games"})
    for index in range(25):
        await service.get({"action": "topic", "query": f"游戏{index}"})
    assert len(service.cache) == 20 and source.calls == 27
    assert not service.locks


async def test_slow_query_does_not_block_a_different_board():
    source, started, finish = Source(), asyncio.Event(), asyncio.Event()
    original = source.fetch_hot_board

    async def blocked(**kwargs):
        if kwargs["board"] == "all":
            started.set()
            await finish.wait()
        return await original(**kwargs)

    source.fetch_hot_board = blocked
    service = Discovery(lambda: source)
    slow = asyncio.create_task(service.get({"action": "hot", "board": "all"}))
    await started.wait()
    try:
        fast = await asyncio.wait_for(service.get({"action": "hot", "board": "games"}), timeout=1)
        assert fast["source_board"] == "games"
    finally:
        finish.set()
        await slow
    assert not service.locks


async def test_http_discovery_is_read_only_and_returns_freshness(tmp_path, monkeypatch):
    from xhh_agent.webui.app import create_app
    from xhh_agent.webui.operations import Operations

    source = Source()
    monkeypatch.setattr(Operations, "client", lambda self: source)
    async with TestClient(TestServer(create_app(tmp_path, load_config()))) as client:
        response = await client.post("/api/operate", json={"action": "hot", "board": "games"})
        data = await response.json()
        assert (
            response.status == 200
            and data["source_board"] == "games"
            and data["refresh_interval"] == 60
        )
        bad = await client.post(
            "/api/operate", json={"action": "topic", "query": "测试", "sort": "bad"}
        )
        assert bad.status == 400
        assert not list((tmp_path / ".data").glob("post-*.md"))
