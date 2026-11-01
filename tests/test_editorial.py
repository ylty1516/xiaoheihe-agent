"""Regression cases for content memory, plans and publication boundaries."""

import types

import pytest
from aiohttp.test_utils import TestClient, TestServer

from xhh_agent.content.editorial import (
    HISTORY,
    brief_path,
    empty_brief,
    load_history,
    plan_options,
    record_publication,
    review,
    save_writing_card,
    validate_brief,
    write_json,
    writing_cards,
)
from xhh_agent.content.style import profile
from xhh_agent.webui.editorial import draft_path, editor_action, read_draft


@pytest.fixture
def brief():
    return {
        "reader": "新玩家",
        "question": "处决提示为何亮了仍不能触发？",
        "conclusion": "须核对目标状态与触发条件，不能只看按钮亮起",
        "new_information": "逐条核对触发条件和反例",
        "exclude": ["画面优化"],
        "structure": "mechanism",
        "facts": [
            {"claim": "测试素材：触发条件需核对目标状态", "source": "https://example.com/manual"}
        ],
    }


def remember(root, markdown, brief=None, link_id="123"):
    record_publication(root, link_id=link_id, title="旧文章", markdown=markdown, brief=brief)


def test_brief_requires_new_information_and_traceable_facts(brief):
    assert validate_brief(brief) == []
    brief["new_information"] = ""
    brief["facts"][0]["source"] = "没有查证"
    assert len(validate_brief(brief)) == 2


def test_malformed_card_cannot_crash_review(tmp_path):
    result = review(tmp_path, "正文", {**empty_brief(), "facts": [123]})
    assert result["blockers"] and not result["matches"]


def test_three_distinct_plans_keep_evidence_without_fabrication(brief):
    plans = plan_options(brief, [])
    assert len({p["id"] for p in plans}) == 3
    assert plans[0]["id"] == "mechanism"
    assert all(p["evidence"] == brief["facts"] for p in plans)


def test_five_articles_on_same_game_keep_distinct_questions(tmp_path, brief):
    topics = [
        ("troubleshooting", "影之刃零的提示亮起后应先核对什么？", "按触发条件排查"),
        ("mechanism", "影之刃零的目标状态怎样影响操作？", "解释状态与操作的关系"),
        ("update", "影之刃零补丁前后哪些条件发生变化？", "对照版本，列明未知项"),
        ("debate", "影之刃零社区对同一机制的分歧来自哪里？", "区分各方的证据与前提"),
        ("investigation", "影之刃零机制说法最初出自哪里？", "梳理来源链与证据缺口"),
    ]
    for index, (structure, question, conclusion) in enumerate(topics):
        card = {
            **brief,
            "structure": structure,
            "question": question,
            "conclusion": conclusion,
            "facts": [
                {
                    "claim": f"测试资料{index}：本篇独有的模拟证据",
                    "source": f"https://example.com/{index}",
                }
            ],
        }
        plans = plan_options(card, load_history(tmp_path))
        assert plans[0]["id"] == structure
        assert plans[0]["question"] == question
        record_publication(
            tmp_path, link_id=str(index), title=question, markdown=f"测试正文 {index}", brief=card
        )
    assert len({p["brief"]["question"] for p in load_history(tmp_path)}) == 5


def test_drafts_do_not_become_publication_history(tmp_path, brief):
    folder = tmp_path / ".data"
    folder.mkdir()
    (folder / "post-old.md").write_text("草稿" * 200, encoding="utf-8")
    result = review(tmp_path, "草稿" * 200, brief)
    assert result["history_count"] == 0
    assert not result["matches"] and not result["blockers"]
    assert result["warnings"]


def test_reformatted_duplicate_is_blocked(tmp_path, brief):
    body = "这个示例围绕同一个问题说明具体条件，需要核对目标状态。" * 12
    remember(tmp_path, body)
    assert review(tmp_path, "## 标题\n" + body, brief)["warnings"]
    assert review(tmp_path, "**" + body + "**\n\n喵~", brief)["blockers"]


def test_reused_fact_and_claim_detected_after_body_changes(tmp_path, brief):
    remember(tmp_path, "旧正文讲操作条件", brief)
    result = review(tmp_path, "完全重写的正文，不能靠换词证明新增。", brief)
    assert result["matches"][0]["same_claim"]
    assert result["matches"][0]["reused_facts"]


