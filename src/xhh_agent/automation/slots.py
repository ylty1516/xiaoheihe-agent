"""发帖排期：3 篇/日上限 + 两小时间隔 + 作息时间窗。

**唯一的规则来源。** 命令行脚本（`scripts/post_slot.py`）和 web 面板
（`xhh_agent.webui`）都从这里读，不允许各写一份——两份规则迟早对不上。

账本落在 `.data/post-ledger.json`：评论有 `sent_log` 表，发帖没走那条路，
所以发帖要独立记一份。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: 硬上限，和 config.HARD_LIMITS["post_per_day"] 保持一致
MAX_POSTS_PER_DAY = 3
#: 两篇之间的最小间隔（秒）
MIN_GAP_SECONDS = 2 * 3600
#: 作息时间窗：这两个小时之间才发，避免半夜刷屏
WINDOW_START = 9
WINDOW_END = 23

DEFAULT_LEDGER = Path(".data/post-ledger.json")

EXIT_OK = 0
EXIT_SKIP = 3
EXIT_WINDOW = 4


@dataclass(frozen=True)
class SlotState:
    """这一轮能不能发。``reason`` 是给人看的一句话，不给人看的部分不进日志。"""

    allowed: bool
    reason: str
    today_count: int
    cap: int
    in_window: bool
    last_at: str = ""
    next_at: str = ""
    exit_code: int = EXIT_OK


def _fmt(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


def load_ledger(path: Path = DEFAULT_LEDGER) -> list[dict]:
    """读账本。文件坏了当空账本处理——宁可多发一篇，不让面板整个崩掉。"""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    posts = data.get("posts") if isinstance(data, dict) else None
    return [p for p in (posts or []) if isinstance(p, dict) and "ts" in p]


def save_ledger(posts: list[dict], path: Path = DEFAULT_LEDGER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"posts": posts}, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def posts_on(posts: list[dict], day: datetime) -> list[dict]:
    """某一天发过的帖子，按时间排序。"""
    picked = []
    for post in posts:
        try:
            when = datetime.fromtimestamp(float(post["ts"]))
        except (TypeError, ValueError, OSError):
            continue
        if when.date() == day.date():
            picked.append(post)
    return sorted(picked, key=lambda p: float(p["ts"]))


def record_post(
    link_id: str, *, path: Path = DEFAULT_LEDGER, now: float | None = None
) -> dict:
    moment = float(now if now is not None else time.time())
    posts = load_ledger(path)
    entry = {"ts": moment, "link_id": str(link_id), "at": _fmt(moment)}
    posts.append(entry)
    save_ledger(posts, path)
    return entry


def slot_state(*, path: Path = DEFAULT_LEDGER, now: float | None = None) -> SlotState:
    moment = float(now if now is not None else time.time())
    when = datetime.fromtimestamp(moment)
    posts = load_ledger(path)
    today = posts_on(posts, when)
    hour = when.hour
    in_window = WINDOW_START <= hour < WINDOW_END
    count = len(today)
    last_at = _fmt(float(today[-1]["ts"])) if today else ""
    next_at = _fmt(float(today[-1]["ts"]) + MIN_GAP_SECONDS) if today else ""

    if not in_window:
        return SlotState(
            allowed=False,
            reason=(
                f"当前 {hour:02d} 点，不在 {WINDOW_START:02d}:00-{WINDOW_END:02d}:00 发帖窗口内"
            ),
            today_count=count,
            cap=MAX_POSTS_PER_DAY,
            in_window=False,
            last_at=last_at,
            next_at=next_at,
            exit_code=EXIT_WINDOW,
        )

    if count >= MAX_POSTS_PER_DAY:
        return SlotState(
            allowed=False,
            reason=f"今日已发 {count} 篇，达到上限 {MAX_POSTS_PER_DAY}",
            today_count=count,
            cap=MAX_POSTS_PER_DAY,
            in_window=True,
            last_at=last_at,
            next_at=next_at,
            exit_code=EXIT_SKIP,
        )

    if today:
        wait = float(today[-1]["ts"]) + MIN_GAP_SECONDS - moment
        if wait > 0:
            return SlotState(
                allowed=False,
                reason=(
                    f"距上一篇（{last_at}）不足两小时，还差 {int(wait // 60)} 分钟"
                ),
                today_count=count,
                cap=MAX_POSTS_PER_DAY,
                in_window=True,
                last_at=last_at,
                next_at=next_at,
                exit_code=EXIT_SKIP,
            )

    return SlotState(
        allowed=True,
        reason=f"可以发：今天第 {count + 1} 篇（上限 {MAX_POSTS_PER_DAY}）",
        today_count=count,
        cap=MAX_POSTS_PER_DAY,
        in_window=True,
        last_at=last_at,
        next_at=next_at,
        exit_code=EXIT_OK,
    )
