"""xhh inbox：只读拉取未读消息。

P0 阶段**不发送任何内容**，只把消息列出来。
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime

from xhh_agent.cli.cmd_login import session_path
from xhh_agent.config import Config
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LOGIN_EXPIRED = 3


async def _run(cfg: Config, fmt: str, limit: int) -> int:
    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    try:
        page = await client.fetch_inbox(limit=limit)
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"拉取失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()

    if page.dropped:
        print(
            f"警告：{page.dropped} 条消息因字段缺失被跳过，接口可能已变更（跑 'xhh doctor'）",
            file=sys.stderr,
        )

    if fmt == "table":
        print(f"{'时间':<14} {'通道':<8} {'发送者':<14} 内容")
        print("-" * 72)
        for item in page.items:
            stamp = datetime.fromtimestamp(item.timestamp).strftime("%m-%d %H:%M")
            text = item.text.replace("\n", " ")[:40]
            print(f"{stamp:<14} {item.channel:<8} {item.sender_name:<14} {text}")
        print(f"\n共 {len(page.items)} 条")
    else:
        print(
            json.dumps(
                {
                    "ok": True,
                    "count": len(page.items),
                "dropped": page.dropped,
                    "items": [asdict(item) for item in page.items],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return EXIT_OK


def main(args: object, cfg: Config) -> int:
    fmt = getattr(args, "format", "json") or "json"
    limit = getattr(args, "limit", 20) or 20
    return asyncio.run(_run(cfg, fmt, limit))
