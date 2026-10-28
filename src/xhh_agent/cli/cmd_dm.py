"""xhh dm：发一条私信。

**默认 dry-run**：只打印将要发送的请求，不真发。
这是本项目第一个写操作，也是不可撤回的操作——先看清再发。

    xhh dm --to 84812994 --text "在不在"           # 只看
    xhh dm --to 84812994 --text "在不在" --send    # 真发
"""

from __future__ import annotations

import asyncio
import sys
from urllib.parse import urlparse, parse_qsl

from xhh_agent.cli.cmd_login import session_path
from xhh_agent.config import Config
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_LOGIN_EXPIRED = 3

_SENSITIVE_KEYS = {"hkey", "nonce", "_time"}


def _redact(url: str) -> str:
    """把 URL 里的签名参数打码后返回，便于展示而不泄露。"""
    parsed = urlparse(url)
    pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)]
    shown = [f"{k}={'***' if k in _SENSITIVE_KEYS else v}" for k, v in pairs]
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?" + "&".join(shown)


def _print_request(request) -> None:
    print("── 将要发送 ─────────────────────────────")
    print(f"收件人 user_id : {request.to_user_id}")
    print(f"内容           : {request.text}")
    print(f"POST           : {_redact(request.url)}")
    print(f"body           : {request.body}")
    print("─────────────────────────────────────────")


async def _history(cfg: Config, to_user_id: str, limit: int) -> int:
    """看与某个人的私信历史。"""
    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    try:
        messages = await client.fetch_dm_history(to_user_id, limit=limit)
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"拉取失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()

    if not messages:
        print("没有历史消息。")
        return EXIT_OK

    from datetime import datetime

    print(f"与 user_id={to_user_id} 的最近 {len(messages)} 条：")
    print("-" * 68)
    for m in messages:
        who = "我" if m.is_mine else to_user_id
        stamp = datetime.fromtimestamp(m.timestamp).strftime("%m-%d %H:%M")
        content = (m.content or "").replace(chr(10), " ")[:44]
        print(f"{stamp}  {who:>10}  {content}")
    return EXIT_OK


async def _run(cfg: Config, to_user_id: str, text: str, do_send: bool) -> int:
    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    try:
        try:
            request = client.build_dm_request(to_user_id, text)
        except ValueError as exc:
            print(f"参数错误：{exc}", file=sys.stderr)
            return 2

        _print_request(request)

        if not do_send:
            print("\n[DRY-RUN] 未发送。确认无误后加 --send。")
            return EXIT_OK

        print("\n正在发送...", flush=True)
        result = await client.send_dm(to_user_id, text)
        print(f"已发送，服务端回执 ack_id={result.ack_id}")
        print("注意：这条消息对方已收到，无法撤回。")
        return EXIT_OK
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"发送失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()


def main(args: object, cfg: Config) -> int:
    to_user_id = getattr(args, "to", "") or ""
    if getattr(args, "history", False):
        return asyncio.run(_history(cfg, to_user_id, int(getattr(args, "limit", 20) or 20)))
    return asyncio.run(
        _run(
            cfg,
            to_user_id,
            getattr(args, "text", "") or "",
            bool(getattr(args, "send", False)),
        )
    )
