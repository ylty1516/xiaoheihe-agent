"""配置加载：唯一读取环境变量的地方。

规格 §5.3 / 全局约束：频率上限写死在 ``HARD_LIMITS``，环境变量只能调低不能调高。
这样即便手滑把 ``XHH_MAX_REPLIES_PER_HOUR`` 改成 999，实际仍按 5 执行。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 硬上限，逐字来自规格 §5.3。环境变量只能小于等于这里的值。
HARD_LIMITS: dict[str, int] = {
    "post_per_day": 3,
    "reply_per_hour": 5,
    "reply_per_day": 30,
    "dm_per_day": 10,
}

_REPLY_MODES = ("off", "queue", "auto")
_AI_DISCLOSURES = ("ask", "tag")

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off")


@dataclass(frozen=True)
class Config:
    """不可变的运行期配置。构造后不允许修改。"""

    cookie: str
    heybox_id: str
    draft_only: bool
    reply_mode: str
    ai_disclosure: str
    poll_interval: int
    max_message_age_hours: int
    max_posts_per_day: int
    max_replies_per_hour: int
    max_replies_per_day: int
    max_dm_per_day: int
    db_path: str
    log_level: str


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        raise ValueError(f"{name} 必须是整数，当前值: {raw!r}") from None


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"{name} 必须是 true/false，当前值: {raw!r}")


def _choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw not in allowed:
        raise ValueError(f"{name} 只接受 {allowed}，当前值: {raw!r}")
    return raw


def _capped(env_name: str, hard_key: str) -> int:
    """读取频率配置并在硬上限处夹取。"""
    hard = HARD_LIMITS[hard_key]
    requested = _int(env_name, hard)
    if requested > hard:
        logger.warning("%s=%d 超过硬上限 %d，已按 %d 执行", env_name, requested, hard, hard)
        return hard
    return requested


def load_config() -> Config:
    """从环境变量构造 Config。配置写错时抛 ValueError，绝不静默降级。"""
    return Config(
        cookie=os.environ.get("XHH_COOKIE", "").strip(),
        heybox_id=os.environ.get("XHH_HEYBOX_ID", "").strip(),
        draft_only=_bool("XHH_DRAFT_ONLY", True),
        reply_mode=_choice("XHH_REPLY_MODE", "queue", _REPLY_MODES),
        ai_disclosure=_choice("XHH_AI_DISCLOSURE", "ask", _AI_DISCLOSURES),
        poll_interval=_int("XHH_POLL_INTERVAL", 600),
        max_message_age_hours=_int("XHH_MAX_MESSAGE_AGE_HOURS", 6),
        max_posts_per_day=_capped("XHH_MAX_POSTS_PER_DAY", "post_per_day"),
        max_replies_per_hour=_capped("XHH_MAX_REPLIES_PER_HOUR", "reply_per_hour"),
        max_replies_per_day=_capped("XHH_MAX_REPLIES_PER_DAY", "reply_per_day"),
        max_dm_per_day=_capped("XHH_MAX_DM_PER_DAY", "dm_per_day"),
        db_path=os.environ.get("XHH_DB_PATH", ".data/xhh.db").strip(),
        log_level=os.environ.get("XHH_LOG_LEVEL", "INFO").strip().upper(),
    )
