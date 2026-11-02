"""Selections survive save/restart and reach the platform without hidden tags."""

import json
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from xhh_agent.content.preferences import load_preferences, save_preferences, validate_topics
from xhh_agent.webui.editorial import editor_action, read_draft
from xhh_agent.webui import publishing


def test_defaults_are_read_only_and_only_new_drafts_change(tmp_path):
    assert load_preferences(tmp_path)["topics"] == ["GitHub", "AI"]
    assert not (tmp_path / ".data").exists()
    old = editor_action(tmp_path, {"action": "new"})
    save_preferences(tmp_path, {"topics": ["软件", "AI", "AI"]})
    new = editor_action(tmp_path, {"action": "new"})
    assert read_draft(tmp_path, old["file"])["metadata"]["topics"] == ["GitHub", "AI"]
    assert new["metadata"]["topics"] == ["软件", "AI"]
    assert load_preferences(tmp_path)["topics"] == ["软件", "AI"]


@pytest.mark.parametrize("values", [[], "AI", [None], ["  "], ["x" * 101], ["x"] * 6])
def test_invalid_selection_cannot_be_saved(tmp_path, values):
    with pytest.raises(ValueError):
        save_preferences(tmp_path, {"topics": values})
    assert not (tmp_path / ".data/authoring-settings.json").exists()


def test_selection_is_trimmed_and_deduplicated():
    assert validate_topics([" GitHub ", "github", "AI", "AI"]) == ["GitHub", "AI"]


def test_old_single_topic_is_preserved_and_multiselect_roundtrips(tmp_path):
    path = tmp_path / ".data/post-legacy.md"
    path.parent.mkdir()
    path.write_text("旧稿", encoding="utf-8")
    path.with_suffix(".meta.json").write_text(json.dumps({"topic": "原游戏"}), encoding="utf-8")
    old = read_draft(tmp_path, path.name)
    editor_action(
        tmp_path,
        {
            "action": "save",
            "file": path.name,
            "revision": old["revision"],
            "markdown": "保留旧稿",
            "metadata": {"title": "旧标题"},
        },
    )
    same = read_draft(tmp_path, path.name)
    assert same["metadata"]["topic"] == "原游戏" and "topics" not in same["metadata"]
    editor_action(
        tmp_path,
        {
            "action": "save",
            "file": path.name,
            "revision": same["revision"],
            "markdown": "选择新的分区",
            "metadata": {"topics": ["GitHub", "AI"]},
        },
    )
    assert read_draft(tmp_path, path.name)["metadata"]["topics"] == ["GitHub", "AI"]


def test_job_freezes_selection_and_blank_task_looks_for_github(tmp_path):
    from test_auto_authoring import service

    svc = service(tmp_path)
    first = svc.create({})
    assert first["topics"] == ["GitHub", "AI"]
    assert first["request"]["query"] == "GitHub" and first["request"]["subject"] == "software"
    save_preferences(tmp_path, {"topics": ["软件"]})
    assert svc.read(first["id"])["topics"] == ["GitHub", "AI"]
    second = svc.create({"topics": ["AI"], "instruction": "写一个游戏工具", "subject": "games"})
    assert second["topics"] == ["AI"] and second["request"]["instruction"] == "写一个游戏工具"
    assert svc.create({})["topics"] == ["软件"]


async def test_platform_receives_two_exact_ids_and_no_pc_topic(tmp_path, monkeypatch):
    from test_writing_range import allow_slot, Client

    allow_slot(monkeypatch)
    draft = editor_action(tmp_path, {"action": "new"})
    editor_action(
        tmp_path,
        {
            "action": "save",
            "file": draft["file"],
            "revision": draft["revision"],
            "markdown": "介绍项目用途，保留材料来源。",
            "metadata": {"title": "项目用途", "profile": "flexible"},
        },
    )
    client = Client()

    async def lookup(name):
        return [{"name": name, "topic_id": {"GitHub": "572430", "AI": "806933"}[name]}]

    client.search_topics = lookup
    monkeypatch.setattr(publishing, "ProtocolClient", lambda *args: client)
    monkeypatch.setattr(
        publishing, "SessionStore", lambda *args: SimpleNamespace(load=lambda: object())
    )
    result = await publishing.publish(
        tmp_path,
        SimpleNamespace(db_path=".data/test.db"),
        file_name=draft["file"],
        title="项目用途",
        topics=[],
        accept_warnings=True,
        confirm=True,
    )
    assert result["ok"]
    assert client.calls[0]["topic_ids"] == ("572430", "806933")


async def test_similar_topic_does_not_replace_ai():
    class Client:
        async def search_topics(self, name):
            return [{"name": "AIgent", "topic_id": "675541"}]

    with pytest.raises(ValueError, match="精确"):
        await publishing._resolve_topic_ids(Client(), ["AI"], include_pc=False, strict=True)

    from xhh_agent.cli.cmd_post import _resolve_topics

    with pytest.raises(ValueError, match="精确"):
        await _resolve_topics(Client(), [], ["AI"])


@pytest.mark.parametrize("selection", [None, ["GitHub", "AI"]])
async def test_cli_defaults_and_explicit_topics_exclude_pc(tmp_path, monkeypatch, selection):
    from test_writing_range import Client
    from xhh_agent.cli import cmd_post
    from xhh_agent.config import load_config

    path = tmp_path / "post-tool.md"
    path.write_text("项目功能与使用条件说明。", encoding="utf-8")
    client = Client()

    async def lookup(name):
        return [{"name": name, "topic_id": {"GitHub": "572430", "AI": "806933"}[name]}]

    client.search_topics = lookup
    monkeypatch.setattr(cmd_post, "ProtocolClient", lambda *args: client)
    monkeypatch.setattr(cmd_post, "SessionStore", lambda *args: SimpleNamespace(load=lambda: object()))
    monkeypatch.setattr(cmd_post, "_editorial_root", lambda path: tmp_path)
    args = SimpleNamespace(md=str(path), title="项目说明", profile="flexible", yes=True, topic=selection)
    assert await cmd_post._run(load_config(), args, draft=False) == 0
    assert list(client.calls[0]["topic_ids"]) == ["572430", "806933"]


async def test_preferences_api_origin_guard_and_explicit_empty_selection(tmp_path):
    from xhh_agent.webui.app import create_app

    client = TestClient(TestServer(create_app(tmp_path)))
    await client.start_server()
    try:
        response = await client.get("/api/writing-options")
        assert (await response.json())["defaults"]["topics"] == ["GitHub", "AI"]
        response = await client.post("/api/authoring-settings", json={"topics": ["GitHub"]})
        assert (await response.json())["topics"] == ["GitHub"]
        response = await client.post(
            "/api/authoring-settings",
            json={"topics": ["AI"]},
            headers={"Origin": "https://foreign.test"},
        )
        assert response.status == 403
        response = await client.post("/api/publish", json={"topics": [], "confirm": True})
        assert response.status == 400
        assert load_preferences(tmp_path)["topics"] == ["GitHub"]
    finally:
        await client.close()
