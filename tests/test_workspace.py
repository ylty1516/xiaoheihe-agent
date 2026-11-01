"""Workflow regressions. All account/model operations use fakes, never live traffic."""

from __future__ import annotations

import asyncio
import io
import json
import time
from dataclasses import replace
from types import SimpleNamespace

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from xhh_agent.config import load_config
from xhh_agent.protocol.models import QrPollResult, QrTicket, SendResult
from xhh_agent.protocol.session import Session
from xhh_agent.store.db import Store
from xhh_agent.webui.editorial import archived_drafts, editor_action, read_draft
from xhh_agent.webui.media import (
    MAX_IMAGE_BYTES,
    media_path,
    publication_markdown,
    render_preview,
    save_image,
)
from xhh_agent.webui.operations import Operations
from xhh_agent.webui.writer import Writer


@pytest.fixture
def cfg(tmp_path):
    return replace(load_config(), db_path=str(tmp_path / ".data/xhh.db"), llm_api_key="")


def new(root):
    return editor_action(root, {"action": "new"})


def save(root, data, text="正文", title="标题"):
    return editor_action(
        root,
        {
            "action": "save",
            "file": data["file"],
            "revision": data["revision"],
            "brief": None,
            "markdown": text,
            "metadata": {"title": title, "topic": "影之刃零", "notes": "保留资料"},
        },
    )


def test_plain_draft_only_needs_title_and_body_and_keeps_notes(tmp_path):
    draft = new(tmp_path)
    save(tmp_path, draft)
    result = read_draft(tmp_path, draft["file"])
    assert result["title"] == "标题"
    assert result["metadata"]["notes"] == "保留资料"
    assert not result["has_brief"]


def test_revision_protects_metadata_too(tmp_path):
    draft = new(tmp_path)
    save(tmp_path, draft)
    with pytest.raises(ValueError, match="其他窗口"):
        save(tmp_path, draft, "过时正文")
    assert read_draft(tmp_path, draft["file"])["markdown"] == "正文"


def test_duplicate_has_independent_content_and_title(tmp_path):
    draft = new(tmp_path)
    save(tmp_path, draft)
    original = read_draft(tmp_path, draft["file"])
    copied = editor_action(
        tmp_path,
        {"action": "duplicate", "file": original["file"], "revision": original["revision"]},
    )
    save(tmp_path, copied, "副本修改", "另一篇")
    assert copied["title"] == "标题（副本）"
    assert read_draft(tmp_path, draft["file"])["markdown"] == "正文"


def test_archive_and_restore_are_reversible_without_touching_other_files(tmp_path):
    draft = new(tmp_path)
    save(tmp_path, draft, "原始内容\n\n![图](.data/media/test.png)")
    current = read_draft(tmp_path, draft["file"])
    other = tmp_path / ".data/other.txt"
    other.write_text("保留", encoding="utf-8")
    editor_action(
        tmp_path, {"action": "archive", "file": current["file"], "revision": current["revision"]}
    )
    records = archived_drafts(tmp_path)
    assert len(records) == 1
    assert not (tmp_path / ".data" / draft["file"]).exists()
    restored = editor_action(
        tmp_path, {"action": "restore", "archive_id": records[0]["archive_id"]}
    )
    assert restored["markdown"] == current["markdown"]
    assert restored["title"] == "标题"
    assert other.read_text(encoding="utf-8") == "保留"
    assert not archived_drafts(tmp_path)


def test_restore_never_overwrites_recreated_filename(tmp_path):
    draft = new(tmp_path)
    save(tmp_path, draft, "归档内容")
    current = read_draft(tmp_path, draft["file"])
    editor_action(
        tmp_path, {"action": "archive", "file": current["file"], "revision": current["revision"]}
    )
    (tmp_path / ".data" / current["file"]).write_text("新建的同名内容", encoding="utf-8")
    restored = editor_action(
        tmp_path, {"action": "restore", "archive_id": archived_drafts(tmp_path)[0]["archive_id"]}
    )
    assert restored["file"] != current["file"]
    assert restored["markdown"] == "归档内容"


@pytest.mark.parametrize("identifier", ["../outside", "abc", "z" * 32])
def test_restore_refuses_untrusted_ids(tmp_path, identifier):
    with pytest.raises(ValueError):
        editor_action(tmp_path, {"action": "restore", "archive_id": identifier})


