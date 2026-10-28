"""自主逛帖：每天挑高质量帖子看别人怎么写。

只读能力，风险低。产出是分析素材 + 已读记录，写作分析由 agent 做。
"""

import pytest

from xhh_agent.automation.study import StudyRunner, pick_high_quality
from xhh_agent.protocol.models import FeedPost
from xhh_agent.store.db import Store


def _post(link_id: str, *, up: int, comments: int, words: int = 500) -> FeedPost:
    return FeedPost(
        link_id=link_id,
        title=f"帖子 {link_id}",
        description="描述 " * (words // 3),
        author_name="作者",
        up=up,
        comment_num=comments,
    )


def test_picks_by_engagement():
    posts = [
        _post("a", up=10, comments=1),
        _post("b", up=500, comments=80),
        _post("c", up=50, comments=5),
    ]
    picked = pick_high_quality(posts, count=2)
    assert [p.link_id for p in picked] == ["b", "c"]


def test_skips_already_read(tmp_path):
    store = Store(tmp_path / "t.db")
    store.claim("study", "b")
    posts = [_post("a", up=10, comments=1), _post("b", up=900, comments=99)]
    picked = pick_high_quality(posts, count=2, store=store)
    assert [p.link_id for p in picked] == ["a"]


def test_skips_too_short_posts():
    """太短的帖子学不到东西。"""
    posts = [
        _post("short", up=900, comments=99, words=20),
        _post("ok", up=10, comments=1, words=600),
    ]
    picked = pick_high_quality(posts, count=2, min_description=200)
    assert [p.link_id for p in picked] == ["ok"]


async def test_study_writes_notes(tmp_path, fake_feed_client):
    store = Store(tmp_path / "t.db")
    notes_dir = tmp_path / "notes"
    runner = StudyRunner(fake_feed_client, store, notes_dir=notes_dir, count=1)
    result = await runner.run_once()
    assert result.picked == 1

    files = list(notes_dir.glob("*.md"))
    assert files, "应生成笔记文件"
    text = files[0].read_text(encoding="utf-8")
    assert "link_id" in text
    assert "写法" in text or "结构" in text


async def test_study_marks_posts_as_read(tmp_path, fake_feed_client):
    store = Store(tmp_path / "t.db")
    runner = StudyRunner(fake_feed_client, store, notes_dir=tmp_path / "n", count=1)
    first = await runner.run_once()
    assert first.picked == 1

    second = await StudyRunner(fake_feed_client, store, notes_dir=tmp_path / "n", count=1).run_once()
    assert second.picked == 0 or second.picked != first.picked_ids


def test_blocks_to_text_extracts_text_and_marks_images():
    from xhh_agent.automation.study import blocks_to_text

    raw = (
        '[{"text":"第一段","type":"text"},'
        '{"height":100,"type":"img","url":"https://x/y.png","width":200},'
        '{"text":"第二段","type":"text"}]'
    )
    out = blocks_to_text(raw)
    assert "第一段" in out
    assert "第二段" in out
    assert "[图片 200x100]" in out
    assert '"type"' not in out      # 不该把 JSON 原样塞进去


def test_blocks_to_text_passes_plain_text_through():
    from xhh_agent.automation.study import blocks_to_text

    assert blocks_to_text("就是一段普通文字") == "就是一段普通文字"
    assert blocks_to_text("") == ""


def test_blocks_to_text_survives_broken_json():
    from xhh_agent.automation.study import blocks_to_text

    assert blocks_to_text("[{not json") == "[{not json"
