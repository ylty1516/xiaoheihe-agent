"""状态层：幂等表 + 频率计数。

幂等靠数据库唯一约束，不靠内存——进程被 kill 后重启，绝不能重复回复。
"""

import time

import pytest

from xhh_agent.store.db import Store


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "test.db")


def test_claim_succeeds_once(store):
    assert store.claim("comment", "m1") is True
    assert store.claim("comment", "m1") is False   # 已被抢占


def test_claim_is_per_channel(store):
    assert store.claim("comment", "m1") is True
    assert store.claim("dm", "m1") is True         # 不同通道互不影响


def test_mark_updates_state(store):
    store.claim("comment", "m1")
    store.mark("comment", "m1", "sent")
    row = store.get("comment", "m1")
    assert row["state"] == "sent"


def test_mark_records_error(store):
    store.claim("comment", "m1")
    store.mark("comment", "m1", "failed", error="网络超时")
    assert store.get("comment", "m1")["error"] == "网络超时"


def test_count_sent_in_window(store):
    now = int(time.time())
    for i in range(3):
        store.log_sent("comment", f"m{i}", "hi")
    assert store.count_sent("comment", since=now - 3600) == 3
    assert store.count_sent("comment", since=now + 3600) == 0


def test_count_sent_for_post(store):
    """每帖上限 5 次 —— 需要一个按 link_id 的计数。"""
    for i in range(3):
        store.log_sent("comment", f"m{i}", "hi", link_id="L1")
    store.log_sent("comment", "m9", "hi", link_id="L2")
    assert store.count_sent_for_post("L1") == 3
    assert store.count_sent_for_post("L2") == 1
    assert store.count_sent_for_post("L3") == 0


def test_queue_roundtrip(store):
    queue_id = store.enqueue(
        channel="comment",
        target_id="m1",
        sender_name="某人",
        incoming='{"text": "在吗"}',
        draft_reply="在的喵",
    )
    pending = store.list_queue(state="pending")
    assert len(pending) == 1
    assert pending[0]["draft_reply"] == "在的喵"

    store.approve(queue_id)
    assert store.list_queue(state="pending") == []
    assert store.get_queue(queue_id)["state"] == "approved"


def test_queue_is_unique_per_target(store):
    store.enqueue("comment", "m1", "某人", "{}", "a")
    with pytest.raises(Exception):
        store.enqueue("comment", "m1", "某人", "{}", "b")


def test_reject_marks_state(store):
    qid = store.enqueue("comment", "m1", "某人", "{}", "a")
    store.reject(qid)
    assert store.get_queue(qid)["state"] == "rejected"


def test_persistence_across_reopen(tmp_path):
    """重启后幂等记录必须还在——这是"绝不重复回复"的底线。"""
    path = tmp_path / "t.db"
    first = Store(path)
    first.claim("comment", "m1")
    first.close()

    second = Store(path)
    assert second.claim("comment", "m1") is False
    second.close()
