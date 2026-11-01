"""Writing habits should survive layout changes without becoming publication bans."""

import json
from dataclasses import replace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from xhh_agent.config import load_config
from xhh_agent.content.diversity import audit, fingerprint, rank_cards, reused_images
from xhh_agent.content.editorial import (
    HISTORY,
    empty_brief,
    load_history,
    plan_options,
    record_publication,
    review,
    validate_brief,
    write_json,
)
from xhh_agent.webui.writer import Writer


@pytest.fixture
def own_posts():
    # Short excerpts from the account's three verified public posts. Only their
    # writing habits are under test; their game claims are not validated facts.
    excerpts = [
        (
            "195437564",
            "首发设置",
            (
                "首发不到两天，影之刃零社区里评论最凶的两条帖子，一条在教人把超分输出分辨率拉到100%。\n\n"
                "我盯着这个结论看了半天，觉得好笑的地方在于流程。\n\n"
                "## 默认值是为谁准备的\n\n声音设置最下面压着两条滑条。\n\n"
                "媒体分 MC88、OC91，IGN 9 分、GS 8 分。\n\n你进游戏第一件事是翻设置，还是默认值直接硬上？"
            ),
        ),
        (
            "195461215",
            "杀气记账",
            (
                "我把‘按住防御键，杀气槽会持续缓慢流失’这行字来回读了几遍。\n\n"
                "这条规则把整场战斗的账本翻了个面。\n\n社区这两天骂得最凶的是打击感。\n\n"
                "## 01 一条槽两份活\n\n同一个数字既要买进攻又要买防守。\n\n"
                "写这篇之前我翻了 Steam 页面，推荐数17896条，MC 88。\n\n"
                "我更想听的是，你们把它当弹药，还是当护身符喵~"
            ),
        ),
        (
            "195479637",
            "难度曲线",
            (
                "我把这周关于《影之刃零》的高赞帖从头翻到尾，最扎眼的一句是‘难度是不是有点低了’。\n\n"
                "说这句话的人玩的是逆天者难度，刚打完花千笑。\n\n第三章是另一回事。\n\n"
                "这游戏不缺难度，缺的是一条一直往上走的线喵~\n\n"
                "老大们打到第三章之后，还有哪个BOSS让你重新坐直过？\n\n喵~"
            ),
        ),
    ]
    return [
        {
            "link_id": link,
            "title": title,
            "markdown": text,
            "brief": {},
            "published_at": i + 1,
            "subject": "games",
        }
        for i, (link, title, text) in enumerate(excerpts)
    ]


def test_actual_posts_share_rhetoric_despite_different_headings(own_posts):
    result = audit(own_posts)
    counts = {p["id"]: p["count"] for p in result["patterns"]}
    assert counts == {
        "community_lead": 3,
        "reading_persona": 3,
        "question_end": 3,
        "late_ratings": 2,
    }
    assert all(p["examples"] and p["suggestion"] for p in result["patterns"])


def test_layout_changes_do_not_hide_repeated_reading_path(tmp_path, own_posts):
    write_json(tmp_path / HISTORY, own_posts)
    draft = (
        "我把社区高赞帖翻了几遍，大家都在问怎么选装备。\n\n"
        "### 改用另一种标题\n\n装备的条件需要单独核对，以下信息还没有经过实测。\n\n"
        "你们是先看条件，还是先看数值？"
    )
    result = review(tmp_path, draft, None)
    assert len(result["diversity"]["warnings"]) >= 3
    assert not result["blockers"]


def test_useful_same_game_answer_does_not_need_random_topic_or_question(own_posts):
    result = audit(
        own_posts,
        "先核对目标是否处于允许触发的状态。\n\n条件满足再检查输入。\n\n仍无效时保留版本与操作记录，再查对应规则。",
    )
    assert not result["warnings"]


def test_sparse_history_and_code_samples_do_not_create_habit_warnings(own_posts):
    assert not audit(own_posts[:1], own_posts[0]["markdown"])["warnings"]
    text = "```text\n我把社区帖子翻了几遍，你们选哪个？\n```\n\n## 怎么选？\n\n已知条件不足，先补资料。\n\n[cube_滑稽]\n\n喵~"
    assert fingerprint(text)["habits"] == []
    assert not audit([], text)["patterns"]


def test_source_in_middle_is_not_automatically_a_community_opening():
    text = "给出条件答案。\n\n解释第一条规则。\n\n核对另一个边界。\n\n社区有人不同意，需要核对原始证据。\n\n目前只能确认这项条件。"
    assert "community_lead" not in fingerprint(text)["habits"]


def test_two_values_from_one_rating_source_are_not_a_source_rollcall():
    assert (
        "late_ratings"
        not in fingerprint("先固定比较条件。\n\n对照结果是MC88与MC91，需注明各自时间。")["habits"]
    )


