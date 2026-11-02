"""Broader subjects and genres must survive authoring, learning and publishing."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from xhh_agent.cli import cmd_post
from xhh_agent.config import load_config
from xhh_agent.content.editorial import (
    empty_brief,
    load_history,
    plan_options,
    record_publication,
    save_writing_card,
    validate_brief,
    write_json,
)
from xhh_agent.content.topics import pick_topic
from xhh_agent.content.writing import GENERAL_TOPIC, GENRES, load_settings
from xhh_agent.protocol.models import PostResult
from xhh_agent.webui import publishing
from xhh_agent.webui.editorial import editor_action, read_draft
from xhh_agent.webui.writer import Writer


def create(
    root, subject="software", genre="tutorial", text="根据现有资料说明这个工具的用途与前提。"
):
    draft = editor_action(root, {"action": "new"})
    editor_action(
        root,
        {
            "action": "save",
            "file": draft["file"],
            "revision": draft["revision"],
            "markdown": text,
            "metadata": {
                "title": "工具使用说明",
                "topic": GENERAL_TOPIC,
                "subject": subject,
                "genre": genre,
                "profile": "flexible",
            },
        },
    )
    return root / ".data" / draft["file"]


def allow_slot(monkeypatch):
    monkeypatch.setattr(
        publishing,
        "slot_state",
        lambda **k: SimpleNamespace(
            allowed=True,
            reason="test",
            today_count=0,
            cap=3,
            next_at="",
        ),
    )


@pytest.mark.parametrize("subject", ["games", "hardware", "software", "ai"])
def test_subject_and_form_persist_without_replacing_custom_topic(tmp_path, subject):
    path = create(tmp_path, subject=subject, genre="review")
    current = read_draft(tmp_path, path.name)
    assert current["metadata"]["subject"] == subject
    assert current["metadata"]["genre"] == "review"
    assert current["metadata"]["topic"] == GENERAL_TOPIC
    settings = load_settings(path)
    assert settings["explicit"] and settings["subject"]["pc"] is (subject == "games")


def test_new_draft_is_not_locked_to_a_specific_game(tmp_path):
    new = editor_action(tmp_path, {"action": "new"})
    assert new["metadata"]["topics"] == ["GitHub", "AI"]
    assert new["metadata"]["subject"] == "software"
    assert new["metadata"]["genre"] == "auto"


def test_subject_and_genre_survive_duplicate_and_restore(tmp_path):
    path = create(tmp_path, subject="software", genre="review")
    current = read_draft(tmp_path, path.name)
    copied = editor_action(
        tmp_path, {"action": "duplicate", "file": path.name, "revision": current["revision"]}
    )
    assert copied["metadata"]["subject"] == "software" and copied["metadata"]["genre"] == "review"
    editor_action(
        tmp_path, {"action": "archive", "file": copied["file"], "revision": copied["revision"]}
    )
    from xhh_agent.webui.editorial import archived_drafts

    restored = editor_action(
        tmp_path, {"action": "restore", "archive_id": archived_drafts(tmp_path)[0]["archive_id"]}
    )
    assert (
        restored["metadata"]["subject"] == "software" and restored["metadata"]["genre"] == "review"
    )


def test_legacy_draft_save_keeps_legacy_routing_until_subject_is_chosen(tmp_path):
    path = tmp_path / ".data" / "post-old.md"
    path.parent.mkdir()
    path.write_text("原稿", encoding="utf-8")
    write_json(path.with_suffix(".meta.json"), {"title": "旧稿", "topic": "原游戏"})
    current = read_draft(tmp_path, path.name)
    editor_action(
        tmp_path,
        {
            "action": "save",
            "file": path.name,
            "revision": current["revision"],
            "markdown": "原稿续写",
            "metadata": {"title": "旧稿新标题"},
        },
    )
    assert not load_settings(path)["explicit"]
    assert read_draft(tmp_path, path.name)["metadata"]["topic"] == "原游戏"


@pytest.mark.parametrize("genre", ["news", "tutorial", "review", "roundup", "narrative", "essay"])
def test_new_forms_work_in_planning_and_learning(tmp_path, genre):
    brief = {
        **empty_brief(),
        "reader": "需要了解工具的人",
        "question": "这个工具能解决什么问题？",
        "conclusion": "先核对用途与使用条件",
        "new_information": "整理已给的文档材料",
        "structure": genre,
        "facts": [{"claim": "测试资料中的功能说明", "source": "https://example.com/docs"}],
    }
    assert not validate_brief(brief)
    plans = plan_options(brief, [])
    assert plans[0]["id"] == genre and all(p["evidence_needed"] for p in plans)
    card = {
        "link_id": "sample-" + genre,
        "article_type": genre,
        "reader_question": brief["question"],
        "argument_order": ["具体材料", "解释和适用范围"],
        "evidence_usage": ["核对文档的说明"],
        "applicable_when": "有可核对的材料",
        "avoid": [],
        "source_url": "https://example.com/article",
    }
    assert save_writing_card(tmp_path, card).exists()


class Client:
    def __init__(self):
        self.calls = []

    async def search_topics(self, name):
        return [{"name": name, "topic_id": "42"}]

    async def submit_post(self, **kwargs):
        self.calls.append(kwargs)
        return PostResult(ok=True, link_id="fake-published", is_draft=False)

    async def close(self):
        pass


@pytest.mark.parametrize("subject", ["hardware", "software", "ai"])
async def test_non_game_web_publish_does_not_force_pc_and_remembers_scope(
    tmp_path, monkeypatch, subject
):
    allow_slot(monkeypatch)
    path = create(tmp_path, subject=subject)
    client = Client()
    monkeypatch.setattr(publishing, "ProtocolClient", lambda *a: client)
    monkeypatch.setattr(
        publishing, "SessionStore", lambda p: SimpleNamespace(load=lambda: object())
    )
    result = await publishing.publish(
        tmp_path,
        SimpleNamespace(db_path=".data/test.db"),
        file_name=path.name,
        title="工具说明",
        topics=[GENERAL_TOPIC],
        accept_warnings=True,
        confirm=True,
    )
    assert result["ok"] and client.calls[0]["topic_ids"] == ("42",)
    history = load_history(tmp_path)
    assert history[0]["subject"] == subject and history[0]["genre"] == "tutorial"


async def test_explicit_web_topics_do_not_add_pc_base(tmp_path, monkeypatch):
    allow_slot(monkeypatch)
    path = create(tmp_path, subject="games")
    client = Client()
    monkeypatch.setattr(publishing, "ProtocolClient", lambda *a: client)
    monkeypatch.setattr(
        publishing, "SessionStore", lambda p: SimpleNamespace(load=lambda: object())
    )
    result = await publishing.publish(
        tmp_path,
        SimpleNamespace(db_path=".data/test.db"),
        file_name=path.name,
        title="游戏说明",
        topics=["游戏B"],
        accept_warnings=True,
        confirm=True,
    )
    assert result["ok"] and client.calls[0]["topic_ids"] == ("42",)


async def test_non_game_cli_uses_explicit_subject_without_pc(tmp_path, monkeypatch):
    file = tmp_path / "post-tool.md"
    file.write_text("简短的软件说明。", encoding="utf-8")
    client = Client()
    monkeypatch.setattr(cmd_post, "ProtocolClient", lambda *a: client)
    monkeypatch.setattr(cmd_post, "SessionStore", lambda p: SimpleNamespace(load=lambda: object()))
    monkeypatch.setattr(cmd_post, "_editorial_root", lambda p: tmp_path)
    args = SimpleNamespace(
        md=str(file), title="说明", profile="flexible", subject="software", yes=True
    )
    assert await cmd_post._run(load_config(), args, draft=False) == 0
    assert list(client.calls[0]["topic_ids"]) == ["42"]
    assert load_history(tmp_path)[0]["subject"] == "software"


def test_topic_resolution_does_not_pick_ambiguous_first_result():
    candidates = [{"name": "软件工具", "topic_id": "2"}, {"name": "游戏工具", "topic_id": "3"}]
    with pytest.raises(ValueError, match="多个"):
        pick_topic("工具", candidates)
    assert pick_topic("黑神话悟空", [{"name": "黑神话：悟空", "topic_id": "4"}])["topic_id"] == "4"


@pytest.mark.parametrize("subject", ["ai", "auto"])
async def test_ai_lens_does_not_import_unrelated_game_facts(tmp_path, monkeypatch, subject):
    import xhh_agent.webui.writer as module

    record_publication(
        tmp_path,
        link_id="old",
        title="影之刃零旧文",
        markdown="影之刃零里的旧数字与经验。",
        writing_subject="games",
    )
    captured = {}

    class Model:
        def __init__(self, **kwargs):
            pass

        async def complete(self, **kwargs):
            captured.update(kwargs)
            return "根据所给版本资料整理用途与限制。"

    monkeypatch.setattr(module, "OpenAICompatClient", Model)
    result = await Writer(tmp_path, replace(load_config(), llm_api_key="fake")).generate(
        {
            "mode": "write",
            "profile": "flexible",
            "subject": subject,
            "genre": "roundup",
            "material": "整理材料中的工具功能清单，不做实测排名。",
        }
    )
    assert "影之刃零" not in captured["prompt"]
    if subject == "ai":
        assert "AI工具" in captured["prompt"]
    assert result["genre"] == "roundup"
    assert result["subject"] == subject and not list((tmp_path / ".data").glob("post-*.md"))


async def test_options_and_topic_lookup_are_read_only(tmp_path, monkeypatch):
    from xhh_agent.webui.app import create_app
    from xhh_agent.webui.operations import Operations

    monkeypatch.setattr(Operations, "client", lambda self: Client())
    async with TestClient(TestServer(create_app(tmp_path, load_config()))) as client:
        options = await (await client.get("/api/writing-options")).json()
        assert (
            len(options["genres"]) == len(GENRES) + 1 and options["default_topic"] == GENERAL_TOPIC
        )
        response = await client.post(
            "/api/operate", json={"action": "find_topics", "query": "软件"}
        )
        assert response.status == 200 and (await response.json())["items"][0]["name"] == "软件"
        assert not list((tmp_path / ".data").glob("post-*.md"))


@pytest.mark.parametrize("phase", ["topic", "submit"])
async def test_network_failure_retains_draft_and_distinguishes_unknown_publication(
    tmp_path, monkeypatch, phase
):
    import aiohttp

    allow_slot(monkeypatch)
    path = create(tmp_path)

    class Offline(Client):
        async def search_topics(self, name):
            if phase == "topic":
                raise aiohttp.ClientConnectionError("offline")
            return await super().search_topics(name)

        async def submit_post(self, **kwargs):
            raise aiohttp.ClientConnectionError("response unavailable")

    monkeypatch.setattr(publishing, "ProtocolClient", lambda *a: Offline())
    monkeypatch.setattr(
        publishing, "SessionStore", lambda p: SimpleNamespace(load=lambda: object())
    )
    result = await publishing.publish(
        tmp_path,
        SimpleNamespace(db_path=".data/test.db"),
        file_name=path.name,
        title="说明",
        topics=[GENERAL_TOPIC],
        accept_warnings=True,
        confirm=True,
    )
    assert not result["ok"] and path.read_text(encoding="utf-8")
    assert ("尚未提交正文" if phase == "topic" else "勿重复发布") in "".join(result["lines"])
    assert not load_history(tmp_path)
