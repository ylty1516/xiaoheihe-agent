"""发帖排期的规则测试。

这套规则是"每 2 小时一帖"能落地的唯一原因，写错了就会半夜刷屏或者一篇都发不出去，
所以每个分支都单独测。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from xhh_agent.automation.slots import (
    EXIT_OK,
    EXIT_SKIP,
    EXIT_WINDOW,
    MAX_POSTS_PER_DAY,
    load_ledger,
    posts_on,
    record_post,
    slot_state,
)


def _ts(day: datetime, hour: int, minute: int = 0) -> float:
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()


def test_empty_ledger_allows_in_window(tmp_path):
    day = datetime.now().replace(hour=10, minute=0)
    state = slot_state(path=tmp_path / "l.json", now=_ts(day, 10, 0))
    assert state.allowed is True
    assert state.today_count == 0
    assert state.exit_code == EXIT_OK


def test_second_post_needs_two_hour_gap(tmp_path):
    day = datetime.now().replace(hour=10, minute=0)
    path = tmp_path / "l.json"
    record_post("111", path=path, now=_ts(day, 10, 0))

    too_soon = slot_state(path=path, now=_ts(day, 11, 30))
    assert too_soon.allowed is False
    assert too_soon.exit_code == EXIT_SKIP
    assert "还差" in too_soon.reason

    later = slot_state(path=path, now=_ts(day, 12, 0))
    assert later.allowed is True


def test_daily_cap_blocks_fourth_post(tmp_path):
    day = datetime.now().replace(hour=9, minute=0)
    path = tmp_path / "l.json"
    for hour in (9, 11, 13):
        record_post(f"10{hour}", path=path, now=_ts(day, hour))

    state = slot_state(path=path, now=_ts(day, 15))
    assert state.today_count == MAX_POSTS_PER_DAY
    assert state.allowed is False
    assert state.exit_code == EXIT_SKIP
    assert "上限" in state.reason


def test_outside_window_blocks_even_with_quota(tmp_path):
    day = datetime.now().replace(hour=9, minute=0)
    state = slot_state(path=tmp_path / "l.json", now=_ts(day, 3, 30))
    assert state.allowed is False
    assert state.in_window is False
    assert state.exit_code == EXIT_WINDOW


def test_ledger_survives_broken_file(tmp_path):
    path = tmp_path / "l.json"
    path.write_text("{ not json", encoding="utf-8")
    assert load_ledger(path) == []


def test_posts_on_only_counts_that_day(tmp_path):
    path = tmp_path / "l.json"
    now = datetime.now()
    record_post("today", path=path, now=now.timestamp())
    record_post("yesterday", path=path, now=(now - timedelta(days=1)).timestamp())

    today = posts_on(load_ledger(path), now)
    assert [p["link_id"] for p in today] == ["today"]


def test_record_appends_and_keeps_order(tmp_path):
    path = tmp_path / "l.json"
    first = record_post("a", path=path, now=time.time())
    second = record_post("b", path=path, now=time.time() + 1)
    posts = load_ledger(path)
    assert [p["link_id"] for p in posts] == ["a", "b"]
    assert posts[0]["at"] == first["at"]
    assert posts[1]["ts"] == second["ts"]
