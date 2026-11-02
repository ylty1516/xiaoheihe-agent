"""Durable authoring, native image handoff and at-most-once publication."""

import asyncio
import copy
import io
import sqlite3
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from xhh_agent.config import load_config
from xhh_agent.webui import autopilot as module
from xhh_agent.webui.autopilot import Autopilot
from xhh_agent.webui.editorial import editor_action, read_draft
from xhh_agent.webui import publishing
from xhh_agent.automation.slots import record_post, load_ledger

MATERIAL = "该开源工具支持在本地整理文件。使用前需要确认操作系统和版本。没有提供测试结果。"


def test_same_remote_post_only_consumes_one_slot(tmp_path):
    path = tmp_path / "ledger.json"
    first = record_post("same-id", path=path, now=100)
    repeated = record_post("same-id", path=path, now=200)
    assert repeated == first and len(load_ledger(path)) == 1


class Writer:
    cfg = load_config()

    def __init__(self):
        self.calls = 0
        self.image_count = 0
        self.bad_quote = False
        self.issue_rounds = 0
        self.block = None
        self.plan_calls = 0

    def public(self):
        return {"configured": True}

    async def structured(self, instruction, context):
        if "核对正文" in instruction:
            if self.issue_rounds:
                self.issue_rounds -= 1
                return {"issues": ["请修正没有资料支持的句子"]}
            return {"issues": []}
        if "规划一篇" not in instruction:
            return {"query": "文件工具"}
        self.plan_calls += 1
        return {
            "title": "文件工具使用前先看哪些条件",
            "subject": "software",
            "genre": "tutorial",
            "topic": "盒友杂谈",
            "question": "使用前要确认什么",
            "conclusion": "先确认系统与版本",
            "new_information": "整理必要前提",
            "evidence": [
                {
                    "source_index": 0,
                    "quote": "凭空捏造一个不存在的性能数据" if self.bad_quote else MATERIAL[:22],
                }
            ],
            "images": [
                {
                    "purpose": "解释准备条件",
                    "prompt": "一张概念示意图，不是产品截图",
                    "anchor": "## 使用前",
                }
                for _ in range(self.image_count)
            ],
        }

    async def generate(self, body):
        self.calls += 1
        if self.block:
            await self.block.wait()
        return {
            "text": "## 使用前\n\n材料说明该工具用于整理文件，使用前应先确认系统与版本。未提供测试结果，不能据此推断速度。"
        }


class Client:
    async def search_topics(self, name):
        return [{"topic_id": "42", "name": name}]

    async def search_topic_posts(self, query, **kwargs):
        return [{"link_id": "123", "published_at": 10}]

    async def fetch_post_detail(self, link):
        return {"title": "原帖", "content": MATERIAL, "author_name": "来源作者"}

    async def close(self):
        pass


def service(root, writer=None):
    return Autopilot(root, writer or Writer(), SimpleNamespace(client=lambda: Client()))


def create(svc, **values):
    return svc.create(
        {
            "instruction": "写一篇软件教程",
            "material": MATERIAL,
            "subject": "software",
            "genre": "tutorial",
            **values,
        }
    )


def clear_check(*args):
    return {"blockers": [], "warnings": [], "slot": {"allowed": True}}


@pytest.mark.parametrize(
    "body",
    [
        {"publish": True},
        {"publish": "true"},
        {"subject": "bad"},
        {"instruction": []},
        {"images": "bad"},
    ],
)
def test_invalid_or_unconfirmed_task_never_starts(tmp_path, body):
    with pytest.raises(ValueError):
        create(service(tmp_path), **body)
    assert not list(tmp_path.rglob("post-*.md"))


async def test_one_request_saves_new_draft_without_modifying_current(tmp_path):
    svc = service(tmp_path)
    old = editor_action(tmp_path, {"action": "new"})
    job = await svc.run(create(svc)["id"])
    assert job["state"] == "ready"
    draft = read_draft(tmp_path, job["file"])
    assert draft["metadata"]["subject"] == "software"
    assert draft["metadata"]["profile"] == "flexible"
    assert draft["markdown"] and old["file"] != job["file"]
    assert read_draft(tmp_path, old["file"])["markdown"] == ""


