"""Web 面板的状态聚合测试。

面板是给人看"现在什么情况"的，所以重点测两件事：
1. 状态读得对（额度、待回评论、稿子清单）；
2. **动作白名单里没有危险命令** —— 面板绝不能提供"发一条帖子"这种按钮。
"""

from __future__ import annotations

from datetime import datetime

from xhh_agent.automation.slots import record_post
from xhh_agent.webui.app import SAFE_ACTIONS
from xhh_agent.webui.state import build_state

DAY = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)


def _root(tmp_path) -> object:
    (tmp_path / ".data").mkdir()
    (tmp_path / "notes" / "study").mkdir(parents=True)
    return tmp_path


def test_state_without_session_is_honest(tmp_path):
    root = _root(tmp_path)
    state = build_state(root, now=DAY.timestamp())
    assert state["account"]["ok"] is False
    assert "login" in state["account"]["note"]


def test_state_reports_quota_and_posts(tmp_path):
    root = _root(tmp_path)
    record_post("195437564", path=root / ".data" / "post-ledger.json", now=DAY.timestamp())
    state = build_state(root, now=(DAY.replace(hour=12)).timestamp())

    assert state["slot"]["today_count"] == 1
    assert state["slot"]["cap"] == 3
    assert state["slot"]["allowed"] is True
    assert state["posts"][0]["link_id"] == "195437564"
    assert state["posts"][0]["url"].endswith("/195437564")


def test_state_lists_drafts_and_notes(tmp_path):
    root = _root(tmp_path)
    (root / ".data" / "post-demo.md").write_text("正文" * 60, encoding="utf-8")
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


def test_panel_never_exposes_publishing_actions():
    assert set(SAFE_ACTIONS) == {"doctor", "hot", "poll"}
    for forbidden in ("publish", "draft", "reply", "dm", "delete"):
        assert forbidden not in SAFE_ACTIONS
