"""频率闸门。

三个维度叠加：每小时、每天、每个帖子。
上限来自 ``HARD_LIMITS``，配置只能调低——环境变量填 999 也按 5 执行。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from xhh_agent.config import Config
from xhh_agent.store.db import Store


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reason: str = ""


class Gate:
    def __init__(self, store: Store, config: Config) -> None:
        self._store = store
        self._config = config

    def check(self, *, link_id: str = "", now: int | None = None) -> GateResult:
        moment = int(now if now is not None else time.time())

        # 先查最具体的一条：每帖上限。它比小时上限更具体，报出来的原因
        # 也更有用（"这个帖子聊够了" vs "你太频繁了"）。
        if link_id:
            per_post = self._store.count_sent_for_post(link_id)
            if per_post >= self._config.max_replies_per_post:
                return GateResult(
                    False,
                    f"该帖子已回复 {per_post} 次，达到每帖上限 "
                    f"{self._config.max_replies_per_post}",
                )

        hourly = self._store.count_sent("comment", since=moment - 3600)
        if hourly >= self._config.max_replies_per_hour:
            return GateResult(
                False, f"本小时已回复 {hourly} 条，达到上限 {self._config.max_replies_per_hour}"
            )

        daily = self._store.count_sent("comment", since=moment - 86400)
        if daily >= self._config.max_replies_per_day:
            return GateResult(
                False, f"今日已回复 {daily} 条，达到上限 {self._config.max_replies_per_day}"
            )

        return GateResult(True)
