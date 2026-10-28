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


def test_login_url_uses_api_origin_not_web_origin(fake_qr_client):
    """登录接口不签名，但域名和签名接口是同一个：api.xiaoheihe.cn。

    写成 www.xiaoheihe.cn 会得到 404 page not found —— 这是实际踩过的 bug。
    """
    url = fake_qr_client.build_login_url("/account/get_qrcode_url/", {"app": "web"})
    assert url.startswith("https://api.xiaoheihe.cn/"), url
    assert "hkey" not in url
    assert "nonce" not in url


def test_render_qr_creates_scannable_png(tmp_path):
    """qr_url 是二维码内容而非网页，必须渲染成图片才能扫。"""
    from xhh_agent.cli.qr_render import render_qr

    path = render_qr(
        "https://api.xiaoheihe.cn/account/qr_login/?qr=abc&app=web",
        tmp_path / "qr.png",
    )
    assert path.exists()
    assert path.stat().st_size > 500          # 不是空图
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_cleanup_removes_qr_file(tmp_path):
    from xhh_agent.cli.qr_render import cleanup, render_qr

    path = render_qr("https://example.com/x", tmp_path / "q.png")
    cleanup(path)
    assert not path.exists()
    cleanup(path)   # 重复调用不应抛异常
