"""xhh login：纯 HTTP 扫码登录，或直接粘贴浏览器 cookie。

不启动浏览器，也不需要 Playwright。
注意：**绝不打印 cookie 内容**，它等价于账号密码。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from xhh_agent.cli.qr_render import cleanup, render_qr, try_open_image
from xhh_agent.config import Config
from xhh_agent.protocol.client import (
    ProtocolClient,
    heybox_id_from_cookie,
    normalize_pasted_cookie,
)
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import Session, SessionStore

EXIT_OK = 0
EXIT_LOGIN_FAILED = 3


def session_path(cfg: Config) -> Path:
    """会话文件与数据库同目录（默认为 ``.data/``）。"""
    return Path(cfg.db_path).parent / "session.json"


async def _run(cfg: Config) -> int:
    client = ProtocolClient(Session(cookie="", heybox_id=cfg.heybox_id), cfg)
    store = SessionStore(session_path(cfg))
    try:
        ticket = await client.request_qr_login()

        # qr_url 是二维码内容，不是网页。必须渲染成图片供 App 扫码，
        # 直接把地址粘进浏览器会跳到"该功能需要登录使用"。
        qr_path = render_qr(ticket.qr_url, session_path(cfg).parent / "login-qr.png")
        print(f"二维码：{qr_path}")
        print(f"有效期：{ticket.expire} 秒，扫码后自动完成")
        print("请用【小黑盒 App】的「扫一扫」扫屏幕上的二维码。")
        print("（请不要把二维码内容粘到浏览器：那里不是网页）")
        if not try_open_image(qr_path):
            print(f"自动打开失败，请手动打开上面的文件。", file=sys.stderr)
        print("等待扫码...", flush=True)

        try:
            result = await client.login_and_save(store, ticket=ticket)
        finally:
            cleanup(qr_path)

        if result.status != "ok" or result.session is None:
            print(f"登录未完成：[{result.status}] {result.message}", file=sys.stderr)
            return EXIT_LOGIN_FAILED

        print(f"登录成功，heybox_id={result.session.heybox_id}")
        print(f"会话已保存到 {store.path}")
        return EXIT_OK
    except XhhError as exc:
        print(f"登录失败：{exc}", file=sys.stderr)
        return EXIT_LOGIN_FAILED
    finally:
        await client.close()


def _read_cookie_arg(value: str) -> str:
    """``--cookie -`` 表示从标准输入读。

    推荐这种写法：直接写在命令行里的 cookie 会留在 shell 历史（``.bash_history``
    / PSReadLine）里，等于把账号凭证另存了一份明文。
    """
    if value == "-":
        return sys.stdin.readline().strip()
    return value


async def _run_cookie(cfg: Config, raw_cookie: str, heybox_id: str | None) -> int:
    """用粘贴来的 cookie 登录：先验证，验证通过才落盘。

    不验证直接存文件的话，一个失效的 cookie 会静默覆盖掉还能用的旧会话。
    """
    try:
        cookie = normalize_pasted_cookie(raw_cookie)
    except ValueError as exc:
        print(f"cookie 无法解析：{exc}", file=sys.stderr)
        return EXIT_LOGIN_FAILED

    resolved = (
        heybox_id_from_cookie(cookie)
        or str(heybox_id or "").strip()
        or cfg.heybox_id
    )
    if not resolved:
        print(
            "cookie 里没有 user_heybox_id，无法确认是哪个账号，已放弃。\n"
            "请在浏览器 Application → Cookies 里把 user_heybox_id 这一项一起复制，"
            "或者用 --heybox-id 指定账号 ID。",
            file=sys.stderr,
        )
        return EXIT_LOGIN_FAILED

    store = SessionStore(session_path(cfg))
    client = ProtocolClient(Session(cookie=cookie, heybox_id=resolved), cfg)
    try:
        await client.whoami()
        logged_in = await client.probe_login_state()
    except LoginExpired as exc:
        print(f"cookie 无效或已过期：{exc}", file=sys.stderr)
        return EXIT_LOGIN_FAILED
    except XhhError as exc:
        print(f"验证 cookie 失败：{exc}", file=sys.stderr)
        return EXIT_LOGIN_FAILED
    finally:
        await client.close()

    if not logged_in:
        print(
            "服务端没有把这份 cookie 当成登录用户，已保留原有会话不覆盖。\n"
            "常见原因：cookie 复制不全、或者它在浏览器里已经退出登录。",
            file=sys.stderr,
        )
        return EXIT_LOGIN_FAILED

    store.save(Session(cookie=cookie, heybox_id=resolved))
    print(f"登录成功，heybox_id={resolved}")
    print(f"会话已保存到 {store.path}")
    return EXIT_OK


def main(args: object, cfg: Config) -> int:
    cookie = getattr(args, "cookie", None)
    if cookie:
        return asyncio.run(
            _run_cookie(
                cfg,
                _read_cookie_arg(str(cookie)),
                getattr(args, "heybox_id", None),
            )
        )
    return asyncio.run(_run(cfg))