def test_repeated_paragraph_returns_both_texts(tmp_path):
    para = "请先检查目标是否进入可触发状态，再按顺序核对提示与操作条件，这一步需要保留版本说明。"
    remember(tmp_path, para + "\n\n旧的其他段落。")
    result = review(tmp_path, "一个新的开头。\n\n" + para, None)
    repeated = result["matches"][0]["repeated_paragraphs"][0]
    assert repeated["text"] == repeated["previous"] == para


def test_same_layout_with_different_subject_is_not_content_duplicate(tmp_path):
    remember(tmp_path, "## 武器升级\n\n升级消耗材料，需要到对应商店查看。")
    result = review(tmp_path, "## 画面设置\n\n渲染分辨率影响图像清晰程度。", None)
    assert not result["matches"] and not result["blockers"]


def test_recording_same_link_updates_instead_of_duplicating(tmp_path):
    remember(tmp_path, "旧内容")
    remember(tmp_path, "新内容")
    assert len(load_history(tmp_path)) == 1
    assert load_history(tmp_path)[0]["markdown"] == "新内容"


def test_editing_publication_does_not_collide_with_itself(tmp_path, brief):
    body = "用于测试编辑同一篇已发文章的素材。" * 30
    remember(tmp_path, body, brief)
    assert review(tmp_path, body, brief)["blockers"]
    assert not review(tmp_path, body, brief, exclude_link_id="123")["blockers"]


def test_corrupt_history_is_not_treated_as_empty(tmp_path):
    (tmp_path / ".data").mkdir()
    (tmp_path / HISTORY).write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="历史读取失败"):
        review(tmp_path, "新内容", None)


def test_incomplete_history_record_is_reported_as_corrupt(tmp_path):
    write_json(tmp_path / HISTORY, [{"markdown": "正文", "brief": {}, "published_at": 1}])
    with pytest.raises(ValueError, match="历史读取失败"):
        review(tmp_path, "新内容", None)


def test_style_recognizes_numbering_and_ignores_signature():
    assert profile("## 01 杀气机制\n\n怎么选择？\n\n喵~")["小标题形态"] == "编号"
    assert profile("## 01 杀气机制\n\n怎么选择？\n\n喵~")["收尾方式"] == "问句收尾"


@pytest.mark.parametrize("script", ["check_post.py", "style_profile.py", "editorial.py"])
def test_scripts_emit_utf8_even_under_western_windows_encoding(tmp_path, script):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "post-中文.md"
    source.write_text("正文" * 800 + "\n![a](x)\n![b](y)\n![c](z)", encoding="utf-8")
    args = {
        "check_post.py": [str(source)],
        "style_profile.py": ["show", str(source)],
        "editorial.py": ["init", str(source)],
    }[script]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / script), *args],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )
    assert result.returncode == 0, result.stderr
    assert "中文" in result.stdout.decode("utf-8") or "小标题" in result.stdout.decode("utf-8")


@pytest.mark.parametrize(
    "name", ["../post-x.md", "post-x.md/other", "post-x.md:stream", "README.md"]
)
def test_edit_path_cannot_escape_data(tmp_path, name):
    with pytest.raises(ValueError):
        draft_path(tmp_path, name)


def test_editor_saves_and_rejects_stale_revision(tmp_path, brief):
    initial = read_draft(tmp_path, "post-x.md")
    data = {
        "file": "post-x.md",
        "action": "save",
        "revision": initial["revision"],
        "brief": brief,
        "markdown": "正文",
    }
    editor_action(tmp_path, data)
    with pytest.raises(ValueError, match="其他窗口"):
        editor_action(tmp_path, {**data, "markdown": "过时内容"})
    assert read_draft(tmp_path, "post-x.md")["markdown"] == "正文"


def test_learning_card_must_be_complete_and_is_searchable(tmp_path):
    card = {
        "link_id": "123",
        "article_type": "mechanism",
        "source_url": "https://example.com/post",
        "reader_question": "理解目标状态",
        "argument_order": ["规则", "反例"],
        "evidence_usage": ["截图核对条件"],
        "applicable_when": "有规则来源",
        "avoid": [],
    }
    save_writing_card(tmp_path, card)
    assert writing_cards(tmp_path, "反例")[0]["status"] == "ready"
    with pytest.raises(ValueError):
        save_writing_card(tmp_path, {**card, "argument_order": []})


