"""定时任务用的准备流程：poll + 生成草稿（不发送）。

人不在场时最危险的是"自己发出去"。所以这条路只**准备草稿**，
发送必须留给人或经确认的 agent。
"""

import json

import pytest

from xhh_agent.automation.poll import PollRunner
from xhh_agent.config import load_config
from xhh_agent.protocol.models import InboxItem, InboxPage
from xhh_agent.store.db import Store

NOW = 1793000000


class _FakeClient:
    heybox_id = "10000001"

    def __init__(self, items):
        self._items = items

    async def fetch_inbox(self, *, limit=20):
        return InboxPage(items=self._items)

    async def is_own_post(self, link_id):
        return True


class _FakeGenerator:
    def __init__(self, text="生成好的回复喵~"):
        self._text = text
        self.calls = 0

    async def generate(self, item):
        self.calls += 1
        return self._text


def _item(mid="m1") -> InboxItem:
    return InboxItem(
        channel="comment", message_id=mid, sender_id="222", sender_name="某人",
        text="这个值得买吗", timestamp=NOW - 60, raw_message_type="1",
        link_id="L1", reply_id="r1", root_id="r1", link_title="标题",
    )


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "t.db")


async def test_poll_with_generator_fills_draft(store):
    gen = _FakeGenerator("光驱版得看版本喵~")
    runner = PollRunner(_FakeClient([_item()]), store, load_config(), now=NOW, generator=gen)
    await runner.run_once()

    row = store.list_queue()[0]
    assert row["draft_reply"] == "光驱版得看版本喵~"
    assert gen.calls == 1


async def test_generator_failure_still_enqueues(store):
    """生成失败不能把评论丢掉——进队列等人写。"""
    class _Boom:
        async def generate(self, item):
            raise RuntimeError("模型挂了")

    runner = PollRunner(_FakeClient([_item()]), store, load_config(), now=NOW, generator=_Boom())
    await runner.run_once()

    rows = store.list_queue()
    assert len(rows) == 1
    assert rows[0]["draft_reply"] == ""


async def test_generator_never_sends(store):
    """准备草稿的路径绝不能发送——没有 send 调用就不可能有这个副作用。"""
    gen = _FakeGenerator()
    runner = PollRunner(_FakeClient([_item()]), store, load_config(), now=NOW, generator=gen)
    report = await runner.run_once()
    assert report.queued == 1
    # 队列状态仍是 pending，没有任何 sent_log
    assert store.count_sent("comment", since=0) == 0