def test_preview_strips_executable_markup_and_remote_image_requests():
    result = render_preview(
        '## 机制\n\n<script>alert(1)</script>\n\n<img src="https://evil/image" onerror="alert(1)">\n\n[坏链接](javascript:alert(1))\n\n**加粗**'
    )
    assert "<h2>机制</h2>" in result and "<strong>加粗</strong>" in result
    assert "<script" not in result and "onerror" not in result and 'src="https:' not in result
    assert 'href="javascript:' not in result


def test_preview_only_embeds_valid_local_media():
    name = "a" * 32 + ".png"
    result = render_preview(f"![图](.data/media/{name})\n\n![私有](../../session.json)")
    assert f'src="/api/media/{name}"' in result
    assert "session.json" not in result


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (3, 4)).save(output, format="PNG")
    return output.getvalue()


def test_uploaded_image_is_validated_and_addressable(tmp_path):
    data = save_image(tmp_path, image_bytes())
    path = media_path(tmp_path, data["url"].split("/")[-1])
    assert path.read_bytes() == image_bytes()
    with pytest.raises(ValueError):
        save_image(tmp_path, b"<script>not an image</script>")
    with pytest.raises(ValueError):
        media_path(tmp_path, "../session.json")
    with pytest.raises(ValueError):
        save_image(tmp_path, b"x" * (MAX_IMAGE_BYTES + 1))


async def test_publication_attachments_work_outside_project_directory(
    tmp_path, monkeypatch, fake_upload_client
):
    from xhh_agent.content import markdown_to_heybox_html

    project = tmp_path / "project with spaces"
    data = save_image(project, image_bytes())
    monkeypatch.chdir(tmp_path)
    prepared = publication_markdown(project, data["markdown"])
    html, images = await fake_upload_client._prepare_images_in_html(
        markdown_to_heybox_html(prepared)
    )
    assert images and images[0]["url"].startswith("https://imgheybox.max-c.com/")
    assert "project with spaces" not in html


def test_writer_settings_never_return_key_and_only_persist_when_requested(tmp_path, cfg):
    writer = Writer(tmp_path, cfg)
    writer.settings_path = tmp_path / "private-ai.json"
    public = writer.configure(
        {"base_url": "https://example.com/v1", "model": "test", "api_key": "fake-secret"}
    )
    assert "fake-secret" not in json.dumps(public)
    assert public["configured"] and not writer.settings_path.exists()
    writer.configure({"base_url": "https://example.com/v1", "model": "test", "persist": True})
    assert json.loads(writer.settings_path.read_text(encoding="utf-8"))["api_key"] == "fake-secret"
    with pytest.raises(ValueError):
        writer.configure({"base_url": "https://secret@example.com", "model": "test"})


async def test_ai_draft_is_reviewable_and_never_edits_saved_file(tmp_path, cfg, monkeypatch):
    import xhh_agent.webui.writer as module

    writer = Writer(tmp_path, replace(cfg, llm_api_key="fake"))
    seen = {}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def complete(self, **kwargs):
            seen.update(kwargs)
            return "待审阅的文章"

    monkeypatch.setattr(module, "OpenAICompatClient", Client)
    draft = new(tmp_path)
    result = await writer.generate(
        {"mode": "write", "material": "测试材料，尚需核实", "markdown": "原稿"}
    )
    assert result["text"] == "待审阅的文章"
    assert "没有浏览能力" in seen["prompt"]
    assert seen["max_tokens"] > 300
    assert read_draft(tmp_path, draft["file"])["markdown"] == ""


async def test_ai_rejects_missing_key_and_empty_rewrite_selection(tmp_path, cfg):
    writer = Writer(tmp_path, cfg)
    with pytest.raises(ValueError, match="配置"):
        await writer.generate({"mode": "write", "material": "资料"})
    writer.cfg = replace(cfg, llm_api_key="fake")
    with pytest.raises(ValueError, match="选中"):
        await writer.generate({"mode": "rewrite", "material": "更简短", "selected": ""})


async def test_ai_serializes_expensive_requests(tmp_path, cfg, monkeypatch):
    import xhh_agent.webui.writer as module

    writer = Writer(tmp_path, replace(cfg, llm_api_key="fake"))
    started, finish = asyncio.Event(), asyncio.Event()

    class Client:
        def __init__(self, **kwargs):
            pass

        async def complete(self, **kwargs):
            started.set()
            await finish.wait()
            return "结果"

    monkeypatch.setattr(module, "OpenAICompatClient", Client)
    task = asyncio.create_task(writer.generate({"mode": "outline", "material": "资料"}))
    await started.wait()
    with pytest.raises(ValueError, match="正在运行"):
        await writer.generate({"mode": "outline", "material": "重复请求"})
    finish.set()
    await task


