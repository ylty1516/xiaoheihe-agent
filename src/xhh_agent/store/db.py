"""状态层：SQLite。

三样东西在这里：
- ``processed`` 幂等表：``(channel, target_id)`` 唯一约束，抢占成功才有资格发送
- ``queue`` 人工审核队列
- ``sent_log`` 发送记录，频率闸门和"每帖 ≤5 次"的计数依据

幂等依赖数据库唯一约束而不是内存：进程被 kill 后重启，绝不重复回复。
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed (
    channel     TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    state       TEXT NOT NULL,
    sender_id   TEXT,
    error       TEXT,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER,
    PRIMARY KEY (channel, target_id)
);

CREATE TABLE IF NOT EXISTS queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    sender_name TEXT,
    incoming    TEXT NOT NULL,
    draft_reply TEXT NOT NULL,
    state       TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    UNIQUE (channel, target_id)
);

CREATE TABLE IF NOT EXISTS sent_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    link_id     TEXT,
    text        TEXT NOT NULL,
    sent_at     INTEGER NOT NULL,
    ok          INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_sent_log_window ON sent_log(channel, sent_at);
CREATE INDEX IF NOT EXISTS idx_sent_log_post ON sent_log(link_id, sent_at);
"""


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ── 幂等 ────────────────────────────────────────────

    def claim(self, channel: str, target_id: str, *, sender_id: str = "") -> bool:
        """抢占一条消息的处理权。返回 True 表示抢到，可以发送。

        ``INSERT OR IGNORE`` 撞唯一约束时 rowcount 为 0 —— 说明别人或上一次
        已经抢过了。这是"宁可漏回，不可重发"的落地点。
        """
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO processed"
            "(channel, target_id, state, sender_id, created_at) VALUES (?,?,'claimed',?,?)",
            (channel, target_id, sender_id, int(time.time())),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def mark(self, channel: str, target_id: str, state: str, *, error: str = "") -> None:
        self._conn.execute(
            "UPDATE processed SET state=?, error=?, updated_at=? "
            "WHERE channel=? AND target_id=?",
            (state, error, int(time.time()), channel, target_id),
        )
        self._conn.commit()

    def get(self, channel: str, target_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM processed WHERE channel=? AND target_id=?",
            (channel, target_id),
        ).fetchone()
        return dict(row) if row else None

    # ── 计数（闸门用）────────────────────────────────────

    def count_sent(self, channel: str, *, since: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM sent_log WHERE channel=? AND sent_at>=? AND ok=1",
            (channel, since),
        ).fetchone()
        return int(row["n"]) if row else 0

    def count_sent_for_post(self, link_id: str) -> int:
        """某个帖子下累计回复了几条。用于"每帖 ≤5 次"上限。"""
        if not link_id:
            return 0
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM sent_log WHERE link_id=? AND ok=1",
            (link_id,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def log_sent(
        self,
        channel: str,
        target_id: str,
        text: str,
        *,
        link_id: str = "",
        ok: bool = True,
    ) -> None:
        self._conn.execute(
            "INSERT INTO sent_log(channel, target_id, link_id, text, sent_at, ok) "
            "VALUES (?,?,?,?,?,?)",
            (channel, target_id, link_id, text, int(time.time()), 1 if ok else 0),
        )
        self._conn.commit()

    # ── 审核队列 ────────────────────────────────────────

    def enqueue(
        self,
        channel: str,
        target_id: str,
        sender_name: str,
        incoming: str,
        draft_reply: str,
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO queue(channel, target_id, sender_name, incoming, draft_reply,"
            " state, created_at) VALUES (?,?,?,?,?,'pending',?)",
            (channel, target_id, sender_name, incoming, draft_reply, int(time.time())),
        )
        self._conn.commit()
        return int(cursor.lastrowid or 0)

    def list_queue(self, *, state: str = "pending") -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM queue WHERE state=? ORDER BY id",
            (state,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_queue(self, queue_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM queue WHERE id=?", (queue_id,)).fetchone()
        return dict(row) if row else None

    def set_queue_state(self, queue_id: int, state: str) -> None:
        self._conn.execute("UPDATE queue SET state=? WHERE id=?", (state, queue_id))
        self._conn.commit()

    def approve(self, queue_id: int) -> None:
        self.set_queue_state(queue_id, "approved")

    def reject(self, queue_id: int) -> None:
        self.set_queue_state(queue_id, "rejected")

    # ── 生命周期 ────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
