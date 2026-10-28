"""xhh topic-posts：看某个话题下社区高赞帖在聊什么。

**发帖前最重要的一步。** 自己搜新闻很容易过时，
社区高赞帖的标题才是当下真正的热点喵。
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


async def _run(cfg: Config, query: str, limit: int, time_range: str) -> int:
    if not query:
        print("参数错误：需要话题关键词", file=sys.stderr)
        return 2

    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    try:
        posts = await client.search_topic_posts(
            query, limit=limit, time_range=time_range
        )
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"搜索失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()

    window = {"7d": "本周", "30d": "本月", "180d": "半年内", "360d": "一年内", "": "不限"}
    print(f'「{query}」{window.get(time_range, time_range)}高互动帖（{len(posts)} 条）：\n')
    for index, post in enumerate(posts, start=1):
        print(f"  {index}. 评{post['comment_num']}  {post['title']}")
        if post["description"]:
            print(f"     {post['description'][:60]}")
        print(f"     link_id={post['link_id']}")
    print("\n看这些标题，找社区真正在聊的角度，别自己搜新闻喵~")
    return EXIT_OK


def main(args: object, cfg: Config) -> int:
    return asyncio.run(
        _run(
            cfg,
            str(getattr(args, "query", "") or ""),
            int(getattr(args, "limit", 8) or 8),
            str(getattr(args, "time_range", "7d") or ""),
        )
    )
