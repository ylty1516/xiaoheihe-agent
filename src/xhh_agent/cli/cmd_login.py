"""xhh login：纯 HTTP 扫码登录。

不启动浏览器，也不需要 Playwright。
注意：**绝不打印 cookie 内容**，它等价于账号密码。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from xhh_agent.config import Config
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import XhhError
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
        print(f"扫码地址：{ticket.qr_url}", flush=True)
        print(f"有效期：{ticket.expire} 秒，扫码后自动完成", flush=True)

        result = await client.login_and_save(store, ticket=ticket)
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


def main(args: object, cfg: Config) -> int:
    return asyncio.run(_run(cfg))
