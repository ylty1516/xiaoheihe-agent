"""xhh poll / queue / reply：回评论的完整闭环。

    xhh poll --once                    # 扫描自己的帖子，把该回的放进队列
    xhh queue list                     # 看队列
    xhh reply --queue-id 3 --text "..."        # dry-run，看请求
    xhh reply --queue-id 3 --text "..." --send # 真发

回复内容由人（或 Pi 侧 agent）写——本工具不替你想话说什么。
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from xhh_agent.automation.gate import Gate
from xhh_agent.automation.poll import PollRunner
from xhh_agent.cli.cmd_login import session_path
from xhh_agent.config import Config
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore
from xhh_agent.store.db import Store

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_LOGIN_EXPIRED = 3


def _store(cfg: Config) -> Store:
    return Store(cfg.db_path)


def _relogin() -> int:
    print("请先运行 'xhh login' 重新登录。", file=sys.stderr)
    return EXIT_LOGIN_EXPIRED


# ── poll ────────────────────────────────────────────────

async def _poll(cfg: Config, limit: int) -> int:
    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    store = _store(cfg)
    try:
        report = await PollRunner(client, store, cfg, inbox_limit=limit).run_once()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        print(f"扫描失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()
        store.close()

    print(report.summary())
    for message_id, reason in report.reasons[:20]:
        print(f"  - {message_id}: {reason}")
    if report.queued:
        print("\n用 'xhh queue list' 查看待回复，写好后 'xhh reply --queue-id N --text \"...\"'")
    return EXIT_OK


def poll_main(args: object, cfg: Config) -> int:
    return asyncio.run(_poll(cfg, int(getattr(args, "limit", 20) or 20)))


# ── queue ───────────────────────────────────────────────

def queue_main(args: object, cfg: Config) -> int:
    action = getattr(args, "action", "list")
    store = _store(cfg)
    try:
        if action == "list":
            rows = store.list_queue()
            if not rows:
                print("队列为空。")
                return EXIT_OK
            print(f"{'ID':<4} {'发送者':<14} {'强制人工':<9} 原评论")
            print("-" * 70)
            for row in rows:
                incoming = json.loads(row["incoming"]) if row["incoming"] else {}
                must = "是" if incoming.get("must_human") else ""
                text = str(incoming.get("text") or "")[:34]
                print(f"{row['id']:<4} {row['sender_name'] or '':<14} {must:<9} {text}")
            return EXIT_OK

        queue_id = int(getattr(args, "id", 0) or 0)
        row = store.get_queue(queue_id)
        if row is None:
            print(f"队列里没有 id={queue_id}", file=sys.stderr)
            return EXIT_USAGE

        if action == "show":
            incoming = json.loads(row["incoming"]) if row["incoming"] else {}
            print(f"id        : {row['id']}")
            print(f"发送者    : {row['sender_name']}")
            print(f"原评论    : {incoming.get('text')}")
            print(f"link_id   : {incoming.get('link_id')}")
            print(f"reply_id  : {incoming.get('reply_id')}")
            print(f"强制人工  : {'是' if incoming.get('must_human') else '否'}")
            print(f"草稿      : {row['draft_reply'] or '(空)'}")
            return EXIT_OK

        if action in {"approve", "reject"}:
            if action == "approve":
                store.approve(queue_id)
                print(f"已放行 id={queue_id}。用 xhh reply 发送。")
            else:
                store.reject(queue_id)
                print(f"已拒绝 id={queue_id}。")
            return EXIT_OK

        print(f"未知动作：{action}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        store.close()


# ── reply ───────────────────────────────────────────────

async def _reply(cfg: Config, queue_id: int, text: str, do_send: bool) -> int:
    store = _store(cfg)
    try:
        row = store.get_queue(queue_id)
        if row is None:
            print(f"队列里没有 id={queue_id}", file=sys.stderr)
            return EXIT_USAGE
        if row["state"] == "rejected":
            print("这条已被拒绝，不发送。", file=sys.stderr)
            return EXIT_USAGE

        incoming = json.loads(row["incoming"]) if row["incoming"] else {}
        link_id = str(incoming.get("link_id") or "")
        reply_id = str(incoming.get("reply_id") or "")
        root_id = str(incoming.get("root_id") or reply_id)
        content = (text or "").strip()
        if not content:
            print("参数错误：缺少 --text（回复内容由你决定）", file=sys.stderr)
            return EXIT_USAGE

        gate = Gate(store, cfg).check(link_id=link_id)
        if not gate.allowed:
            print(f"闸门拦截：{gate.reason}", file=sys.stderr)
            return EXIT_ERROR
    finally:
        pass

    print("── 将要回复 ─────────────────────────────")
    print(f"原评论 : {incoming.get('text')}")
    print(f"发送者 : {row['sender_name']}")
    print(f"内容   : {content}")
    print("─────────────────────────────────────────")

    if not do_send:
        print("\n[DRY-RUN] 未发送。确认无误后加 --send。")
        store.close()
        return EXIT_OK

    try:
        session = SessionStore(session_path(cfg)).load()
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        store.close()
        return EXIT_LOGIN_EXPIRED

    client = ProtocolClient(session, cfg)
    try:
        result = await client.reply_comment(
            link_id=link_id, reply_id=reply_id, root_id=root_id, text=content
        )
    except LoginExpired as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOGIN_EXPIRED
    except XhhError as exc:
        store.mark("comment", row["target_id"], "failed", error=str(exc))
        print(f"发送失败：{exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        await client.close()

    store.log_sent("comment", row["target_id"], content, link_id=link_id)
    store.mark("comment", row["target_id"], "sent")
    store.set_queue_state(queue_id, "sent")
    store.close()

    print(f"\n已回复" + (f"，comment_id={result.ack_id}" if result.ack_id else ""))
    print(f"该帖子累计已回复 {_post_count(cfg, link_id)} / {cfg.max_replies_per_post} 次")
    return EXIT_OK


def _post_count(cfg: Config, link_id: str) -> int:
    store = _store(cfg)
    try:
        return store.count_sent_for_post(link_id)
    finally:
        store.close()


def reply_main(args: object, cfg: Config) -> int:
    return asyncio.run(
        _reply(
            cfg,
            int(getattr(args, "queue_id", 0) or 0),
            getattr(args, "text", "") or "",
            bool(getattr(args, "send", False)),
        )
    )
