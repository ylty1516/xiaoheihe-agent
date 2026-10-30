"""Web 面板的状态聚合：把「现在什么情况」压成一个 JSON。

**只读。** 这里不发起任何网络请求，也不写文件——面板要能随时刷新而不产生副作用。
真正的动作（自检、热搜、拉评论）在 ``app.py`` 的 /api/action 里，单独开关。
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from xhh_agent.automation.slots import (
    DEFAULT_LEDGER,
    MAX_POSTS_PER_DAY,
    load_ledger,
    posts_on,
    slot_state,
)
from xhh_agent.store.db import Store

#: 日志卡片只看这两个，其他日志不往面板上堆
LOG_NAMES = ("daily-poll", "daily-study")
#: 每个日志尾巴多少行
LOG_TAIL = 40


def _tail(path: Path, lines: int = LOG_TAIL) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _account(root: Path) -> dict:
    from xhh_agent.protocol.session import SessionStore

    path = root / ".data" / "session.json"
    if not path.exists():
        return {"ok": False, "heybox_id": "", "saved_at": "", "note": "还没有会话，先跑 xhh login"}
    try:
        session = SessionStore(path).load()
    except Exception as exc:  # noqa: BLE001 - 面板不该因为会话文件坏了就整页白屏
        return {"ok": False, "heybox_id": "", "saved_at": "", "note": f"会话读取失败：{exc}"}
    saved = datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M")
    return {
        "ok": bool(getattr(session, "cookie", "")),
        "heybox_id": getattr(session, "heybox_id", ""),
        "saved_at": saved,
        "note": "",
    }


def _queue(root: Path) -> dict:
    db = root / ".data" / "xhh.db"
    if not db.exists():
        return {"pending": 0, "items": [], "counts": {}}
    store = Store(db)
    try:
        pending = store.list_queue()
        counts = {
            state: len(store.list_queue(state=state))
            for state in ("pending", "approved", "rejected")
        }
    finally:
        store.close()

    items = []
    for row in pending[:10]:
        try:
            incoming = json.loads(row["incoming"]) if row["incoming"] else {}
        except json.JSONDecodeError:
            incoming = {}
        items.append(
            {
                "id": row["id"],
                "sender": row["sender_name"] or "",
                "text": str(incoming.get("text") or "")[:120],
                "must_human": bool(incoming.get("must_human")),
                "created_at": datetime.fromtimestamp(row["created_at"]).strftime("%m-%d %H:%M"),
                "draft": (row.get("draft_reply") or "")[:120],
            }
        )
    return {"pending": counts.get("pending", 0), "items": items, "counts": counts}


def _notes(root: Path, limit: int = 5) -> dict:
    folder = root / "notes" / "study"
    if not folder.exists():
        return {"count": 0, "latest": []}
    files = sorted(folder.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "count": len(files),
        "latest": [
            {
                "name": p.stem,
                "at": datetime.fromtimestamp(p.stat().st_mtime).strftime("%m-%d %H:%M"),
            }
            for p in files[:limit]
        ],
    }


def _drafts(root: Path, limit: int = 6) -> list[dict]:
    """最近写过的稿子。写稿落盘的地方不统一，这里认两个约定位置。"""
    folder = root / ".data"
    if not folder.exists():
        return []
    found = list(folder.glob("post-*.md")) + list(folder.glob("*.md"))
    unique = {p.resolve(): p for p in found}
    files = sorted(unique.values(), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for path in files[:limit]:
        try:
            chars = len(path.read_text(encoding="utf-8").replace("\n", "").replace(" ", ""))
        except OSError:
            chars = 0
        out.append(
            {
                "name": path.name,
                "chars": chars,
                "at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M"),
            }
        )
    return out


def build_state(root: Path, *, now: float | None = None) -> dict:
    moment = float(now if now is not None else time.time())
    ledger_path = root / DEFAULT_LEDGER
    posts = load_ledger(ledger_path)
    slot = slot_state(path=ledger_path, now=moment)
    today = posts_on(posts, datetime.fromtimestamp(moment))

    return {
        "now": datetime.fromtimestamp(moment).strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(root),
        "account": _account(root),
        "slot": {
            "allowed": slot.allowed,
            "reason": slot.reason,
            "today_count": slot.today_count,
            "cap": MAX_POSTS_PER_DAY,
            "in_window": slot.in_window,
            "last_at": slot.last_at,
            "next_at": slot.next_at,
        },
        "posts": [
            {
                "link_id": str(p.get("link_id", "")),
                "at": p.get("at", ""),
                "url": f"https://www.xiaoheihe.cn/app/bbs/link/{p.get('link_id', '')}",
            }
            for p in sorted(today, key=lambda p: float(p["ts"]), reverse=True)
        ],
        "queue": _queue(root),
        "notes": _notes(root),
        "drafts": _drafts(root),
        "logs": {
            name: _tail(root / ".data" / "logs" / f"{name}.log") for name in LOG_NAMES
        },
        "docs": {
            "duty": (root / "docs" / "posting-duty.md").exists(),
            "styles": (root / "docs" / "style-ledger.md").exists(),
        },
    }