def operations(root, cfg):
    return Operations(root, cfg, SimpleNamespace(cfg=replace(cfg, llm_api_key="fake")))


def enqueue(root, cfg, *, hard=False, state="pending", text="这个触发条件应该如何核对？"):
    with Store(cfg.db_path) as store:
        store.claim("comment", "message1")
        identity = store.enqueue(
            "comment",
            "message1",
            "玩家",
            json.dumps(
                {
                    "text": text,
                    "timestamp": int(time.time()),
                    "link_id": "post1",
                    "reply_id": "reply1",
                    "must_human": hard,
                }
            ),
            "",
        )
        store.set_queue_state(identity, state)
    return identity


async def test_comment_needs_confirmation_before_any_account_request(tmp_path, cfg, monkeypatch):
    ops = operations(tmp_path, cfg)
    identity = enqueue(tmp_path, cfg)
    monkeypatch.setattr(ops, "client", lambda **k: pytest.fail("未确认前不应请求账号"))
    with pytest.raises(ValueError, match="确认"):
        await ops.action({"action": "send_reply", "id": identity, "text": "核对目标状态"})


@pytest.mark.parametrize("hard,state", [(True, "pending"), (False, "sent"), (False, "uncertain")])
async def test_human_only_or_processed_comments_cannot_be_sent(
    tmp_path, cfg, monkeypatch, hard, state
):
    ops = operations(tmp_path, cfg)
    identity = enqueue(tmp_path, cfg, hard=hard, state=state)
    monkeypatch.setattr(ops, "client", lambda **k: pytest.fail("不应发出请求"))
    with pytest.raises(ValueError):
        await ops.action(
            {"action": "send_reply", "id": identity, "text": "测试回复", "confirm": True}
        )


@pytest.mark.parametrize("own,ack", [(False, True), (True, False), (True, True)])
async def test_reply_checks_ownership_and_receipt_without_duplicate_send(
    tmp_path, cfg, monkeypatch, own, ack
):
    ops = operations(tmp_path, cfg)
    identity = enqueue(tmp_path, cfg)
    sent = []

    class Client:
        async def is_own_post(self, link_id):
            return own

        async def reply_comment(self, **kwargs):
            sent.append(kwargs)
            return SendResult(ok=ack, ack_id="ack1" if ack else "")

        async def close(self):
            pass

    monkeypatch.setattr(ops, "client", lambda **k: Client())
    args = {"action": "send_reply", "id": identity, "text": "核对目标状态", "confirm": True}
    if not own or not ack:
        with pytest.raises(ValueError):
            await ops.action(args)
    else:
        assert (await ops.action(args))["ok"]
    if own:
        with pytest.raises(ValueError):
            await ops.action(args)
    assert len(sent) == int(own)
    with Store(cfg.db_path) as store:
        assert store.get_queue(identity)["state"] == (
            "pending" if not own else "sent" if ack else "uncertain"
        )


async def test_reply_respects_existing_per_post_limit(tmp_path, cfg, monkeypatch):
    ops = operations(tmp_path, cfg)
    identity = enqueue(tmp_path, cfg)
    with Store(cfg.db_path) as store:
        for index in range(cfg.max_replies_per_post):
            store.log_sent("comment", str(index), "历史回复", link_id="post1")

    class Client:
        async def is_own_post(self, link_id):
            return True

        async def reply_comment(self, **kwargs):
            pytest.fail("限额已满，不得发送")

        async def close(self):
            pass

    monkeypatch.setattr(ops, "client", lambda **k: Client())
    with pytest.raises(ValueError, match="上限"):
        await ops.action({"action": "send_reply", "id": identity, "text": "测试", "confirm": True})


def test_empty_comment_view_does_not_create_database(tmp_path, cfg):
    assert operations(tmp_path, cfg).queue() == []
    assert not (tmp_path / ".data/xhh.db").exists()


