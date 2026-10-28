import logging

from xhh_agent.protocol.session import SessionStore


async def test_request_qr_returns_url_and_id(fake_qr_client):
    qr = await fake_qr_client.request_qr_login()
    assert qr.qr_url.startswith("https://")
    assert qr.qr
    assert qr.expire > 0


async def test_poll_returns_pending_then_ok(fake_qr_client, monkeypatch):
    """未扫码返回 pending，扫码确认后返回会话"""
    assert (await fake_qr_client.poll_qr_login("qid")).status == "pending"
    monkeypatch.setattr(fake_qr_client, "_qr_state", "ok")
    result = await fake_qr_client.poll_qr_login("qid")
    assert result.status == "ok"
    assert result.session.heybox_id == "83709585"


async def test_login_saves_session_without_logging_cookie(fake_qr_client, tmp_path, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(fake_qr_client, "_qr_state", "ok")   # 免去轮询等待
    store = SessionStore(tmp_path / "s.json")
    result = await fake_qr_client.login_and_save(store)
    assert result.status == "ok"
    assert store.load().cookie
    assert "hkey" not in caplog.text.lower()
