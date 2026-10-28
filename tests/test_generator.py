"""AI 生成回复：prompt 构造 + 输出校验。

生成只是第一步，**校验才是关键**——生成出来的东西必须过得了 C4
（不编造第一人称经历）和 profile 的禁用词检查，否则直接发出去就是事故。
"""

import pytest

from xhh_agent.automation.generator import (
    LlmReplyGenerator,
    build_prompt,
    validate_generated,
)
from xhh_agent.protocol.models import InboxItem


def _item() -> InboxItem:
    return InboxItem(
        channel="comment",
        message_id="m1",
        sender_id="222",
        sender_name="桀骜不濯",
        text="3k去闲鱼随便挑一个光驱版啊",
        timestamp=1793000000,
        raw_message_type="1",
        link_id="194358228",
        reply_id="r1",
        root_id="r1",
        link_title="为了买ps5玩gta6把刀碎了",
        replied_text="",
    )


PROFILE = "# 语气规格\n句尾用喵~，少用转折，15-40字。"


# ── prompt 构造 ────────────────────────────────────────────

def test_prompt_contains_context():
    prompt = build_prompt(_item(), PROFILE)
    assert "3k去闲鱼随便挑一个光驱版啊" in prompt      # 对方说的
    assert "为了买ps5玩gta6把刀碎了" in prompt         # 帖子语境
    assert "喵~" in prompt                              # 语气规格
    assert "不编造" in prompt or "不写" in prompt


def test_prompt_includes_replied_text_when_present():
    item = InboxItem(
        channel="comment", message_id="m1", sender_id="2", sender_name="某人",
        text="同意", timestamp=1793000000, raw_message_type="1",
        link_id="L1", reply_id="r1", root_id="r1",
        link_title="标题", replied_text="光驱版和数字版怎么选",
    )
    prompt = build_prompt(item, PROFILE)
    assert "光驱版和数字版怎么选" in prompt


# ── 输出校验（C4 的代码级落地）────────────────────────────

def test_accepts_normal_reply():
    ok, reason = validate_generated("3k 就能拿下？我一直以为得 4k 往上喵~")
    assert ok, reason


def test_rejects_empty():
    assert not validate_generated("")[0]
    assert not validate_generated("   ")[0]


def test_rejects_too_long():
    assert not validate_generated("字" * 250)[0]


def test_rejects_fabricated_experience():
    """AI 不能替真人编造经历 —— 这是 C4，比语气重要得多。"""
    for text in (
        "我上周也买了光驱版，打了 40 小时喵~",
        "我昨天去店里试了，感觉还行喵~",
        "我之前买过一台，翻车了喵~",
    ):
        ok, reason = validate_generated(text)
        assert not ok, f"应该拒绝：{text}"
        assert "经历" in reason


def test_rejects_banned_words():
    ok, reason = validate_generated("综上所述，这个方案整体不错喵~")
    assert not ok
    assert "禁用" in reason or "综上" in reason


def test_rejects_too_many_transitions():
    """堆转折词是 AI 腔的主要来源。"""
    ok, reason = validate_generated("虽然便宜，不过水深，但其实还行，然而要小心喵~")
    assert not ok
    assert "转折" in reason


def test_strips_wrapping_quotes_and_prefix():
    """模型常会把回复包在引号里或加「回复：」前缀。"""
    ok, cleaned = validate_generated("「3k 就能拿下？得看版本喵~」")
    assert ok
    assert not cleaned.startswith("「")


# ── 生成器 ─────────────────────────────────────────────────

async def test_generator_calls_llm_and_returns_validated_text(fake_llm_client):
    gen = LlmReplyGenerator(
        client=fake_llm_client, profile_text=PROFILE, model="test-model"
    )
    text = await gen.generate(_item())
    assert "喵" in text
    assert fake_llm_client.calls, "应该调过模型"


async def test_generator_retries_once_on_invalid_output(fake_llm_client_bad_then_good):
    gen = LlmReplyGenerator(
        client=fake_llm_client_bad_then_good, profile_text=PROFILE, model="test-model"
    )
    text = await gen.generate(_item())
    assert "喵" in text
    assert len(fake_llm_client_bad_then_good.calls) == 2


async def test_generator_raises_after_two_invalid_outputs(fake_llm_client_always_bad):
    from xhh_agent.automation.generator import GenerationError

    gen = LlmReplyGenerator(
        client=fake_llm_client_always_bad, profile_text=PROFILE, model="test-model"
    )
    with pytest.raises(GenerationError):
        await gen.generate(_item())
