"""编排：一轮扫描 → 过滤 → 决策 → 闸门 → 入队。

P2 只处理**自己帖子下方的评论**（规格 §5.4b）。

这里刻意不生成回复内容：生成是 Pi 侧 agent 的事。本层只负责
"找出该回的、判断能不能回、把它安全地放进队列"。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from xhh_agent.config import Config
from xhh_agent.protocol.models import InboxItem
from xhh_agent.store.db import Store

from .decisions import DecideContext, decide
from .gate import Gate

logger = logging.getLogger(__name__)


@dataclass
class PollReport:
    scanned: int = 0
    skipped: int = 0
    queued: int = 0
    blocked: str = ""
    reasons: list[tuple[str, str]] = field(default_factory=list)

    def note(self, message_id: str, reason: str) -> None:
        self.reasons.append((message_id, reason))

    def summary(self) -> str:
        parts = [f"扫描 {self.scanned}", f"跳过 {self.skipped}", f"入队 {self.queued}"]
        if self.blocked:
            parts.append(f"被闸门拦下：{self.blocked}")
        return "，".join(parts)


class PollRunner:
    def __init__(
        self,
        client: object,
        store: Store,
        config: Config,
        *,
        now: int | None = None,
        inbox_limit: int = 20,
    ) -> None:
        self._client = client
        self._store = store
        self._config = config
        self._now = int(now if now is not None else time.time())
        self._inbox_limit = inbox_limit
        self._gate = Gate(store, config)
        #: 帖子归属缓存：一轮里同一帖子会被多条评论引用，不该每条都查一次
        self._own_post_cache: dict[str, bool] = {}

    async def run_once(self) -> PollReport:
        report = PollReport()
        page = await self._client.fetch_inbox(limit=self._inbox_limit)  # type: ignore[attr-defined]
        ctx = DecideContext(now=self._now, max_age_hours=self._config.max_message_age_hours)

        for item in page.items:
            report.scanned += 1

            # 1) 只看自己帖子下的评论
            if item.channel != "comment":
                report.skipped += 1
                report.note(item.message_id, f"通道 {item.channel} 不在 P2 范围")
                continue

            if not item.link_id:
                report.skipped += 1
                report.note(item.message_id, "缺少 link_id")
                continue

            if not await self._is_own_post(item.link_id):
                report.skipped += 1
                report.note(item.message_id, "不是自己的帖子，不回")
                continue

            # 2) 决策三道门
            decision = decide(item, ctx)
            if decision.action == "skip":
                report.skipped += 1
                report.note(item.message_id, decision.reason)
                self._mark(item, "skipped", decision.reason)
                continue

            # 3) 闸门（每帖 ≤5 / 每小时 / 每天）
            gate = self._gate.check(link_id=item.link_id, now=self._now)
            if not gate.allowed:
                report.blocked = gate.reason
                report.note(item.message_id, gate.reason)
                # 不标记 processed：额度恢复后还能处理
                break

            # 4) 抢占式幂等：抢不到说明已处理过
            if not self._store.claim("comment", item.message_id, sender_id=item.sender_id):
                report.skipped += 1
                report.note(item.message_id, "已处理过")
                continue

            # 5) 入队等人（或等 agent）写回复
            try:
                self._store.enqueue(
                    channel="comment",
                    target_id=item.message_id,
                    sender_name=item.sender_name,
                    incoming=json.dumps(
                        {
                            "message_id": item.message_id,
                            "text": item.text,
                            "link_id": item.link_id,
                            "reply_id": item.reply_id,
                            "root_id": item.root_id,
                            "sender_name": item.sender_name,
                            "timestamp": item.timestamp,
                            "must_human": decision.is_hard,
                        },
                        ensure_ascii=False,
                    ),
                    draft_reply="必须人处理" if decision.is_hard else "",
                )
                report.queued += 1
            except Exception as exc:  # noqa: BLE001 - 队列写失败不该标记成已处理
                self._store.mark("comment", item.message_id, "failed", error=str(exc))
                report.note(item.message_id, f"入队失败：{exc}")

        return report

    async def _is_own_post(self, link_id: str) -> bool:
        cached = self._own_post_cache.get(link_id)
        if cached is not None:
            return cached
        try:
            owned = await self._client.is_own_post(link_id)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - 查不到就当不是自己的
            owned = False
        self._own_post_cache[link_id] = owned
        return owned

    def _mark(self, item: InboxItem, state: str, reason: str) -> None:
        if self._store.claim("comment", item.message_id, sender_id=item.sender_id):
            self._store.mark("comment", item.message_id, state, error=reason)
