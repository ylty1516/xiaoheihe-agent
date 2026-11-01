"""Flexible authoring must not widen account permissions or publication gates."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from xhh_agent.cli import cmd_post
from xhh_agent.config import load_config
from xhh_agent.content.editorial import load_history, record_publication, write_json
from xhh_agent.content.stats import check_post, get_profile, load_profile
from xhh_agent.protocol.models import PostResult
from xhh_agent.webui import publishing
from xhh_agent.webui.editorial import editor_action, read_draft
from xhh_agent.webui.writer import Writer


@pytest.mark.parametrize("profile", ["short", "flexible"])
def test_no_image_short_text_can_pass_without_legacy_bypass(profile):
    assert check_post("这是用户要求的简短说明，不需要为了凑篇幅再展开。", profile=profile)[0] == []
    problems, _ = check_post("简短说明")
    assert any("1000" in p for p in problems) and any("配图" in p for p in problems)


@pytest.mark.parametrize("profile", ["article", "short", "flexible"])
def test_empty_content_is_never_publishable(profile):
    assert check_post(" \n\t", profile=profile)[0]


def test_image_only_post_is_allowed_in_flexible_profile():
    assert not check_post("![说明](https://example.com/verified.png)", profile="flexible")[0]


def test_style_preferences_are_advisory_for_flexible_content():
    problems, notes = check_post("说明。" + "[cube_鹅]" * 8 + "喵~" * 6, profile="flexible")
    assert not problems and any("表情" in x for x in notes) and any("喵~" in x for x in notes)


def test_cli_and_web_read_saved_choice_and_explicit_override(tmp_path):
    file = tmp_path / "post-test.md"
    file.write_text("简短说明", encoding="utf-8")
    write_json(file.with_suffix(".meta.json"), {"profile": "short"})
    assert load_profile(file).id == "short"
    assert load_profile(file, "article").id == "article"
    write_json(file.with_suffix(".meta.json"), {"profile": "unknown"})
    with pytest.raises(ValueError):
        load_profile(file)
    assert load_profile(file, "flexible").id == "flexible"


def test_editor_persists_profile_and_rejects_invalid_choice_before_write(tmp_path):
    draft = editor_action(tmp_path, {"action": "new"})
    saved = editor_action(
        tmp_path,
        {
            "action": "save",
            "file": draft["file"],
            "revision": draft["revision"],
            "markdown": "用户的短帖",
            "metadata": {"title": "标题", "profile": "short"},
        },
    )
    assert read_draft(tmp_path, draft["file"])["metadata"]["profile"] == "short"
    legacy_save = editor_action(tmp_path, {
        "action": "save", "file": draft["file"], "revision": saved["revision"],
        "markdown": "用户的短帖", "metadata": {"title": "只更新标题"},
    })
    assert read_draft(tmp_path, draft["file"])["metadata"]["profile"] == "short"
    with pytest.raises(ValueError):
        editor_action(
            tmp_path,
            {
                "action": "save",
                "file": draft["file"],
                "revision": legacy_save["revision"],
                "markdown": "不应写入",
                "metadata": {"profile": []},
            },
        )
    assert read_draft(tmp_path, draft["file"])["markdown"] == "用户的短帖"


def allow_slot(monkeypatch, allowed=True):
    monkeypatch.setattr(
        publishing,
        "slot_state",
        lambda **k: SimpleNamespace(
            allowed=allowed,
            reason="ok" if allowed else "达到上限",
            today_count=0,
            cap=3,
            next_at="",
        ),
    )


def short_draft(tmp_path, text="一篇简短说明。"):
    draft = editor_action(tmp_path, {"action": "new"})
    editor_action(
        tmp_path,
        {
            "action": "save",
            "file": draft["file"],
            "revision": draft["revision"],
            "markdown": text,
            "metadata": {"title": "标题", "profile": "short"},
        },
    )
    return draft["file"]


def test_web_short_profile_keeps_title_slot_and_duplicate_checks(tmp_path, monkeypatch):
    allow_slot(monkeypatch)
    text = "这段有具体说明，用来验证重复正文不因规格改变而放行。" * 15
    file = short_draft(tmp_path, text)
    result = publishing.preflight(tmp_path, file, "标题")
    assert result["ok"] and result["profile"]["id"] == "short"
    assert not any("缺少选题卡" in x for x in result["warnings"])
    assert not publishing.preflight(tmp_path, file, "")["ok"]
    allow_slot(monkeypatch, False)
    assert any("上限" in x for x in publishing.preflight(tmp_path, file, "标题")["blockers"])
    allow_slot(monkeypatch)
    record_publication(tmp_path, link_id="1", title="已发", markdown=text)
    assert any("相同" in x for x in publishing.preflight(tmp_path, file, "标题")["blockers"])


@pytest.mark.parametrize("draft,profile", [(True, "article"), (False, "short")])
async def test_cli_saves_incomplete_draft_and_supports_explicit_short_publish(
    tmp_path, monkeypatch, draft, profile
):
    calls = []

    class Client:
        async def submit_post(self, **kwargs):
            calls.append(kwargs)
            return PostResult(ok=True, link_id="test-1", is_draft=draft)

        async def close(self):
            pass

    monkeypatch.setattr(cmd_post, "ProtocolClient", lambda *a: Client())
    monkeypatch.setattr(cmd_post, "SessionStore", lambda *a: SimpleNamespace(load=lambda: object()))
    monkeypatch.setattr(cmd_post, "_editorial_root", lambda p: tmp_path)
    monkeypatch.setattr(cmd_post, "markdown_to_heybox_html", lambda text: "<p>短说明</p>")
    file = tmp_path / "post-test.md"
    file.write_text("只写一段。", encoding="utf-8")
    args = SimpleNamespace(md=str(file), title="标题", yes=True, profile=profile)
    assert await cmd_post._run(load_config(), args, draft=draft) == 0
    assert calls[0]["draft"] is draft
    assert bool(load_history(tmp_path)) is (not draft)
    if not draft:
        calls.clear()
        args.yes = False
        assert await cmd_post._run(load_config(), args, draft=False) == cmd_post.EXIT_USAGE
        assert not calls


@pytest.mark.parametrize("mode,profile", [("write", "short"), ("rewrite", "article")])
async def test_ai_respects_short_requests_and_local_rewrites_without_long_article_rules(
    tmp_path, monkeypatch, mode, profile
):
    import xhh_agent.webui.writer as module

    captured = {}

    class Client:
        def __init__(self, **kwargs):
            pass

        async def complete(self, **kwargs):
            captured.update(kwargs)
            return "按要求处理后的短句。"

    monkeypatch.setattr(module, "OpenAICompatClient", Client)
    result = await Writer(tmp_path, replace(load_config(), llm_api_key="fake")).generate(
        {
            "mode": mode,
            "profile": profile,
            "material": "80字以内，不配图，只处理这段。",
            "selected": "需要处理的原句。",
        }
    )
    assert result["text"] == "按要求处理后的短句。"
    assert "80字以内" in captured["prompt"] and "1500-2500" not in captured["prompt"]
    if mode == "rewrite":
        assert "社区吐槽开场" not in captured["prompt"]
    assert not list((tmp_path / ".data").glob("*.md"))


@pytest.mark.parametrize("value", [None, {}, [], "unknown"])
def test_invalid_profile_is_an_error_not_silent_relaxation(value):
    with pytest.raises(ValueError):
        get_profile(value)
