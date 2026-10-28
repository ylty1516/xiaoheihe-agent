"""图片上传：base64 内嵌图会被服务端拒（"图片链接不合法"），
必须先传到小黑盒图床拿 URL。签名是腾讯云 COS 的 q-sign-algorithm=sha1。
"""

import pytest

from xhh_agent.protocol.cos_upload import cos_authorization, cos_quote


def _auth(**overrides):
    kwargs = dict(
        secret_id="AKIDEXAMPLE",
        secret_key="SECRETKEY",
        method="PUT",
        path="/bbs/abc.png",
        headers={
            "Host": "bucket-1250000000.cos.ap-shanghai.myqcloud.com",
            "Content-Type": "image/png",
            "x-cos-security-token": "TOKEN",
        },
        start_time=1700000000,
        end_time=1700000300,
    )
    kwargs.update(overrides)
    return cos_authorization(**kwargs)


def test_authorization_is_deterministic():
    assert _auth() == _auth()


def test_authorization_shape():
    value = _auth()
    assert value.startswith("q-sign-algorithm=sha1&q-ak=AKIDEXAMPLE&")
    assert "q-sign-time=1700000000;1700000300" in value
    assert "q-signature=" in value


def test_authorization_changes_with_secret():
    assert _auth() != _auth(secret_key="OTHER")


def test_authorization_changes_with_path():
    assert _auth() != _auth(path="/bbs/other.png")


def test_cos_quote_keeps_slashes():
    assert cos_quote("/a/b c.png") == "/a/b%20c.png"


async def test_upload_runs_full_flow(fake_cos_client):
    from xhh_agent.protocol.cos_upload import CosUploader

    uploader = CosUploader(fake_cos_client)
    url = await uploader.upload(
        data=b"\x89PNG\r\n\x1a\n" + b"0" * 64,
        name="code.png",
        mimetype="image/png",
        width=100,
        height=40,
    )
    assert url == "https://imgheybox.max-c.com/bbs/code.png"

    called = [path for path, _ in fake_cos_client.calls]
    assert called == [
        "/bbs/app/api/qcloud/cos/upload/info/v2",
        "/bbs/app/api/qcloud/cos/upload/token/v2",
        "PUT_COS",
        "/bbs/app/api/qcloud/cos/upload/callback/v2",
    ]


async def test_upload_fails_without_preview_url(fake_cos_client_no_url):
    from xhh_agent.protocol.cos_upload import CosUploader

    with pytest.raises(Exception, match="preview_url"):
        await CosUploader(fake_cos_client_no_url).upload(
            data=b"x", name="a.png", mimetype="image/png", width=1, height=1
        )
