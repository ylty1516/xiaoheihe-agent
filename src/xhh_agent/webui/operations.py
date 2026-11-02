"""Explicit account actions for the UI, using existing protocol and reply gates."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import time
import uuid
from dataclasses import fields, replace
from pathlib import Path

import qrcode

from xhh_agent.automation.decisions import DecideContext, decide
from xhh_agent.automation.gate import Gate
from xhh_agent.automation.generator import LlmReplyGenerator, OpenAICompatClient
from xhh_agent.automation.study import StudyRunner
from xhh_agent.protocol.client import ProtocolClient
from xhh_agent.protocol.models import InboxItem
from xhh_agent.protocol.session import Session, SessionStore
from xhh_agent.store.db import Store

from .discovery import Discovery
from xhh_agent.content.persona import Personas


class Operations:
    def __init__(self, root, cfg, writer):
        self.root, self.writer = root, writer
        db = Path(cfg.db_path)
        self.cfg = replace(cfg, db_path=str(db if db.is_absolute() else root / db))
        self.session_path = Path(self.cfg.db_path).parent / "session.json"
        self.tickets = {}
        self.send_lock = asyncio.Lock()
        self.discovery = Discovery(lambda: self.client())

    def client(self, *, blank=False):
        session = (
            Session(cookie="", heybox_id=self.cfg.heybox_id)
            if blank
            else SessionStore(self.session_path).load()
        )
        return ProtocolClient(session, self.cfg)

    def queue(self):
        if not Path(self.cfg.db_path).exists():
            return []
        with Store(Path(self.cfg.db_path)) as store:
            result = []
            for state in ("pending", "approved", "sending", "uncertain"):
                for row in store.list_queue(state=state):
                    incoming = json.loads(row["incoming"] or "{}")
                    if not isinstance(incoming, dict):
                        raise ValueError("评论语境数据损坏，请核对队列")
                    result.append(
                        {
                            "id": row["id"],
                            "sender": row["sender_name"],
                            "state": state,
                            "draft": row["draft_reply"],
                            "incoming": incoming,
                        }
                    )
        return result

    @staticmethod
    def item(row, incoming):
        values = {
            "channel": "comment",
            "message_id": str(row["target_id"]),
            "sender_id": "",
            "sender_name": row["sender_name"],
            "text": "",
            "timestamp": 0,
            "raw_message_type": "1",
        }
        values.update(
            {k: v for k, v in incoming.items() if k in {f.name for f in fields(InboxItem)}}
        )
        return InboxItem(**values)

    async def comment(self, body):
        action = body.get("action")
        if action not in {"ignore", "generate_reply", "send_reply"}:
            raise ValueError("未知评论动作")
        async with self.send_lock:
            with Store(Path(self.cfg.db_path)) as store:
                row = store.get_queue(int(body.get("id", 0)))
                if not row or row["channel"] != "comment":
                    raise ValueError("评论不存在")
                if row["state"] not in {"pending", "approved"}:
                    raise ValueError("该评论已处理或发送结果待核对，不能重复发送")
                if action == "ignore":
                    store.reject(row["id"])
                    return {"ok": True}
                incoming = json.loads(row["incoming"] or "{}")
                item = self.item(row, incoming)
                decision = decide(
                    item,
                    DecideContext(
                        now=int(time.time()), max_age_hours=self.cfg.max_message_age_hours
                    ),
                )
                if incoming.get("must_human") or decision.is_hard or decision.action == "skip":
                    raise ValueError("该评论需要人工处理或不适合回复，请到小黑盒 App 核对")
                link_id, reply_id = str(item.link_id or ""), str(item.reply_id or "")
                if not link_id or not reply_id:
                    raise ValueError("评论语境不完整，不能回复")
                if action == "generate_reply":
                    cfg = self.writer.cfg
                    if not cfg.llm_api_key:
                        raise ValueError("请先配置 AI 模型")
                    generator = LlmReplyGenerator(
                        client=OpenAICompatClient(
                            base_url=cfg.llm_base_url, api_key=cfg.llm_api_key
                        ),
                        model=cfg.llm_model,
                        profile_text="",
                        persona_snapshot=Personas(self.root).get(),
                    )
                    return {"ok": True, "text": await generator.generate(item), "persona": generator.persona_reference}
                text = body.get("text", "")
                if body.get("confirm") is not True:
                    raise ValueError("发送评论需要明确确认")
                if not isinstance(text, str) or not 1 <= len(text.strip()) <= 200:
                    raise ValueError("回复须为 1–200 字")
                client = self.client()
                claimed = False
                try:
                    if not await client.is_own_post(link_id):
                        raise ValueError("只能回复自己帖子下的评论")
                    gate = Gate(store, self.cfg).check(link_id=link_id)
                    if not gate.allowed:
                        raise ValueError(gate.reason)
                    claimed = store.transition_queue(row["id"], ("pending", "approved"), "sending")
                    if not claimed:
                        raise ValueError("这条评论已被其他任务处理")
                    result = await client.reply_comment(
                        link_id=link_id,
                        reply_id=reply_id,
                        root_id=str(item.root_id or reply_id),
                        text=text.strip(),
                    )
                    if not result.ok or not result.ack_id:
                        raise ValueError("没有收到可靠回执，请到 App 核对，勿重复发送")
                    store.log_sent("comment", row["target_id"], text.strip(), link_id=link_id)
                    store.mark("comment", row["target_id"], "sent")
                    store.set_queue_state(row["id"], "sent")
                    return {"ok": True, "ack_id": result.ack_id}
                except Exception:
                    if claimed:
                        store.set_queue_state(row["id"], "uncertain")
                    raise
                finally:
                    await client.close()

    async def action(self, body):
        name = body.get("action")
        if name in {"ignore", "generate_reply", "send_reply"}:
            return await self.comment(body)
        if name == "login_start":
            client = self.client(blank=True)
            try:
                ticket = await client.request_qr_login()
            finally:
                await client.close()
            self.tickets = {k: v for k, v in self.tickets.items() if v[1] > time.monotonic()}
            handle = uuid.uuid4().hex
            self.tickets[handle] = (ticket, time.monotonic() + min(ticket.expire, 300))
            img = qrcode.make(ticket.qr_url)
            output = io.BytesIO()
            img.save(output, format="PNG")
            return {
                "ok": True,
                "handle": handle,
                "image": "data:image/png;base64," + base64.b64encode(output.getvalue()).decode(),
                "expire": ticket.expire,
            }
        if name == "login_poll":
            handle = str(body.get("handle", ""))
            ticket = self.tickets.get(handle)
            if not ticket or ticket[1] <= time.monotonic():
                self.tickets.pop(handle, None)
                return {"ok": True, "status": "expired"}
            client = self.client(blank=True)
            try:
                result = await client.poll_qr_login(ticket[0].qr)
                if result.status == "ok" and result.session is not None:
                    SessionStore(self.session_path).save(result.session)
                    self.tickets.pop(handle, None)
                return {"ok": True, "status": result.status}
            finally:
                await client.close()
        if name not in {"hot", "topic", "study", "find_topics"}:
            raise ValueError("未知运营动作")
        if name in {"hot", "topic"}:
            return await self.discovery.get(body)
        client = self.client()
        try:
            if name == "find_topics":
                query = body.get("query", "")
                if not isinstance(query, str) or not query.strip() or len(query) > 100:
                    raise ValueError("请输入100字以内的分区关键词")
                return {"ok": True, "items": (await client.search_topics(query.strip()))[:20]}
            with Store(Path(self.cfg.db_path)) as store:
                result = await StudyRunner(
                    client, store, notes_dir=self.root / "notes/study", count=2
                ).run_once()
                return {"ok": True, "summary": result.summary()}
        finally:
            await client.close()
