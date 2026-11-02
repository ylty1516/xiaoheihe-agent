"""Shared expression settings, immutable snapshots and explicit local management."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from xhh_agent.config import load_config
from xhh_agent.content.persona import (
    DEFAULT_PERSONA,
    Personas,
    compile_persona,
    compile_visual,
    digest,
    validate,
    voice_notes,
)
from xhh_agent.webui.writer import Writer


def card(name="A"):
    return {
        "schema_version": 1,
        "id": "author",
        "name": name,
        "system_prompt": "保留自己的判断，表达具体，不编造经历。" + name,
        "examples": [
            {"input": "假设修复了启动崩溃", "output": "这次修了启动崩溃。", "avoid": "注入新的活力"}
        ],
        "scenes": {"comment": "直接回应对方的具体问题"},
    }


def test_legacy_is_read_without_writing_and_preserved_in_first_save(tmp_path):
    profile = tmp_path / "voice/profile.md"
    profile.parent.mkdir()
    profile.write_text("私人身份与原有偏好", encoding="utf-8")
    store = Personas(tmp_path)
    snapshot = store.get("legacy")
    assert snapshot["revision"] == 0 and "私人身份" in snapshot["card"]["system_prompt"]
    assert not store.path.exists()
    modified = {**snapshot["card"], "system_prompt": "新表达"}
    saved = store.save(modified, 0, activate=True)
    assert saved["revision"] == 1
    restored = store.rollback("legacy", 0, 1)
    assert restored["revision"] == 2 and restored["card"]["system_prompt"] == "私人身份与原有偏好"
    assert profile.read_text(encoding="utf-8") == "私人身份与原有偏好"
    assert [x["revision"] for x in store.revisions("legacy")] == [2, 1, 0]


def test_saving_versions_is_optimistic_and_snapshots_stay_unchanged(tmp_path):
    store = Personas(tmp_path)
    first = store.save(card(), 0, activate=True)
    second = store.save(card("B"), 1)
    assert store.get()["revision"] == 2
    assert first["card"]["name"] == "A" and first["digest"] != second["digest"]
    assert store.get("author", 1) == first
    with pytest.raises(ValueError, match="其他窗口"):
        store.save(card("stale"), 1)


def test_astrbot_roundtrip_and_native_extensions(tmp_path):
    store = Personas(tmp_path)
    imported = store.import_card(
        {
            "persona_id": "test",
            "system_prompt": "简洁自然",
            "begin_dialogs": ["材料一", "文章一"],
            "tools": ["publish"],
            "skills": [],
            "api_key": "must-not-store",
        }
    )
    assert set(imported["ignored_fields"]) == {"tools", "skills", "api_key"}
    assert store.active_id() == DEFAULT_PERSONA
    assert store.revisions(DEFAULT_PERSONA)[0]["revision"] == 0
    assert "must-not-store" not in json.dumps(store.export("test"), ensure_ascii=False)
    assert store.export("test", "astrbot")["begin_dialogs"] == ["材料一", "文章一"]
    duplicate = store.import_card(store.export("test", "astrbot"))
    assert duplicate["card"]["id"] != "test"
    native = store.save(card(), 0)
    full = store.import_card(native["card"])
    assert full["card"]["examples"][0]["avoid"] == "注入新的活力"
    assert full["card"]["scenes"] == card()["scenes"]


@pytest.mark.parametrize(
    "bad",
    [
        {"system_prompt": ""},
        {"id": "../session"},
        {"examples": [{}]},
        {"scenes": {"publish": "yes"}},
        {"schema_version": True},
        {"system_prompt": "x" * 12001},
    ],
)
def test_invalid_cards_are_rejected(bad):
    with pytest.raises(ValueError):
        validate({**card(), **bad})


@pytest.mark.parametrize("dialogs", [["odd"], [{"role": "user"}, {}], "not a list"])
def test_bad_astrbot_dialogs_do_not_touch_storage(tmp_path, dialogs):
    store = Personas(tmp_path)
    with pytest.raises(ValueError):
        store.import_card({"system_prompt": "测试", "begin_dialogs": dialogs})
    assert not store.path.exists()


def test_scene_constraints_and_specific_advice(tmp_path):
    snapshot = Personas(tmp_path).save(card(), 0)
    assert "直接回应对方" in compile_persona(snapshot, "comment")
    assert "正常使用连接词" in compile_persona(snapshot, "article")
    assert "不能授予" in compile_persona(snapshot)
    assert not voice_notes("不过，这次修复了一个问题。因此可以继续测试。")
    assert not voice_notes("> 为游戏注入新的活力\n\n`总而言之`\n```\n总而言之\n``` ")
    assert voice_notes("为游戏注入新的活力。")[0]["excerpt"] == "注入新的活力"
    with pytest.raises(ValueError):
        compile_persona({**snapshot, "digest": "wrong"})


async def test_writer_and_comment_use_same_card_version(tmp_path, monkeypatch):
    from test_generator import _item

    from xhh_agent.automation.generator import LlmReplyGenerator

    store = Personas(tmp_path)
    snapshot = store.save(card(), 0, activate=True)
    seen = []

    class Client:
        def __init__(self, **kwargs):
            pass

        async def complete(self, **kwargs):
            seen.append(kwargs["prompt"])
            return "先确认对应版本。"

    monkeypatch.setattr("xhh_agent.webui.writer.OpenAICompatClient", Client)
    result = await Writer(tmp_path, replace(load_config(), llm_api_key="fake")).generate(
        {"mode": "write", "profile": "short", "material": "根据给定材料写两句"}
    )
    generator = LlmReplyGenerator(
        client=Client(), profile_text="", model="fake", persona_snapshot=store.get()
    )
    await generator.generate(_item())
    assert result["persona"] == generator.persona_reference
    assert result["persona"]["digest"] == snapshot["digest"]
    assert all("假设修复了启动崩溃" in text for text in seen)
    assert "直接回应对方" in seen[1]


async def test_autopilot_freezes_card_and_records_it_on_draft(tmp_path):
    from test_auto_authoring import Client, create
    from test_auto_authoring import Writer as FakeWriter

    from xhh_agent.webui.autopilot import Autopilot
    from xhh_agent.webui.editorial import read_draft

    class Probe(FakeWriter):
        async def generate(self, body):
            self.used = body["_persona_snapshot"]
            return await super().generate(body)

    store = Personas(tmp_path)
    first = store.save(card(), 0, activate=True)
    writer = Probe()
    service = Autopilot(tmp_path, writer, SimpleNamespace(client=lambda: Client()))
    job = create(service)
    store.save(card("B"), 1)
    result = await service.run(job["id"])
    assert result["state"] == "ready" and writer.used == first
    draft = read_draft(tmp_path, result["file"])
    assert draft["metadata"]["persona"]["revision"] == 1
    assert draft["metadata"]["persona"]["digest"] == first["digest"]


async def test_http_import_preview_export_and_origin_guard(tmp_path, monkeypatch):
    from xhh_agent.webui import workspace
    from xhh_agent.webui.app import create_app

    seen = []

    class FakeWriter:
        async def generate(self, data):
            seen.append(data)
            return {"text": "仅预览文本", "voice_notes": []}

    monkeypatch.setattr(workspace, "Writer", lambda *args: FakeWriter())
    client = TestClient(TestServer(create_app(tmp_path)))
    await client.start_server()
    try:
        response = await client.get("/api/personas?summary=1")
        assert (await response.json())["active"]["id"] == DEFAULT_PERSONA
        assert not (tmp_path / ".data/personas.sqlite").exists()
        response = await client.get("/api/personas?list=1")
        listing = await response.json()
        assert listing["active"]["id"] == DEFAULT_PERSONA
        assert any(item["id"] == DEFAULT_PERSONA and item["active"] for item in listing["items"])
        assert "system_prompt" not in json.dumps(listing)
        response = await client.post(
            "/api/personas",
            json={"action": "import", "card": {"system_prompt": "导入的人设", "begin_dialogs": []}},
        )
        imported = (await response.json())["snapshot"]
        assert imported["revision"] == 1
        response = await client.post(
            "/api/personas/preview",
            json={
                "card": {**imported["card"], "system_prompt": "未保存的编辑版"},
                "material": "修复启动崩溃，写两句",
            },
        )
        assert len((await response.json())["results"]) == 2
        invalid = await client.post(
            "/api/personas/preview",
            json={"card": imported["card"], "material": "试写材料", "scene": []},
        )
        assert invalid.status == 400 and len(seen) == 2
        assert seen[0]["persona_scene"] == "short"
        assert seen[0]["material"] == seen[1]["material"]
        assert seen[0]["_persona_snapshot"]["card"]["system_prompt"] == "导入的人设"
        assert seen[1]["_persona_snapshot"]["card"]["system_prompt"] == "未保存的编辑版"
        assert Personas(tmp_path).get()["card"]["id"] == DEFAULT_PERSONA
        assert not list(tmp_path.rglob("post-*.md"))
        response = await client.post(
            "/api/generate", json={"_persona_snapshot": {"card": "forged"}}
        )
        assert "_persona_snapshot" not in seen[-1]
        response = await client.post(
            "/api/personas",
            json={"action": "activate", "id": imported["card"]["id"]},
            headers={"Origin": "https://foreign.example"},
        )
        assert response.status == 403
        response = await client.get("/api/personas?export=astrbot&id=" + imported["card"]["id"])
        exported = (await response.json())["card"]
        assert set(exported) == {"persona_id", "system_prompt", "begin_dialogs"}
    finally:
        await client.close()


def test_cli_reads_same_persona(tmp_path, capsys):
    from xhh_agent.cli.main import main

    store = Personas(tmp_path)
    snapshot = store.save(card(), 0, activate=True)
    assert main(["persona", "prompt", "--root", str(tmp_path), "--scene", "tutorial"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["persona"]["digest"] == snapshot["digest"]
    assert "环境、操作和结果判据" in result["prompt"]


def test_builtin_default_and_example_stay_identical_and_read_only(tmp_path):
    from pathlib import Path

    store = Personas(tmp_path)
    snapshot = store.get()
    example = json.loads(
        (Path(__file__).parents[1] / "examples/personas/shirakawa-mio.json").read_text(
            encoding="utf-8"
        )
    )
    assert snapshot["card"] == validate(example)
    assert snapshot["card"]["id"] == DEFAULT_PERSONA
    assert snapshot["digest"] == digest(example)
    assert len(snapshot["card"]["examples"]) == 8
    assert {item["id"] for item in store.list()} == {DEFAULT_PERSONA, "legacy"}
    assert store.revisions(DEFAULT_PERSONA)[0]["id"] == DEFAULT_PERSONA
    assert not store.path.exists()


def test_builtin_edit_archives_original_and_explicit_selection_survives(tmp_path):
    store = Personas(tmp_path)
    original = store.get()
    saved = store.save({**original["card"], "system_prompt": "自定义调整"}, 0)
    assert saved["revision"] == 1
    assert store.get(DEFAULT_PERSONA, 0) == original
    assert store.rollback(DEFAULT_PERSONA, 0, 1)["card"] == original["card"]
    store.activate("legacy")
    assert Personas(tmp_path).active_id() == "legacy"
    assert Personas(tmp_path).get()["card"]["id"] == "legacy"


def test_visual_roundtrip_and_legacy_hash_compatibility(tmp_path):
    store = Personas(tmp_path)
    old = validate(card())
    assert "visual" not in old
    assert digest({**old, "visual": {}}) == digest(old)
    snapshot = store.save(
        {**card(), "visual": {"character": "白发蓝发夹", "direction": "信息卡与人物分区"}}, 0
    )
    exported = store.export("author")
    assert exported["visual"] == snapshot["card"]["visual"]
    imported = store.import_card(exported)
    assert imported["card"]["visual"] == exported["visual"]
    assert "visual" not in imported["ignored_fields"]
    assert "visual" not in store.export("author", "astrbot")
    prompt = compile_visual(snapshot, kind="diagram", purpose="解释文件流向", brief="三个步骤")
    assert "白发蓝发夹" in prompt and "角色可省略" in prompt and "三个步骤" in prompt
    assert "不是事实证据" in prompt and "敏感身体部位" in prompt
    assert "白发蓝发夹" not in compile_persona(snapshot)
    with pytest.raises(ValueError, match="快照校验"):
        compile_visual({**snapshot, "digest": "tampered"})
    for kind in ("screenshot", [], None):
        with pytest.raises(ValueError, match="配图类型"):
            compile_visual(snapshot, kind=kind)


@pytest.mark.parametrize(
    "visual", [[], {"tools": "publish"}, {"character": "x" * 2401}, {"direction": 1}]
)
def test_invalid_visual_settings_are_rejected(visual):
    with pytest.raises(ValueError):
        validate({**card(), "visual": visual})


def test_cli_visual_uses_the_saved_version(tmp_path, capsys):
    from xhh_agent.cli.main import main

    store = Personas(tmp_path)
    first = store.save({**card(), "visual": {"character": "白发蓝发夹"}}, 0, activate=True)
    store.save({**first["card"], "visual": {"character": "另一形象"}}, 1)
    assert (
        main(["persona", "visual", "--root", str(tmp_path), "--id", "author", "--revision", "1"])
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["persona"]["digest"] == first["digest"]
    assert "白发蓝发夹" in result["prompt"] and "另一形象" not in result["prompt"]