async def test_editor_http_plan_save_and_rewrite_are_local(tmp_path, brief, monkeypatch):
    import xhh_agent.webui.app as app_module
    from xhh_agent.config import load_config
    from xhh_agent.webui.app import create_app

    monkeypatch.setattr(app_module, "_make_client", lambda *a: pytest.fail("不应访问账号"))
    async with TestClient(TestServer(create_app(tmp_path, load_config()))) as client:
        response = await client.get("/api/editorial?file=post-test.md")
        initial = await response.json()
        saved = await client.post(
            "/api/editorial",
            json={
                "file": "post-test.md",
                "action": "save",
                "markdown": "前文\n\n中段\n\n后文",
                "brief": brief,
                "revision": initial["revision"],
            },
        )
        assert (await saved.json())["ok"]
        plans = await client.post(
            "/api/editorial", json={"file": "post-test.md", "action": "plan", "brief": brief}
        )
        assert len((await plans.json())["plans"]) == 3
        rewrite = await client.post(
            "/api/editorial",
            json={
                "file": "post-test.md",
                "action": "rewrite",
                "brief": brief,
                "selected": "中段",
                "instruction": "更具体",
            },
        )
        prompt = (await rewrite.json())["prompt"]
        assert "其余正文保持原样" in prompt and "https://example.com/manual" in prompt
        assert "前文" not in prompt
        bad = await client.post("/api/editorial", json=[])
        assert bad.status == 400
        assert (await client.get("/editorial.js")).status == 200


@pytest.mark.parametrize("draft,ok", [(True, True), (False, True), (False, False)])
async def test_cli_only_archives_successful_publications(tmp_path, brief, monkeypatch, draft, ok):
    from xhh_agent.cli import cmd_post
    from xhh_agent.config import load_config
    from xhh_agent.protocol.models import PostResult

    class Client:
        async def submit_post(self, **kwargs):
            return PostResult(ok=ok, link_id="123" if ok else "", is_draft=draft)

        async def close(self):
            pass

    source = tmp_path / "post-x.md"
    source.write_text("正文事实与来源。" * 160 + "\n![a](x)\n![b](y)\n![c](z)", encoding="utf-8")
    write_json(brief_path(source), brief)
    monkeypatch.setattr(cmd_post, "_editorial_root", lambda p: tmp_path)
    monkeypatch.setattr(cmd_post, "markdown_to_heybox_html", lambda m: "<p>预览</p>")
    monkeypatch.setattr(cmd_post, "ProtocolClient", lambda *a: Client())
    monkeypatch.setattr(
        cmd_post, "SessionStore", lambda p: types.SimpleNamespace(load=lambda: object())
    )
    args = types.SimpleNamespace(md=str(source), title="标题", yes=True, allow_short=False)
    code = await cmd_post._run(load_config(), args, draft=draft)
    assert code == (0 if ok else cmd_post.EXIT_ERROR)
    assert bool(load_history(tmp_path)) is (not draft and ok)


async def test_web_publish_failure_does_not_archive(tmp_path, monkeypatch):
    from xhh_agent.protocol.models import PostResult
    from xhh_agent.webui import publishing

    folder = tmp_path / ".data"
    folder.mkdir()
    (folder / "post-x.md").write_text("字" * 1500 + "\n![a](x)\n![b](y)\n![c](z)", encoding="utf-8")

    class Client:
        async def search_topics(self, name):
            return [{"name": name, "topic_id": "1"}]

        async def submit_post(self, **kwargs):
            return PostResult(ok=False, link_id="bad")

        async def close(self):
            pass

    monkeypatch.setattr(
        publishing,
        "slot_state",
        lambda **k: types.SimpleNamespace(
            allowed=True, reason="ok", today_count=0, cap=3, next_at=""
        ),
    )
    monkeypatch.setattr(publishing, "markdown_to_heybox_html", lambda m: "<p>正文</p>")
    monkeypatch.setattr(
        publishing, "SessionStore", lambda p: types.SimpleNamespace(load=lambda: object())
    )
    monkeypatch.setattr(publishing, "ProtocolClient", lambda *a: Client())
    result = await publishing.publish(
        tmp_path,
        types.SimpleNamespace(db_path=".data/x.db"),
        file_name="post-x.md",
        title="标题",
        topics=["PC游戏"],
        accept_warnings=True,
        confirm=True,
    )
    assert not result["ok"] and not load_history(tmp_path)
