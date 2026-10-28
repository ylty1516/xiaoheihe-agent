"""xhh whoami：验证会话是否仍然有效，并打印账号信息。"""

from __future__ import annotations

import asyncio
import json
import sys

from xhh_agent.cli.cmd_login import session_path
from xhh_agent.config import Config
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LOGIN_EXPIRED = 3


async def _run(cfg: Config) -> int:
    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    try:
        account = await client.whoami()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"查询失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()

    print(
        json.dumps(
            {
                "ok": True,
                "heybox_id": account.heybox_id,
                "username": account.username,
                "level": account.level,
            },
            ensure_ascii=False,
        )
    )
    return EXIT_OK


def main(args: object, cfg: Config) -> int:
    return asyncio.run(_run(cfg))
