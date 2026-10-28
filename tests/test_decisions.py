"""回复决策三道门（规格 §5.7）。

逐条乱回是最快暴露机器特征的行为，也最容易招人烦。
三道门按顺序：直接跳过 → 强制人工 → 正常处理。
"""

import pytest

from xhh_agent.automation.decisions import Decision, DecideContext, decide
from xhh_agent.protocol.models import InboxItem


def _item(text: str, *, link_id: str = "L1", ts: int = 1793000000) -> InboxItem:
    return InboxItem(
        channel="comment",
        message_id="m1",
        sender_id="111",
        sender_name="某人",
        text=text,
        timestamp=ts,
        raw_message_type="1",
        link_id=link_id,
        reply_id="r1",
        root_id="r1",
    )


@pytest.fixture
def ctx() -> DecideContext:
    return DecideContext(now=1793000000, max_age_hours=6)


# ── 第一道：直接跳过 ────────────────────────────────────────

@pytest.mark.parametrize("text", ["顶", "1", "哈哈哈", "😀", "[cube_笑cry]", "。", "  "])
def test_meaningless_comments_skipped(text, ctx):
    assert decide(_item(text), ctx).action == "skip"


def test_contact_info_skipped(ctx):
    assert decide(_item("加我微信 abc123 便宜出"), ctx).action == "skip"
    assert decide(_item("VX 联系我"), ctx).action == "skip"


def test_insult_skipped(ctx):
    assert decide(_item("你就是个傻逼"), ctx).action == "skip"


def test_sensitive_domain_skipped(ctx):
    assert decide(_item("这个药能治高血压吗"), ctx).action == "skip"


def test_stale_comment_skipped(ctx):
    """只回 6 小时内的。半年前的评论回了像诈尸。"""
    old = _item("你好", ts=1793000000 - 7 * 3600)
    assert decide(old, ctx).action == "skip"


# ── 第二道：强制人工 ────────────────────────────────────────

def test_complaint_goes_to_queue(ctx):
    result = decide(_item("你卖的东西有质量问题，我要退款"), ctx)
    assert result.action == "queue"
    assert result.is_hard


def test_trade_goes_to_queue(ctx):
    assert decide(_item("多少钱能卖我"), ctx).action == "queue"


def test_asking_if_ai_goes_to_queue(ctx):
    """被问是不是 AI 时必须承认，而这类对话后续更难驾驭，交给人。"""
    result = decide(_item("你是ai吗"), ctx)
    assert result.action == "queue"
    assert result.is_hard


def test_promise_request_goes_to_queue(ctx):
    assert decide(_item("你能保证明天一定发货吗"), ctx).action == "queue"


# ── 第三道：正常处理 ────────────────────────────────────────

def test_normal_question_is_replyable(ctx):
    assert decide(_item("这个游戏值得买吗"), ctx).action == "reply"


def test_normal_chat_is_replyable(ctx):
    assert decide(_item("老哥说得挺有道理"), ctx).action == "reply"


def test_decision_is_frozen():
    d = Decision(action="skip", reason="test")
    with pytest.raises(Exception):
        d.action = "reply"
