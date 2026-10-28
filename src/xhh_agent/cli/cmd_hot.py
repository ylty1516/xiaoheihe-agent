"""xhh hot：看小黑盒热搜榜（「热搜榜」）。

写帖前应该先跑这个喵。选题从里面挑，不要凭空想。
"""

from __future__ import annotations

import asyncio
import sys

from xhh_agent.cli.cmd_login import session_path
from xhh_agent.config import Config
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LOGIN_EXPIRED = 3


async def _run(cfg: Config, limit: int) -> int:
    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    try:
        topics = await client.fetch_hot_topics(limit=limit)
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"拿热搜失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()

    print(f"热搜榜（前 {len(topics)} 条）：\n")
    for topic in topics:
        tag = f"  [{topic['right_tag']}]" if topic["right_tag"] else ""
        print(f"  {topic['index']}. {topic['text']}{tag}")
    print("\n选题时优先挑**游戏相关**的，电竞和商业新闻不适合这个号。")
    return EXIT_OK


def main(args: object, cfg: Config) -> int:
    return asyncio.run(_run(cfg, int(getattr(args, "limit", 10) or 10)))
