"""粘贴 cookie 登录（``xhh login --cookie``）的测试。

重点不是"能解析"，而是三条安全性质：
1. 只保留白名单字段（照单全收会让请求指纹偏离真实浏览器）
2. 验证不过不落盘（免得一个废 cookie 覆盖掉还能用的会话）
3. 任何输出里都不出现 cookie 内容
"""

from dataclasses import replace

import pytest

from xhh_agent.cli import cmd_login
from xhh_agent.config import load_config
from xhh_agent.protocol.client import normalize_pasted_cookie
from xhh_agent.protocol.errors import LoginExpired
from xhh_agent.protocol.models import Account
from xhh_agent.protocol.session import Session, SessionStore

# 形状与真实 user_pkey 相似，但内容是自造的假值，故意不含真实的账号 ID / 时间戳。
PKEY = "fake-user-pkey-value-used-only-in-tests"


# ── normalize_pasted_cookie ────────────────────────────────


def test_full_cookie_header_is_accepted():
    out = normalize_pasted_cookie(f"user_pkey={PKEY}; user_heybox_id=85183285")
    assert f"user_pkey={PKEY}" in out
    assert "user_heybox_id=85183285" in out


def test_cookie_prefix_is_stripped():
    out = normalize_pasted_cookie(f"Cookie: user_pkey={PKEY}; user_heybox_id=85183285")
    assert out.startswith("user_pkey=")
    assert "Cookie:" not in out


def test_bare_pkey_value_is_accepted():
    """DevTools 的 Value 列只给 pkey 本体，没有字段名。"""
    assert normalize_pasted_cookie(PKEY) == f"user_pkey={PKEY}"


def test_non_whitelisted_fields_are_dropped():
    raw = f"_ga=GA1.2.3; user_pkey={PKEY}; _gid=xyz; user_heybox_id=85183285"
    out = normalize_pasted_cookie(raw)
    assert "_ga" not in out
    assert "_gid" not in out
    assert f"user_pkey={PKEY}" in out


def test_whitelisted_extra_fields_are_kept():
    out = normalize_pasted_cookie(f"user_pkey={PKEY}; x_xhh_tokenid=tok123")
    assert "x_xhh_tokenid=tok123" in out


def test_empty_cookie_is_rejected():
    with pytest.raises(ValueError, match="为空"):
        normalize_pasted_cookie("   ")


def test_cookie_without_pkey_is_rejected():
    with pytest.raises(ValueError, match="user_pkey"):
        normalize_pasted_cookie("nickname=someone; _ga=1")


# ── _run_cookie ───────────────────────────────────────────


def _cfg(tmp_path):
    return replace(load_config(), db_path=str(tmp_path / "xhh.db"))


async def test_verified_cookie_is_saved(tmp_path, monkeypatch, capsys):
    async def fake_whoami(self):
        return Account(heybox_id="85183285", username="", level=0)

    async def fake_probe(self):
        return True

    monkeypatch.setattr(cmd_login.ProtocolClient, "whoami", fake_whoami)
    monkeypatch.setattr(cmd_login.ProtocolClient, "probe_login_state", fake_probe)
    code = await cmd_login._run_cookie(
        _cfg(tmp_path), f"user_pkey={PKEY}; user_heybox_id=85183285", None
    )

    assert code == 0
    saved = SessionStore(tmp_path / "session.json").load()
    assert saved.heybox_id == "85183285"
    assert PKEY in saved.cookie
    # 屏幕上不该出现 cookie 本体
    assert PKEY not in capsys.readouterr().out


async def test_guest_state_does_not_clobber_existing_session(tmp_path, monkeypatch, capsys):
    """实测过的坑：服务端对无效 cookie 也返回 status=ok，whoami 会误判。

    所以还要看 probe_login_state；它报游客态时必须拒绝写入。
    """
    store = SessionStore(tmp_path / "session.json")
    store.save(Session(cookie="user_pkey=GOOD; user_heybox_id=85183285", heybox_id="85183285"))

    async def fake_whoami(self):
        return Account(heybox_id="85183285", username="", level=0)

    async def guest(self):
        return False

    monkeypatch.setattr(cmd_login.ProtocolClient, "whoami", fake_whoami)
    monkeypatch.setattr(cmd_login.ProtocolClient, "probe_login_state", guest)
    code = await cmd_login._run_cookie(
        _cfg(tmp_path), f"user_pkey={PKEY}; user_heybox_id=85183285", None
    )

    assert code == cmd_login.EXIT_LOGIN_FAILED
    assert "GOOD" in store.load().cookie


async def test_invalid_cookie_does_not_clobber_existing_session(tmp_path, monkeypatch):
    """废 cookie 覆盖掉还能用的会话，是最容易踩的坑。"""
    store = SessionStore(tmp_path / "session.json")
    store.save(Session(cookie="user_pkey=GOOD; user_heybox_id=85183285", heybox_id="85183285"))

    async def expired(self):
        raise LoginExpired("登录态失效")

    monkeypatch.setattr(cmd_login.ProtocolClient, "whoami", expired)
    code = await cmd_login._run_cookie(
        _cfg(tmp_path), f"user_pkey={PKEY}; user_heybox_id=85183285", None
    )

    assert code == cmd_login.EXIT_LOGIN_FAILED
    assert "GOOD" in store.load().cookie


async def test_unparseable_cookie_exits_without_touching_session(tmp_path, caplog):
    code = await cmd_login._run_cookie(_cfg(tmp_path), "   ", None)
    assert code == cmd_login.EXIT_LOGIN_FAILED
    assert not (tmp_path / "session.json").exists()

async def test_heybox_id_falls_back_to_cli_arg(tmp_path, monkeypatch):
    """cookie 里没有 user_heybox_id 时，--heybox-id 要能兜住。"""
    async def fake_whoami(self):
        return Account(heybox_id="", username="", level=0)

    async def fake_probe(self):
        return True

    monkeypatch.setattr(cmd_login.ProtocolClient, "whoami", fake_whoami)
    monkeypatch.setattr(cmd_login.ProtocolClient, "probe_login_state", fake_probe)
    code = await cmd_login._run_cookie(_cfg(tmp_path), PKEY, "85183285")

    assert code == 0
    assert SessionStore(tmp_path / "session.json").load().heybox_id == "85183285"


async def test_missing_heybox_id_is_rejected_before_any_request(tmp_path, monkeypatch, capsys):
    """只有 user_pkey 的 cookie 无法确认账号归属，必须在发请求前就拦住。"""
    called = []

    async def boom(self):
        called.append(1)
        return Account(heybox_id="x", username="", level=0)

    monkeypatch.setattr(cmd_login.ProtocolClient, "whoami", boom)
    code = await cmd_login._run_cookie(_cfg(tmp_path), PKEY, None)

    assert code == cmd_login.EXIT_LOGIN_FAILED
    assert called == []          # 没有白跑一次请求
    assert "user_heybox_id" in capsys.readouterr().err
    assert not (tmp_path / "session.json").exists()


async def test_whoami_hint_is_used_when_cookie_has_no_id(tmp_path, monkeypatch):
    """没有 heybox_id 时不再靠 whoami 补：直接拒绝（避免存错账号）。"""
    async def fake_whoami(self):
        return Account(heybox_id="99998888", username="", level=0)

    monkeypatch.setattr(cmd_login.ProtocolClient, "whoami", fake_whoami)
    code = await cmd_login._run_cookie(_cfg(tmp_path), PKEY, None)

    assert code == cmd_login.EXIT_LOGIN_FAILED
