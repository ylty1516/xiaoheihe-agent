"""频率闸门。上限写死在代码里，环境变量只能调低不能调高。"""

import time

import pytest

from xhh_agent.automation.gate import Gate
from xhh_agent.config import HARD_LIMITS, load_config
from xhh_agent.store.db import Store


@pytest.fixture
def store(tmp_path) -> Store:
    return Store(tmp_path / "t.db")


@pytest.fixture
def cfg(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("XHH_"):
            monkeypatch.delenv(key, raising=False)
    return load_config()


def test_allows_when_under_all_limits(store, cfg):
    assert Gate(store, cfg).check(link_id="L1").allowed


def test_blocks_on_hourly_limit(store, cfg):
    for i in range(HARD_LIMITS["reply_per_hour"]):
        store.log_sent("comment", f"m{i}", "hi", link_id="L1")
    result = Gate(store, cfg).check(link_id="L2")
    assert not result.allowed
    assert "小时" in result.reason


def test_blocks_on_per_post_limit(store, cfg):
    """用户新规则：每个帖子最多回复 5 次。

    把记录挪到 2 小时前，绕开"每小时"闸门 —— 否则 5 条会先撞小时上限，
    测不到每帖这条规则。
    """
    for i in range(HARD_LIMITS["reply_per_post"]):
        store.log_sent("comment", f"m{i}", "hi", link_id="L1")
    store._conn.execute("UPDATE sent_log SET sent_at=?", (int(time.time()) - 7200,))
    store._conn.commit()

    result = Gate(store, cfg).check(link_id="L1")
    assert not result.allowed
    assert "帖" in result.reason
    # 小时额度已经空出来了，另一个帖子和另一个时间窗都不受影响
    assert Gate(store, cfg).check(link_id="L2").allowed


def test_env_cannot_raise_limits(store, cfg, monkeypatch):
    monkeypatch.setenv("XHH_MAX_REPLIES_PER_HOUR", "999")
    from importlib import reload

    import xhh_agent.config as config_module

    reload(config_module)
    cfg2 = config_module.load_config()
    assert cfg2.max_replies_per_hour == HARD_LIMITS["reply_per_hour"]
    reload(config_module)


def test_env_can_lower_limits(store, monkeypatch):
    monkeypatch.setenv("XHH_MAX_REPLIES_PER_POST", "1")
    from importlib import reload

    import xhh_agent.config as config_module

    reload(config_module)
    cfg = config_module.load_config()
    store.log_sent("comment", "m1", "hi", link_id="L1")
    assert not Gate(store, cfg).check(link_id="L1").allowed
    reload(config_module)


def test_hourly_window_ignores_old_sends(store, cfg):
    for i in range(HARD_LIMITS["reply_per_hour"]):
        store.log_sent("comment", f"m{i}", "hi", link_id="L1")
    # 把记录时间往前挪两小时
    store._conn.execute("UPDATE sent_log SET sent_at=?", (int(time.time()) - 7200,))
    store._conn.commit()
    assert Gate(store, cfg).check(link_id="L2").allowed
