"""面板的状态聚合 + 发帖通道测试。

面板是给人看"现在什么情况"的，所以重点测三件事：
1. 状态读得对（额度、待回评论、稿子清单）；
2. 只读动作的**白名单里没有危险命令**；
3. 发布通道该拦的必须拦住（没确认、字不够、排期不允许都发不出去）。
"""

from __future__ import annotations

import types
from datetime import datetime

from xhh_agent.automation.slots import EXIT_SKIP, SlotState, record_post
from xhh_agent.protocol.models import PostResult
from xhh_agent.webui import publishing
from xhh_agent.webui.app import SAFE_ACTIONS
from xhh_agent.webui.publishing import list_drafts, preflight
from xhh_agent.webui.state import build_state

DAY = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)

BODY = "影之刃零这把双钩的防反窗口比想象中短，弹反成功之后能接两段。" * 60
IMAGES = "\n![图一](.data/a.gif)\n![图二](https://x/2.jpg)\n![图三](https://x/3.jpg)\n"


def _root(tmp_path):
    (tmp_path / ".data").mkdir()
    (tmp_path / "notes" / "study").mkdir(parents=True)
    return tmp_path


def _cfg(root):
    """发布链路只需要 db_path（会话文件同目录）。"""
    return types.SimpleNamespace(db_path=str(root / ".data" / "xhh.db"), heybox_id="10000001")


def _post_file(root, name="post-demo.md", body=BODY):
    path = root / ".data" / name
    path.write_text("## 一段小标题\n" + body + IMAGES, encoding="utf-8")
    return path


# ── 状态聚合 ────────────────────────────────────────────────


def test_state_without_session_is_honest(tmp_path):
    root = _root(tmp_path)
    state = build_state(root, now=DAY.timestamp())
    assert state["account"]["ok"] is False
    assert "login" in state["account"]["note"]


def test_state_reports_quota_and_posts(tmp_path):
    root = _root(tmp_path)
    record_post("195437564", path=root / ".data" / "post-ledger.json", now=DAY.timestamp())
    state = build_state(root, now=DAY.replace(hour=12).timestamp())

    assert state["slot"]["today_count"] == 1
    assert state["slot"]["cap"] == 3
    assert state["slot"]["allowed"] is True
    assert state["posts"][0]["link_id"] == "195437564"
    assert state["posts"][0]["url"].endswith("/195437564")


def test_state_lists_drafts_and_notes(tmp_path):
    root = _root(tmp_path)
    _post_file(root)
    (root / "notes" / "study" / "2026-10-30-1.md").write_text("# 笔记", encoding="utf-8")

    state = build_state(root, now=DAY.timestamp())
    names = [d["name"] for d in state["drafts"]]
    assert "post-demo.md" in names
    assert state["drafts"][0]["chars"] > 0
    assert state["notes"]["count"] == 1


def test_state_queue_defaults_to_empty(tmp_path):
    root = _root(tmp_path)
    state = build_state(root, now=DAY.timestamp())
    assert state["queue"]["pending"] == 0
    assert state["queue"]["items"] == []


def test_readonly_actions_stay_readonly():
    assert set(SAFE_ACTIONS) == {"doctor", "hot", "poll"}
    for forbidden in ("publish", "draft", "reply", "dm", "delete"):
        assert forbidden not in SAFE_ACTIONS


# ── 稿子清单 ────────────────────────────────────────────────


def test_list_drafts_only_reads_post_md(tmp_path):
    root = _root(tmp_path)
    _post_file(root, "post-a.md")
    (root / ".data" / "notes.md").write_text("随便写点", encoding="utf-8")

    drafts = list_drafts(root)
    assert [d["name"] for d in drafts] == ["post-a.md"]
    assert drafts[0]["images"] == 3
    assert drafts[0]["suggested_title"]


# ── 体检 ────────────────────────────────────────────────────


def test_preflight_blocks_short_post(tmp_path):
    root = _root(tmp_path)
    _post_file(root, body="太短了。")
    result = preflight(root, "post-demo.md", "标题")
    assert result["ok"] is False
    assert any("字数" in b for b in result["blockers"])


def test_preflight_blocks_missing_title(tmp_path):
    root = _root(tmp_path)
    _post_file(root)
    result = preflight(root, "post-demo.md", "  ")
    assert any("标题" in b for b in result["blockers"])


def test_preflight_blocks_when_daily_cap_reached(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _post_file(root)
    blocked = SlotState(
        allowed=False,
        reason="今日已发 3 篇，达到上限 3",
        today_count=3,
        cap=3,
        in_window=True,
        exit_code=EXIT_SKIP,
    )
    monkeypatch.setattr(publishing, "slot_state", lambda path=None, now=None: blocked)

    result = preflight(root, "post-demo.md", "标题")
    assert any("上限" in b for b in result["blockers"])


def test_preflight_passes_good_draft(tmp_path):
    root = _root(tmp_path)
    _post_file(root)
    result = preflight(root, "post-demo.md", "一个能发的标题")
    assert result["ok"] is True, result["blockers"]
    assert result["stats"]["chars"] >= 1000
    assert result["stats"]["images"] == 3


# ── 发布 ────────────────────────────────────────────────────


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.closed = False

    async def search_topics(self, query: str):
        return [{"name": query, "topic_id": "733575"}]

    async def submit_post(self, **kwargs):
        self.calls.append(kwargs)
        return PostResult(ok=True, link_id="195000001", is_draft=False)

    async def close(self) -> None:
        self.closed = True


def _patch_client(monkeypatch, client: _FakeClient) -> None:
    monkeypatch.setattr(publishing, "ProtocolClient", lambda session, cfg: client)
    monkeypatch.setattr(
        publishing,
        "SessionStore",
        lambda path: types.SimpleNamespace(load=lambda: types.SimpleNamespace()),
    )


async def test_publish_requires_confirm(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _post_file(root)
    client = _FakeClient()
    _patch_client(monkeypatch, client)

    result = await publishing.publish(
        root,
        _cfg(root),
        file_name="post-demo.md",
        title="标题",
        topics=["影之刃零"],
        accept_warnings=True,
        confirm=False,
    )
    assert result["ok"] is False
    assert client.calls == []


async def test_publish_hits_both_topics_and_records_ledger(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _post_file(root)
    client = _FakeClient()
    _patch_client(monkeypatch, client)

    result = await publishing.publish(
        root,
        _cfg(root),
        file_name="post-demo.md",
        title="影之刃零这把双钩值得先练",
        topics=["影之刃零"],
        accept_warnings=True,
        confirm=True,
    )

    assert result["ok"] is True, result
    assert result["link_id"] == "195000001"
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["mode"] == "article"
    assert call["draft"] is False
    assert call["topic_ids"] == ("1", "733575")
    assert client.closed is True

    from xhh_agent.automation.slots import load_ledger

    assert [p["link_id"] for p in load_ledger(root / ".data" / "post-ledger.json")] == [
        "195000001"
    ]


async def test_publish_refuses_when_blockers_exist(tmp_path, monkeypatch):
    root = _root(tmp_path)
    _post_file(root, body="太短。")
    client = _FakeClient()
    _patch_client(monkeypatch, client)

    result = await publishing.publish(
        root,
        _cfg(root),
        file_name="post-demo.md",
        title="标题",
        topics=["影之刃零"],
        accept_warnings=True,
        confirm=True,
    )
    assert result["ok"] is False
    assert client.calls == []
