"""xhh delete：删除帖子或草稿。

**不可逆**。默认 dry-run，先查出标题给你确认，加 --yes 才真删。
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
EXIT_USAGE = 2
EXIT_LOGIN_EXPIRED = 3


async def _run(cfg: Config, link_id: str, is_draft: bool, do_delete: bool) -> int:
    if not link_id:
        print("参数错误：需要 --link-id", file=sys.stderr)
        return EXIT_USAGE

    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    try:
        # 先查出来给用户看，避免删错
        title = ""
        try:
            detail = await client.fetch_post_detail(link_id)
            title = detail.get("title") or ""
            author = detail.get("author_name") or ""
        except XhhError:
            author = ""
            if not do_delete:
                print(
                    f"查不到 link_id={link_id} 的详情（可能已删除，或是草稿）。\n"
                    "草稿请加 --draft。",
                    file=sys.stderr,
                )

        print("── 将要删除 ─────────────────────────────")
        print(f"link_id : {link_id}")
        print(f"标题    : {title or '(查不到标题)'}")
        if author:
            print(f"作者    : {author}")
        print(f"类型    : {'草稿' if is_draft else '已发布帖子'}")
        print("─────────────────────────────────────────")

        if not do_delete:
            print("\n[DRY-RUN] 未删除。确认无误后加 --yes。")
            return EXIT_OK

        if is_draft:
            await client.change_link_status(link_id, status=0)
        else:
            await client.delete_link(link_id)
        print("\n已删除。这一步不可撤销。")
        return EXIT_OK
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"删除失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()


def main(args: object, cfg: Config) -> int:
    return asyncio.run(
        _run(
            cfg,
            str(getattr(args, "link_id", "") or ""),
            bool(getattr(args, "draft", False)),
            bool(getattr(args, "yes", False)),
        )
    )
