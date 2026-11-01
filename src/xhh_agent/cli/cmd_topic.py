"""搜索最新或高互动讨论，区分发布时间与采集时间。"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime

from xhh_agent.cli.cmd_login import session_path
from xhh_agent.config import Config
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LOGIN_EXPIRED = 3


async def _run(
    cfg: Config,
    query: str,
    limit: int,
    time_range: str,
    *,
    sort="create_date",
    output_format="table",
) -> int:
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
            query, limit=limit, time_range=time_range, sort=sort
        )
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"搜索失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()

    if output_format == "json":
        print(
            json.dumps(
                {
                    "items": posts,
                    "query": query,
                    "time_range": time_range,
                    "sort": sort,
                    "source": "小黑盒社区搜索样本",
                    "fetched_at": time.time(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return EXIT_OK
    window = {
        "1d": "近24小时",
        "7d": "本周",
        "30d": "本月",
        "180d": "半年内",
        "360d": "一年内",
        "": "不限",
    }
    order = {
        "create_date": "最新",
        "award_num": "点赞优先",
        "comment_num": "评论优先",
        "default": "平台排序",
    }
    print(f"「{query}」{window.get(time_range, time_range)} · {order[sort]}（{len(posts)} 条）：\n")
    for index, post in enumerate(posts, start=1):
        stamp = (
            datetime.fromtimestamp(post["published_at"]).strftime("%m-%d %H:%M")
            if post.get("published_at")
            else "发布时间未知"
        )
        print(
            f"  {index}. {stamp}  评{post['comment_num']}  赞{post.get('award_num', 0) or post['up']}  {post['title']}"
        )
        if post["description"]:
            print(f"     {post['description'][:60]}")
        print(f"     link_id={post['link_id']}")
    print("\n仅为取回样本；近24小时按发布时间过滤，不把旧高互动帖当成实时讨论。")
    return EXIT_OK


def main(args: object, cfg: Config) -> int:
    return asyncio.run(
        _run(
            cfg,
            str(getattr(args, "query", "") or ""),
            int(getattr(args, "limit", 8) or 8),
            str(getattr(args, "time_range", "1d") or ""),
            sort=getattr(args, "sort", "create_date"),
            output_format=getattr(args, "format", "table"),
        )
    )
