"""Persistent event dossiers, provenance and editorial memory. No account writes."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

KINDS = {"source", "note", "article", "question", "experiment", "image", "feedback"}


class Desk:
    def __init__(self, root):
        self.path = root / ".data/editorial-desk.sqlite"

    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=10) as db:
            db.row_factory = sqlite3.Row
            db.execute(
                "CREATE TABLE IF NOT EXISTS cards (id TEXT PRIMARY KEY, event TEXT NOT NULL, kind TEXT NOT NULL, fingerprint TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL, UNIQUE(event,kind,fingerprint))"
            )
            yield db

    def put(self, data):
        if not isinstance(data, dict) or data.get("kind") not in KINDS:
            raise ValueError("请选择有效的素材类型")
        event, text = data.get("event", "未分类"), data.get("text", "")
        if not isinstance(event, str) or not 1 <= len(event.strip()) <= 100:
            raise ValueError("专题名应为1至100字")
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 30000:
            raise ValueError("资料正文应为1至30000字")
        if len(json.dumps(data, ensure_ascii=False)) > 60000:
            raise ValueError("素材记录过长")
        record = {**data, "event": event.strip(), "text": text.strip()}
        # Equal passages syndicated at different URLs are one source, not corroboration.
        fingerprint = hashlib.sha256(
            ("".join(text.split()) + str(data.get("version") or "")).encode()
        ).hexdigest()
        with self.db() as db:
            row = db.execute(
                "SELECT id,data FROM cards WHERE event=? AND kind=? AND fingerprint=?",
                (record["event"], record["kind"], fingerprint),
            ).fetchone()
            if row:
                return {**json.loads(row["data"]), "id": row["id"], "duplicate": True}
            card_id = uuid.uuid4().hex
            record.update(id=card_id, captured_at=time.time())
            db.execute(
                "INSERT INTO cards VALUES (?,?,?,?,?,?,?)",
                (
                    card_id,
                    record["event"],
                    record["kind"],
                    fingerprint,
                    json.dumps(record, ensure_ascii=False),
                    time.time(),
                    time.time(),
                ),
            )
        return record

    def list(self, event="", kind=""):
        if not self.path.exists():
            return []
        with self.db() as db:
            rows = db.execute(
                "SELECT data FROM cards WHERE (?='' OR event=?) AND (?='' OR kind=?) ORDER BY updated DESC LIMIT 100",
                (event, event, kind, kind),
            ).fetchall()
        return [json.loads(row["data"]) for row in rows]

    def get(self, card_id):
        if not isinstance(card_id, str) or len(card_id) != 32:
            raise ValueError("素材编号无效")
        with self.db() as db:
            row = db.execute("SELECT data FROM cards WHERE id=?", (card_id,)).fetchone()
        if not row:
            raise ValueError("找不到素材")
        return json.loads(row["data"])

    def context(self, event=""):
        return [
            {
                k: x.get(k)
                for k in (
                    "id",
                    "event",
                    "kind",
                    "text",
                    "question",
                    "conclusion",
                    "new_information",
                    "url",
                    "published_at",
                    "provenance",
                )
            }
            for x in self.list(event)[:20]
        ]

    def overview(self):
        rows = self.list()
        events = {}
        for row in rows:
            counts = events.setdefault(row["event"], {})
            counts[row["kind"]] = counts.get(row["kind"], 0) + 1
        followups = []
        for event in events:
            sources = [x for x in rows if x["event"] == event and x["kind"] == "source"]
            articles = [x for x in rows if x["event"] == event and x["kind"] == "article"]
            if (
                sources
                and articles
                and max(x["captured_at"] for x in sources) > max(x["captured_at"] for x in articles)
            ):
                followups.append(
                    {"event": event, "reason": "稿件完成后收到新资料，建议核对是否需要后续稿或修订"}
                )
        summaries = [
            {
                **{
                    k: x.get(k)
                    for k in ("id", "event", "kind", "captured_at", "title", "provenance", "url")
                },
                "text": x["text"][:1200],
            }
            for x in rows
        ]
        return {"events": events, "items": summaries, "followups": followups}