async def test_fake_evidence_does_not_produce_draft(tmp_path):
    writer = Writer()
    writer.bad_quote = True
    svc = service(tmp_path, writer)
    job = await svc.run(create(svc)["id"])
    assert job["state"] == "failed" and "无法" in job["message"]
    assert writer.calls == 0


async def test_query_reads_bodies_and_keeps_attribution(tmp_path):
    svc = service(tmp_path)
    job = await svc.run(create(svc, material="", query="文件工具")["id"])
    draft = read_draft(tmp_path, job["file"])
    assert job["sources"][0]["kind"] == "community"
    assert "来源作者的材料摘录（非独立核实）" in draft["brief"]["facts"][0]["claim"]
    assert "https://www.xiaoheihe.cn/app/bbs/link/123" in draft["markdown"]


async def test_check_can_repair_once_without_unbounded_model_loop(tmp_path):
    writer = Writer()
    writer.issue_rounds = 5
    svc = service(tmp_path, writer)
    job = await svc.run(create(svc)["id"])
    assert job["state"] == "review" and writer.calls == 2
    assert job["repair_attempted"] is True
    await svc.run(job["id"])
    assert writer.calls == 2


def image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (20, 20), "green").save(stream, format="PNG")
    return stream.getvalue()


async def test_native_images_attach_then_continue_without_rewriting(tmp_path):
    writer = Writer()
    writer.image_count = 2
    svc = service(tmp_path, writer)
    job = await svc.run(create(svc)["id"])
    assert job["state"] == "awaiting_images"
    requests = svc.image_requests(job)
    assert len(requests) == 2
    for request in requests:
        svc.attach(job["id"], request["id"], image_bytes())
    restarted = service(tmp_path, writer)
    done = await restarted.run(job["id"])
    text = read_draft(tmp_path, done["file"])["markdown"]
    assert done["state"] == "ready" and writer.calls == 1
    assert text.count("![AI生成示意图]") == 2
    assert "非实测或官方画面" in text
    await restarted.run(job["id"])
    assert read_draft(tmp_path, done["file"])["markdown"].count("![AI生成示意图]") == 2
    with pytest.raises(ValueError):
        restarted.attach(job["id"], requests[0]["id"], image_bytes())


async def test_manual_edits_are_preserved_and_never_auto_published(tmp_path, monkeypatch):
    writer = Writer()
    writer.image_count = 1
    svc = service(tmp_path, writer)
    job = await svc.run(create(svc, publish=True, confirm=True)["id"])
    draft = read_draft(tmp_path, job["file"])
    editor_action(
        tmp_path,
        {
            "action": "save",
            "file": job["file"],
            "revision": draft["revision"],
            "markdown": "人工修改",
            "metadata": draft["metadata"],
        },
    )
    done = await svc.run(job["id"])
    assert done["state"] == "failed" and "手动修改" in done["message"]
    assert read_draft(tmp_path, job["file"])["markdown"] == "人工修改"


@pytest.mark.parametrize(
    "result,expected",
    [
        ({"ok": True, "link_id": "500"}, "published"),
        ({"ok": False, "title": "提交结果未确认"}, "uncertain"),
        ({"ok": False, "title": "接口没回 link_id"}, "uncertain"),
    ],
)
async def test_publication_is_not_replayed_after_ack_or_ambiguity(
    tmp_path, monkeypatch, result, expected
):
    monkeypatch.setattr(module, "preflight", clear_check)
    calls = []

    async def fake_publish(*args, **kwargs):
        calls.append(kwargs)
        return copy.deepcopy(result)

    monkeypatch.setattr(module, "publish", fake_publish)
    svc = service(tmp_path)
    job = await svc.run(create(svc, publish=True, confirm=True)["id"])
    assert job["state"] == expected and len(calls) == 1
    assert calls[0]["confirm"] and not calls[0]["accept_warnings"]
    assert calls[0]["topics"] == ["42"]
    await service(tmp_path).run(job["id"])
    assert len(calls) == 1


