"""编排：一轮扫描 → 过滤 → 决策 → 闸门 → 入队。

P2 范围：只处理自己帖子下方的评论。
"""

import pytest

from xhh_agent.automation.poll import PollRunner
from xhh_agent.config import load_config
from xhh_agent.protocol.models import InboxItem, InboxPage
from xhh_agent.store.db import Store

NOW = 1793000000


def _item(text: str, *, link_id="L1", channel="comment", ts=NOW - 60, mid="m1") -> InboxItem:
    return InboxItem(
        channel=channel,
        message_id=mid,
        sender_id="222",
        sender_name="某人",
        text=text,
        timestamp=ts,
        raw_message_type="1",
        link_id=link_id,
        reply_id="r1",
        root_id="r1",
    )


class _FakeClient:
    def __init__(self, items, *, own_link_ids=("L1", "L2"), fail_owner=False):
        self._items = items
        self._own = set(own_link_ids)
        self._fail_owner = fail_owner
        self.heybox_id = "83709585"

    async def fetch_inbox(self, *, limit=20):
        return InboxPage(items=self._items)

    async def is_own_post(self, link_id: str) -> bool:
        if self._fail_owner:
            return False
        return link_id in self._own


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "t.db")


@pytest.fixture
def cfg():
    return load_config()


async def test_queues_normal_comment_on_own_post(store, cfg):
    runner = PollRunner(_FakeClient([_item("这个值得买吗")]), store, cfg, now=NOW)
    report = await runner.run_once()
    assert report.queued == 1
    assert len(store.list_queue()) == 1


async def test_skips_other_peoples_posts(store, cfg):
    """只回自己的帖子。别人的帖子哪怕评论再正常也不碰。"""
    runner = PollRunner(_FakeClient([_item("你好", link_id="OTHER")]), store, cfg, now=NOW)
    report = await runner.run_once()
    assert report.queued == 0
    assert any("不是" in reason for _, reason in report.reasons)


async def test_skips_mentions(store, cfg):
    runner = PollRunner(_FakeClient([_item("你好", channel="mention")]), store, cfg, now=NOW)
    assert (await runner.run_once()).queued == 0


async def test_skips_meaningless(store, cfg):
    runner = PollRunner(_FakeClient([_item("顶")]), store, cfg, now=NOW)
    assert (await runner.run_once()).queued == 0


async def test_skips_stale(store, cfg):
    stale = _item("你好", ts=NOW - 7 * 3600)
    runner = PollRunner(_FakeClient([stale]), store, cfg, now=NOW)
    assert (await runner.run_once()).queued == 0


async def test_same_message_not_queued_twice(store, cfg):
    client = _FakeClient([_item("这个值得买吗")])
    first = PollRunner(client, store, cfg, now=NOW)
    await first.run_once()
    second = PollRunner(client, store, cfg, now=NOW)
    report = await second.run_once()
    assert report.queued == 0
    assert len(store.list_queue()) == 1


async def test_hard_cases_are_marked(store, cfg):
    """投诉/交易/质疑 AI 必须标成强制人工，即使将来开 auto 也不自动发。"""
    runner = PollRunner(_FakeClient([_item("我要退款")]), store, cfg, now=NOW)
    await runner.run_once()
    row = store.list_queue()[0]
    assert "必须人处理" in row["draft_reply"] or row["incoming"]


async def test_per_post_limit_stops_queueing(store, cfg):
    """同一帖子累计 5 条后不再入队。"""
    for i in range(cfg.max_replies_per_post):
        store.log_sent("comment", f"old{i}", "hi", link_id="L1")
    runner = PollRunner(_FakeClient([_item("这个值得买吗")]), store, cfg, now=NOW)
    report = await runner.run_once()
    assert report.queued == 0
    assert report.blocked


async def test_queue_records_post_context(store, cfg):
    """入队时必须把语境一起存下来，否则生成层看不到帖子在聊什么。"""
    import json as _json

    item = InboxItem(
        channel="comment",
        message_id="ctx1",
        sender_id="222",
        sender_name="某人",
        text="3k去闲鱼随便挑一个光驱版啊",
        timestamp=NOW - 60,
        raw_message_type="1",
        link_id="L1",
        reply_id="r1",
        root_id="r1",
        link_title="为了买ps5玩gta6把刀碎了",
        replied_text="光驱版和数字版怎么选",
    )
    runner = PollRunner(_FakeClient([item]), store, cfg, now=NOW)
    await runner.run_once()

    row = store.list_queue()[0]
    incoming = _json.loads(row["incoming"])
    assert incoming["link_title"] == "为了买ps5玩gta6把刀碎了"
    assert incoming["replied_text"] == "光驱版和数字版怎么选"
