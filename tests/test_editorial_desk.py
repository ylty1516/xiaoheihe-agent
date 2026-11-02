import asyncio
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from xhh_agent.content.desk import Desk
from xhh_agent.webui.experiments import execute
from xhh_agent.webui.research import fetch_sources
from xhh_agent.webui.autopilot import Autopilot


def test_sources_deduplicate_syndication_and_keep_provenance(tmp_path):
    desk = Desk(tmp_path)
    one = desk.put(
        {
            "event": "版本A",
            "kind": "source",
            "text": "具体的发布内容",
            "url": "https://a.example",
            "provenance": "github_public_api",
        }
    )
    other = desk.put(
        {"event": "版本A", "kind": "source", "text": "具体的 发布内容", "url": "https://b.example"}
    )
    assert one["id"] == other["id"] and other["duplicate"]
    assert len(desk.list()) == 1
    assert desk.get(one["id"])["provenance"] == "github_public_api"
    desk.put({"event": "版本B", "kind": "note", "text": "另外一个专题"})
    assert len(desk.context("版本A")) == 1


def test_old_article_has_followup_when_new_material_arrives(tmp_path):
    desk = Desk(tmp_path)
    desk.put({"event": "A", "kind": "article", "text": "之前的文章"})
    desk.put({"event": "A", "kind": "source", "text": "新版本出现了新的资料"})
    assert desk.overview()["followups"][0]["event"] == "A"


@pytest.mark.parametrize(
    "provider,key",
    [("url", "http://localhost"), ("github", "a/b/../../private"), ("steam", "1&key=secret")],
)
async def test_arbitrary_endpoints_rejected(provider, key):
    with pytest.raises(ValueError):
        await fetch_sources(provider, key)


async def test_runtime_recipe_is_actually_executed(tmp_path):
    record = await execute(tmp_path, "runtime")
    assert record["exit_code"] == 0 and "Python" in record["text"]
    assert len(record["log_sha256"]) == 64
    assert record["provenance"] == "executed_on_host"
    with pytest.raises(ValueError):
        await execute(tmp_path, "python -c arbitrary_code")


async def test_desk_http_preserves_supplied_material_and_origin(tmp_path):
    from xhh_agent.webui.app import create_app

    client = TestClient(TestServer(create_app(tmp_path)))
    await client.start_server()
    try:
        response = await client.post(
            "/api/desk",
            json={
                "event": "自己的游戏记录",
                "kind": "experiment",
                "text": "尚未实测，只是准备步骤",
                "provenance": "executed_on_host",
            },
        )
        assert response.status == 200
        card = (await response.json())["card"]
        assert card["provenance"] == "user_provided"
        response = await client.get("/api/desk")
        assert (await response.json())["items"][0]["id"] == card["id"]
        response = await client.post(
            "/api/desk",
            json={"kind": "note", "text": "abc"},
            headers={"Origin": "https://foreign.example"},
        )
        assert response.status == 403
    finally:
        await client.close()


async def test_pause_and_cancel_are_durable_and_do_not_watch_resume(tmp_path):
    from test_auto_authoring import Writer, Client, create

    writer = Writer()
    writer.block = asyncio.Event()
    service = Autopilot(tmp_path, writer, SimpleNamespace(client=lambda: Client()))
    job = create(service)
    service.launch(job["id"])
    await asyncio.sleep(0.02)
    paused = await service.control(job["id"], "pause")
    assert paused["state"] == "user_paused"
    watcher = asyncio.create_task(service.watch())
    await asyncio.sleep(0.02)
    watcher.cancel()
    await asyncio.gather(watcher, return_exceptions=True)
    assert service.read(job["id"])["state"] == "user_paused"
    cancelled = await service.control(job["id"], "cancel")
    assert cancelled["state"] == "cancelled"


async def test_budget_bounds_model_calls(tmp_path):
    from test_auto_authoring import Writer, Client, create

    writer = Writer()
    service = Autopilot(tmp_path, writer, SimpleNamespace(client=lambda: Client()))
    job = create(service, max_model_calls=1)
    result = await service.run(job["id"])
    assert result["state"] == "failed" and "预算" in result["message"]
    assert result["model_calls"] == 1 and writer.calls == 0


async def test_material_to_draft_and_semantic_overlap(tmp_path):
    from test_auto_authoring import Writer, Client, MATERIAL

    class MemoryWriter(Writer):
        async def structured(self, instruction, context):
            if "比较本次规划" in instruction:
                return {"overlap": True, "reason": "问题和结论与旧文一致，未增加新证据"}
            return await super().structured(instruction, context)

    writer = MemoryWriter()
    service = Autopilot(tmp_path, writer, SimpleNamespace(client=lambda: Client()))
    card = service.desk.put({"kind": "note", "event": "软件专题", "text": MATERIAL})
    first = service.create(
        {"material_id": card["id"], "subject": "software", "genre": "tutorial", "images": "none"}
    )
    result = await service.run(first["id"])
    assert result["state"] == "ready"
    second = service.create(
        {"material_id": card["id"], "subject": "software", "genre": "tutorial", "images": "none"}
    )
    result = await service.run(second["id"])
    assert result["state"] == "skipped" and "增量不足" in result["message"]
    assert writer.calls == 1
    again = await service.run(second["id"])
    assert again["state"] == "skipped" and writer.calls == 1


async def test_indexed_citations_use_original_passage(tmp_path):
    from test_auto_authoring import Writer, Client, create

    class IndexedWriter(Writer):
        async def structured(self, instruction, context):
            value = await super().structured(instruction, context)
            if "规划一篇" in instruction:
                value["evidence"] = [{"source_index": 0, "paragraph_index": 0}]
            return value

    service = Autopilot(tmp_path, IndexedWriter(), SimpleNamespace(client=lambda: Client()))
    result = await service.run(create(service)["id"])
    assert result["state"] == "ready"
    assert result["plan"]["evidence"][0]["quote"] == result["sources"][0]["text"]


async def test_source_polling_does_not_starve_fifth_subscription(tmp_path, monkeypatch):
    from test_auto_authoring import Writer
    import xhh_agent.webui.research as research

    calls = []

    async def fetch(provider, key):
        calls.append(key)
        return []

    monkeypatch.setattr(research, "fetch_sources", fetch)
    service = Autopilot(tmp_path, Writer(), SimpleNamespace())
    for i in range(5):
        service.desk.put(
            {
                "kind": "source",
                "event": "A",
                "text": f"source {i}",
                "provider": "github",
                "key": f"a/repo{i}",
            }
        )
    await service.refresh_dossiers()
    assert len(calls) == 4
    await service.refresh_dossiers()
    assert len(calls) == 5 and len(set(calls)) == 5


async def test_wall_clock_budget_does_not_restart_automatically(tmp_path):
    from test_auto_authoring import Writer, Client, create

    writer = Writer()
    writer.block = asyncio.Event()
    service = Autopilot(tmp_path, writer, SimpleNamespace(client=lambda: Client()))
    job = create(service, max_seconds=1)
    result = await service.run(job["id"])
    assert result["state"] == "budget_exhausted"
    assert service.read(job["id"])["elapsed_seconds"] >= 1
