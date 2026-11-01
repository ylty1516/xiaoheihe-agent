"""Bounded read-only discovery cache, with honest freshness and rank provenance."""

from __future__ import annotations

import asyncio
import copy
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

import aiohttp

from xhh_agent.protocol.errors import XhhError


class Discovery:
    TTL = 60

    def __init__(self, client_factory, *, clock=time.monotonic, wall=time.time):
        self.client_factory, self.clock, self.wall = client_factory, clock, wall
        self.cache = OrderedDict()
        self.failed = set()
        self.locks = {}
        self.network_slots = asyncio.Semaphore(4)

    @asynccontextmanager
    async def view_lock(self, key):
        if key not in self.locks and len(self.locks) >= 20:
            raise ValueError("当前查询较多，请稍后刷新")
        state = self.locks.setdefault(key, [asyncio.Lock(), 0])
        state[1] += 1
        try:
            async with state[0]:
                yield
        finally:
            state[1] -= 1
            if state[1] == 0:
                self.locks.pop(key, None)

    async def get(self, body):
        action = body.get("action")
        board = body.get("board", "all")
        query = body.get("query", "")
        sort = body.get("sort", "create_date")
        window = body.get("time_range", "1d")
        force = body.get("refresh", False)
        if not isinstance(force, bool):
            raise ValueError("refresh 必须为布尔值")  # noqa: TRY004 - exposed as an HTTP 400.
        if action == "hot":
            if not isinstance(board, str) or board not in {"all", "games", "discussions"}:
                raise ValueError("请选择有效热榜")
            key = (action, board)
        elif action == "topic":
            if not isinstance(query, str) or not query.strip() or len(query) > 100:
                raise ValueError("请输入100字以内的话题")
            if not isinstance(sort, str) or sort not in {
                "create_date",
                "award_num",
                "comment_num",
                "default",
            }:
                raise ValueError("请选择有效排序")
            if not isinstance(window, str) or window not in {"1d", "7d", "30d", "180d", "360d", ""}:
                raise ValueError("请选择有效时间范围")
            query = query.strip()
            key = (action, query, sort, window)
        else:
            raise ValueError("不支持的发现操作")

        before = self.cache.get(key)
        async with self.view_lock(key):
            cached = self.cache.get(key)
            if cached and (
                cached is not before or (not force and self.clock() - cached[0] < self.TTL)
            ):
                self.cache.move_to_end(key)
                return self.response(cached[1], cached=True, stale=key in self.failed)
            client = None
            try:
                client = self.client_factory()
                if action == "hot":
                    async with self.network_slots:
                        data = await client.fetch_hot_board(board=board, limit=15, refresh=True)
                    previous = cached[1] if cached else None
                    same_source = previous and previous["source_board"] == data["source_board"]
                    ranks = (
                        {self.topic_key(x["text"]): x["index"] for x in previous["items"]}
                        if same_source
                        else {}
                    )
                    data["compared_at"] = previous["fetched_at"] if same_source else None
                    for item in data["items"]:
                        old = ranks.get(self.topic_key(item["text"]))
                        change = old - item["index"] if old is not None else None
                        item.update(
                            previous_rank=old,
                            change=change,
                            movement=("initial" if not same_source else "new")
                            if old is None
                            else ("up" if change > 0 else "down" if change < 0 else "same"),
                        )
                else:
                    async with self.network_slots:
                        posts = await client.search_topic_posts(
                            query, limit=15, sort=sort, time_range=window
                        )
                    data = {
                        "items": posts,
                        "query": query,
                        "sort": sort,
                        "time_range": window,
                        "source": "小黑盒社区搜索",
                        "fetched_at": self.wall(),
                        "sample_note": "取回搜索样本；近24小时按发布时间本地过滤，非全站完整统计",
                    }
            except (XhhError, OSError, TimeoutError, aiohttp.ClientError):
                if not cached:
                    raise
                self.failed.add(key)
                return self.response(cached[1], cached=True, stale=True)
            finally:
                if client is not None:
                    await client.close()
            self.cache[key] = (self.clock(), copy.deepcopy(data))
            self.failed.discard(key)
            self.cache.move_to_end(key)
            while len(self.cache) > 20:
                removed, _ = self.cache.popitem(last=False)
                self.failed.discard(removed)
            return self.response(data)

    @staticmethod
    def topic_key(text):
        return "".join(text.split()).casefold()

    def response(self, data, *, cached=False, stale=False):
        return {
            "ok": True,
            **copy.deepcopy(data),
            "cached": cached,
            "stale": stale,
            "refresh_interval": self.TTL,
            "warning": "更新失败，保留上次成功采集结果；请核对账号或网络后重试" if stale else "",
        }
