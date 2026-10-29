"""发帖分区：默认 PC 区之外，还要能挂上游戏专属分区。

用户反馈的问题：只选 PC 区的话，帖子进不了游戏自己的分区，作者不知道。
所以 --topic 解析失败必须报错，不能静默降级成只挂 PC 区。

另外注意：小黑盒的「分区」就是 topic，ID 必须真实存在，
抄网上的数字会一直报"错误的帖子类型#0001"。
"""

import pytest

from xhh_agent.cli.cmd_post import DEFAULT_TOPIC_ID, _resolve_topics, _split_topic_args
from xhh_agent.config import load_config
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.session import Session


def _client() -> ProtocolClient:
    return ProtocolClient(Session(cookie="cookie=secret", heybox_id="10000001"), load_config())


# ── _split_topic_args ─────────────────────────────────────


def test_ids_and_names_are_separated():
    ids, names = _split_topic_args(["1", "影之刃零"])
    assert ids == ["1"]
    assert names == ["影之刃零"]


def test_comma_separated_values_are_split():
    ids, names = _split_topic_args(["1,733575", "影之刃零,Steam"])
    assert ids == ["1", "733575"]
    assert names == ["影之刃零", "Steam"]


def test_blank_values_are_ignored():
    ids, names = _split_topic_args(["", "  ", ",", None])
    assert ids == []
    assert names == []


def test_none_gives_empty_lists():
    assert _split_topic_args(None) == ([], [])


# ── _resolve_topics ───────────────────────────────────────


async def test_name_resolves_to_exact_match(monkeypatch):
    async def search(self, query):
        return [
            {"topic_id": "68910", "name": "影之刃3"},
            {"topic_id": "733575", "name": "影之刃零"},
        ]

    monkeypatch.setattr(ProtocolClient, "search_topics", search)
    topics, resolved = await _resolve_topics(_client(), ["1"], ["影之刃零"])
    assert topics == ["1", "733575"]
    assert resolved == {"影之刃零": "733575"}


async def test_falls_back_to_first_hit_when_no_exact_name(monkeypatch):
    """分区名不必一字不差，"影之刃" 也该能挂到游戏分区。"""

    async def search(self, query):
        return [{"topic_id": "733575", "name": "影之刃零"}]

    monkeypatch.setattr(ProtocolClient, "search_topics", search)
    topics, _ = await _resolve_topics(_client(), ["1"], ["影之刃"])
    assert topics == ["1", "733575"]


async def test_unknown_topic_raises_instead_of_silently_dropping(monkeypatch):
    """解析不到就报错：静默只挂 PC 区正是用户抱怨的那个 bug。"""

    async def search(self, query):
        return []

    monkeypatch.setattr(ProtocolClient, "search_topics", search)
    with pytest.raises(ValueError, match="找不到分区"):
        await _resolve_topics(_client(), ["1"], ["根本不存在的游戏"])


async def test_duplicate_ids_are_collapsed(monkeypatch):
    """名字解析出的 ID 和 --tag 给的重复时只留一份。"""

    async def search(self, query):
        return [{"topic_id": "733575", "name": "影之刃零"}]

    monkeypatch.setattr(ProtocolClient, "search_topics", search)
    topics, _ = await _resolve_topics(_client(), ["1", "733575"], ["影之刃零"])
    assert topics == ["1", "733575"]


async def test_pc_topic_is_kept_alongside_game_topic(monkeypatch):
    """两个分区都要在：PC 区不是被替换，是被保留。"""

    async def search(self, query):
        return [{"topic_id": "733575", "name": "影之刃零"}]

    monkeypatch.setattr(ProtocolClient, "search_topics", search)
    topics, _ = await _resolve_topics(_client(), [DEFAULT_TOPIC_ID], ["影之刃零"])
    assert topics[0] == "1"
    assert "733575" in topics
    assert len(topics) == 2
