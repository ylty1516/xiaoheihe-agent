"""逛帖学习：每天挑几篇高质量帖子，把素材存下来供分析。

这是个**只读**能力——不点赞、不评论、不关注。

分工：
- 本模块负责机械部分：拉推荐流、按互动热度排序、去重、把素材落成文件
- 写作分析由 agent 做：读这些文件，总结别人怎么开头、怎么排布段落、怎么收尾

产出目录默认 `notes/study/`，文件名带日期和 link_id，便于追溯。
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from xhh_agent.protocol.models import FeedPost
from xhh_agent.store.db import Store

logger = logging.getLogger(__name__)


def blocks_to_text(raw: str) -> str:
    """把帖子的 block JSON 转成可读文本。

    实测：``link.text`` 存的是发帖时的 block 数组 JSON，
    形如 ``[{"type":"text","text":"..."}, {"type":"img","url":"..."}]``。
    直接存进笔记就是一堆 JSON，读不懂。
    """
    if not raw or not raw.strip():
        return ""
    stripped = raw.strip()
    if not stripped.startswith("["):
        return stripped

    try:
        blocks = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if not isinstance(blocks, list):
        return stripped

    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = str(block.get("type") or "")
        if kind in {"text", "html"}:
            text = str(block.get("text") or "").strip()
            if text:
                # html block 里是完整 HTML：去标签、保留图片位置
                if kind == "html":
                    text = re.sub(
                        r'<img[^>]*?(?:data-description="([^"]*)")?[^>]*?/?>',
                        lambda m: f"[图片 {m.group(1)}]" if m.group(1) else "[图片]",
                        text,
                    )
                    text = re.sub(r"<br\s*/?>", chr(10), text)
                    text = re.sub(r"</p>", chr(10), text)
                    text = re.sub(r"<[^>]+>", "", text)
                    text = re.sub(r"&nbsp;", " ", text)
                    text = re.sub(r"\n{3,}", chr(10) * 2, text).strip()
                if text:
                    parts.append(text)
        elif kind == "img":
            parts.append(f"[图片 {block.get('width')}x{block.get('height')}]")
        elif kind == "game_card":
            parts.append(f"[游戏卡片 appid={block.get('appid')}]")
    return (chr(10) * 2).join(parts)

#: 推荐流返回的是**短摘要**（实测中位数 128 字），不是全文。
#: 门槛设太高会把所有帖子滤掉——真正的长度判断要在拉详情之后做。
DEFAULT_MIN_DESCRIPTION = 50


def pick_high_quality(
    posts: list[FeedPost],
    *,
    count: int = 2,
    store: Store | None = None,
    min_description: int = DEFAULT_MIN_DESCRIPTION,
) -> list[FeedPost]:
    """按互动热度挑帖子。已读过的跳过，太短的跳过。"""
    candidates = [p for p in posts if len(p.description) >= min_description]
    if store is not None:
        candidates = [p for p in candidates if store.get("study", p.link_id) is None]
    candidates.sort(key=lambda p: p.engagement, reverse=True)
    return candidates[:count]


@dataclass
class StudyResult:
    scanned: int = 0
    picked: int = 0
    picked_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.picked:
            return f"扫了 {self.scanned} 篇，没有合适的新帖子（可能都看过了）"
        return f"扫了 {self.scanned} 篇，挑了 {self.picked} 篇：{', '.join(self.picked_ids)}"


class StudyRunner:
    def __init__(
        self,
        client: object,
        store: Store,
        *,
        notes_dir: str | Path = "notes/study",
        count: int = 2,
        feed_limit: int = 30,
        min_description: int = DEFAULT_MIN_DESCRIPTION,
    ) -> None:
        self._client = client
        self._store = store
        self._notes_dir = Path(notes_dir)
        self._count = count
        self._feed_limit = feed_limit
        self._min_description = min_description

    async def run_once(self) -> StudyResult:
        result = StudyResult()
        posts = await self._client.fetch_feed_posts(limit=self._feed_limit)  # type: ignore[attr-defined]
        result.scanned = len(posts)

        picked = pick_high_quality(
            posts,
            count=self._count,
            store=self._store,
            min_description=self._min_description,
        )
        if not picked:
            return result

        self._notes_dir.mkdir(parents=True, exist_ok=True)
        for post in picked:
            # 先抢占，避免并发/重复运行写两遍
            if not self._store.claim("study", post.link_id):
                continue
            try:
                detail = await self._client.fetch_post_detail(post.link_id)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001 - 单篇失败不该中断整轮
                logger.warning("拉取帖子详情失败 %s: %s", post.link_id, exc)
                self._store.mark("study", post.link_id, "skipped", error=str(exc))
                continue

            path = self._write_note(post, detail)
            self._store.mark("study", post.link_id, "read")
            result.picked += 1
            result.picked_ids.append(post.link_id)
            result.notes.append(str(path))

        return result

    def _write_note(self, post: FeedPost, detail: dict) -> Path:
        today = time.strftime("%Y-%m-%d")
        path = self._notes_dir / f"{today}-{post.link_id}.md"
        topics = "、".join(detail.get("topics") or post.topics or []) or "（无）"
        body = (
            f"# 逛帖笔记 {today}\n\n"
            f"- **link_id**: {post.link_id}\n"
            f"- **标题**: {detail.get('title') or post.title}\n"
            f"- **作者**: {detail.get('author_name') or post.author_name}\n"
            f"- **话题**: {topics}\n"
            f"- **数据**: 赞 {detail.get('up', post.up)} / 评论 "
            f"{detail.get('comment_num', post.comment_num)}\n"
            f"- **链接**: https://www.xiaoheihe.cn/app/bbs/link/{post.link_id}\n\n"
            f"## 正文\n\n```text\n{detail.get('content') or detail.get('description') or post.description}\n```\n\n"
            f"## 待分析\n\n"
            f"读完上面这段正文，回答：\n\n"
            f"1. **开头**：第一句怎么起手的？直接说事还是先铺垫？\n"
            f"2. **结构**：分段多不多？有没有小标题？段落长度多少？\n"
            f"3. **语气**：句子长短、有没有口语、有没有情绪词？\n"
            f"4. **信息密度**：有没有给具体数字 / 价格 / 结论？还是空话多？\n"
            f"5. **收尾**：怎么结束的？总结、反问、还是直接停？\n"
            f"6. **可借用的一点**：这段里有什么是你在写帖子时能学的？\n"
            f"7. **不值得学的**：有没有明显的 AI 腔或废话？\n\n"
            f"## 原始数据\n\n```json\n{json.dumps(detail, ensure_ascii=False, indent=2)}\n```\n"
        )
        path.write_text(body, encoding="utf-8")
        return path