async def test_slot_waits_but_other_blockers_do_not_auto_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(
        module, "preflight", lambda *a: {"blockers": ["现在不能发：不在窗口"], "warnings": []}
    )
    svc = service(tmp_path)
    job = await svc.run(create(svc, publish=True, confirm=True)["id"])
    assert job["state"] == "waiting_slot"
    monkeypatch.setattr(module, "preflight", lambda *a: {"blockers": [], "warnings": ["来源不足"]})
    job = await svc.run(job["id"])
    assert job["state"] == "review"


async def test_restart_never_replays_publishing_stage(tmp_path):
    svc = service(tmp_path)
    job = create(svc, publish=True, confirm=True)
    svc.update(job, "publishing", "正在提交")
    await svc.run(job["id"])
    assert svc.read(job["id"])["state"] == "publishing"
    watcher = asyncio.create_task(svc.watch())
    await asyncio.sleep(0.02)
    watcher.cancel()
    await asyncio.gather(watcher, return_exceptions=True)
    assert svc.read(job["id"])["state"] == "uncertain"


async def test_concurrent_server_and_cli_lease_cannot_run_same_job(tmp_path):
    writer = Writer()
    writer.block = asyncio.Event()
    svc = service(tmp_path, writer)
    job = create(svc)
    svc.launch(job["id"])
    await asyncio.sleep(0.02)
    with pytest.raises(ValueError):
        svc.launch(job["id"])
    other = service(tmp_path, writer)
    assert (await other.run(job["id"]))["state"] == "writing"
    writer.block.set()
    await asyncio.gather(*list(svc.tasks.values()))
    assert writer.calls == 1


async def test_publication_guard_refuses_second_submit(tmp_path):
    folder = tmp_path / ".data"
    folder.mkdir()
    connection = sqlite3.connect(folder / "publication.sqlite", timeout=0)
    connection.execute("BEGIN EXCLUSIVE")
    try:
        result = await publishing.publish(
            tmp_path,
            load_config(),
            file_name="post-test.md",
            title="标题",
            topics=[],
            accept_warnings=False,
            confirm=True,
        )
        assert result["title"] == "另一个发布正在处理"
    finally:
        connection.close()


async def test_http_job_survives_response_and_get_is_read_only(tmp_path, monkeypatch):
    from xhh_agent.webui.app import create_app
    import xhh_agent.webui.workspace as workspace

    fake_writer = Writer()
    fake_writer.block = asyncio.Event()
    monkeypatch.setattr(workspace, "Writer", lambda *a: fake_writer)
    client = TestClient(TestServer(create_app(tmp_path, load_config())))
    await client.start_server()
    try:
        response = await client.post(
            "/api/autopilot",
            json={
                "instruction": "软件教程",
                "material": MATERIAL,
                "subject": "software",
                "genre": "tutorial",
            },
        )
        job = (await response.json())["job"]
        assert response.status == 200
        await asyncio.sleep(0.02)
        denied = await client.post(
            "/api/autopilot", json={}, headers={"Origin": "https://foreign.test"}
        )
        assert denied.status == 403
        read = await client.get("/api/autopilot?id=" + job["id"])
        assert (await read.json())["job"]["state"] == "writing"
        duplicate = await client.post(
            "/api/autopilot", json={"action": "resume", "id": job["id"], "max_model_calls": 30}
        )
        assert duplicate.status == 400
        assert "正在运行" in (await duplicate.json())["error"]
        read = await client.get("/api/autopilot?id=" + job["id"])
        assert (await read.json())["job"]["max_model_calls"] == job["max_model_calls"]
        fake_writer.block.set()
        for _ in range(25):
            read = await client.get("/api/autopilot?id=" + job["id"])
            if (await read.json())["job"]["state"] == "ready":
                break
            await asyncio.sleep(0.01)
        assert fake_writer.calls == 1
    finally:
        await client.close()