async def test_qr_login_keeps_poll_token_server_side_and_saves_session(tmp_path, cfg, monkeypatch):
    ops = operations(tmp_path, cfg)

    class Client:
        async def request_qr_login(self):
            return QrTicket("private-poll-ticket", "https://example.com/qr-content", 60)

        async def poll_qr_login(self, token):
            assert token == "private-poll-ticket"
            return QrPollResult("ok", Session("fake-cookie", "owner"))

        async def close(self):
            pass

    monkeypatch.setattr(ops, "client", lambda **k: Client())
    start = await ops.action({"action": "login_start"})
    assert start["image"].startswith("data:image/png;base64,")
    assert "private-poll-ticket" not in json.dumps(start)
    status = await ops.action({"action": "login_poll", "handle": start["handle"]})
    assert status == {"ok": True, "status": "ok"}
    assert "cookie" not in json.dumps(status)
    assert ops.session_path.exists()
    assert (await ops.action({"action": "login_poll", "handle": start["handle"]}))[
        "status"
    ] == "expired"


async def test_workspace_http_preview_export_upload_and_origin_guard(tmp_path, cfg):
    from xhh_agent.webui.app import create_app

    async with TestClient(TestServer(create_app(tmp_path, cfg))) as client:
        created = await (await client.post("/api/editorial", json={"action": "new"})).json()
        await client.post(
            "/api/editorial",
            json={
                "action": "save",
                "file": created["file"],
                "revision": created["revision"],
                "brief": None,
                "metadata": {"title": "导出标题"},
                "markdown": "**正文**",
            },
        )
        library = await (await client.get("/api/library")).json()
        assert library["drafts"][0]["suggested_title"] == "导出标题"
        preview = await (await client.post("/api/preview", json={"markdown": "**正文**"})).json()
        assert "<strong>正文</strong>" in preview["html"]
        exported = await client.get("/api/export?file=" + created["file"])
        assert "# 导出标题" in await exported.text()
        data = aiohttp.FormData()
        data.add_field("image", image_bytes(), filename="image.png", content_type="image/png")
        upload = await (await client.post("/api/images", data=data)).json()
        assert upload["ok"]
        image = await client.get(upload["url"])
        assert image.status == 200 and image.headers["Content-Type"].startswith("image/")
        denied = await client.post(
            "/api/model", json={"model": "x"}, headers={"Origin": "https://other.example"}
        )
        assert denied.status == 403
        malformed = await client.post("/api/preview", json=[])
        assert malformed.status == 400


async def test_note_analysis_saves_verified_source_card_and_preserves_raw_note(
    tmp_path, cfg, monkeypatch
):
    from xhh_agent.webui.app import create_app

    folder = tmp_path / "notes/study"
    folder.mkdir(parents=True)
    note = folder / "2026-11-01-123.md"
    original = "# 笔记\n\n## 正文\n\n```text\n这是待分析的原文。\n```\n\n## 待分析\n"
    note.write_text(original, encoding="utf-8")

    async def fake_generate(self, body):
        assert body["mode"] == "study" and body["markdown"] == "这是待分析的原文。"
        return {
            "text": json.dumps(
                {
                    "article_type": "mechanism",
                    "reader_question": "机制如何生效？",
                    "argument_order": ["误解", "规则", "案例"],
                    "evidence_usage": ["引用原文中的规则"],
                    "applicable_when": "有规则资料",
                    "avoid": [],
                    "source_url": "https://untrusted.example",
                }
            )
        }

    monkeypatch.setattr(Writer, "generate", fake_generate)
    async with TestClient(TestServer(create_app(tmp_path, cfg))) as client:
        result = await (await client.post("/api/note/analyze", json={"name": note.name})).json()
        assert result["card"]["source_url"].endswith("/123")
        assert (folder / "cards/123.json").exists()
        assert note.read_text(encoding="utf-8") == original
        denied = await client.get("/api/note?name=../../session.json")
        assert denied.status == 400


async def test_model_error_does_not_echo_credentials(tmp_path, cfg, monkeypatch):
    import xhh_agent.webui.writer as module
    from xhh_agent.automation.generator import GenerationError

    writer = Writer(tmp_path, replace(cfg, llm_api_key="fake-secret"))

    class Client:
        def __init__(self, **kwargs):
            pass

        async def complete(self, **kwargs):
            raise GenerationError("provider echoed fake-secret")

    monkeypatch.setattr(module, "OpenAICompatClient", Client)
    with pytest.raises(ValueError) as error:
        await writer.generate({"mode": "write", "material": "真实材料"})
    assert "fake-secret" not in str(error.value)


def test_queue_transition_can_only_be_claimed_once(tmp_path, cfg):
    identity = enqueue(tmp_path, cfg)
    with Store(cfg.db_path) as first, Store(cfg.db_path) as second:
        assert first.transition_queue(identity, ("pending", "approved"), "sending")
        assert not second.transition_queue(identity, ("pending", "approved"), "sending")
