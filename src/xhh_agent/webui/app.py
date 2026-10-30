"""本地只读面板：把「agent 现在在做什么」摊开给人看。

设计上的三条底线：

1. **只绑 127.0.0.1**，不做鉴权也不对外网开放——面板能读账号状态，
   一旦暴露到局域网就等于半个后台。
2. **默认只读**。刷新页面不产生任何请求、不写文件；真要触发动作必须显式点按钮，
   而且只放三个安全动作（自检 / 热搜 / 拉评论），发帖和私信永远不放进面板。
3. **动作失败也要说人话**，不把 traceback 直接吐到页面上。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from pathlib import Path

from aiohttp import web

from xhh_agent.config import Config, load_config
from xhh_agent.protocol.errors import LoginExpired, XhhError
from xhh_agent.protocol.session import SessionStore
from xhh_agent.store.db import Store

from .state import build_state

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).with_name("static")
#: 面板只放行这三个动作。加新的动作前先想清楚：它会不会在没人看着的时候发出内容。
SAFE_ACTIONS = ("doctor", "hot", "poll")


def _session_path(cfg: Config, root: Path) -> Path:
    db_path = Path(cfg.db_path)
    if not db_path.is_absolute():
        db_path = root / db_path
    return db_path.parent / "session.json"


def _make_client(cfg: Config, root: Path):
    from xhh_agent.protocol.client import ProtocolClient

    session = SessionStore(_session_path(cfg, root)).load()
    return ProtocolClient(session, cfg)


async def _action(name: str, cfg: Config, root: Path) -> dict:
    """跑一个安全动作。返回 ``{"ok": bool, "title": str, "lines": [...]}``。"""
    if name == "doctor":
        from xhh_agent.cli.cmd_doctor import run_checks

        client = _make_client(cfg, root)
        try:
            report = await run_checks(client)
        finally:
            await client.close()
        lines = [
            f"{'OK ' if check.ok else 'X  '}{check.name:<10}{check.detail}"
            for check in report.checks
        ]
        return {
            "ok": report.ok,
            "title": "自检通过" if report.ok else "自检没过，别急着发东西",
            "lines": lines,
        }

    if name == "hot":
        client = _make_client(cfg, root)
        try:
            topics = await client.fetch_hot_topics(limit=8)
        finally:
            await client.close()
        return {
            "ok": True,
            "title": f"热搜榜前 {len(topics)} 条",
            "lines": [
                f"{t['index']}. {t['text']}" + (f"  [{t['right_tag']}]" if t["right_tag"] else "")
                for t in topics
            ],
        }

    if name == "poll":
        from xhh_agent.automation.poll import PollRunner

        db_path = Path(cfg.db_path)
        if not db_path.is_absolute():
            db_path = root / db_path
        store = Store(db_path)
        client = _make_client(cfg, root)
        try:
            report = await PollRunner(client, store, cfg).run_once()
        finally:
            await client.close()
            store.close()
        lines = [f"扫描 {report.scanned} / 跳过 {report.skipped} / 入队 {report.queued}"]
        if report.blocked:
            lines.append(f"被闸门拦下：{report.blocked}")
        lines += [f"  {message_id}  {reason}" for message_id, reason in report.reasons[:12]]
        return {"ok": True, "title": "拉了一轮评论", "lines": lines}

    raise ValueError(f"动作 {name} 不在白名单里")


def create_app(root: Path | None = None, cfg: Config | None = None) -> web.Application:
    base = Path(root or Path.cwd()).resolve()
    config = cfg or load_config()

    async def index(_: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC_DIR / "index.html")

    async def state(request: web.Request) -> web.Response:
        payload = await asyncio.to_thread(build_state, base)
        payload["duty_url"] = request.app["duty_url"]
        return web.json_response(payload)

    async def action(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"ok": False, "title": "请求体不是 JSON", "lines": []}, status=400)

        name = str(body.get("name", ""))
        if name not in SAFE_ACTIONS:
            return web.json_response(
                {"ok": False, "title": f"动作 {name} 不在白名单里", "lines": []}, status=403
            )
        try:
            result = await _action(name, config, base)
        except LoginExpired as exc:
            return web.json_response({"ok": False, "title": "会话失效", "lines": [str(exc)]})
        except XhhError as exc:
            return web.json_response({"ok": False, "title": "接口报错", "lines": [str(exc)]})
        except FileNotFoundError as exc:
            return web.json_response({"ok": False, "title": "缺文件", "lines": [str(exc)]})
        except Exception as exc:
            logger.exception("面板动作失败：%s", name)
            return web.json_response(
                {"ok": False, "title": "动作失败", "lines": [f"{type(exc).__name__}: {exc}"]}
            )
        return web.json_response(result)

    app = web.Application()
    app["duty_url"] = ""
    app.router.add_get("/", index)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/action", action)
    return app


async def serve(
    *, host: str = "127.0.0.1", port: int = 8765, root: Path | None = None
) -> None:
    """起服务，一直跑到 Ctrl+C。"""
    app = create_app(root)
    app["duty_url"] = f"http://{host}:{port}/"
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"面板已启动：{app['duty_url']}")
    print("按 Ctrl+C 关闭。")
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        with contextlib.suppress(Exception):
            await runner.cleanup()
