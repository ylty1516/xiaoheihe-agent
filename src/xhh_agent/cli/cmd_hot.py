"""刷新指定小黑盒榜单，保留来源与采集时间。"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime

from xhh_agent.cli.cmd_login import session_path
from xhh_agent.config import Config
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LOGIN_EXPIRED = 3


async def _run(cfg: Config, limit: int, *, board="all", refresh=True, output_format="table") -> int:
    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    try:
        data = await client.fetch_hot_board(limit=limit, board=board, refresh=refresh)
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"拿热搜失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()

    if output_format == "json":
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return EXIT_OK
    topics = data["items"]
    stamp = datetime.fromtimestamp(data["fetched_at"]).strftime("%m-%d %H:%M:%S")
    print(f"{data['source']}（{len(topics)} 条，采集于 {stamp}）：\n")
    if data["fallback"]:
        print("主榜不可用，当前为社区热议子榜，排名不能当成主榜。")
    for topic in topics:
        tag = f"  [{topic['right_tag']}]" if topic["right_tag"] else ""
        print(f"  {topic['index']}. {topic['text']}{tag}")
    print("\n榜单为小黑盒平台数据，采集时间不代表话题发生时间。")
    return EXIT_OK


def main(args: object, cfg: Config) -> int:
    return asyncio.run(
        _run(
            cfg,
            int(getattr(args, "limit", 10) or 10),
            board=getattr(args, "board", "all"),
            refresh=not getattr(args, "no_refresh", False),
            output_format=getattr(args, "format", "table"),
        )
    )
