# tests/test_session.py
import json, os, stat, sys
import pytest
from xhh_agent.protocol.session import Session, SessionStore
from xhh_agent.protocol.errors import LoginExpired


def test_save_and_load_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "session.json")
    store.save(Session(cookie="a=b; c=d", heybox_id="123", device_id="dev"))
    loaded = store.load()
    assert loaded.heybox_id == "123"
    assert loaded.cookie == "a=b; c=d"


def test_file_mode_is_owner_only(tmp_path):
    """Cookie 等价于密码，文件不能被组/其他用户读（审查重点 #1）"""
    p = tmp_path / "session.json"
    SessionStore(p).save(Session(cookie="a=b", heybox_id="1", device_id="d"))
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_load_missing_file_raises_login_expired(tmp_path):
    with pytest.raises(LoginExpired):
        SessionStore(tmp_path / "nope.json").load()


def test_repr_never_leaks_cookie(tmp_path):
    """即便被打进日志也不能泄露（审查重点 #1）"""
    s = Session(cookie="SECRET_COOKIE_VALUE", heybox_id="1", device_id="d")
    assert "SECRET_COOKIE_VALUE" not in repr(s)
    assert "1" in repr(s)          # heybox_id 可见，便于排查


def test_corrupt_json_raises_actionable_error(tmp_path):
    p = tmp_path / "session.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(LoginExpired, match="login"):
        SessionStore(p).load()