def test_historical_import_and_edit_preserve_publication_order(tmp_path):
    record_publication(tmp_path, link_id="old", title="旧", markdown="旧文", published_at=100)
    record_publication(tmp_path, link_id="new", title="新", markdown="新文", published_at=200)
    record_publication(tmp_path, link_id="old", title="旧", markdown="编辑后的旧文")
    history = load_history(tmp_path)
    assert [p["link_id"] for p in history] == ["new", "old"]
    assert history[1]["published_at"] == 100


@pytest.mark.parametrize("stamp", [float("nan"), float("inf"), True, -1, 0])
def test_bad_import_time_cannot_poison_memory(tmp_path, stamp):
    with pytest.raises(ValueError, match="发布时间"):
        record_publication(tmp_path, link_id="1", title="文章", markdown="内容", published_at=stamp)
    assert not (tmp_path / HISTORY).exists()


def test_routes_rotate_by_recent_use_without_changing_reader_problem(own_posts):
    brief = {
        **empty_brief(),
        "reader": "遇到问题的人",
        "question": "何时可以触发？",
        "conclusion": "先核对条件",
        "new_information": "条件边界",
        "facts": [{"claim": "测试规则原文", "source": "https://example.com/rules"}],
    }
    first = plan_options(brief, own_posts)
    for old in own_posts:
        old["brief"]["route"] = first[0]["route"]
    next_plans = plan_options(brief, own_posts)
    assert next_plans[0]["route"] != first[0]["route"]
    assert next_plans[0]["id"] == "mechanism"
    assert len({p["route"] for p in next_plans}) == 3
    assert all(p["question"] == brief["question"] and p["evidence_needed"] for p in next_plans)
    assert validate_brief({**brief, "route": ["bad"]})
    assert validate_brief({**brief, "route": "change_trace"})


def test_images_compare_assets_across_heybox_hosts_but_not_visual_similarity():
    asset = "a" * 32
    history = [
        {
            "link_id": "1",
            "title": "旧图",
            "markdown": f"![](https://imgheybox.max-c.com/web/bbs/{asset}/thumb.jpeg)",
        }
    ]
    draft = f"![](https://imgheybox1.max-c.com/web/bbs/{asset}/thumb.jpeg?thumbnail=850)"
    assert reused_images(draft, history)[0]["count"] == 1
    assert not reused_images(draft.replace(asset, "b" * 32), history)
    assert not reused_images("![别的图](https://example.com/image.png)", history)


def test_learning_cards_must_fit_material_and_do_not_repeat_same_argument_order():
    cards = [
        {"link_id": "1", "reader_question": "桌面硬件", "argument_order": ["先解释"]},
        {"link_id": "2", "reader_question": "触发条件", "argument_order": ["先规则", "再边界"]},
        {"link_id": "3", "reader_question": "触发条件", "argument_order": ["先规则", "再边界"]},
        {"link_id": "4", "reader_question": "触发条件", "argument_order": ["先动作", "再例外"]},
    ]
    assert [c["link_id"] for c in rank_cards(cards, "触发条件怎么判断")] == ["2", "4"]
    assert not rank_cards(cards, "完全无关的资料")


async def test_writer_sees_published_body_habits_and_returns_review_without_saving(
    tmp_path, own_posts, monkeypatch
):
    import xhh_agent.webui.writer as module

    write_json(tmp_path / HISTORY, own_posts)
    seen = {}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def complete(self, **kwargs):
            seen.update(kwargs)
            return own_posts[2]["markdown"]

    monkeypatch.setattr(module, "OpenAICompatClient", Client)
    writer = Writer(tmp_path, replace(load_config(), llm_api_key="fake-only"))
    result = await writer.generate(
        {"mode": "write", "subject": "games", "material": "机制条件的测试材料"}
    )
    assert own_posts[2]["markdown"].split("\n\n")[0] in seen["prompt"]
    assert result["warnings"] and result["diversity"]["history_count"] == 3
    assert not list((tmp_path / ".data").glob("post-*.md"))
    assert len(json.loads((tmp_path / HISTORY).read_text(encoding="utf-8"))) == 3


async def test_library_exposes_grounded_habit_examples_without_account_calls(tmp_path, own_posts):
    from xhh_agent.webui.app import create_app

    write_json(tmp_path / HISTORY, own_posts)
    async with TestClient(TestServer(create_app(tmp_path, load_config()))) as client:
        response = await client.get("/api/library")
        assert response.status == 200
        data = await response.json()
        assert len(data["published"]) == data["diversity"]["history_count"] == 3
        examples = data["diversity"]["patterns"][0]["examples"]
        assert {e["link_id"] for e in examples} == {p["link_id"] for p in own_posts}
        assert "api_key" not in data
